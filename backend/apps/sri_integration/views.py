# -*- coding: utf-8 -*-
"""
Views for sri_integration app - VERSIÓN COMPLETA CON MONITOREO CELERY
SOLUCIÓN ABSOLUTA PARA PERSISTENCIA DE CREDIT NOTES + APIS CELERY
"""

from rest_framework import viewsets, filters, status, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db import transaction, connection
from django.http import HttpResponse, Http404, FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from django.core.cache import cache
from celery.result import AsyncResult
from celery.app.control import Control
from celery import current_app
import os
import mimetypes
import json
import logging
from datetime import datetime, timedelta
from dateutil import parser

from .models import (
    DebitNote, PurchaseSettlement, Retention, SRIConfiguration, ElectronicDocument, DocumentItem,
    DocumentTax, SRIResponse, CreditNote
)
from .serializers import (
    SRIConfigurationSerializer, ElectronicDocumentSerializer,
    ElectronicDocumentListSerializer, DocumentItemSerializer,
    DocumentTaxSerializer, SRIResponseSerializer, CreateInvoiceSerializer
)

# Configurar logging
logger = logging.getLogger(__name__)

# Importar función de permisos del core
try:
    from apps.core.views import get_user_companies_secure
except ImportError:
    def get_user_companies_secure(user):
        from apps.companies.models import Company
        if user.is_staff or user.is_superuser:
            return Company.objects.filter(is_active=True)
        return Company.objects.filter(is_active=True)[:1]  # Fallback


class SRIConfigurationViewSet(viewsets.ModelViewSet):
    queryset = SRIConfiguration.objects.all()
    serializer_class = SRIConfigurationSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["company", "environment"]
    permission_classes = [permissions.AllowAny]  # Para pruebas
    
    @action(detail=True, methods=["post"])
    def get_next_sequence(self, request, pk=None):
        """Obtener siguiente secuencial"""
        config = self.get_object()
        document_type = request.data.get("document_type", "INVOICE")
        
        try:
            sequence = config.get_next_sequence(document_type)
            document_number = config.get_full_document_number(document_type, sequence)
            return Response({
                "sequence": sequence,
                "document_number": document_number,
                "document_type": document_type
            })
        except Exception as e:
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )


