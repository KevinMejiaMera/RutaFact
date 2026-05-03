# -*- coding: utf-8 -*-
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from apps.orders.models import Order
from apps.orders.serializers import OrderSerializer, OrderCreateSerializer
from apps.api.user_company_helper import get_user_companies_exact
from apps.sri_integration.models import SRIConfiguration, ElectronicDocument, DocumentItem, DocumentTax, DocumentPayment
from decimal import Decimal, ROUND_HALF_UP

class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    filterset_fields = ['company', 'customer', 'status']
    search_fields = ['customer__name', 'delivery_address']
    ordering_fields = ['created_at', 'total_amount']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return OrderCreateSerializer
        return OrderSerializer

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def cancel(self, request, pk=None):
        """
        Cancela un pedido y revierte el stock
        """
        from django.db import transaction
        order = self.get_object()
        
        if order.status == 'CANCELLED':
            return Response({"error": "El pedido ya está cancelado"}, status=status.HTTP_400_BAD_REQUEST)
        
        if order.status == 'COMPLETED' and not request.user.is_staff:
            return Response({"error": "No se puede cancelar un pedido ya completado/facturado"}, status=status.HTTP_400_BAD_REQUEST)

        from apps.inventory.services import InventoryService
        from apps.logistics.models import RouteProduct
        
        try:
            with transaction.atomic():
                order.status = 'CANCELLED'
                order.save()
                
                # Revertir stock
                for item in order.items.all():
                    # 1. Devolver al inventario general (IN)
                    InventoryService.register_movement(
                        company=order.company,
                        product=item.product,
                        movement_type='IN',
                        quantity=item.quantity,
                        reference=f"CAN-{order.id}",
                        notes=f"Cancelación de pedido #{order.id}",
                        user=request.user
                    )
                    
                    # 2. Si tenía ruta, devolver al stock del camión
                    if order.route:
                        route_product = RouteProduct.objects.filter(route=order.route, product=item.product).first()
                        if route_product:
                            route_product.quantity_sold -= item.quantity
                            route_product.save()
                            
            return Response({"success": True, "message": "Pedido cancelado correctamente y stock revertido."})
        except Exception as e:
            return Response({"error": f"Error al cancelar pedido: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    def get_queryset(self):
        user = self.request.user
        
        if not user or not user.is_authenticated:
            return Order.objects.none()

        if user.is_superuser:
            return Order.objects.all()
        
        if user.role.upper() in ['CLIENTE', 'CLIENT', 'CUSTOMER']:
            from django.db.models import Q
            return Order.objects.filter(Q(customer__user=user) | Q(created_by=user))
        
        companies = get_user_companies_exact(user)
        return Order.objects.filter(company__in=companies)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def complete_and_invoice(self, request, pk=None):
        """
        Completa un pedido, reduce stock y genera factura SRI o Nota de Entrega.
        """
        from django.db import transaction
        import logging
        import traceback
        from apps.inventory.services import InventoryService
        
        logger = logging.getLogger(__name__)
        order = self.get_object()
        
        if order.status != 'PENDING':
            return Response({"error": f"El pedido ya está en estado {order.status}"}, status=status.HTTP_400_BAD_REQUEST)

        if not order.customer:
            return Response({"error": "El pedido no tiene un cliente asociado."}, status=status.HTTP_400_BAD_REQUEST)

        doc_type = request.data.get('document_type', order.document_type)
        
        try:
            with transaction.atomic():
                # Registrar quién completa el pedido
                order.seller = request.user
                order.status = 'COMPLETED'
                order.save()

                def fix_decimal(value, places=2):
                    if value is None: return Decimal('0.00')
                    if isinstance(value, (int, float)):
                        value = Decimal(str(value))
                    elif isinstance(value, str):
                        value = Decimal(value)
                    quantizer = Decimal('0.' + '0' * places)
                    return value.quantize(quantizer, rounding=ROUND_HALF_UP)

                if doc_type == 'factura':
                    # LÓGICA FACTURA SRI
                    sri_config = order.company.sri_configuration
                    if not sri_config:
                        raise ValueError("La empresa no tiene configuración SRI activa.")

                    sequence = sri_config.get_next_sequence('INVOICE')
                    document_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
                    
                    # Crear Documento Electrónico (SRI)
                    electronic_doc = ElectronicDocument.objects.create(
                        company=order.company,
                        document_type='INVOICE',
                        document_number=document_number,
                        issue_date=timezone.now().date(),
                        customer_identification_type=order.customer.identification_type,
                        customer_identification=order.customer.identification,
                        customer_name=order.customer.name,
                        customer_address=order.delivery_address or order.customer.address or '',
                        customer_email=order.customer.email or '',
                        customer_phone=order.customer.phone or '',
                        status='DRAFT'
                    )

                    total_subtotal = Decimal('0.00')
                    total_tax = Decimal('0.00')

                    for item in order.items.all():
                        qty = fix_decimal(item.quantity, 2)
                        u_price = fix_decimal(item.unit_price, 6)
                        subtotal = fix_decimal(qty * u_price, 2)
                        tax_rate = fix_decimal(item.tax_rate, 2)
                        tax_amount = fix_decimal(subtotal * tax_rate / 100, 2)

                        # Crear Ítem de Factura
                        doc_item = DocumentItem.objects.create(
                            document=electronic_doc,
                            main_code=item.product.main_code,
                            description=item.product.name,
                            quantity=qty,
                            unit_price=u_price,
                            discount=Decimal('0.00'),
                            subtotal=subtotal
                        )

                        # Crear Impuesto del Ítem (IVA)
                        DocumentTax.objects.create(
                            document=electronic_doc,
                            item=doc_item,
                            tax_code='2', # IVA
                            percentage_code='4', # 15% (Ojo: ajustable según SRI config si varía)
                            rate=tax_rate,
                            taxable_base=subtotal,
                            tax_amount=tax_amount
                        )

                        # REDUCIR STOCK
                        InventoryService.register_movement(
                            company=order.company,
                            product=item.product,
                            movement_type='OUT',
                            quantity=qty,
                            reference=f"Factura {document_number}",
                            notes=f"Venta Pedido #{order.id}",
                            user=request.user
                        )

                        total_subtotal += subtotal
                        total_tax += tax_amount

                    # Totales finales redondeados
                    electronic_doc.subtotal_without_tax = fix_decimal(total_subtotal, 2)
                    electronic_doc.total_tax = fix_decimal(total_tax, 2)
                    electronic_doc.total_amount = fix_decimal(total_subtotal + total_tax, 2)

                    # Resumen de Impuesto a nivel de documento (Obligatorio SRI)
                    DocumentTax.objects.create(
                        document=electronic_doc,
                        tax_code='2',
                        percentage_code='4',
                        rate=Decimal('15.00'),
                        taxable_base=electronic_doc.subtotal_without_tax,
                        tax_amount=electronic_doc.total_tax
                    )

                    # Pago por defecto (Efectivo - Requerido por SRI en facturas)
                    DocumentPayment.objects.create(
                        document=electronic_doc,
                        payment_method_code='01',
                        amount=electronic_doc.total_amount,
                        payment_term=0,
                        time_unit='dias'
                    )

                    electronic_doc.status = 'PENDING'
                    electronic_doc.save()
                    
                    order.invoice = electronic_doc
                    order.save()

                    # Lanzar procesamiento SRI en background tras commit
                    from apps.sri_integration.tasks import process_document_async
                    transaction.on_commit(lambda: process_document_async.delay(electronic_doc.id))
                    
                    return Response({
                        "success": True,
                        "message": "Pedido completado y factura enviada al SRI.",
                        "invoice_number": document_number
                    })

                else:
                    # LÓGICA NOTA DE ENTREGA INTERNA
                    internal_number = f"INT-{order.id:06d}"
                    
                    electronic_doc = ElectronicDocument.objects.create(
                        company=order.company,
                        document_type='INTERNAL_NOTE',
                        document_number=internal_number,
                        issue_date=timezone.now().date(),
                        customer_identification_type=order.customer.identification_type,
                        customer_identification=order.customer.identification,
                        customer_name=order.customer.name,
                        customer_address=order.delivery_address or order.customer.address or '',
                        status='INTERNAL'
                    )

                    total_amount = Decimal('0.00')
                    for item in order.items.all():
                        qty = fix_decimal(item.quantity, 2)
                        u_price = fix_decimal(item.unit_price, 2)
                        subtotal = fix_decimal(qty * u_price, 2)
                        
                        DocumentItem.objects.create(
                            document=electronic_doc,
                            main_code=item.product.main_code,
                            description=item.product.name,
                            quantity=qty,
                            unit_price=u_price,
                            subtotal=subtotal
                        )
                        
                        # REDUCIR STOCK
                        InventoryService.register_movement(
                            company=order.company,
                            product=item.product,
                            movement_type='OUT',
                            quantity=qty,
                            reference=f"Nota {internal_number}",
                            notes=f"Venta Interna Pedido #{order.id}",
                            user=request.user
                        )
                        total_amount += subtotal

                    electronic_doc.total_amount = fix_decimal(total_amount, 2)
                    electronic_doc.save()
                    
                    order.invoice = electronic_doc
                    order.save()

                    return Response({
                        "success": True,
                        "message": "Pedido completado con nota de entrega interna.",
                        "internal_number": internal_number
                    })

        except Exception as e:
            logger.error(f"💥 Error crítico en complete_and_invoice: {str(e)}")
            logger.error(traceback.format_exc())
            return Response({
                "error": "PROCESSING_ERROR", 
                "message": f"Error al procesar el pedido: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
