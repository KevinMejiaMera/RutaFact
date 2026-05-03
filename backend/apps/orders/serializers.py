# -*- coding: utf-8 -*-
from rest_framework import serializers
from .models import Order, OrderItem
from apps.invoicing.models import ProductTemplate, Customer
from apps.companies.models import Company
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
            'delivery_reference', 'contact_phone',
            'status', 'status_display', 'subtotal_without_tax', 'total_tax', 
            'total_amount', 'invoice', 'notes', 'items', 'created_at'
        ]
        read_only_fields = ['company', 'status', 'total_amount', 'invoice']

class OrderCreateSerializer(serializers.ModelSerializer):
    items = serializers.ListField(
        child=serializers.DictField(),
        write_only=True
    )
    
    class Meta:
        model = Order
        fields = ['delivery_address', 'delivery_reference', 'contact_phone', 'notes', 'items']
    
    def create(self, validated_data):
        from django.db import transaction
        print(f"DEBUG: OrderCreateSerializer.create data={validated_data}")
        items_data = validated_data.pop('items')
        user = self.context['request'].user
        
        try:
            billing_type = self.context['request'].data.get('billing_type', 'final_consumer')
            print(f"DEBUG: Billing Type selected: {billing_type}")
            
            with transaction.atomic():
                # Determinar la empresa
                user_company = user.company or Company.objects.filter(id=1).first() or Company.objects.first()
                
                if billing_type == 'final_consumer':
                    # BUSCAR O CREAR CONSUMIDOR FINAL GENÉRICO (13 nueves para SRI)
                    customer, created = Customer.objects.get_or_create(
                        company=user_company,
                        identification='9999999999999',
                        defaults={
                            'name': 'CONSUMIDOR FINAL',
                            'identification_type': '07'
                        }
                    )
                    company = user_company
                else:
                    # FACTURA CON DATOS: Intentar usar perfil del usuario
                    try:
                        customer = user.customer_profile
                        company = customer.company
                    except Exception:
                        # Si no existe, crearlo con sus datos de usuario
                        print(f"DEBUG: Creating profile for user {user.id} on the fly")
                        customer = Customer.objects.create(
                            user=user,
                            company=user_company,
                            name=f"{user.first_name} {user.last_name}".strip() or user.email,
                            email=user.email,
                            identification=user.phone or f"ID{user.id}", # Placeholder si no tiene ID
                            identification_type='05' # Cédula por defecto
                        )
                        company = user_company
                
                order = Order.objects.create(
                    company=company,
                    customer=customer,
                    created_by=user,
                    **validated_data
                )
                print(f"DEBUG: Order base created: {order.id}")
                
                if not items_data:
                    raise serializers.ValidationError("El pedido debe contener al menos un producto.")
                
                total_amount = Decimal('0')
                for item_data in items_data:
                    print(f"DEBUG: Processing item: {item_data}")
                    product_id = item_data.get('product_id')
                    if not product_id:
                        raise serializers.ValidationError("Falta product_id en uno de los ítems.")
                        
                    product = ProductTemplate.objects.get(id=product_id)
                    quantity = Decimal(str(item_data.get('quantity', 1)))
                    
                    # Desglosar IVA: El precio en ProductTemplate es el PRECIO FINAL (Inclusive)
                    tax_rate = product.tax_rate
                    unit_price_inclusive = product.unit_price
                    
                    if tax_rate > 0:
                        unit_price_exclusive = unit_price_inclusive / (Decimal('1.0') + (tax_rate / Decimal('100.0')))
                    else:
                        unit_price_exclusive = unit_price_inclusive
                    
                    # REDONDEAR para evitar error de max_digits en Django
                    unit_price_exclusive = unit_price_exclusive.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    
                    print(f"DEBUG: Product: {product.name}, Inclusive: {unit_price_inclusive}, Exclusive: {unit_price_exclusive}")
                    
                    item = OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        unit_price=unit_price_exclusive,
                        tax_rate=tax_rate
                    )
                    total_amount += item.total
                    
                # Redondear el total final
                order.total_amount = total_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                order.save()
                print(f"DEBUG: Order finalized. Total: {total_amount}")
                
                return order
        except Exception as e:
            print(f"ERROR creating order: {str(e)}")
            import traceback
            traceback.print_exc()
            if isinstance(e, serializers.ValidationError):
                raise e
            raise serializers.ValidationError(f"Error al crear el pedido: {str(e)}")

