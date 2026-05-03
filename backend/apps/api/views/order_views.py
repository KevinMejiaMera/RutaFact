# -*- coding: utf-8 -*-
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from apps.orders.models import Order
from apps.orders.serializers import OrderSerializer, OrderCreateSerializer
from apps.api.user_company_helper import get_user_companies_exact
from apps.sri_integration.models import SRIConfiguration, ElectronicDocument, DocumentItem
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

    @action(detail=True, methods=['post'])
    def complete_and_invoice(self, request, pk=None):
        """
        Marca un pedido como completado y genera la factura electrónica
        """
        order = self.get_object()
        
        if order.status != 'PENDING':
            return Response(
                {"error": "ORDER_NOT_PENDING", "message": "Solo se pueden completar pedidos pendientes."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # 1. Obtener configuración SRI de la empresa
        sri_config = SRIConfiguration.objects.filter(company=order.company, is_active=True).first()
        if not sri_config:
            return Response(
                {"error": "SRI_CONFIG_MISSING", "message": "No se encontró configuración SRI activa para la empresa."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # 2. Generar Factura Electrónica (ElectronicDocument)
            sequence = sri_config.get_next_sequence('INVOICE')
            document_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
            
            def fix_decimal(value, places=2):
                if isinstance(value, (int, float)):
                    value = Decimal(str(value))
                elif isinstance(value, str):
                    value = Decimal(value)
                quantizer = Decimal('0.' + '0' * places)
                return value.quantize(quantizer, rounding=ROUND_HALF_UP)

            electronic_doc = ElectronicDocument.objects.create(
                company=order.company,
                document_type='INVOICE',
                document_number=document_number,
                issue_date=order.created_at.date(),
                customer_identification_type=order.customer.identification_type,
                customer_identification=order.customer.identification,
                customer_name=order.customer.name,
                customer_address=order.delivery_address,
                customer_email=order.customer.email,
                customer_phone=order.customer.phone,
                status='DRAFT'
            )
            
            electronic_doc.access_key = electronic_doc._generate_access_key()
            
            total_subtotal = Decimal('0.00')
            total_tax = Decimal('0.00')
            
            for item in order.items.all():
                quantity = fix_decimal(item.quantity, 6)
                unit_price = fix_decimal(item.unit_price, 6)
                discount = Decimal('0.00')
                subtotal = fix_decimal((quantity * unit_price) - discount, 2)
                
                DocumentItem.objects.create(
                    document=electronic_doc,
                    main_code=item.product.main_code,
                    auxiliary_code=item.product.auxiliary_code,
                    description=item.product.name,
                    quantity=quantity,
                    unit_price=unit_price,
                    discount=discount,
                    subtotal=subtotal
                )
                
                # IVA 15% (O el que tenga el producto)
                tax_amount = fix_decimal(subtotal * item.tax_rate / 100, 2)
                total_subtotal += subtotal
                total_tax += tax_amount
            
            electronic_doc.subtotal_without_tax = fix_decimal(total_subtotal, 2)
            electronic_doc.total_tax = fix_decimal(total_tax, 2)
            electronic_doc.total_amount = fix_decimal(total_subtotal + total_tax, 2)
            electronic_doc.status = 'PENDING'
            electronic_doc.save()
            
            # 3. Vincular factura al pedido y marcar como completado
            order.status = 'COMPLETED'
            order.invoice = electronic_doc
            order.save()
            
            # 4. Enviar a procesamiento asíncrono
            from apps.sri_integration.tasks import process_document_async
            process_document_async.delay(electronic_doc.id)
            
            return Response({
                "success": True,
                "message": "Pedido completado y factura enviada al SRI.",
                "order_id": order.id,
                "invoice_id": electronic_doc.id,
                "document_number": document_number
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {"error": "PROCESSING_ERROR", "message": f"Error al procesar factura: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
