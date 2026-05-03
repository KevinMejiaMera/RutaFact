# -*- coding: utf-8 -*-
from rest_framework import serializers
from .models import Order, OrderItem
from apps.invoicing.models import ProductTemplate, Customer
from apps.companies.models import Company
from apps.inventory.services import InventoryService
from apps.logistics.models import RouteProduct
from decimal import Decimal, ROUND_HALF_UP

class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    subtotal = serializers.ReadOnlyField()
    tax_amount = serializers.ReadOnlyField()
    total = serializers.ReadOnlyField()
    
    class Meta:
        model = OrderItem
        fields = ['id', 'product', 'product_name', 'quantity', 'unit_price', 'tax_rate', 'subtotal', 'tax_amount', 'total']

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    customer_name = serializers.ReadOnlyField(source='customer.name')
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'id', 'company', 'customer', 'customer_name', 'delivery_address', 
            'delivery_reference', 'contact_phone', 'latitude', 'longitude',
            'status', 'status_display', 'subtotal_without_tax', 'total_tax', 
            'total_amount', 'invoice', 'notes', 'items', 'created_at'
        ]
        read_only_fields = ['company', 'status', 'total_amount', 'invoice']

class OrderCreateSerializer(serializers.ModelSerializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all(), required=False, allow_null=True)
    contact_phone = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    
    items = serializers.ListField(
        child=serializers.DictField(),
        write_only=True
    )
    
    class Meta:
        model = Order
        fields = ['customer', 'delivery_address', 'delivery_reference', 'contact_phone', 'latitude', 'longitude', 'notes', 'items', 'document_type']
    
    def create(self, validated_data):
        from django.db import transaction
        items_data = validated_data.pop('items')
        user = self.context['request'].user
        
        try:
            # Soportar tanto document_type como billing_type (legacy)
            document_type = validated_data.pop('document_type', None)
            billing_type = self.context['request'].data.get('billing_type')
            
            if not document_type:
                if billing_type == 'with_data':
                    document_type = 'factura'
                else:
                    document_type = 'nota_entrega'
            
            with transaction.atomic():
                # Determinar la empresa
                user_company = user.company or Company.objects.filter(id=1).first() or Company.objects.first()
                
                customer = validated_data.pop('customer', None)
                contact_phone = validated_data.pop('contact_phone', '') or ''
                latitude = validated_data.pop('latitude', None)
                longitude = validated_data.pop('longitude', None)
                
                # Redondear coordenadas para evitar errores de precisión en DB
                if latitude is not None:
                    latitude = Decimal(str(latitude)).quantize(Decimal('0.000000000'), rounding=ROUND_HALF_UP)
                if longitude is not None:
                    longitude = Decimal(str(longitude)).quantize(Decimal('0.000000000'), rounding=ROUND_HALF_UP)
                
                if not customer:
                    # Por defecto intentamos usar el perfil del cliente asociado al usuario
                    try:
                        customer = user.customer_profile
                    except:
                        # Si no tiene perfil, buscar por identificación o crear uno
                        identification = user.phone[-10:] if (user.phone and len(user.phone) >= 10) else '9999999999'
                        
                        # Si es Nota de Entrega y no tiene datos, forzar Consumidor Final genérico
                        if document_type == 'nota_entrega' and billing_type != 'with_data':
                            identification = '9999999999999'
                        
                        customer = Customer.objects.filter(company=user_company, identification=identification).first()
                        
                        if not customer:
                            customer = Customer.objects.create(
                                user=user,
                                company=user_company,
                                name=f"{user.first_name} {user.last_name}".strip() or user.email,
                                email=user.email,
                                identification=identification,
                                identification_type='07' if identification == '9999999999999' else '05'
                            )
                        elif not customer.user:
                            # Vincular el usuario si el cliente existía sin usuario
                            customer.user = user
                            customer.save()
                
                order = Order.objects.create(
                    company=user_company,
                    customer=customer,
                    created_by=user,
                    document_type=document_type,
                    contact_phone=contact_phone,
                    latitude=latitude,
                    longitude=longitude,
                    **validated_data
                )
                
                if not items_data:
                    raise serializers.ValidationError("El pedido debe contener al menos un producto.")
                
                total_amount = Decimal('0')
                for item_data in items_data:
                    product_id = item_data.get('product') or item_data.get('product_id')
                    if not product_id:
                        continue
                        
                    try:
                        product = ProductTemplate.objects.get(id=product_id)
                    except ProductTemplate.DoesNotExist:
                        raise serializers.ValidationError(f"Producto con ID {product_id} no encontrado.")
                        
                    quantity = Decimal(str(item_data.get('quantity', 1)))
                    
                    tax_rate = product.tax_rate
                    unit_price_inclusive = product.unit_price
                    
                    if tax_rate > 0:
                        unit_price_exclusive = unit_price_inclusive / (Decimal('1.0') + (tax_rate / Decimal('100.0')))
                    else:
                        unit_price_exclusive = unit_price_inclusive
                    
                    unit_price_exclusive = unit_price_exclusive.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    
                    item = OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        unit_price=unit_price_exclusive,
                        tax_rate=tax_rate
                    )
                    
                    # 1. Descontar del inventario general (OUT)
                    try:
                        InventoryService.register_movement(
                            company=user_company,
                            product=product,
                            movement_type='OUT',
                            quantity=quantity,
                            reference=f"ORD-{order.id}",
                            notes=f"Venta en pedido #{order.id}",
                            user=user
                        )
                    except Exception as e:
                        print(f"⚠️ Error al registrar movimiento de stock: {e}")

                    # 2. Si hay ruta, actualizar el stock de la furgoneta (quantity_sold)
                    if hasattr(order, 'route') and order.route:
                        route_product = RouteProduct.objects.filter(route=order.route, product=product).first()
                        if route_product:
                            route_product.quantity_sold += quantity
                            route_product.save()

                    total_amount += item.total
                    
                order.total_amount = total_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                order.save()
                
                return order
        except Exception as e:
            print(f"ERROR creating order: {str(e)}")
            import traceback
            traceback.print_exc()
            if isinstance(e, serializers.ValidationError):
                raise e
            raise serializers.ValidationError(f"Error al crear el pedido: {str(e)}")