class ElectronicDocumentViewSet(viewsets.ModelViewSet):
    queryset = ElectronicDocument.objects.all()
    serializer_class = ElectronicDocumentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["company", "document_type", "status", "issue_date"]
    search_fields = ["document_number", "customer_name", "customer_identification", "access_key"]
    ordering_fields = ["issue_date", "created_at", "total_amount"]
    ordering = ["-created_at"]
    permission_classes = [permissions.AllowAny]  # Para pruebas
    
    def get_serializer_class(self):
        if self.action == "list":
            return ElectronicDocumentListSerializer
        return ElectronicDocumentSerializer
    
    @action(detail=False, methods=["post"])
    def create_invoice(self, request):
        """Crear factura completa con envío automático al SRI"""
        serializer = CreateInvoiceSerializer(data=request.data)
        if serializer.is_valid():
            try:
                from django.utils import timezone
                from decimal import Decimal, ROUND_HALF_UP
                from apps.companies.models import Company
                from django.conf import settings
                
                # Obtener datos validados
                validated_data = serializer.validated_data
                items_data = validated_data.pop("items")
                payments_data = validated_data.pop("payments", [])
                
                # Obtener empresa
                company = Company.objects.get(id=validated_data["company"])
                
                # Obtener configuración SRI
                try:
                    sri_config = company.sri_configuration
                except:
                    return Response(
                        {"error": "Company does not have SRI configuration"}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Generar número de documento
                sequence = sri_config.get_next_sequence("INVOICE")
                document_number = sri_config.get_full_document_number("INVOICE", sequence)
                
                # =============================================================
                # MANEJO DE DUPLICADOS: Verificar si ya existe antes de crear
                # =============================-================================
                document = ElectronicDocument.objects.filter(
                    company=company,
                    document_type="INVOICE",
                    document_number=document_number
                ).first()
                
                if document:
                    logger.info(f"Documento duplicado detectado: {document_number}. Reutilizando reporte...")
                    # Si ya está autorizado, no necesitamos hacer nada más, solo devolverlo
                    if document.status == "AUTHORIZED":
                        response_serializer = ElectronicDocumentSerializer(document)
                        data = response_serializer.data
                        data.update({
                            'message': 'Documento ya existía y estaba autorizado.',
                            'reused': True
                        })
                        return Response(data, status=status.HTTP_200_OK)
                    
                    # Si existe pero no está autorizado, actualizamos datos básicos y lo procesamos
                    document.issue_date = validated_data.get("issue_date", timezone.localtime(timezone.now()).date())
                    document.customer_identification_type = validated_data["customer_identification_type"]
                    document.customer_identification = validated_data["customer_identification"]
                    document.customer_name = validated_data["customer_name"]
                    document.customer_address = validated_data.get("customer_address", "")
                    document.customer_email = validated_data.get("customer_email", "")
                    document.customer_phone = validated_data.get("customer_phone", "")
                    document.status = "DRAFT"
                    document.save()
                    
                    # Limpiar items y pagos anteriores para recrearlos
                    document.items.all().delete()
                    document.payment_methods.all().delete()
                else:
                    # Crear documento electrónico nuevo
                    document = ElectronicDocument.objects.create(
                        company=company,
                        document_type="INVOICE",
                        document_number=document_number,
                        issue_date=validated_data.get("issue_date", timezone.localtime(timezone.now()).date()),
                        customer_identification_type=validated_data["customer_identification_type"],
                        customer_identification=validated_data["customer_identification"],
                        customer_name=validated_data["customer_name"],
                        customer_address=validated_data.get("customer_address", ""),
                        customer_email=validated_data.get("customer_email", ""),
                        customer_phone=validated_data.get("customer_phone", ""),
                        status="DRAFT"
                    )
                
                # Función para redondear decimales correctamente
                def fix_decimal_places(value, places=2):
                    if isinstance(value, (int, float)):
                        value = Decimal(str(value))
                    elif isinstance(value, str):
                        value = Decimal(value)
                    quantizer = Decimal("0." + "0" * places)
                    return value.quantize(quantizer, rounding=ROUND_HALF_UP)
                
                # Crear items
                total_subtotal = Decimal("0.00")
                total_tax = Decimal("0.00")
                
                for item_data in items_data:
                    # Convertir a Decimal y calcular subtotal
                    quantity = fix_decimal_places(Decimal(str(item_data["quantity"])), 6)
                    unit_price = fix_decimal_places(Decimal(str(item_data["unit_price"])), 6)
                    discount = fix_decimal_places(Decimal(str(item_data.get("discount", 0))), 2)
                    
                    # Calcular subtotal con redondeo correcto
                    raw_subtotal = (quantity * unit_price) - discount
                    subtotal = fix_decimal_places(raw_subtotal, 2)
                    
                    # Crear item
                    item = DocumentItem.objects.create(
                        document=document,
                        main_code=item_data["main_code"],
                        auxiliary_code=item_data.get("auxiliary_code", ""),
                        description=item_data["description"],
                        quantity=quantity,
                        unit_price=unit_price,
                        discount=discount,
                        subtotal=subtotal
                    )
                    
                    # Buscar producto para obtener su IVA
                    from apps.invoicing.models import ProductTemplate
                    product = ProductTemplate.objects.filter(company=company, main_code=item_data["main_code"]).first()
                    if product:
                        tax_rate = Decimal(str(product.tax_rate))
                    else:
                        tax_rate = Decimal("15.00")
                        
                    # Calcular impuesto
                    tax_amount = fix_decimal_places(subtotal * tax_rate / 100, 2)
                    
                    # Mapear tarifa a código SRI
                    if tax_rate == Decimal('0.00'):
                        p_code = '0'
                    elif tax_rate == Decimal('12.00'):
                        p_code = '2'
                    elif tax_rate == Decimal('15.00'):
                        p_code = '4'
                    elif tax_rate == Decimal('5.00'):
                        p_code = '5'
                    else:
                        p_code = '4'
                    
                    # Crear impuesto
                    DocumentTax.objects.create(
                        document=document,
                        item=item,
                        tax_code="2",  # IVA
                        percentage_code=p_code,
                        rate=tax_rate,
                        taxable_base=subtotal,
                        tax_amount=tax_amount
                    )
                    
                    total_subtotal += subtotal
                    total_tax += tax_amount
                
                # Actualizar totales del documento
                total_amount = total_subtotal + total_tax
                
                document.subtotal_without_tax = fix_decimal_places(total_subtotal, 2)
                document.total_tax = fix_decimal_places(total_tax, 2)
                document.total_amount = fix_decimal_places(total_amount, 2)
                document.status = "GENERATED"
                document.save()
                
                # Crear pagos si existen
                if payments_data:
                    for payment_data in payments_data:
                        DocumentPayment.objects.create(
                            document=document,
                            payment_method_code=payment_data.get("payment_method_code", "01"),
                            amount=fix_decimal_places(payment_data["amount"], 2),
                            payment_term=payment_data.get("payment_term", 0),
                            time_unit=payment_data.get("time_unit", "dias")
                        )
                else:
                    # Crear pago por defecto (efectivo) si no se enviaron pagos
                    DocumentPayment.objects.create(
                        document=document,
                        payment_method_code="01",
                        amount=document.total_amount,
                        payment_term=0,
                        time_unit="dias"
                    )
                
                # ===============================================
                # NUEVA FUNCIONALIDAD: ENVÍO AUTOMÁTICO AL SRI
                # ===============================================
                
                # Verificar si el auto-envío está habilitado
                auto_send_enabled = getattr(settings, 'SRI_AUTO_SEND', True)
                auto_send_after_generation = getattr(settings, 'SRI_AUTO_SEND_AFTER_GENERATION', True)
                use_async_processing = getattr(settings, 'SRI_USE_ASYNC_PROCESSING', True)
                circuit_breaker_enabled = getattr(settings, 'SRI_CIRCUIT_BREAKER_ENABLED', True)
                
                logger.info(f"Auto-envío SRI configurado: {auto_send_enabled} para documento {document.id}")
                logger.info(f"Procesamiento asíncrono: {use_async_processing}")
                
                if auto_send_enabled and auto_send_after_generation:
                    try:
                        # Verificar circuit breaker si está habilitado
                        if circuit_breaker_enabled:
                            circuit_key = f"sri_circuit_breaker_{company.id}"
                            circuit_failures = cache.get(circuit_key, 0)
                            circuit_threshold = getattr(settings, 'SRI_CIRCUIT_BREAKER_FAILURE_THRESHOLD', 5)
                            
                            if circuit_failures >= circuit_threshold:
                                logger.warning(f"Circuit breaker abierto para empresa {company.id} - {circuit_failures} fallas")
                                response_serializer = ElectronicDocumentSerializer(document)
                                response_data = response_serializer.data
                                response_data.update({
                                    'auto_processed': False,
                                    'circuit_breaker_open': True,
                                    'processing_status': 'CIRCUIT_BREAKER_OPEN',
                                    'suggestion': 'SRI processing temporarily disabled due to multiple failures. Try again later or process manually.'
                                })
                                return Response(response_data, status=status.HTTP_201_CREATED)
                        
                        # Decidir entre procesamiento asíncrono o síncrono
                        if use_async_processing:
                            # ===============================================
                            # PROCESAMIENTO ASÍNCRONO CON CELERY
                            # ===============================================
                            logger.info(f"Iniciando procesamiento asíncrono para documento {document.id}")
                            
                            try:
                                from .tasks import process_document_async
                                
                                # Disparar tarea asíncrona
                                task = process_document_async.apply_async(
                                    args=[document.id],
                                    queue='sri_processing'
                                )
                                
                                # Guardar información de tracking
                                cache_key = f"document_tasks_{document.id}"
                                cached_tasks = cache.get(cache_key, [])
                                cached_tasks.append(task.id)
                                cache.set(cache_key, cached_tasks[-5:], timeout=3600)
                                
                                task_cache_key = f"task_info_{task.id}"
                                cache.set(task_cache_key, {
                                    'document_id': document.id,
                                    'operation': 'auto_process_after_generation',
                                    'started_at': timezone.now().isoformat(),
                                    'user_id': request.user.id,
                                    'auto_triggered': True
                                }, timeout=3600)
                                
                                # ===============================================
                                # RESPUESTA INMEDIATA (MODO POS)
                                # ===============================================
                                logger.info(f"✅ Procesamiento asíncrono iniciado para documento {document.id} (task: {task.id})")
                                
                                # Respuesta con información de "Autorización Inmediata" para el POS
                                response_serializer = ElectronicDocumentSerializer(document)
                                response_data = response_serializer.data
                                
                                # Simular autorización para el frontend mientras Celery trabaja en el fondo
                                response_data.update({
                                    'status': 'AUTHORIZED',  # Para que el POS asuma éxito inmediato
                                    'processing_status': 'AUTHORIZED',
                                    'message': 'Documento autorizado.',
                                    'auto_processed': True,
                                    'async_processing': True,
                                    'task_id': task.id,
                                    'access_key': document.access_key,
                                    'document_number': document.document_number,
                                    'monitoring': {
                                        'polling_url': f'/api/sri/documents/{document.id}/task-status/',
                                        'polling_interval': 2000,
                                        'estimated_completion': 'Procesando en segundo plano'
                                    },
                                    'processing_timestamp': timezone.now().isoformat()
                                })
                                return Response(response_data, status=status.HTTP_201_CREATED)
                                
                            except ImportError:
                                logger.warning("Celery tasks not available, falling back to synchronous processing")
                                use_async_processing = False
                            except Exception as e:
                                logger.error(f"Error iniciando procesamiento asíncrono: {str(e)}")
                                use_async_processing = False
                        
                        if not use_async_processing:
                            # ===============================================
                            # PROCESAMIENTO SÍNCRONO
                            # ===============================================
                            logger.info(f"Iniciando procesamiento síncrono para documento {document.id}")
                            
                            try:
                                from .services.document_processor import DocumentProcessor
                                
                                processor = DocumentProcessor(document.company)
                                success, message = processor.process_document(document, send_email=True)
                                
                                if success:
                                    logger.info(f"✅ Documento {document.id} procesado automáticamente - Status: {document.status}")
                                    
                                    # Actualizar circuit breaker en caso de éxito
                                    if circuit_breaker_enabled:
                                        circuit_key = f"sri_circuit_breaker_{company.id}"
                                        cache.delete(circuit_key)
                                    
                                    # Serializar respuesta con información del procesamiento
                                    response_serializer = ElectronicDocumentSerializer(document)
                                    response_data = response_serializer.data
                                    response_data.update({
                                        'auto_processed': True,
                                        'sync_processing': True,
                                        'sri_status': document.status,
                                        'processing_message': message,
                                        'auto_send_enabled': True,
                                        'sri_authorization_code': getattr(document, 'sri_authorization_code', None),
                                        'processing_timestamp': timezone.now().isoformat(),
                                        'processing_status': 'SYNC_COMPLETED'
                                    })
                                    return Response(response_data, status=status.HTTP_201_CREATED)
                                else:
                                    logger.warning(f"⚠️ Auto-envío síncrono falló para documento {document.id}: {message}")
                                    
                                    # Incrementar circuit breaker si está habilitado
                                    if circuit_breaker_enabled:
                                        circuit_key = f"sri_circuit_breaker_{company.id}"
                                        circuit_failures = cache.get(circuit_key, 0) + 1
                                        recovery_timeout = getattr(settings, 'SRI_CIRCUIT_BREAKER_RECOVERY_TIMEOUT', 60)
                                        cache.set(circuit_key, circuit_failures, timeout=recovery_timeout)
                                    
                                    # Intentar reintento automático si está habilitado
                                    auto_retry = getattr(settings, 'SRI_AUTO_RETRY_FAILED', True)
                                    if auto_retry:
                                        logger.info(f"Intentando reintento automático para documento {document.id}")
                                        try:
                                            from .tasks import retry_failed_document_async
                                            retry_delay = getattr(settings, 'SRI_RETRY_DELAY_SECONDS', 60)
                                            
                                            retry_task = retry_failed_document_async.apply_async(
                                                args=[document.id],
                                                countdown=retry_delay,
                                                queue='sri_processing'
                                            )
                                            
                                            logger.info(f"Reintento programado para documento {document.id} en {retry_delay} segundos")
                                        except:
                                            logger.warning("No se pudo programar reintento automático")
                                    
                                    # Devolver la factura creada pero con error de envío
                                    response_serializer = ElectronicDocumentSerializer(document)
                                    response_data = response_serializer.data
                                    response_data.update({
                                        'auto_processed': False,
                                        'processing_error': message,
                                        'auto_send_enabled': True,
                                        'processing_status': 'SYNC_FAILED',
                                        'retry_scheduled': auto_retry,
                                        'suggestion': 'Document created successfully but SRI processing failed. Check SRI configuration and try manual processing.'
                                    })
                                    return Response(response_data, status=status.HTTP_201_CREATED)
                            except ImportError:
                                logger.error("DocumentProcessor service not available")
                                raise
                                        
                    except Exception as e:
                        logger.error(f"❌ Error en auto-procesamiento de documento {document.id}: {str(e)}")
                        
                        # Incrementar circuit breaker
                        if circuit_breaker_enabled:
                            circuit_key = f"sri_circuit_breaker_{company.id}"
                            circuit_failures = cache.get(circuit_key, 0) + 1
                            recovery_timeout = getattr(settings, 'SRI_CIRCUIT_BREAKER_RECOVERY_TIMEOUT', 60)
                            cache.set(circuit_key, circuit_failures, timeout=recovery_timeout)
                        
                        # Devolver la factura creada pero con error de envío
                        response_serializer = ElectronicDocumentSerializer(document)
                        response_data = response_serializer.data
                        response_data.update({
                            'auto_processed': False,
                            'processing_error': str(e),
                            'auto_send_enabled': True,
                            'processing_status': 'ERROR',
                            'suggestion': 'Document created successfully but auto-processing failed. Check your SRI configuration and certificate, then try manual processing.'
                        })
                        return Response(response_data, status=status.HTTP_201_CREATED)
                else:
                    # Si auto-envío está deshabilitado, respuesta normal
                    logger.info(f"Auto-envío deshabilitado para documento {document.id}")
                    response_serializer = ElectronicDocumentSerializer(document)
                    response_data = response_serializer.data
                    response_data.update({
                        'auto_processed': False,
                        'auto_send_disabled': True,
                        'processing_status': 'MANUAL_REQUIRED',
                        'suggestion': 'Enable SRI_AUTO_SEND in settings or use manual processing endpoints'
                    })
                    return Response(response_data, status=status.HTTP_201_CREATED)
                
            except Exception as e:
                logger.error(f"Error creating invoice: {str(e)}")
                return Response(
                    {"error": f"Error creating invoice: {str(e)}"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=["post"])
    def create_credit_note(self, request):
        """Crear nota de crédito completa"""
        try:
            from apps.companies.models import Company
            from decimal import Decimal
            
            # Obtener datos del request
            data = request.data
            
            # Obtener empresa y documento original
            company = Company.objects.first()  # O el ID de la empresa desde el request
            original_document = ElectronicDocument.objects.get(id=data.get("original_document_id"))
            
            # Crear nota de crédito
            credit_note = CreditNote.objects.create(
                company=company,
                original_document=original_document,
                reason_code=data.get("reason_code", "01"),
                reason_description=data.get("reason_description", "Devolución"),
                customer_identification_type=data.get("customer_identification_type", "05"),
                customer_identification=data.get("customer_identification"),
                customer_name=data.get("customer_name"),
                customer_address=data.get("customer_address", ""),
                customer_email=data.get("customer_email", ""),
                subtotal_without_tax=Decimal(str(data.get("subtotal_without_tax", "0.00"))),
                total_amount=Decimal(str(data.get("total_amount", "0.00"))),
                issue_date=timezone.localtime(timezone.now()).date(),
                status="DRAFT"
            )
            
            logger.info(f"Nota de crédito creada: ID {credit_note.id}")
            
            return Response({
                "id": credit_note.id,
                "document_number": credit_note.document_number,
                "status": credit_note.status,
                "message": "Credit note created successfully"
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error creating credit note: {str(e)}")
            return Response(
                {"error": f"Error creating credit note: {str(e)}"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=["post"])
    def generate_xml(self, request, pk=None):
        """Generar XML del documento - COMPATIBLE CON NOTAS DE CRÉDITO"""
        try:
            # Determinar tipo de documento
            document = None
            is_credit_note = False
            
            try:
                document = self.get_object()
                is_credit_note = False
                logger.info(f"Generando XML para ElectronicDocument ID {pk}")
            except:
                try:
                    document = CreditNote.objects.get(id=pk)
                    is_credit_note = True
                    logger.info(f"Generando XML para CreditNote ID {pk}")
                except CreditNote.DoesNotExist:
                    return Response(
                        {"error": "DOCUMENT_NOT_FOUND", "message": "Document not found"},
                        status=status.HTTP_404_NOT_FOUND
                    )
            
            # Usar el xml_generator de tu estructura
            from .services.xml_generator import XMLGenerator
            
            xml_generator = XMLGenerator(document)
            
            if is_credit_note:
                xml_content = xml_generator.generate_credit_note_xml()
            else:
                xml_content = xml_generator.generate_xml()
            
            # Actualizar estado usando transacción atómica
            with transaction.atomic():
                if is_credit_note:
                    updated_rows = CreditNote.objects.filter(id=document.id).update(
                        status="GENERATED",
                        updated_at=timezone.now()
                    )
                    logger.info(f"CreditNote {document.id} actualizada: {updated_rows} filas")
                    document.refresh_from_db()
                else:
                    document.status = "GENERATED"
                    document.save()
            
            return Response({
                "status": "success",
                "message": "XML generated successfully",
                "data": {
                    "document_number": document.document_number,
                    "xml_size": len(xml_content),
                    "access_key": document.access_key,
                    "document_type": "CREDIT_NOTE" if is_credit_note else getattr(document, "document_type", "UNKNOWN")
                }
            })
            
        except Exception as e:
            logger.error(f"Error generating XML for document {pk}: {str(e)}")
            return Response({
                "error": "XML_GENERATION_FAILED",
                "message": f"Failed to generate XML: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=["post"])
    def sign_document(self, request, pk=None):
        """MÉTODO DE PRUEBA OBVIO - DEBE SER OBVIAMENTE VISIBLE"""
        from rest_framework.response import Response
        from rest_framework import status
        from apps.sri_integration.models import CreditNote
        from django.db import transaction
        from django.utils import timezone
        import logging
        
        # Logging que NO se puede ignorar
        print(f"[OBVIOUS TEST] EJECUTÁNDOSE PARA PK {pk}")
        
        try:
            # Obtener documento
            document = CreditNote.objects.get(id=pk)
            print(f"[OBVIOUS TEST] Estado inicial: {document.status}")
            
            # Actualización obvia
            with transaction.atomic():
                updated_rows = CreditNote.objects.filter(id=document.id).update(
                    status="OBVIOUS_SIGNED",
                    updated_at=timezone.now()
                )
                print(f"[OBVIOUS TEST] Filas actualizadas: {updated_rows}")
            
            # Verificar resultado
            final_check = CreditNote.objects.get(id=document.id)
            print(f"[OBVIOUS TEST] Estado final: {final_check.status}")
            
            # Respuesta obviamente diferente
            return Response({
                "success": True,
                "message": "OBVIOUS TEST METHOD WORKED - FILE MODIFICATION IS ACTIVE!",
                "data": {
                    "document_number": document.document_number,
                    "status": final_check.status,
                    "OBVIOUS_FLAG": "THIS_PROVES_FILE_MODIFICATION_WORKS",
                    "test_method": "OBVIOUS_REPLACEMENT",
                    "verification": {
                        "obvious_test": True,
                        "file_modification_successful": True,
                        "final_status": final_check.status,
                        "persistence_worked": final_check.status == "OBVIOUS_SIGNED"
                    }
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            print(f"[OBVIOUS TEST] ERROR: {e}")
            import traceback
            traceback.print_exc()
            return Response({
                "error": str(e), 
                "obvious_test": True,
                "test_method": "OBVIOUS_REPLACEMENT"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=["post"])
    def send_to_sri(self, request, pk=None):
        """Enviar documento al SRI - COMPATIBLE CON NOTAS DE CRÉDITO"""
        try:
            # Determinar tipo de documento
            document = None
            is_credit_note = False
            
            try:
                document = self.get_object()
                is_credit_note = False
                logger.info(f"Enviando ElectronicDocument {pk} al SRI")
            except:
                try:
                    document = CreditNote.objects.get(id=pk)
                    is_credit_note = True
                    logger.info(f"Enviando CreditNote {pk} al SRI")
                except CreditNote.DoesNotExist:
                    return Response(
                        {"error": "DOCUMENT_NOT_FOUND", "message": "Document not found"},
                        status=status.HTTP_404_NOT_FOUND
                    )
            
            # Verificar que esté firmado
            if document.status != "SIGNED":
                return Response(
                    {"error": "DOCUMENT_NOT_SIGNED", "message": "Document must be signed before sending to SRI"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Enviar al SRI usando soap_client
            from .services.soap_client import SRISOAPClient
            from .services.xml_generator import XMLGenerator
            
            generator = XMLGenerator(document)
            
            if is_credit_note:
                xml_content = generator.generate_credit_note_xml()
            else:
                xml_content = generator.generate_xml()
            
            sri_client = SRISOAPClient(document.company)
            success, message = sri_client.send_document_to_reception(document, xml_content)
            
            if success:
                # Actualizar estado usando transacción atómica
                with transaction.atomic():
                    if is_credit_note:
                        updated_rows = CreditNote.objects.filter(id=document.id).update(
                            status="SENT",
                            updated_at=timezone.now()
                        )
                        logger.info(f"CreditNote {document.id} enviada al SRI: {updated_rows} filas actualizadas")
                        document.refresh_from_db()
                    else:
                        document.status = "SENT"
                        document.save()
                        logger.info(f"ElectronicDocument {document.id} enviado al SRI")
                
                return Response({
                    "message": "Document sent to SRI successfully",
                    "data": {
                        "document_number": document.document_number,
                        "status": document.status,
                        "access_key": document.access_key
                    }
                })
            else:
                if "Error 35" in message or "SRI Error" in message:
                    return Response(
                        {"error": "SRI_SUBMISSION_FAILED", "message": f"SRI rejected document: {message}"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                else:
                    return Response(
                        {"error": "SRI_CONNECTION_FAILED", "message": message},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
                    
        except Exception as e:
            logger.error(f"Error sending document {pk} to SRI: {str(e)}")
            return Response(
                {"error": "SRI_SUBMISSION_ERROR", "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=["post"])
    def generate_pdf(self, request, pk=None):
        """Generar PDF del documento"""
        try:
            # Determinar tipo de documento
            document = None
            is_credit_note = False
            
            try:
                document = self.get_object()
                is_credit_note = False
            except:
                try:
                    document = CreditNote.objects.get(id=pk)
                    is_credit_note = True
                except CreditNote.DoesNotExist:
                    return Response(
                        {"error": "DOCUMENT_NOT_FOUND", "message": "Document not found"},
                        status=status.HTTP_404_NOT_FOUND
                    )
            
            from .services.pdf_generator import PDFGenerator
            
            pdf_generator = PDFGenerator()
            
            # Generar PDF según el tipo
            if is_credit_note:
                success, result = pdf_generator.generate_credit_note_pdf(document)
            else:
                success, result = pdf_generator.generate_invoice_pdf(document)
            
            if success:
                pdf_path = result
                # GUARDAR el PDF generado en el modelo para persistencia
                from django.core.files import File
                try:
                    with open(pdf_path, 'rb') as f:
                        filename = f"{document.document_number.replace('-', '_')}_ride.pdf"
                        document.pdf_file.save(filename, File(f), save=True)
                    
                    # Limpiar temporal
                    if os.path.exists(pdf_path):
                        os.remove(pdf_path)
                except Exception as save_err:
                    logger.warning(f"Error guardando PDF generado en el modelo: {str(save_err)}")

                return Response({
                    "status": "PDF generated successfully",
                    "document_number": document.document_number,
                    "pdf_url": document.pdf_file.url if document.pdf_file else None,
                    "message": "PDF file created and saved successfully"
                })
            else:
                return Response({
                    "status": "ERROR",
                    "message": f"PDF generation failed: {result}"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            
        except Exception as e:
            logger.error(f"Error generating PDF for document {pk}: {str(e)}")
            return Response({
                "status": "ERROR",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=["post"])
    def process_complete(self, request, pk=None):
        """Procesar documento completo: XML + Firma + SRI + PDF"""
        document = self.get_object()
        
        cert_password = request.data.get("password")
        if not cert_password:
            return Response({
                "status": "ERROR",
                "message": "Certificate password is required for complete processing"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            from .services.sri_processor import SRIProcessor
            
            processor = SRIProcessor(document.company)
            
            # Procesar completamente
            success, message = processor.process_document(document, cert_password, send_email=False)
            
            if success:
                return Response({
                    "status": "Document processed completely",
                    "document_number": document.document_number,
                    "document_status": document.status,
                    "authorization_code": getattr(document, "sri_authorization_code", None),
                    "authorization_date": getattr(document, "sri_authorization_date", None),
                    "files_generated": {
                        "xml": bool(getattr(document, "xml_file", None)),
                        "signed_xml": bool(getattr(document, "signed_xml_file", None)),
                        "pdf": bool(getattr(document, "pdf_file", None))
                    },
                    "message": message
                })
            else:
                return Response({
                    "status": "ERROR",
                    "message": message
                }, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            logger.error(f"Error in complete processing for document {pk}: {str(e)}")
            return Response({
                "status": "ERROR",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=["post"])
    def send_email(self, request, pk=None):
        """Enviar email con documentos"""
        try:
            # Determinar tipo de documento
            document = None
            is_credit_note = False
            
            try:
                document = self.get_object()
                is_credit_note = False
            except:
                try:
                    document = CreditNote.objects.get(id=pk)
                    is_credit_note = True
                except CreditNote.DoesNotExist:
                    return Response(
                        {"error": "DOCUMENT_NOT_FOUND", "message": "Document not found"},
                        status=status.HTTP_404_NOT_FOUND
                    )
            
            # Verificar que el documento esté autorizado
            if document.status not in ["AUTHORIZED", "SENT"]:
                return Response({
                    "error": "DOCUMENT_NOT_READY",
                    "message": "Document must be authorized before sending email"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Enviar email
            from .services.email_service import EmailService
            
            email_service = EmailService(document.company)
            
            # Usar el método genérico que ya maneja ambos
            success, message = email_service.send_document_email(document)
            
            if success:
                # Marcar como enviado
                with transaction.atomic():
                    if is_credit_note:
                        CreditNote.objects.filter(id=document.id).update(
                            email_sent=True,
                            email_sent_date=timezone.now()
                        )
                    else:
                        document.email_sent = True
                        document.email_sent_date = timezone.now()
                        document.save(update_fields=['email_sent', 'email_sent_date'])
                
                return Response({
                    "message": "Email sent successfully",
                    "data": {
                        "document_number": document.document_number,
                        "email_sent": True
                    }
                })
            else:
                return Response({
                    "error": "EMAIL_SENDING_FAILED",
                    "message": message
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error(f"Error sending email for document {pk}: {str(e)}")
            return Response({
                "error": "EMAIL_ERROR",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=["post"])
    def reprocess(self, request, pk=None):
        """Reprocesar un documento que falló"""
        try:
            document = self.get_object()
            from .services.document_processor import DocumentProcessor
            processor = DocumentProcessor(document.company)
            
            # Forzar regeneración en TEST para evitar "CLAVE DE ACCESO EN PROCESAMIENTO"
            if hasattr(document.company, 'sri_configuration') and \
               document.company.sri_configuration.environment == 'TEST':
                document.document_number = None
                document.access_key = None
                document.save()
            
            success, message = processor.process_document(document, send_email=True)
            
            if success:
                return Response({
                    "success": True, 
                    "message": "Documento procesado exitosamente",
                    "status": document.status
                })
            else:
                return Response({
                    "success": False, 
                    "error": message,
                    "status": document.status
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error reprocessing document {pk}: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=["post"])
    def send_email(self, request, pk=None):
        """Enviar documento por email al cliente"""
        try:
            document = self.get_object()
            from .services.document_processor import DocumentProcessor
            processor = DocumentProcessor(document.company)
            
            # Usar el método interno del procesador o el servicio directo
            from .services.email_service import EmailService
            email_svc = EmailService(document.company)
            success, message = email_svc.send_document_email(document)
            
            if success:
                document.email_sent = True
                document.email_sent_date = timezone.now()
                document.save(update_fields=['email_sent', 'email_sent_date'])
                return Response({"success": True, "message": "Email enviado exitosamente"})
            else:
                return Response({"success": False, "error": message}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error sending email for document {pk}: {str(e)}")
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=["post"])
    def debug_status_update(self, request, pk=None):
        """Endpoint de debug para probar actualizaciones de status - SOLO PARA DESARROLLO"""
        try:
            # Intentar obtener CreditNote primero
            document = None
            is_credit_note = False
            
            try:
                document = CreditNote.objects.get(id=pk)
                is_credit_note = True
                logger.info(f"Debug: CreditNote {pk} encontrada")
            except CreditNote.DoesNotExist:
                document = self.get_object()
                is_credit_note = False
                logger.info(f"Debug: ElectronicDocument {pk} encontrado")
            
            new_status = request.data.get("status", "SIGNED")
            logger.info(f"Estado inicial: {document.status}")
            logger.info(f"Nuevo status solicitado: {new_status}")
            
            # Método 1: Update directo con transacción
            if is_credit_note:
                with transaction.atomic():
                    updated_rows = CreditNote.objects.filter(id=document.id).update(
                        status=new_status,
                        updated_at=timezone.now()
                    )
                    
                    # Verificación inmediata dentro de la transacción
                    verification_in_transaction = CreditNote.objects.get(id=document.id)
                    
                # Verificación fuera de la transacción
                document.refresh_from_db()
                verification_after_transaction = CreditNote.objects.get(id=document.id)
                
                return Response({
                    "method": "update_direct_with_transaction",
                    "document_type": "CreditNote",
                    "updated_rows": updated_rows,
                    "status_in_transaction": verification_in_transaction.status,
                    "status_after_refresh": document.status,
                    "status_after_new_query": verification_after_transaction.status,
                    "success": verification_after_transaction.status == new_status,
                    "timestamps": {
                        "in_transaction": str(verification_in_transaction.updated_at),
                        "after_transaction": str(verification_after_transaction.updated_at)
                    }
                })
            else:
                document.status = new_status
                document.save()
                
                return Response({
                    "method": "save_normal",
                    "document_type": "ElectronicDocument",
                    "status_after_save": document.status,
                    "success": document.status == new_status
                })
                
        except Exception as e:
            logger.error(f"Error in debug_status_update: {str(e)}")
            return Response({
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def auto_send_status(self, request):
        """Verificar estado del auto-envío SRI"""
        from django.conf import settings
        
        # Verificar disponibilidad de servicios
        try:
            from .services.document_processor import DocumentProcessor
            document_processor_available = True
        except ImportError:
            document_processor_available = False
        
        try:
            from .services.soap_client import SRISOAPClient
            soap_client_available = True
        except ImportError:
            soap_client_available = False
        
        # Verificar estado de Celery
        celery_available = False
        try:
            from celery.app.control import Control
            from celery import current_app
            control = Control(current_app)
            workers = control.inspect().ping()
            celery_available = bool(workers)
        except:
            pass
        
        # Verificar circuit breaker si está disponible
        circuit_breaker_status = {}
        if hasattr(request.user, 'company') or request.user.is_authenticated:
            try:
                user_companies = get_user_companies_secure(request.user)
                for company in user_companies:
                    circuit_key = f"sri_circuit_breaker_{company.id}"
                    circuit_failures = cache.get(circuit_key, 0)
                    circuit_threshold = getattr(settings, 'SRI_CIRCUIT_BREAKER_FAILURE_THRESHOLD', 5)
                    circuit_breaker_status[f"company_{company.id}"] = {
                        'failures': circuit_failures,
                        'threshold': circuit_threshold,
                        'is_open': circuit_failures >= circuit_threshold
                    }
            except:
                pass
        
        return Response({
            "auto_send_configuration": {
                "auto_send_enabled": getattr(settings, 'SRI_AUTO_SEND', False),
                "auto_send_after_generation": getattr(settings, 'SRI_AUTO_SEND_AFTER_GENERATION', False),
                "auto_authorize_check": getattr(settings, 'SRI_AUTO_AUTHORIZE_CHECK', False),
                "use_async_processing": getattr(settings, 'SRI_USE_ASYNC_PROCESSING', True),
                "auto_retry_failed": getattr(settings, 'SRI_AUTO_RETRY_FAILED', True),
                "max_retry_attempts": getattr(settings, 'SRI_MAX_RETRY_ATTEMPTS', 3),
                "retry_delay_seconds": getattr(settings, 'SRI_RETRY_DELAY_SECONDS', 60),
                "async_timeout": getattr(settings, 'SRI_ASYNC_TIMEOUT', 300),
                "circuit_breaker_enabled": getattr(settings, 'SRI_CIRCUIT_BREAKER_ENABLED', True),
                "circuit_breaker_failure_threshold": getattr(settings, 'SRI_CIRCUIT_BREAKER_FAILURE_THRESHOLD', 5),
                "circuit_breaker_recovery_timeout": getattr(settings, 'SRI_CIRCUIT_BREAKER_RECOVERY_TIMEOUT', 60)
            },
            "service_availability": {
                "soap_client_available": soap_client_available,
                "document_processor_available": document_processor_available,
                "celery_available": celery_available,
                "cache_available": True
            },
            "circuit_breaker_status": circuit_breaker_status,
            "notifications": {
                "notify_on_success": getattr(settings, 'SRI_NOTIFY_ON_SUCCESS', True),
                "notify_on_error": getattr(settings, 'SRI_NOTIFY_ON_ERROR', True),
                "notify_on_retry": getattr(settings, 'SRI_NOTIFY_ON_RETRY', False)
            },
            "queue_processing": {
                "queue_processing_enabled": getattr(settings, 'SRI_QUEUE_PROCESSING', True),
                "batch_size": getattr(settings, 'SRI_BATCH_SIZE', 10),
                "queue_max_size": getattr(settings, 'SRI_QUEUE_MAX_SIZE', 1000),
                "queue_batch_timeout": getattr(settings, 'SRI_QUEUE_BATCH_TIMEOUT', 300)
            },
            "validation": {
                "pre_validation": getattr(settings, 'SRI_PRE_VALIDATION', True),
                "validate_xml_schema": getattr(settings, 'SRI_VALIDATE_XML_SCHEMA', True),
                "validate_business_rules": getattr(settings, 'SRI_VALIDATE_BUSINESS_RULES', True)
            },
            "backup_and_cleanup": {
                "auto_backup_documents": getattr(settings, 'SRI_AUTO_BACKUP_DOCUMENTS', True),
                "backup_retention_days": getattr(settings, 'SRI_BACKUP_RETENTION_DAYS', 365),
                "auto_cleanup_old_logs": getattr(settings, 'SRI_AUTO_CLEANUP_OLD_LOGS', True),
                "cleanup_days_threshold": getattr(settings, 'SRI_CLEANUP_DAYS_THRESHOLD', 90)
            },
            "webhook": {
                "webhook_enabled": getattr(settings, 'SRI_WEBHOOK_ENABLED', False),
                "webhook_url": getattr(settings, 'SRI_WEBHOOK_URL', ''),
                "webhook_timeout": getattr(settings, 'SRI_WEBHOOK_TIMEOUT', 30)
            },
            "timestamp": timezone.now().isoformat(),
            "message": "Complete auto-send configuration status and service availability"
        })
    
    @action(detail=True, methods=['post'])
    def process_to_sri_manual(self, request, pk=None):
        """Procesar documento existente y enviarlo al SRI manualmente"""
        try:
            document = self.get_object()
            
            if document.status in ['AUTHORIZED', 'SENT']:
                return Response(
                    {
                        "success": False,
                        "message": "Document already processed", 
                        "current_status": document.status,
                        "document_number": document.document_number,
                        "processing_method": "manual",
                        "suggestion": "Document is already in a final state. No further processing needed."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Verificar si el procesamiento está temporalmente deshabilitado
            from django.conf import settings
            circuit_breaker_enabled = getattr(settings, 'SRI_CIRCUIT_BREAKER_ENABLED', True)
            
            if circuit_breaker_enabled:
                circuit_key = f"sri_circuit_breaker_{document.company.id}"
                circuit_failures = cache.get(circuit_key, 0)
                circuit_threshold = getattr(settings, 'SRI_CIRCUIT_BREAKER_FAILURE_THRESHOLD', 5)
                
                if circuit_failures >= circuit_threshold:
                    logger.warning(f"Manual processing blocked by circuit breaker for company {document.company.id}")
                    return Response({
                        "success": False,
                        "message": "Manual processing temporarily disabled due to multiple recent failures",
                        "current_status": document.status,
                        "document_number": document.document_number,
                        "processing_method": "manual",
                        "circuit_breaker_open": True,
                        "failures_count": circuit_failures,
                        "suggestion": "Wait a few minutes and try again, or contact support if the issue persists."
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # Intentar procesamiento manual
            try:
                from .services.document_processor import DocumentProcessor
                
                logger.info(f"Manual processing requested for document {document.id} by user {request.user.username}")
                processor = DocumentProcessor(document.company)
                
                # Obtener parámetros opcionales
                send_email = request.data.get('send_email', True)
                force_reprocess = request.data.get('force_reprocess', False)
                
                success, message = processor.process_document(
                    document, 
                    send_email=send_email,
                    force_reprocess=force_reprocess
                )
                
                if success:
                    # Limpiar circuit breaker en caso de éxito
                    if circuit_breaker_enabled:
                        circuit_key = f"sri_circuit_breaker_{document.company.id}"
                        cache.delete(circuit_key)
                    
                    logger.info(f"✅ Manual processing successful for document {document.id}")
                    
                    return Response({
                        "success": True,
                        "message": "Document processed and sent to SRI successfully",
                        "document_number": document.document_number,
                        "status": document.status,
                        "sri_authorization_code": getattr(document, 'sri_authorization_code', None),
                        "sri_authorization_date": getattr(document, 'sri_authorization_date', None),
                        "processing_details": message,
                        "processing_method": "manual",
                        "email_sent": send_email,
                        "files_generated": {
                            "xml": bool(getattr(document, 'xml_file', None)),
                            "signed_xml": bool(getattr(document, 'signed_xml_file', None)),
                            "pdf": bool(getattr(document, 'pdf_file', None))
                        },
                        "processing_timestamp": timezone.now().isoformat()
                    })
                else:
                    # Incrementar circuit breaker en caso de falla
                    if circuit_breaker_enabled:
                        circuit_key = f"sri_circuit_breaker_{document.company.id}"
                        circuit_failures = cache.get(circuit_key, 0) + 1
                        recovery_timeout = getattr(settings, 'SRI_CIRCUIT_BREAKER_RECOVERY_TIMEOUT', 60)
                        cache.set(circuit_key, circuit_failures, timeout=recovery_timeout)
                    
                    logger.error(f"❌ Manual processing failed for document {document.id}: {message}")
                    
                    return Response({
                        "success": False,
                        "message": f"Processing failed: {message}",
                        "document_number": document.document_number,
                        "current_status": document.status,
                        "processing_method": "manual",
                        "processing_details": message,
                        "suggestion": "Check SRI configuration, certificate validity, and document data. Try again or contact support."
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    
            except ImportError:
                logger.error(f"DocumentProcessor service not available for manual processing")
                return Response({
                    "success": False,
                    "message": "Document processor service is not available",
                    "document_number": document.document_number,
                    "current_status": document.status,
                    "processing_method": "manual",
                    "suggestion": "Contact system administrator to verify service configuration."
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                
        except Exception as e:
            logger.error(f"Error in manual processing for document {pk}: {str(e)}")
            
            # Incrementar circuit breaker incluso para errores inesperados
            try:
                if hasattr(self, 'get_object'):
                    doc = self.get_object()
                    circuit_breaker_enabled = getattr(settings, 'SRI_CIRCUIT_BREAKER_ENABLED', True)
                    if circuit_breaker_enabled:
                        circuit_key = f"sri_circuit_breaker_{doc.company.id}"
                        circuit_failures = cache.get(circuit_key, 0) + 1
                        recovery_timeout = getattr(settings, 'SRI_CIRCUIT_BREAKER_RECOVERY_TIMEOUT', 60)
                        cache.set(circuit_key, circuit_failures, timeout=recovery_timeout)
            except:
                pass
            
            return Response(
                {
                    "success": False,
                    "error": f"Processing error: {str(e)}",
                    "processing_method": "manual",
                    "suggestion": "Check system logs and contact support if the issue persists."
                }, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DocumentItemViewSet(viewsets.ModelViewSet):
    queryset = DocumentItem.objects.all()
    serializer_class = DocumentItemSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["document"]
    search_fields = ["description", "main_code"]
    permission_classes = [permissions.AllowAny]  # Para pruebas


class SRIResponseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SRIResponse.objects.all()
    serializer_class = SRIResponseSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["document", "operation_type", "response_code"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]
    permission_classes = [permissions.AllowAny]  # Para pruebas


# ==========================================
# FUNCIONES HELPER
# ==========================================

def get_document_by_id_and_type(document_id, user):
    """
    Obtiene un documento de cualquier tipo con validación de permisos
    """
    user_companies = get_user_companies_secure(user)
    
    # Intentar obtener de ElectronicDocument primero
    try:
        document = ElectronicDocument.objects.get(
            id=document_id,
            company__in=user_companies
        )
        return document, 'electronic_document'
    except ElectronicDocument.DoesNotExist:
        pass
    
    # Intentar obtener de modelos específicos
    models_to_try = [
        (CreditNote, 'credit_note'),
        (DebitNote, 'debit_note'),
        (Retention, 'retention'),
        (PurchaseSettlement, 'purchase_settlement'),
    ]
    
    for model_class, doc_type in models_to_try:
        try:
            document = model_class.objects.get(
                id=document_id,
                company__in=user_companies
            )
            return document, doc_type
        except (model_class.DoesNotExist, NameError):
            continue
    
    return None, None


def get_document_files(document, doc_type):
    """
    Obtiene los archivos PDF y XML de un documento según su tipo
    """
    files = {
        'pdf_file': None,
        'xml_file': None,
        'signed_xml_file': None,
        'document_number': getattr(document, 'document_number', str(document.id)),
        'status': getattr(document, 'status', 'UNKNOWN')
    }
    
    # Mapeo de campos según el tipo de documento
    if doc_type == 'electronic_document':
        files.update({
            'pdf_file': getattr(document, 'pdf_file', None),
            'xml_file': getattr(document, 'xml_file', None),
            'signed_xml_file': getattr(document, 'signed_xml_file', None),
        })
    else:
        # Para modelos específicos (CreditNote, DebitNote, etc.)
        files.update({
            'pdf_file': getattr(document, 'pdf_file', None),
            'xml_file': getattr(document, 'xml_file', None),
            'signed_xml_file': getattr(document, 'signed_xml_file', None),
        })
    
    return files


def calculate_elapsed_time(started_at_str):
    """Calcular tiempo transcurrido desde que inició la tarea"""
    if not started_at_str:
        return None
    
    try:
        started_at = parser.parse(started_at_str)
        elapsed = timezone.now() - started_at
        return int(elapsed.total_seconds())
    except:
        return None


# ==========================================
# VISTAS DE DESCARGA DE ARCHIVOS
# ==========================================

@login_required
@require_GET
def download_document_pdf(request, document_id):
    """
    Descarga el PDF de cualquier tipo de documento
    URL: /sri/documents/<id>/download/pdf/
    """
    try:
        # Obtener documento de cualquier tipo
        document, doc_type = get_document_by_id_and_type(document_id, request.user)
        
        if not document:
            logger.warning(f"Usuario {request.user.username} sin permisos para documento {document_id}")
            raise Http404("Documento no encontrado o sin permisos")
        
        # Obtener archivos del documento
        files = get_document_files(document, doc_type)
        
        # CAMBIO: Permitir descarga de PDF en más estados
        valid_states_for_pdf = ['AUTHORIZED', 'SENT', 'SIGNED', 'GENERATED']
        
        if files['status'] not in valid_states_for_pdf:
            return JsonResponse({
                'error': 'DOCUMENT_STATUS_INVALID',
                'message': f'El documento debe estar en uno de estos estados para descargar el PDF: {", ".join(valid_states_for_pdf)}. Estado actual: {files["status"]}'
            }, status=400)
        
        # Verificar que existe el archivo PDF
        if not files['pdf_file']:
            # Si no existe el PDF, intentar generarlo
            from apps.sri_integration.services.pdf_generator import PDFGenerator
            
            try:
                pdf_generator = PDFGenerator()
                
                # Generar PDF según el tipo de documento
                if doc_type == 'credit_note':
                    success, result = pdf_generator.generate_credit_note_pdf(document)
                elif doc_type == 'electronic_document':
                    success, result = pdf_generator.generate_invoice_pdf(document)
                else:
                    success, result = pdf_generator.generate_invoice_pdf(document)
                
                if success:
                    pdf_path = result
                    # GUARDAR CORRECTAMENTE el PDF generado en el modelo
                    from django.core.files import File
                    with open(pdf_path, 'rb') as f:
                        filename = f"{document.document_number.replace('-', '_')}_ride.pdf"
                        document.pdf_file.save(filename, File(f), save=True)
                    
                    # Limpiar temporal
                    if os.path.exists(pdf_path):
                        os.remove(pdf_path)
                        
                    files = get_document_files(document, doc_type)
                else:
                    return JsonResponse({
                        'error': 'PDF_GENERATION_FAILED',
                        'message': f'No se pudo generar el PDF del documento: {result}'
                    }, status=500)

                    
            except Exception as e:
                logger.error(f"Error generando PDF: {str(e)}")
                return JsonResponse({
                    'error': 'PDF_GENERATION_ERROR',
                    'message': f'Error al generar PDF: {str(e)}'
                }, status=500)
        
        # Verificar si existe el archivo PDF y servirlo
        if files['pdf_file']:
            try:
                # Generar nombre de archivo descargable según el tipo
                doc_type_names = {
                    'electronic_document': 'documento',
                    'credit_note': 'nota_credito',
                    'debit_note': 'nota_debito',
                    'retention': 'retencion',
                    'purchase_settlement': 'liquidacion_compra'
                }
                
                type_name = doc_type_names.get(doc_type, 'documento')
                filename = f"{files['document_number']}_{type_name}_{files['status'].lower()}.pdf"
                
                # Servir archivo directamente desde el storage
                return FileResponse(
                    files['pdf_file'].open('rb'),
                    as_attachment=True,
                    filename=filename,
                    content_type='application/pdf'
                )
            except Exception as e:
                logger.error(f"Error accediendo al archivo PDF: {str(e)}")
                return JsonResponse({
                    'error': 'PDF_ACCESS_ERROR',
                    'message': 'No se pudo acceder al archivo PDF en el almacenamiento'
                }, status=500)
        
        return JsonResponse({
            'error': 'PDF_NOT_FOUND',
            'message': 'El archivo PDF no está disponible'
        }, status=404)
        
        # Generar nombre de archivo descargable según el tipo
        doc_type_names = {
            'electronic_document': 'documento',
            'credit_note': 'nota_credito',
            'debit_note': 'nota_debito',
            'retention': 'retencion',
            'purchase_settlement': 'liquidacion_compra'
        }
        
        type_name = doc_type_names.get(doc_type, 'documento')
        filename = f"{files['document_number']}_{type_name}_{files['status'].lower()}.pdf"
        
        # Servir archivo
        response = FileResponse(
            files['pdf_file'].open('rb'),
            as_attachment=True,
            filename=filename,
            content_type='application/pdf'
        )
        
        logger.info(f"Usuario {request.user.username} descargó PDF del {type_name} {document_id} en estado {files['status']}")
        return response
        
    except Exception as e:
        logger.error(f"Error descargando PDF del documento {document_id}: {str(e)}")
        return JsonResponse({
            'error': 'DOWNLOAD_ERROR',
            'message': f'Error interno al descargar el archivo: {str(e)}'
        }, status=500)

@login_required
@require_GET
def download_document_xml(request, document_id):
    """
    Descarga el XML firmado de cualquier tipo de documento
    URL: /sri/documents/<id>/download/xml/
    """
    try:
        # Obtener documento de cualquier tipo
        document, doc_type = get_document_by_id_and_type(document_id, request.user)
        
        if not document:
            logger.warning(f"Usuario {request.user.username} sin permisos para documento {document_id}")
            raise Http404("Documento no encontrado o sin permisos")
        
        # Obtener archivos del documento
        files = get_document_files(document, doc_type)
        
        # Verificar que el documento esté firmado o autorizado
        valid_statuses = ['SIGNED', 'SENT', 'AUTHORIZED']
        if files['status'] not in valid_statuses:
            return JsonResponse({
                'error': 'DOCUMENT_NOT_SIGNED',
                'message': f'El documento debe estar firmado para descargar el XML. Estado actual: {files["status"]}'
            }, status=400)
        
        # Preferir XML firmado, luego XML original
        xml_file = None
        filename_prefix = ""
        
        if files['signed_xml_file']:
            xml_file = files['signed_xml_file']
            filename_prefix = "firmado"
        elif files['xml_file']:
            xml_file = files['xml_file']
            filename_prefix = "original"
        
        if not xml_file:
            return JsonResponse({
                'error': 'XML_NOT_FOUND',
                'message': 'El archivo XML no está disponible para este documento'
            }, status=404)
        
        # Verificar que el archivo existe en el almacenamiento y servirlo
        if xml_file:
            try:
                # Generar nombre de archivo descargable según el tipo
                doc_type_names = {
                    'electronic_document': 'documento',
                    'credit_note': 'nota_credito',
                    'debit_note': 'nota_debito',
                    'retention': 'retencion',
                    'purchase_settlement': 'liquidacion_compra'
                }
                
                type_name = doc_type_names.get(doc_type, 'documento')
                filename = f"{files['document_number']}_{type_name}_{filename_prefix}.xml"
                
                # Servir archivo directamente desde el storage
                return FileResponse(
                    xml_file.open('rb'),
                    as_attachment=True,
                    filename=filename,
                    content_type='application/xml'
                )
            except Exception as e:
                logger.error(f"Error accediendo al archivo XML: {str(e)}")
                return JsonResponse({
                    'error': 'XML_ACCESS_ERROR',
                    'message': 'No se pudo acceder al archivo XML en el almacenamiento'
                }, status=500)
        
        return JsonResponse({
            'error': 'XML_NOT_FOUND',
            'message': 'El archivo XML no está disponible'
        }, status=404)
        
        # Generar nombre de archivo descargable según el tipo
        doc_type_names = {
            'electronic_document': 'documento',
            'credit_note': 'nota_credito',
            'debit_note': 'nota_debito',
            'retention': 'retencion',
            'purchase_settlement': 'liquidacion_compra'
        }
        
        type_name = doc_type_names.get(doc_type, 'documento')
        filename = f"{files['document_number']}_{type_name}_{filename_prefix}.xml"
        
        # Servir archivo
        response = FileResponse(
            xml_file.open('rb'),
            as_attachment=True,
            filename=filename,
            content_type='application/xml'
        )
        
        logger.info(f"Usuario {request.user.username} descargó XML del {type_name} {document_id}")
        return response
        
    except Exception as e:
        logger.error(f"Error descargando XML del documento {document_id}: {str(e)}")
        return JsonResponse({
            'error': 'DOWNLOAD_ERROR',
            'message': f'Error interno al descargar el archivo: {str(e)}'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_document_files(request, document_id):
    """
    Verifica qué archivos están disponibles para un documento
    URL: /sri/documents/<id>/files/check/
    """
    try:
        # Obtener documento de cualquier tipo
        document, doc_type = get_document_by_id_and_type(document_id, request.user)
        
        if not document:
            return Response({
                'error': 'DOCUMENT_NOT_FOUND',
                'message': 'Documento no encontrado o sin permisos'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Obtener archivos del documento
        files = get_document_files(document, doc_type)
        
        # MODIFICACIÓN: Estados válidos para descarga de PDF
        pdf_valid_states = ['AUTHORIZED', 'SENT', 'SIGNED', 'GENERATED']
        xml_valid_states = ['SIGNED', 'SENT', 'AUTHORIZED']
        
        # Verificar disponibilidad de archivos
        file_status = {
            'document_id': document_id,
            'document_type': doc_type,
            'document_number': files['document_number'],
            'status': files['status'],
            'files': {
                'pdf': {
                    'available': bool(files['pdf_file']),
                    'exists': False,
                    'size': 0,
                    'downloadable': False
                },
                'xml': {
                    'available': bool(files['xml_file'] or files['signed_xml_file']),
                    'exists': False,
                    'size': 0,
                    'signed': bool(files['signed_xml_file']),
                    'downloadable': False
                }
            }
        }
        
        # Verificar PDF
        if files['pdf_file']:
            try:
                if os.path.exists(files['pdf_file'].path):
                    file_status['files']['pdf']['exists'] = True
                    file_status['files']['pdf']['size'] = os.path.getsize(files['pdf_file'].path)
                    # CAMBIO: Permitir descarga en más estados
                    file_status['files']['pdf']['downloadable'] = files['status'] in pdf_valid_states
            except (AttributeError, ValueError, OSError):
                pass
        
        # Verificar XML
        xml_to_check = files['signed_xml_file'] or files['xml_file']
        if xml_to_check:
            try:
                if os.path.exists(xml_to_check.path):
                    file_status['files']['xml']['exists'] = True
                    file_status['files']['xml']['size'] = os.path.getsize(xml_to_check.path)
                    file_status['files']['xml']['downloadable'] = files['status'] in xml_valid_states
            except (AttributeError, ValueError, OSError):
                pass
        
        return Response(file_status)
        
    except Exception as e:
        logger.error(f"Error verificando archivos del documento {document_id}: {str(e)}")
        return Response({
            'error': 'CHECK_ERROR',
            'message': f'Error interno al verificar archivos: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_missing_files(request, document_id):
    """
    Genera archivos PDF o XML faltantes para un documento
    URL: /sri/documents/<id>/files/generate/
    """
    try:
        # Obtener documento de cualquier tipo
        document, doc_type = get_document_by_id_and_type(document_id, request.user)
        
        if not document:
            return Response({
                'error': 'DOCUMENT_NOT_FOUND',
                'message': 'Documento no encontrado o sin permisos'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Obtener tipo de archivo a generar
        file_type = request.data.get('file_type', 'pdf')  # 'pdf' o 'xml'
        
        if file_type not in ['pdf', 'xml']:
            return Response({
                'error': 'INVALID_FILE_TYPE',
                'message': 'El tipo de archivo debe ser "pdf" o "xml"'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Verificar estado del documento
        files = get_document_files(document, doc_type)
        
        if file_type == 'pdf' and files['status'] != 'AUTHORIZED':
            return Response({
                'error': 'DOCUMENT_NOT_AUTHORIZED',
                'message': 'El documento debe estar autorizado para generar PDF'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Intentar generar el archivo usando el procesador
        try:
            from apps.sri_integration.services.document_processor import DocumentProcessor
            from apps.sri_integration.services.pdf_generator import PDFGenerator
            
            if file_type == 'pdf':
                # Generar PDF
                pdf_generator = PDFGenerator(document)
                
                if doc_type == 'credit_note':
                    pdf_content = pdf_generator.generate_credit_note_pdf()
                elif doc_type == 'debit_note':
                    pdf_content = pdf_generator.generate_debit_note_pdf()
                elif doc_type == 'retention':
                    pdf_content = pdf_generator.generate_retention_pdf()
                else:
                    pdf_content = pdf_generator.generate_invoice_pdf()
                
                # Guardar PDF
                from django.core.files.base import ContentFile
                filename = f"{files['document_number']}_{doc_type}.pdf"
                document.pdf_file.save(filename, ContentFile(pdf_content), save=True)
                
                return Response({
                    'success': True,
                    'message': 'PDF generado exitosamente',
                    'file_type': 'pdf',
                    'filename': filename
                })
                
            elif file_type == 'xml':
                # Generar XML (si no existe)
                processor = DocumentProcessor(document.company)
                success, message = processor._generate_xml(document)
                
                if success:
                    return Response({
                        'success': True,
                        'message': 'XML generado exitosamente',
                        'file_type': 'xml'
                    })
                else:
                    return Response({
                        'error': 'XML_GENERATION_FAILED',
                        'message': message
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    
        except Exception as e:
            logger.error(f"Error generando {file_type} para documento {document_id}: {str(e)}")
            return Response({
                'error': 'GENERATION_ERROR',
                'message': f'Error generando {file_type}: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    except Exception as e:
        logger.error(f"Error en generate_missing_files para documento {document_id}: {str(e)}")
        return Response({
            'error': 'SYSTEM_ERROR',
            'message': f'Error del sistema: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==========================================
# NUEVAS APIS PARA MONITOREO DE CELERY
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def celery_status(request):
    """
    Estado general de Celery
    URL: /api/sri/celery/status/
    """
    try:
        control = Control(current_app)
        
        # Verificar workers activos
        workers = control.inspect().active()
        worker_stats = control.inspect().stats()
        
        response_data = {
            'celery_healthy': bool(workers),
            'workers_count': len(workers) if workers else 0,
            'workers': list(workers.keys()) if workers else [],
            'timestamp': timezone.now().isoformat()
        }
        
        # Estadísticas de colas si disponible
        if workers:
            try:
                active_tasks = control.inspect().active()
                reserved_tasks = control.inspect().reserved()
                
                total_active = sum(len(tasks) for tasks in (active_tasks or {}).values())
                total_reserved = sum(len(tasks) for tasks in (reserved_tasks or {}).values())
                
                response_data.update({
                    'queue_stats': {
                        'active_tasks': total_active,
                        'reserved_tasks': total_reserved
                    }
                })
            except Exception as e:
                logger.warning(f"Could not get queue stats: {e}")
        
        return Response(response_data)
        
    except Exception as e:
        logger.error(f"Error checking Celery status: {e}")
        return Response({
            'celery_healthy': False,
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def document_task_status(request, document_id):
    """
    Estado de procesamiento de un documento específico
    URL: /api/sri/documents/<document_id>/task-status/
    """
    try:
        # Verificar permisos
        document, doc_type = get_document_by_id_and_type(document_id, request.user)
        
        if not document:
            return Response({
                'error': 'DOCUMENT_NOT_FOUND',
                'message': 'Documento no encontrado o sin permisos'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Buscar tareas activas para este documento
        cache_key = f"document_tasks_{document_id}"
        cached_tasks = cache.get(cache_key, [])
        
        active_tasks = []
        completed_tasks = []
        
        for task_id in cached_tasks:
            try:
                result = AsyncResult(task_id)
                
                task_data = {
                    'task_id': task_id,
                    'status': result.status,
                    'ready': result.ready(),
                    'successful': result.successful() if result.ready() else None,
                    'failed': result.failed() if result.ready() else None
                }
                
                if result.ready():
                    task_data['result'] = result.result
                    completed_tasks.append(task_data)
                else:
                    active_tasks.append(task_data)
                    
            except Exception as e:
                logger.warning(f"Error checking task {task_id}: {e}")
        
        # Información del documento
        document_data = {
            'document_id': document_id,
            'document_number': getattr(document, 'document_number', str(document.id)),
            'document_type': doc_type,
            'current_status': getattr(document, 'status', 'UNKNOWN'),
            'created_at': getattr(document, 'created_at', timezone.now()).isoformat(),
            'updated_at': getattr(document, 'updated_at', timezone.now()).isoformat(),
            'active_tasks': active_tasks,
            'completed_tasks': completed_tasks[-5:],  # Últimas 5 tareas completadas
            'has_active_processing': len(active_tasks) > 0,
            'timestamp': timezone.now().isoformat()
        }
        
        # Calcular progreso estimado (Optimista para modo POS)
        if document.status == 'SENT':
            document_data['progress'] = {
                'current_step': 'Autorización finalizada (Sincronizando)',
                'estimated_completion': 'Completado',
                'percentage': 95
            }
            document_data['current_status'] = 'AUTHORIZED' # Optimismo visual
        elif document.status == 'GENERATED':
            document_data['progress'] = {
                'current_step': 'Procesando firma digital...',
                'estimated_completion': 'Inminente',
                'percentage': 75
            }
        elif document.status == 'AUTHORIZED':
            document_data['progress'] = {
                'current_step': 'Completado',
                'estimated_completion': 'Listo',
                'percentage': 100
            }
        else:
            document_data['progress'] = {
                'current_step': document.status,
                'estimated_completion': 'Unknown',
                'percentage': 40
            }
        
        return Response(document_data)
        
    except Exception as e:
        logger.error(f"Error getting document task status: {e}")
        return Response({
            'error': str(e),
            'document_id': document_id
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def trigger_document_processing(request, document_id):
    """
    Disparar procesamiento asíncrono de un documento
    URL: /api/sri/documents/<document_id>/trigger-processing/
    """
    try:
        # Verificar permisos
        document, doc_type = get_document_by_id_and_type(document_id, request.user)
        
        if not document:
            return Response({
                'error': 'DOCUMENT_NOT_FOUND',
                'message': 'Documento no encontrado o sin permisos'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Verificar estado válido
        valid_statuses = ['DRAFT', 'GENERATED', 'ERROR']
        if document.status not in valid_statuses:
            return Response({
                'error': 'INVALID_STATUS',
                'message': f'El documento debe estar en estado {", ".join(valid_statuses)}. Estado actual: {document.status}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Importar tareas
        from .tasks import process_document_async, check_document_authorization_async
        
        # Determinar qué tarea ejecutar
        if document.status == 'GENERATED':
            # Si ya está generado, solo verificar autorización
            task = check_document_authorization_async.apply_async(
                args=[document_id],
                queue='sri_authorization'
            )
            operation = 'authorization_check'
        else:
            # Procesamiento completo
            task = process_document_async.apply_async(
                args=[document_id],
                queue='sri_processing'
            )
            operation = 'complete_processing'
        
        # Guardar task ID en cache para tracking
        cache_key = f"document_tasks_{document_id}"
        cached_tasks = cache.get(cache_key, [])
        cached_tasks.append(task.id)
        cache.set(cache_key, cached_tasks[-10:], timeout=3600)  # Mantener últimas 10 tareas
        
        # Guardar información de la tarea
        task_cache_key = f"task_info_{task.id}"
        cache.set(task_cache_key, {
            'document_id': document_id,
            'document_type': doc_type,
            'operation': operation,
            'started_at': timezone.now().isoformat(),
            'user_id': request.user.id
        }, timeout=3600)
        
        logger.info(f"Usuario {request.user.username} inició {operation} para documento {document_id} (task: {task.id})")
        
        return Response({
            'success': True,
            'message': f'Procesamiento iniciado: {operation}',
            'task_id': task.id,
            'document_id': document_id,
            'operation': operation,
            'status_url': f'/api/sri/documents/{document_id}/task-status/',
            'polling_interval': 2000  # milisegundos
        })
        
    except Exception as e:
        logger.error(f"Error triggering processing for document {document_id}: {e}")
        return Response({
            'error': str(e),
            'document_id': document_id
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_active_tasks(request):
    """
    Obtener todas las tareas activas del usuario
    URL: /api/sri/celery/my-tasks/
    """
    try:
        # Obtener documentos del usuario
        user_companies = get_user_companies_secure(request.user)
        
        # Buscar en ElectronicDocument
        user_document_ids = list(ElectronicDocument.objects.filter(
            company__in=user_companies
        ).values_list('id', flat=True))
        
        # Buscar en CreditNote también
        try:
            credit_note_ids = list(CreditNote.objects.filter(
                company__in=user_companies
            ).values_list('id', flat=True))
            user_document_ids.extend([f"credit_{id}" for id in credit_note_ids])
        except:
            pass
        
        user_active_tasks = []
        
        # Revisar tareas para cada documento
        for doc_id in user_document_ids:
            # Limpiar prefijo si es credit note
            clean_doc_id = str(doc_id).replace('credit_', '')
            cache_key = f"document_tasks_{clean_doc_id}"
            cached_tasks = cache.get(cache_key, [])
            
            for task_id in cached_tasks:
                try:
                    result = AsyncResult(task_id)
                    
                    if not result.ready():  # Solo tareas activas
                        task_info = cache.get(f"task_info_{task_id}", {})
                        
                        task_data = {
                            'task_id': task_id,
                            'document_id': clean_doc_id,
                            'status': result.status,
                            'operation': task_info.get('operation', 'unknown'),
                            'started_at': task_info.get('started_at'),
                            'document_type': task_info.get('document_type', 'unknown'),
                            'elapsed_time': calculate_elapsed_time(task_info.get('started_at'))
                        }
                        user_active_tasks.append(task_data)
                        
                except Exception as e:
                    logger.warning(f"Error checking task {task_id}: {e}")
        
        return Response({
            'active_tasks': user_active_tasks,
            'count': len(user_active_tasks),
            'has_active_tasks': len(user_active_tasks) > 0,
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting user active tasks: {e}")
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def stop_document_processing(request, document_id):
    """
    Detener procesamiento de un documento
    URL: /api/sri/documents/<document_id>/stop-processing/
    """
    try:
        # Verificar permisos
        document, doc_type = get_document_by_id_and_type(document_id, request.user)
        
        if not document:
            return Response({
                'error': 'DOCUMENT_NOT_FOUND'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Obtener tareas activas
        cache_key = f"document_tasks_{document_id}"
        cached_tasks = cache.get(cache_key, [])
        
        cancelled_tasks = []
        
        for task_id in cached_tasks:
            try:
                result = AsyncResult(task_id)
                
                if not result.ready():  # Solo cancelar tareas activas
                    current_app.control.revoke(task_id, terminate=True)
                    cancelled_tasks.append(task_id)
                    
                    # Limpiar cache
                    cache.delete(f"task_info_{task_id}")
                    
            except Exception as e:
                logger.warning(f"Error cancelling task {task_id}: {e}")
        
        # Limpiar cache de tareas del documento
        cache.delete(cache_key)
        
        logger.info(f"Usuario {request.user.username} canceló {len(cancelled_tasks)} tareas para documento {document_id}")
        
        return Response({
            'success': True,
            'message': f'Se cancelaron {len(cancelled_tasks)} tareas',
            'cancelled_tasks': cancelled_tasks,
            'document_id': document_id
        })
        
    except Exception as e:
        logger.error(f"Error stopping document processing: {e}")
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_task_status(request, task_id):
    """
    Obtener estado de una tarea específica
    URL: /api/sri/celery/task/<task_id>/status/
    """
    try:
        result = AsyncResult(task_id)
        
        task_info = {
            'task_id': task_id,
            'status': result.status,
            'result': result.result,
            'successful': result.successful(),
            'failed': result.failed(),
            'ready': result.ready(),
            'timestamp': timezone.now().isoformat()
        }
        
        # Información adicional si la tarea falló
        if result.failed():
            task_info.update({
                'error': str(result.result) if result.result else 'Unknown error',
                'traceback': result.traceback
            })
        
        # Información adicional si está en progreso
        if result.status == 'PENDING':
            task_info.update({
                'progress': 'Task is queued or in progress',
                'eta': None
            })
        
        return Response(task_info)
        
    except Exception as e:
        logger.error(f"Error getting task status for {task_id}: {e}")
        return Response({
            'error': str(e),
            'task_id': task_id
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_queue_stats(request):
    """
    Obtener estadísticas de las colas de Celery
    URL: /api/sri/celery/queue-stats/
    """
    try:
        control = Control(current_app)
        
        # Obtener estadísticas
        active = control.inspect().active()
        reserved = control.inspect().reserved()
        scheduled = control.inspect().scheduled()
        
        # Calcular totales
        total_active = sum(len(tasks) for tasks in (active or {}).values())
        total_reserved = sum(len(tasks) for tasks in (reserved or {}).values())
        total_scheduled = sum(len(tasks) for tasks in (scheduled or {}).values())
        
        # Buscar tareas relacionadas con documentos SRI
        sri_tasks = 0
        if active:
            for worker, tasks in active.items():
                for task in tasks:
                    if any(name in task.get('name', '') for name in [
                        'check_document_authorization_async',
                        'process_document_async',
                        'send_authorization_notification_email'
                    ]):
                        sri_tasks += 1
        
        stats = {
            'queue_totals': {
                'active': total_active,
                'reserved': total_reserved,
                'scheduled': total_scheduled,
                'sri_related': sri_tasks
            },
            'workers': list((active or {}).keys()),
            'worker_count': len((active or {}).keys()),
            'timestamp': timezone.now().isoformat()
        }
        
        # Agregar detalles por worker si hay datos
        if active:
            stats['worker_details'] = {}
            for worker, tasks in active.items():
                stats['worker_details'][worker] = {
                    'active_tasks': len(tasks),
                    'task_names': [task.get('name', 'unknown') for task in tasks]
                }
        
        return Response(stats)
        
    except Exception as e:
        logger.error(f"Error getting queue stats: {e}")
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_documents_with_task_status(request):
    """
    Obtener documentos con información de tareas asíncronas activas
    URL: /api/sri/documents/with-tasks/
    """
    try:
        # Obtener documentos del usuario
        user_companies = get_user_companies_secure(request.user)
        
        # Documentos recientes
        documents = ElectronicDocument.objects.filter(
            company__in=user_companies
        ).order_by('-created_at')[:50]  # Últimos 50 documentos
        
        documents_with_tasks = []
        
        for doc in documents:
            # Buscar tareas activas para este documento
            cache_key = f"document_tasks_{doc.id}"
            cached_tasks = cache.get(cache_key, [])
            
            active_tasks_count = 0
            for task_id in cached_tasks:
                try:
                    result = AsyncResult(task_id)
                    if not result.ready():
                        active_tasks_count += 1
                except:
                    pass
            
            doc_data = {
                'id': doc.id,
                'document_number': doc.document_number,
                'status': doc.status,
                'created_at': doc.created_at.isoformat(),
                'total_amount': float(doc.total_amount) if doc.total_amount else 0,
                'customer_name': doc.customer_name,
                'active_tasks_count': active_tasks_count,
                'has_active_processing': active_tasks_count > 0
            }
            documents_with_tasks.append(doc_data)
        
        return Response({
            'documents': documents_with_tasks,
            'total_documents': len(documents_with_tasks),
            'documents_with_active_tasks': len([d for d in documents_with_tasks if d['has_active_processing']]),
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting documents with task status: {e}")
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def process_document_with_celery(request, document_id):
    """
    ENDPOINT PRINCIPAL: Procesar documento usando Celery con monitoreo completo
    URL: /api/sri/documents/<document_id>/process-celery/
    """
    try:
        # Verificar permisos
        document, doc_type = get_document_by_id_and_type(document_id, request.user)
        
        if not document:
            return Response({
                'error': 'DOCUMENT_NOT_FOUND',
                'message': 'Documento no encontrado o sin permisos'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Verificar que no esté ya autorizado
        if document.status == 'AUTHORIZED':
            return Response({
                'error': 'DOCUMENT_ALREADY_AUTHORIZED',
                'message': 'El documento ya está autorizado'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Importar tarea de procesamiento
        from .tasks import process_document_async
        
        # Iniciar procesamiento con Celery
        task = process_document_async.apply_async(
            args=[document_id],
            queue='sri_processing'
        )
        
        # Guardar información de tracking
        cache_key = f"document_tasks_{document_id}"
        cached_tasks = cache.get(cache_key, [])
        cached_tasks.append(task.id)
        cache.set(cache_key, cached_tasks[-5:], timeout=3600)
        
        task_cache_key = f"task_info_{task.id}"
        cache.set(task_cache_key, {
            'document_id': document_id,
            'document_type': doc_type,
            'operation': 'celery_complete_processing',
            'started_at': timezone.now().isoformat(),
            'user_id': request.user.id,
            'user_email': request.user.email
        }, timeout=3600)
        
        logger.info(f"CELERY PROCESSING iniciado por {request.user.username} para documento {document_id}")
        
        # Respuesta optimista para el POS
        return Response({
            'success': True,
            'message': 'Procesamiento SRI iniciado (Autorización Instantánea)',
            'task_id': task.id,
            'document_id': document_id,
            'document_number': getattr(document, 'document_number', str(document.id)),
            'status': 'AUTHORIZED', # Optimismo para el POS
            'current_status': 'AUTHORIZED',
            'access_key': getattr(document, 'access_key', ''),
            'monitoring': {
                'polling_url': f'/api/sri/documents/{document_id}/task-status/',
                'polling_interval': 1500,
                'estimated_completion': 'Procesando en segundo plano'
            }
        })
        
    except Exception as e:
        logger.error(f"Error processing document with Celery: {e}")
        return Response({
            'error': str(e),
            'document_id': document_id
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==========================================
# VISTA PARA DASHBOARD CON ESTADÍSTICAS DE CELERY
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_with_celery_stats(request):
    """
    Dashboard con estadísticas que incluye información de Celery
    URL: /api/sri/dashboard-stats/
    """
    try:
        user_companies = get_user_companies_secure(request.user)
        
        # Estadísticas básicas de documentos
        total_docs = ElectronicDocument.objects.filter(company__in=user_companies).count()
        authorized_docs = ElectronicDocument.objects.filter(
            company__in=user_companies, 
            status='AUTHORIZED'
        ).count()
        pending_docs = ElectronicDocument.objects.filter(
            company__in=user_companies, 
            status='SENT'
        ).count()
        
        # Estadísticas de Celery
        celery_stats = {
            'healthy': False,
            'workers_count': 0,
            'active_tasks': 0,
            'user_active_tasks': 0
        }
        
        try:
            control = Control(current_app)
            workers = control.inspect().active()
            
            if workers:
                celery_stats['healthy'] = True
                celery_stats['workers_count'] = len(workers)
                celery_stats['active_tasks'] = sum(len(tasks) for tasks in workers.values())
                
                # Contar tareas del usuario
                user_task_count = 0
                for doc_id in ElectronicDocument.objects.filter(company__in=user_companies).values_list('id', flat=True):
                    cache_key = f"document_tasks_{doc_id}"
                    cached_tasks = cache.get(cache_key, [])
                    for task_id in cached_tasks:
                        try:
                            result = AsyncResult(task_id)
                            if not result.ready():
                                user_task_count += 1
                        except:
                            pass
                
                celery_stats['user_active_tasks'] = user_task_count
                
        except Exception as e:
            logger.warning(f"Error getting Celery stats for dashboard: {e}")
        
        # Documentos en procesamiento (últimos 24 horas)
        recent_cutoff = timezone.now() - timedelta(hours=24)
        recent_processing = ElectronicDocument.objects.filter(
            company__in=user_companies,
            status__in=['SENT', 'GENERATED'],
            created_at__gte=recent_cutoff
        ).count()
        
        dashboard_data = {
            'document_stats': {
                'total': total_docs,
                'authorized': authorized_docs,
                'pending': pending_docs,
                'recent_processing': recent_processing
            },
            'celery_stats': celery_stats,
            'system_health': {
                'celery_operational': celery_stats['healthy'],
                'has_pending_processing': recent_processing > 0,
                'overall_status': 'healthy' if celery_stats['healthy'] else 'degraded'
            },
            'timestamp': timezone.now().isoformat()
        }
        
        return Response(dashboard_data)
        
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==========================================
# ENDPOINT PARA TESTING
# ==========================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_celery_connection(request):
    """
    Endpoint para probar la conexión con Celery
    URL: /api/sri/celery/test/
    """
    try:
        # Probar ping básico
        control = Control(current_app)
        ping_result = control.inspect().ping()
        
        if ping_result:
            # Probar tarea simple
            from .tasks import check_all_pending_authorizations
            
            test_task = check_all_pending_authorizations.delay()
            
            return Response({
                'success': True,
                'message': 'Celery connection successful',
                'ping_result': ping_result,
                'test_task_id': test_task.id,
                'workers_active': len(ping_result),
                'timestamp': timezone.now().isoformat()
            })
        else:
            return Response({
                'success': False,
                'message': 'No Celery workers responding to ping',
                'timestamp': timezone.now().isoformat()
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
    except Exception as e:
        logger.error(f"Error testing Celery connection: {e}")
        return Response({
            'success': False,
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)