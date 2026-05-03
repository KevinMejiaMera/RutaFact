# -*- coding: utf-8 -*-
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from apps.logistics.models import Vehicle, Route, RouteStop
from apps.api.serializers.logistics_serializers import (
    VehicleSerializer, RouteSerializer, RouteDetailSerializer, RouteStopSerializer
)
from apps.api.user_company_helper import get_user_companies_exact
from decimal import Decimal
from django.utils import timezone

class VehicleViewSet(viewsets.ModelViewSet):
    serializer_class = VehicleSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['company', 'is_active']

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Vehicle.objects.all()
        user_companies = get_user_companies_exact(user)
        return Vehicle.objects.filter(company__in=user_companies)

class RouteViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['company', 'status', 'date', 'driver', 'vehicle']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return RouteDetailSerializer
        return RouteSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Route.objects.all()
        user_companies = get_user_companies_exact(user)
        queryset = Route.objects.filter(company__in=user_companies)
        
        # Si no es admin, solo ve sus propias rutas
        if not user.is_staff and not user.is_company_admin:
            queryset = queryset.filter(driver=user)
        return queryset

    @action(detail=True, methods=['post'])
    def start_route(self, request, pk=None):
        route = self.get_object()
        # Permitir PENDING o DRAFT (por compatibilidad)
        if route.status not in ['PENDING', 'DRAFT']:
            return Response({'error': f'Estado actual {route.status} no permite inicio. Solo PENDING/DRAFT.'}, status=status.HTTP_400_BAD_REQUEST)
        
        from django.db import transaction
        
        try:
            with transaction.atomic():
                route.status = 'ACTIVE'
                route.save()
                # Nota: El stock se descuenta automáticamente al asignar productos a la ruta
                # en apps.logistics.models.RouteProduct.save()
            return Response({'status': 'Ruta activada correctamente'})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def record_delivery(self, request, pk=None):
        """Registra productos entregados y genera factura electrónica completa"""
        route = self.get_object()
        deliveries = request.data.get('deliveries', [])
        customer_id = request.data.get('customer_id')
        customer_name = request.data.get('customer_name', 'Consumidor Final')
        notes = request.data.get('notes', '')
        
        from django.db import transaction
        from apps.logistics.models import RouteDelivery, RouteDeliveryItem
        from apps.invoicing.models import Customer
        from apps.sri_integration.models import ElectronicDocument, DocumentItem, DocumentTax, DocumentPayment
        from apps.sri_integration.tasks import process_document_async
        from decimal import Decimal, ROUND_HALF_UP
        from django.utils import timezone
        
        try:
            with transaction.atomic():
                # 1. Registro interno de la entrega
                delivery_record = RouteDelivery.objects.create(
                    route=route,
                    customer_name=customer_name,
                    notes=notes
                )
                
                customer = None
                if customer_id:
                    customer = Customer.objects.filter(id=customer_id, company=route.company).first()
                
                electronic_doc = None
                if customer:
                    # Crear factura en borrador (el modelo genera número y clave solo)
                    electronic_doc = ElectronicDocument.objects.create(
                        company=route.company,
                        document_type='INVOICE',
                        issue_date=timezone.now().date(),
                        customer_identification_type=customer.identification_type,
                        customer_identification=customer.identification,
                        customer_name=customer.name,
                        customer_address=customer.address or '',
                        customer_email=customer.email or '',
                        status='DRAFT'
                    )
                
                total_subtotal = Decimal('0.00')
                total_tax = Decimal('0.00')

                for item in deliveries:
                    p_id = item.get('product_id')
                    qty = Decimal(str(item.get('qty', 0)))
                    rp = route.products.filter(product_id=p_id).first()
                    
                    if rp and qty > 0:
                        # Descontar del camión
                        rp.quantity_sold += qty
                        rp.save()
                        
                        # Guardar detalle de entrega
                        RouteDeliveryItem.objects.create(
                            delivery=delivery_record,
                            product=rp.product,
                            quantity=qty
                        )
                        
                        # Detalle de factura
                        if electronic_doc:
                            unit_price = rp.product.unit_price
                            # SRI requiere base imponible (subtotal antes de impuestos)
                            subtotal = (qty * unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                            tax_amount = (subtotal * Decimal('0.15')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                            
                            doc_item = DocumentItem.objects.create(
                                document=electronic_doc,
                                main_code=rp.product.main_code,
                                description=rp.product.name,
                                quantity=qty,
                                unit_price=unit_price,
                                subtotal=subtotal
                            )
                            
                            # Impuesto por ITEM (Obligatorio SRI)
                            DocumentTax.objects.create(
                                document=electronic_doc,
                                item=doc_item,
                                tax_code='2', # IVA
                                percentage_code='4', # 15% según el modelo
                                rate=Decimal('15.00'),
                                taxable_base=subtotal,
                                tax_amount=tax_amount
                            )
                            
                            total_subtotal += subtotal
                            total_tax += tax_amount
                
                # Finalizar factura y añadir resumen de impuestos y pagos
                if electronic_doc:
                    electronic_doc.subtotal_without_tax = total_subtotal
                    electronic_doc.total_tax = total_tax
                    electronic_doc.total_amount = total_subtotal + total_tax
                    
                    # Resumen de Impuesto a nivel de DOCUMENTO (Obligatorio SRI)
                    DocumentTax.objects.create(
                        document=electronic_doc,
                        tax_code='2',
                        percentage_code='4',
                        rate=Decimal('15.00'),
                        taxable_base=total_subtotal,
                        tax_amount=total_tax
                    )
                    
                    # Forma de Pago por defecto: Efectivo (Obligatorio SRI)
                    DocumentPayment.objects.create(
                        document=electronic_doc,
                        payment_method_code='01', # Efectivo
                        amount=electronic_doc.total_amount,
                        payment_term=0,
                        time_unit='dias'
                    )
                    
                    electronic_doc.status = 'PENDING'
                    electronic_doc.save()
                    
                    # Enviar al SRI de forma asíncrona
                    transaction.on_commit(lambda: process_document_async.delay(electronic_doc.id))

            msg = 'Entrega registrada correctamente'
            if electronic_doc:
                msg += f'. Factura {electronic_doc.document_number} generada.'
            
            return Response({'status': msg, 'invoice_id': electronic_doc.id if electronic_doc else None})
            
        except Exception as e:
            return Response({'error': f"Error en servidor: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def complete_route(self, request, pk=None):
        route = self.get_object()
        if route.status != 'ACTIVE':
            return Response({'error': f'Estado actual {route.status} no permite finalizar. Debe estar ACTIVE.'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.inventory.services import InventoryService
        from django.db import transaction
        
        try:
            with transaction.atomic():
                route.status = 'COMPLETED'
                route.save()
                
                # RECONCILIACIÓN AUTOMÁTICA: 
                # Lo que vuelve al local es (Cargado - Vendido)
                for rp in route.products.all():
                    returned_qty = rp.quantity_loaded - rp.quantity_sold
                    if returned_qty > 0:
                        rp.quantity_returned = returned_qty
                        rp.save()
                        
                        InventoryService.register_movement(
                            company=route.company,
                            product=rp.product,
                            movement_type='IN',
                            quantity=returned_qty,
                            reference=f'RUTA-FIN-{route.id}',
                            notes=f'Reintegro automático de sobrantes - Ruta: {route.name}',
                            user=request.user
                        )
            return Response({'status': 'Ruta finalizada. El stock restante ha sido devuelto al local.'})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class RouteStopViewSet(viewsets.ModelViewSet):
    serializer_class = RouteStopSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        # Filtrar por las rutas que el usuario puede ver
        user = self.request.user
        user_companies = get_user_companies_exact(user)
        return RouteStop.objects.filter(route__company__in=user_companies)

    @action(detail=True, methods=['post'])
    def mark_visited(self, request, pk=None):
        stop = self.get_object()
        from django.utils import timezone
        stop.status = 'VISITED'
        stop.arrival_time = timezone.now()
        stop.save()
        return Response({'status': 'Stop marked as visited'})
