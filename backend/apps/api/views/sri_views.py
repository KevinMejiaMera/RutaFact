# -*- coding: utf-8 -*-
"""
Views completas para SRI integration
apps/api/views/sri_views.py 
"""

from rest_framework import viewsets, filters, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from django.conf import settings
import logging
import os
from functools import wraps
from apps.api.user_company_helper import get_user_companies_exact, get_user_company_by_id_or_token
import time

from apps.sri_integration.models import (
    SRIConfiguration, ElectronicDocument, DocumentItem,
    DocumentTax, SRIResponse, CreditNote, DebitNote, 
    Retention, RetentionDetail, PurchaseSettlement, PurchaseSettlementItem
)
from apps.api.serializers.sri_serializers import (
    SRIConfigurationSerializer, ElectronicDocumentSerializer,
    ElectronicDocumentCreateSerializer, DocumentItemSerializer,
    DocumentTaxSerializer, SRIResponseSerializer, 
    CreateCreditNoteSerializer, CreateDebitNoteSerializer, CreateRetentionSerializer,
    CreatePurchaseSettlementSerializer, CreditNoteResponseSerializer,
    DebitNoteResponseSerializer, RetentionResponseSerializer, PurchaseSettlementResponseSerializer,
    DocumentProcessRequestSerializer, DocumentStatusSerializer
)
from apps.sri_integration.services.global_certificate_manager import get_certificate_manager
from apps.api.permissions import IsCompanyOwnerOrAdmin
from apps.settings.models import SystemSetting
from apps.sri_integration.tasks import process_document_async

logger = logging.getLogger(__name__)


# ========== FUNCIONES AUXILIARES PARA TOKEN VSR ==========

def validate_company_certificate_for_vsr_token(company):
    """
    Valida certificado para token VSR (sin validación de usuario)
    """
    try:
        cert_manager = get_certificate_manager()
        cert_data = cert_manager.get_certificate(company.id)
        
        if not cert_data:
            return False, "Certificate not available in GlobalCertificateManager. Please configure certificate."
        
        is_valid, message = cert_manager.validate_certificate(company.id)
        if not is_valid:
            return False, f"Certificate validation failed: {message}"
        
        if "expires in" in message:
            logger.warning(f"Certificate warning for company {company.id}: {message}")
        
        return True, "Certificate is available and valid"
        
    except Exception as e:
        logger.error(f"Error validating certificate for company {company.id}: {str(e)}")
        return False, f"Error validating certificate: {str(e)}"


def validate_company_sri_configuration_vsr(company):
    """Valida que la empresa tenga configuración SRI completa - VSR VERSION"""
    try:
        sri_config = company.sri_configuration
        
        errors = []
        
        # Validar ambiente SRI
        if not sri_config.environment:
            errors.append("Ambiente SRI no configurado")
        elif sri_config.environment not in ['TEST', 'PRODUCTION']:
            errors.append("Ambiente SRI debe ser TEST o PRODUCTION")
        
        # Validar códigos de establecimiento y emisión
        if not sri_config.establishment_code:
            errors.append("Código de establecimiento no configurado")
        elif len(sri_config.establishment_code) != 3 or not sri_config.establishment_code.isdigit():
            errors.append("Código de establecimiento debe tener exactamente 3 dígitos")
        
        if not sri_config.emission_point:
            errors.append("Punto de emisión no configurado")
        elif len(sri_config.emission_point) != 3 or not sri_config.emission_point.isdigit():
            errors.append("Punto de emisión debe tener exactamente 3 dígitos")
        
        # Validar secuencias (verificar que sean > 0)
        sequence_fields = [
            ('invoice_sequence', 'FACTURA'),
            ('credit_note_sequence', 'NOTA DE CRÉDITO'),
            ('debit_note_sequence', 'NOTA DE DÉBITO'),
            ('retention_sequence', 'RETENCIÓN'),
            ('purchase_settlement_sequence', 'LIQUIDACIÓN DE COMPRA')
        ]
        
        for field_name, display_name in sequence_fields:
            sequence_value = getattr(sri_config, field_name, 0)
            if sequence_value <= 0:
                errors.append(f"Secuencia de {display_name} no configurada o inválida")
        
        # Validar configuración de email si está habilitada
        if sri_config.email_enabled:
            if not sri_config.email_subject_template:
                errors.append("Plantilla de asunto de email no configurada")
            if not sri_config.email_body_template:
                errors.append("Plantilla de cuerpo de email no configurada")
        
        # Verificar URLs automáticas (propiedad)
        try:
            reception_url = sri_config.reception_url
            authorization_url = sri_config.authorization_url
            if not reception_url or not authorization_url:
                errors.append("URLs del SRI no generadas correctamente")
        except Exception:
            errors.append("Error al generar URLs del SRI")
        
        if errors:
            return False, f"Configuración SRI incompleta: {'; '.join(errors)}"
        
        return True, f"Configuración SRI válida para ambiente {sri_config.environment}"
        
    except AttributeError:
        return False, "Empresa no tiene configuración SRI. Debe crear una configuración SRI para esta empresa."


def validate_company_basic_info_vsr(company):
    """Valida información básica de la empresa - VSR VERSION"""
    errors = []
    
    # Validar campos básicos
    if not company.business_name or len(company.business_name.strip()) < 3:
        errors.append("Razón social no configurada o muy corta (mínimo 3 caracteres)")
    
    if not company.ruc:
        errors.append("RUC no configurado")
    elif len(company.ruc) != 13:
        errors.append("RUC debe tener exactamente 13 dígitos")
    elif not company.ruc.isdigit():
        errors.append("RUC debe contener solo números")
    
    if not company.address or len(company.address.strip()) < 10:
        errors.append("Dirección no configurada o muy corta (mínimo 10 caracteres)")
    
    if not company.email:
        errors.append("Email de la empresa no configurado")
    
    # Validar campos específicos del SRI usando el modelo Company
    if not company.tipo_contribuyente:
        errors.append("Tipo de contribuyente no configurado")
    
    if not company.obligado_contabilidad:
        errors.append("Campo 'obligado a llevar contabilidad' no configurado")
    
    # Validar códigos adicionales si están configurados
    if company.codigo_establecimiento and len(company.codigo_establecimiento) != 3:
        errors.append("Código de establecimiento en empresa debe tener 3 dígitos")
    
    if company.codigo_punto_emision and len(company.codigo_punto_emision) != 3:
        errors.append("Código de punto de emisión en empresa debe tener 3 dígitos")
    
    # Validar ambiente SRI
    if not company.ambiente_sri:
        errors.append("Ambiente SRI no configurado en empresa")
    elif company.ambiente_sri not in ['1', '2']:
        errors.append("Ambiente SRI debe ser '1' (Pruebas) o '2' (Producción)")
    
    # Validar tipo de emisión
    if not company.tipo_emision:
        errors.append("Tipo de emisión no configurado")
    elif company.tipo_emision not in ['1', '2']:
        errors.append("Tipo de emisión debe ser '1' (Normal) o '2' (Contingencia)")
    
    if errors:
        return False, f"Información básica incompleta: {'; '.join(errors)}"
    
    return True, f"Información básica de empresa válida - {company.display_name}"


# ========== DECORADOR ESPECÍFICO PARA TOKEN VSR ==========

def require_vsr_token_only():
    """
    Decorador que SOLO permite tokens VSR (Token de empresa)
    No permite tokens de usuario normales
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            # Obtener token del header
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if not auth_header.startswith('Token '):
                return Response(
                    {
                        'error': 'TOKEN_REQUIRED',
                        'message': 'Se requiere token de autenticación',
                        'required_token_type': 'VSR Company Token',
                        'token_format': 'Token vsr_XXXXXXXXXXXXXXXXX'
                    },
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            token_key = auth_header.split(' ')[1]
            
            # Verificar que sea token VSR
            if not token_key.startswith('vsr_'):
                return Response(
                    {
                        'error': 'INVALID_TOKEN_TYPE',
                        'message': 'Este endpoint requiere token de empresa (VSR)',
                        'provided_token_type': 'User Token',
                        'required_token_type': 'VSR Company Token',
                        'token_format': 'Token vsr_XXXXXXXXXXXXXXXXX'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Validar token VSR
            try:
                from apps.companies.models import CompanyAPIToken
                company_token = CompanyAPIToken.objects.get(key=token_key, is_active=True)
                
                if not company_token.is_valid():
                    return Response(
                        {
                            'error': 'TOKEN_INVALID',
                            'message': 'Token VSR inválido o expirado',
                            'company_id': company_token.company.id if company_token.company else None
                        },
                        status=status.HTTP_401_UNAUTHORIZED
                    )
                
                # Agregar información de la empresa al request
                request.company = company_token.company
                request.company_token = company_token
                
                # Actualizar estadísticas del token
                company_token.increment_usage(
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                
                logger.info(f"✅ VSR Token validated for company {company_token.company.business_name}")
                
            except CompanyAPIToken.DoesNotExist:
                return Response(
                    {
                        'error': 'TOKEN_NOT_FOUND',
                        'message': 'Token VSR no encontrado o inactivo',
                        'token_prefix': token_key[:10] + '...' if len(token_key) > 10 else token_key
                    },
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            return view_func(self, request, *args, **kwargs)
        return wrapper
    return decorator


# ========== DECORADORES CORREGIDOS PARA TOKEN VSR ==========

def require_user_company_access(get_company_id_func=None):
    """
    Decorador que valida acceso a empresa - CORREGIDO PARA TOKEN VSR
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            company = None
            
            # 🔑 MÉTODO 1: Token VSR (identificación automática)
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.startswith('Token '):
                token_key = auth_header.split(' ')[1]
                
                if token_key.startswith('vsr_'):
                    try:
                        from apps.companies.models import CompanyAPIToken
                        company_token = CompanyAPIToken.objects.get(key=token_key, is_active=True)
                        company = company_token.company
                        logger.info(f"✅ VSR Token: Company {company.business_name} identified automatically")
                    except CompanyAPIToken.DoesNotExist:
                        logger.warning(f"❌ Invalid VSR token: {token_key[:20]}...")
            
            # 🔑 MÉTODO 2: Token de usuario + company_id
            if not company:
                # Función personalizada para obtener company_id
                if get_company_id_func:
                    company_id = get_company_id_func(request, *args, **kwargs)
                else:
                    # Buscar en data, query_params o kwargs
                    company_id = (
                        request.data.get('company') or 
                        request.data.get('company_id') or
                        request.query_params.get('company_id') or
                        kwargs.get('company_id')
                    )
                
                if not company_id:
                    return Response(
                        {
                            'error': 'COMPANY_ID_REQUIRED',
                            'message': 'Company ID is required for this operation',
                            'user': getattr(request.user, 'username', 'Unknown'),
                            'audit_info': {
                                'processed_by': getattr(request.user, 'username', 'Unknown'),
                                'processing_time_ms': 1.0,
                                'action_type': 'VALIDATION_ERROR',
                                'timestamp': timezone.now().isoformat(),
                                'security_method': 'token_validation_with_decorators'
                            }
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Validar acceso usando la función auxiliar
                company = get_user_company_by_id_or_token(company_id, request.user)
            
            if not company:
                logger.warning(f"🚫 User {getattr(request.user, 'username', 'Unknown')} denied access to company")
                return Response(
                    {
                        'error': 'COMPANY_ACCESS_DENIED',
                        'message': 'You do not have access to this company',
                        'user': getattr(request.user, 'username', 'Unknown'),
                        'security_check': 'user_company_access_decorator'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Agregar la empresa validada al request para uso posterior
            request.validated_company = company
            logger.info(f"✅ User {getattr(request.user, 'username', 'Unknown')} validated access to company {company.id}")
            
            return view_func(self, request, *args, **kwargs)
        return wrapper
    return decorator


def require_document_access():
    """
    Decorador que valida que el usuario tenga acceso al documento especificado
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            document_id = kwargs.get('pk')
            
            if not document_id:
                return Response(
                    {
                        'error': 'DOCUMENT_ID_REQUIRED',
                        'message': 'Document ID is required for this operation'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validar acceso al documento
            document, document_type, electronic_doc = find_document_by_id_for_user(document_id, request.user)
            
            if not document:
                logger.warning(f"🚫 User {getattr(request.user, 'username', 'Unknown')} denied access to document {document_id}")
                return Response(
                    {
                        'error': 'DOCUMENT_NOT_FOUND',
                        'message': f'Document with ID {document_id} not found or you do not have access to it',
                        'user': getattr(request.user, 'username', 'Unknown'),
                        'requested_document': str(document_id),
                        'security_check': 'document_access_decorator'
                    },
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Agregar documentos validados al request
            request.validated_document = document
            request.validated_document_type = document_type
            request.validated_electronic_doc = electronic_doc
            
            logger.info(f" User {getattr(request.user, 'username', 'Unknown')} validated access to {document_type} {document_id}")
            
            return view_func(self, request, *args, **kwargs)
        return wrapper
    return decorator


def require_certificate_validation():
    """
    Decorador que valida que la empresa tenga certificado disponible
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            # La empresa debe estar ya validada por otro decorador
            company = getattr(request, 'validated_company', None)
            
            if not company:
                # Intentar obtener de documento validado
                document = getattr(request, 'validated_document', None)
                if document:
                    company = document.company
            
            if not company:
                return Response(
                    {
                        'error': 'COMPANY_NOT_VALIDATED',
                        'message': 'Company must be validated before certificate check',
                        'suggestion': 'Use @require_user_company_access decorator first'
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Validar certificado
            cert_valid, cert_message = validate_company_certificate_for_user(company, request.user)
            
            if not cert_valid:
                logger.warning(f"🔐 Certificate not available for company {company.id}: {cert_message}")
                return Response(
                    {
                        'error': 'CERTIFICATE_NOT_AVAILABLE',
                        'message': cert_message,
                        'company_id': company.id,
                        'company_name': company.business_name,
                        'user': getattr(request.user, 'username', 'Unknown'),
                        'security_check': 'certificate_validation_decorator',
                        'suggestion': 'Please configure digital certificate for this company'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Agregar información del certificado al request
            request.certificate_validated = True
            request.certificate_message = cert_message
            
            logger.info(f"🔐 Certificate validated for company {company.id} by user {getattr(request.user, 'username', 'Unknown')}")
            
            return view_func(self, request, *args, **kwargs)
        return wrapper
    return decorator


def audit_api_action(action_type=None, include_response_data=False):
    """
    Decorador para auditoría completa de acciones API
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            start_time = time.time()
            action = action_type or view_func.__name__.upper()
            
            # Log inicial
            logger.info(f"🚀 [{action}] User {getattr(request.user, 'username', 'Unknown')} - {view_func.__name__} - Started")
            
            try:
                # Ejecutar la función original
                response = view_func(self, request, *args, **kwargs)
                
                # Calcular tiempo de ejecución
                execution_time = time.time() - start_time
                
                logger.info(f" [{action}] User {getattr(request.user, 'username', 'Unknown')} - SUCCESS - {execution_time:.2f}s")
                
                return response
                
            except Exception as e:
                # Calcular tiempo hasta el error
                execution_time = time.time() - start_time
                
                logger.error(f" [{action}] User {getattr(request.user, 'username', 'Unknown')} - ERROR: {str(e)} - {execution_time:.2f}s")
                
                # Re-lanzar la excepción para que sea manejada normalmente
                raise
                
        return wrapper
    return decorator


def validate_sri_configuration():
    """
    Decorador que valida que la empresa tenga configuración SRI válida
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            # La empresa debe estar validada previamente
            company = getattr(request, 'validated_company', None)
            
            if not company:
                document = getattr(request, 'validated_document', None)
                if document:
                    company = document.company
            
            if not company:
                return Response(
                    {
                        'error': 'COMPANY_NOT_VALIDATED',
                        'message': 'Company must be validated before SRI configuration check'
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Verificar configuración SRI
            try:
                sri_config = company.sri_configuration
                request.validated_sri_config = sri_config
                logger.info(f" SRI configuration validated for company {company.id}")
                
            except AttributeError:
                logger.warning(f" No SRI configuration found for company {company.id}")
                return Response(
                    {
                        'error': 'SRI_CONFIGURATION_MISSING',
                        'message': 'Company does not have SRI configuration',
                        'company_id': company.id,
                        'company_name': company.business_name,
                        'user': getattr(request.user, 'username', 'Unknown'),
                        'suggestion': 'Please configure SRI settings for this company'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            return view_func(self, request, *args, **kwargs)
        return wrapper
    return decorator


def validate_request_data(required_fields=None):
    """
    Decorador para validar datos del request - CORREGIDO PARA VSR
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            if required_fields:
                missing_fields = []
                
                # 🔑 EXCEPCIÓN: Si es token VSR, no requerir 'company'
                auth_header = request.META.get('HTTP_AUTHORIZATION', '')
                is_vsr_token = auth_header.startswith('Token vsr_')
                
                for field in required_fields:
                    # Saltar validación de 'company' para tokens VSR
                    if field == 'company' and is_vsr_token:
                        continue
                        
                    if field not in request.data:
                        missing_fields.append(field)
                
                if missing_fields:
                    logger.warning(f" Missing required fields: {missing_fields} - User: {getattr(request.user, 'username', 'Unknown')}")
                    return Response(
                        {
                            'error': 'VALIDATION_ERROR',
                            'message': 'Missing required fields',
                            'missing_fields': missing_fields,
                            'required_fields': required_fields,
                            'user': getattr(request.user, 'username', 'Unknown'),
                            'token_type': 'VSR' if is_vsr_token else 'USER'
                        },
                        status=status.HTTP_422_UNPROCESSABLE_ENTITY
                    )
            
            logger.info(f" Request data validated for {view_func.__name__} - User: {getattr(request.user, 'username', 'Unknown')}")
            return view_func(self, request, *args, **kwargs)
        return wrapper
    return decorator


def atomic_transaction():
    """
    Decorador para transacciones atómicas con manejo de errores
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            try:
                with transaction.atomic():
                    logger.info(f" Transaction started for {view_func.__name__} - User: {getattr(request.user, 'username', 'Unknown')}")
                    response = view_func(self, request, *args, **kwargs)
                    logger.info(f" Transaction committed for {view_func.__name__} - User: {getattr(request.user, 'username', 'Unknown')}")
                    return response
                    
            except Exception as e:
                logger.error(f" Transaction rolled back for {view_func.__name__} - Error: {str(e)} - User: {getattr(request.user, 'username', 'Unknown')}")
                raise
                
        return wrapper
    return decorator


# Decorador combinado para endpoints SRI seguros
def sri_secure_endpoint(
    require_company_access=True,
    require_certificate=False,
    require_sri_config=False,
    audit_action=None,
    validate_fields=None,
    atomic=True
):
    """
    Decorador combinado para endpoints SRI seguros - CORREGIDO PARA VSR
    """
    def decorator(view_func):
        func = view_func
        
        if atomic:
            func = atomic_transaction()(func)
        
        if validate_fields:
            func = validate_request_data(required_fields=validate_fields)(func)
        
        if require_sri_config:
            func = validate_sri_configuration()(func)
        
        if require_certificate:
            func = require_certificate_validation()(func)
        
        if require_company_access:
            func = require_user_company_access()(func)
        
        if audit_action:
            func = audit_api_action(action_type=audit_action, include_response_data=True)(func)
        
        return func
    return decorator


# Decorador para endpoints de documentos
def sri_document_endpoint(
    require_certificate=False,
    audit_action=None,
    atomic=True
):
    """
    Decorador especializado para endpoints que trabajan con documentos
    """
    def decorator(view_func):
        func = view_func
        
        if atomic:
            func = atomic_transaction()(func)
        
        if require_certificate:
            func = require_certificate_validation()(func)
        
        func = require_document_access()(func)
        
        if audit_action:
            func = audit_api_action(action_type=audit_action, include_response_data=True)(func)
        
        return func
    return decorator


# ========== FUNCIONES AUXILIARES ==========

def sync_document_to_electronic_document(document, document_type):
    """
    Sincroniza cualquier tipo de documento con ElectronicDocument
    """
    try:
        # Verificar si ya existe ElectronicDocument
        try:
            existing = ElectronicDocument.objects.get(access_key=document.access_key)
            logger.info(f'ElectronicDocument already exists for {document_type} {document.id}')
            return existing
        except ElectronicDocument.DoesNotExist:
            pass
        
        # Mapear campos según el tipo de documento
        base_data = {
            'company': document.company,
            'document_type': document_type,
            'document_number': document.document_number,
            'access_key': document.access_key,
            'issue_date': document.issue_date,
            'status': document.status,
            'xml_file': '',
            'signed_xml_file': '',
        }
        
        # Campos específicos según el tipo
        if document_type in ['CREDIT_NOTE', 'DEBIT_NOTE']:
            base_data.update({
                'customer_identification_type': document.customer_identification_type,
                'customer_identification': document.customer_identification,
                'customer_name': document.customer_name,
                'customer_address': document.customer_address,
                'customer_email': document.customer_email,
                'subtotal_without_tax': document.subtotal_without_tax,
                'total_tax': document.total_tax,
                'total_amount': document.total_amount,
            })
        elif document_type == 'RETENTION':
            base_data.update({
                'customer_identification_type': document.supplier_identification_type,
                'customer_identification': document.supplier_identification,
                'customer_name': document.supplier_name,
                'customer_address': getattr(document, 'supplier_address', ''),
                'customer_email': '',
                'subtotal_without_tax': 0,
                'total_tax': 0,
                'total_amount': document.total_retained,
            })
        elif document_type == 'PURCHASE_SETTLEMENT':
            base_data.update({
                'customer_identification_type': document.supplier_identification_type,
                'customer_identification': document.supplier_identification,
                'customer_name': document.supplier_name,
                'customer_address': getattr(document, 'supplier_address', ''),
                'customer_email': '',
                'subtotal_without_tax': document.subtotal_without_tax,
                'total_tax': document.total_tax,
                'total_amount': document.total_amount,
            })
        
        # Crear ElectronicDocument
        electronic_doc = ElectronicDocument.objects.create(**base_data)
        
        logger.info(f'ElectronicDocument {electronic_doc.id} created for {document_type} {document.id}')
        return electronic_doc
        
    except Exception as e:
        logger.error(f'Error syncing {document_type} {document.id} to ElectronicDocument: {e}')
        return None


def find_document_by_id_for_user(pk, user):
    """
    Busca un documento por ID SOLO en las empresas del usuario autenticado
    """
    document = None
    document_type = None
    electronic_doc = None
    
    # 🔒 SEGURIDAD: Obtener empresas del usuario
    if user.is_superuser:
        from apps.companies.models import Company
        user_companies = Company.objects.filter(is_active=True)
    else:
        user_companies = get_user_companies_exact(user)
    
    if not user_companies.exists():
        logger.warning(f"User {getattr(user, 'username', 'Unknown')} has no accessible companies")
        return None, None, None
    
    # Buscar en orden de prioridad, LIMITADO a empresas del usuario
    search_order = [
        (CreditNote, 'CREDIT_NOTE'),
        (DebitNote, 'DEBIT_NOTE'),
        (Retention, 'RETENTION'),
        (PurchaseSettlement, 'PURCHASE_SETTLEMENT'),
        (ElectronicDocument, 'INVOICE')
    ]
    
    for model, doc_type in search_order:
        try:
            document = model.objects.filter(
                id=pk,
                company__in=user_companies  # 🔒 FILTRO DE SEGURIDAD
            ).first()
            
            if document:
                document_type = doc_type
                logger.info(f'Found document {pk} as {doc_type} for user {getattr(user, "username", "Unknown")}')
                break
        except Exception as e:
            logger.error(f"Error searching in {model}: {e}")
            continue
    
    if not document:
        logger.warning(f"Document {pk} not found or not accessible for user {getattr(user, 'username', 'Unknown')}")
        return None, None, None
    
    # Si encontramos un documento específico, sincronizar con ElectronicDocument
    if document_type != 'INVOICE':
        electronic_doc = sync_document_to_electronic_document(document, document_type)
    else:
        electronic_doc = document
    
    return document, document_type, electronic_doc


def validate_company_certificate_for_user(company, user):
    """
    Valida que la empresa pertenezca al usuario Y tenga certificado disponible
    """
    # 🔒 SEGURIDAD: Verificar que el usuario tiene acceso a la empresa
    if user.is_superuser:
        # Superuser tiene acceso a todas las empresas activas
        from apps.companies.models import Company
        if not Company.objects.filter(id=company.id, is_active=True).exists():
            return False, "Company not found or inactive"
    else:
        # Usuario normal solo puede acceder a sus empresas
        if company not in get_user_companies_exact(user):
            logger.warning(f"User {getattr(user, 'username', 'Unknown')} tried to access company {company.id} without permission")
            return False, "You do not have access to this company"
    
    try:
        cert_manager = get_certificate_manager()
        cert_data = cert_manager.get_certificate(company.id)
        
        if not cert_data:
            return False, "Certificate not available in GlobalCertificateManager. Please configure certificate."
        
        is_valid, message = cert_manager.validate_certificate(company.id)
        if not is_valid:
            return False, f"Certificate validation failed: {message}"
        
        if "expires in" in message:
            logger.warning(f"Certificate warning for company {company.id}: {message}")
        
        return True, "Certificate is available and valid"
        
    except Exception as e:
        logger.error(f"Error validating certificate for company {company.id}: {str(e)}")
        return False, f"Error validating certificate: {str(e)}"


def get_user_company_by_id(company_id, user):
    """
    Obtiene empresa por ID o JWT token - VERSIÓN HÍBRIDA CORREGIDA
    """
    return get_user_company_by_id_or_token(company_id, user)


# ========== CLASE PRINCIPAL CON RESPUESTAS SIMPLIFICADAS ==========

class SRIDocumentViewSet(viewsets.ModelViewSet):
    """
    ViewSet principal para todos los documentos SRI 
    ✅ CON RESPUESTAS SIMPLIFICADAS PARA PRODUCCIÓN
    ✅ RESUELVE ERROR 35
    ✅ COMPATIBLE CON TOKEN VSR
    ✅ INCLUYE ENDPOINT DE VALIDACIÓN VSR
    """
    queryset = ElectronicDocument.objects.all()
    serializer_class = ElectronicDocumentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['company', 'document_type', 'status', 'issue_date', 'customer_identification_type']
    search_fields = ['document_number', 'customer_name', 'customer_identification', 'access_key']
    ordering_fields = ['issue_date', 'created_at', 'total_amount', 'document_number']
    ordering = ['-created_at']
    permission_classes = [permissions.IsAuthenticated, IsCompanyOwnerOrAdmin]
    
    def get_queryset(self):
        """
        Filtra documentos SOLO por empresas del usuario autenticado
        """
        user = self.request.user
        
        if user.is_superuser:
            logger.info(f"Superuser {getattr(user, 'username', 'Admin')} accessing all documents")
            return ElectronicDocument.objects.all()
        
        # 🔒 SEGURIDAD: Usuario normal solo ve documentos de sus empresas
        user_companies = get_user_companies_exact(user)
        if user_companies.exists():
            logger.info(f"User {getattr(user, 'username', 'Unknown')} accessing documents from {user_companies.count()} companies")
            return ElectronicDocument.objects.filter(company__in=user_companies)
        
        # Si no tiene empresas, no ve nada
        logger.warning(f"User {getattr(user, 'username', 'Unknown')} has no accessible companies")
        return ElectronicDocument.objects.none()
    
    def get_serializer_class(self):
        """
        Retorna el serializer apropiado según la acción
        """
        if self.action == 'create':
            return ElectronicDocumentCreateSerializer
        elif self.action == 'list':
            return ElectronicDocumentSerializer
        return ElectronicDocumentSerializer
    
    def handle_exception(self, exc):
        """
        Manejo centralizado de excepciones
        """
        if isinstance(exc, ValueError):
            return Response(
                {
                    'error': 'VALIDATION_ERROR',
                    'message': str(exc),
                    'code': 'INVALID_DATA'
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        elif isinstance(exc, PermissionError):
            return Response(
                {
                    'error': 'PERMISSION_DENIED',
                    'message': 'Insufficient permissions to perform this action',
                    'code': 'FORBIDDEN'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        return super().handle_exception(exc)
    
    # ========== NUEVO: ENDPOINT DE VALIDACIÓN PARA TOKEN VSR ==========
    
    @action(detail=False, methods=['post', 'get'])
    @require_vsr_token_only()
    @audit_api_action(action_type='VALIDATE_COMPANY_CERTIFICATE_AND_CONFIG')
    def validate_certificate_and_config(self, request):
        """
         VALIDACIÓN SIMPLE: Certificado y Configuraciones
        
         SOLO FUNCIONA CON TOKEN VSR (Token de empresa)
        
        Valida únicamente:
        - Estado del certificado digital
        - Configuración SRI básica  
        - Información mínima de la empresa
        
        REQUIERE: Token vsr_XXXXXXXXXXXXXXXXX
        """
        try:
            start_time = time.time()
            company = request.company  # Obtenido del decorador VSR
            company_token = request.company_token
            
            logger.info(f" [VSR_VALIDATION] Checking certificate and config for company {company.id} - Token: {company_token.name}")
            
            # Estructura de respuesta simple
            validation_result = {
                'company_id': company.id,
                'company_name': company.business_name,
                'company_ruc': company.ruc,
                'token_info': {
                    'name': company_token.name,
                    'last_used': company_token.last_used_at.isoformat() if company_token.last_used_at else None,
                    'total_requests': company_token.total_requests
                },
                'certificate': {
                    'status': 'unknown',
                    'valid': False,
                    'message': '',
                    'details': {}
                },
                'sri_configuration': {
                    'status': 'unknown',
                    'valid': False,
                    'message': '',
                    'missing_items': []
                },
                'company_basic_info': {
                    'status': 'unknown',
                    'valid': False,
                    'message': '',
                    'missing_items': []
                },
                'overall_status': 'incomplete',
                'ready_for_documents': False,
                'next_actions': []
            }
            
            # ===== VALIDACIÓN 1: INFORMACIÓN BÁSICA DE EMPRESA =====
            basic_valid, basic_msg = validate_company_basic_info_vsr(company)
            missing_basic = []
            if not basic_valid:
                # Extraer items faltantes del mensaje
                if "incompleta:" in basic_msg:
                    missing_text = basic_msg.split("incompleta:")[1].strip()
                    missing_basic = [item.strip() for item in missing_text.split(";")]
            
            validation_result['company_basic_info'] = {
                'status': 'complete' if basic_valid else 'incomplete',
                'valid': basic_valid,
                'message': basic_msg,
                'missing_items': missing_basic
            }
            
            # ===== VALIDACIÓN 2: CONFIGURACIÓN SRI =====
            sri_valid, sri_msg = validate_company_sri_configuration_vsr(company)
            missing_sri = []
            if not sri_valid:
                # Extraer items faltantes del mensaje
                if "incompleta:" in sri_msg:
                    missing_text = sri_msg.split("incompleta:")[1].strip()
                    missing_sri = [item.strip() for item in missing_text.split(";")]
                elif "no tiene configuración SRI" in sri_msg:
                    missing_sri = ["Configuración SRI completa (no existe)"]
            
            try:
                sri_config = company.sri_configuration
                validation_result['sri_configuration'] = {
                    'status': 'complete' if sri_valid else 'incomplete',
                    'valid': sri_valid,
                    'message': sri_msg,
                    'missing_items': missing_sri,
                    'environment': sri_config.environment if sri_config else None,
                    'establishment': sri_config.establishment_code if sri_config else None,
                    'emission_point': sri_config.emission_point if sri_config else None
                }
            except AttributeError:
                validation_result['sri_configuration'] = {
                    'status': 'missing',
                    'valid': False,
                    'message': 'No existe configuración SRI para esta empresa',
                    'missing_items': ["Configuración SRI completa (no existe)"]
                }
            
            # ===== VALIDACIÓN 3: CERTIFICADO DIGITAL =====
            cert_valid, cert_msg = validate_company_certificate_for_vsr_token(company)
            
            if cert_valid:
                # Obtener detalles del certificado
                try:
                    cert_manager = get_certificate_manager()
                    cert_data = cert_manager.get_certificate(company.id)
                    cert_info = cert_manager.get_company_certificate_info(company.id)
                    
                    validation_result['certificate'] = {
                        'status': 'valid',
                        'valid': True,
                        'message': cert_msg,
                        'details': {
                            'has_certificate': True,
                            'certificate_info': cert_info,
                            'expiration_warning': "expires in" in cert_msg.lower()
                        }
                    }
                except Exception as e:
                    validation_result['certificate'] = {
                        'status': 'valid_with_warnings',
                        'valid': True,
                        'message': f"{cert_msg} (No se pudieron obtener detalles)",
                        'details': {
                            'has_certificate': True,
                            'error_getting_details': str(e)
                        }
                    }
            else:
                validation_result['certificate'] = {
                    'status': 'invalid',
                    'valid': False,
                    'message': cert_msg,
                    'details': {
                        'has_certificate': False,
                        'error_details': cert_msg
                    }
                }
            
            # ===== EVALUACIÓN GENERAL =====
            all_valid = (
                validation_result['company_basic_info']['valid'] and
                validation_result['sri_configuration']['valid'] and
                validation_result['certificate']['valid']
            )
            
            if all_valid:
                validation_result['overall_status'] = 'ready'
                validation_result['ready_for_documents'] = True
                validation_result['next_actions'] = [
                    " Empresa lista para crear documentos electrónicos",
                    " Puede usar los endpoints de creación completa",
                    " Todos los documentos se procesarán correctamente"
                ]
            else:
                validation_result['overall_status'] = 'incomplete'
                validation_result['ready_for_documents'] = False
                
                # Generar acciones específicas
                next_actions = []
                
                if not validation_result['company_basic_info']['valid']:
                    next_actions.append(f" Completar información básica: {', '.join(missing_basic)}")
                
                if not validation_result['sri_configuration']['valid']:
                    if 'Configuración SRI completa (no existe)' in missing_sri:
                        next_actions.append(" Crear configuración SRI para la empresa")
                    else:
                        next_actions.append(f" Completar configuración SRI: {', '.join(missing_sri)}")
                
                if not validation_result['certificate']['valid']:
                    next_actions.append(" Configurar certificado digital válido")
                
                next_actions.append(" Volver a validar después de completar configuraciones")
                
                validation_result['next_actions'] = next_actions
            
            # ===== INFORMACIÓN ADICIONAL =====
            processing_time = time.time() - start_time
            validation_result.update({
                'processing_time_ms': round(processing_time * 1000, 2),
                'timestamp': timezone.now().isoformat(),
                'validation_version': '2.4.0-VSR-ONLY'
            })
            
            # ===== RESPUESTA =====
            logger.info(f"🔍 [VSR_VALIDATION] Completed in {processing_time:.2f}s - Ready: {validation_result['ready_for_documents']} - Company: {company.business_name}")
            
            # Status HTTP según el resultado
            if validation_result['ready_for_documents']:
                response_status = status.HTTP_200_OK
            else:
                response_status = status.HTTP_422_UNPROCESSABLE_ENTITY
            
            return Response(validation_result, status=response_status)
            
        except Exception as e:
            logger.error(f" [VSR_VALIDATION] Critical error: {str(e)} - Company: {getattr(company, 'business_name', 'Unknown') if 'company' in locals() else 'Unknown'}")
            return Response(
                {
                    'company_id': getattr(company, 'id', None) if 'company' in locals() else None,
                    'error': 'VALIDATION_ERROR',
                    'message': f'Error durante la validación: {str(e)}',
                    'timestamp': timezone.now().isoformat(),
                    'validation_version': '2.4.0-VSR-ONLY'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    @require_vsr_token_only()
    @audit_api_action(action_type='VIEW_COMPANY_VALIDATION_STATUS')
    def validation_status_summary(self, request):
        """
         RESUMEN RÁPIDO DE ESTADO DE VALIDACIÓN
        
         SOLO FUNCIONA CON TOKEN VSR
        Endpoint GET simple para obtener el estado de LA empresa del token VSR
        """
        try:
            company = request.company  # Solo una empresa con token VSR
            company_token = request.company_token
            
            # Validación rápida de la empresa del token
            basic_valid, _ = validate_company_basic_info_vsr(company)
            sri_valid, _ = validate_company_sri_configuration_vsr(company)
            cert_valid, cert_msg = validate_company_certificate_for_vsr_token(company)
            
            overall_ready = basic_valid and sri_valid and cert_valid
            
            summary = {
                'company_id': company.id,
                'company_name': company.business_name,
                'company_ruc': company.ruc,
                'token_info': {
                    'name': company_token.name,
                    'total_requests': company_token.total_requests,
                    'last_used': company_token.last_used_at.isoformat() if company_token.last_used_at else None
                },
                'validations': {
                    'basic_info': basic_valid,
                    'sri_config': sri_valid,
                    'certificate': cert_valid
                },
                'overall_status': 'ready' if overall_ready else 'incomplete',
                'ready_for_documents': overall_ready,
                'certificate_message': cert_msg,
                'validation_timestamp': timezone.now().isoformat()
            }
            
            return Response(summary, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f" Error getting VSR validation summary: {str(e)}")
            return Response(
                {
                    'error': 'SUMMARY_ERROR',
                    'message': str(e),
                    'validation_version': '2.4.0-VSR-ONLY'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ========== ENDPOINTS CON RESPUESTAS SIMPLIFICADAS ==========
    
    @action(detail=False, methods=['post'])
    @sri_secure_endpoint(
        require_company_access=True,
        require_certificate=True,
        require_sri_config=True,
        audit_action='CREATE_AND_PROCESS_INVOICE_COMPLETE',
        validate_fields=['customer_identification_type', 'customer_identification', 'customer_name', 'issue_date', 'items'],
        atomic=True
    )
    def create_and_process_invoice_complete(self, request):
        """
         ENDPOINT COMPLETO PARA FACTURAS: Crear + Procesar completamente
         RESPUESTA SIMPLIFICADA PARA PRODUCCIÓN
        """
        try:
            from decimal import Decimal, ROUND_HALF_UP
            from apps.sri_integration.services.document_processor import DocumentProcessor
            
            start_time = time.time()
            data = request.data
            company = request.validated_company
            sri_config = request.validated_sri_config
            
            logger.info(f" [INVOICE_COMPLETE] Creating and processing invoice for user {getattr(request.user, 'username', 'Unknown')}")
            
            # Función para manejar decimales
            def fix_decimal(value, places=2):
                if isinstance(value, (int, float)):
                    value = Decimal(str(value))
                elif isinstance(value, str):
                    value = Decimal(value)
                quantizer = Decimal('0.' + '0' * places)
                return value.quantize(quantizer, rounding=ROUND_HALF_UP)
            
            # ===== PASO 1: CREAR FACTURA =====
            sequence = sri_config.get_next_sequence('INVOICE')
            document_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
            
            electronic_doc = ElectronicDocument.objects.create(
                company=company,
                document_type='INVOICE',
                document_number=document_number,
                issue_date=data['issue_date'],
                customer_identification_type=data['customer_identification_type'],
                customer_identification=data['customer_identification'],
                customer_name=data['customer_name'],
                customer_address=data.get('customer_address', ''),
                customer_email=data.get('customer_email', ''),
                customer_phone=data.get('customer_phone', ''),
                status='DRAFT'
            )
            
            # Generar clave de acceso
            electronic_doc.access_key = electronic_doc._generate_access_key()
            
            # Crear items y calcular totales
            total_subtotal = Decimal('0.00')
            total_tax = Decimal('0.00')
            
            items_data = data.get('items', [])
            for item_data in items_data:
                quantity = fix_decimal(Decimal(str(item_data['quantity'])), 6)
                unit_price = fix_decimal(Decimal(str(item_data['unit_price'])), 6)
                discount = fix_decimal(Decimal(str(item_data.get('discount', 0))), 2)
                
                subtotal = fix_decimal((quantity * unit_price) - discount, 2)
                
                DocumentItem.objects.create(
                    document=electronic_doc,
                    main_code=item_data['main_code'],
                    auxiliary_code=item_data.get('auxiliary_code', ''),
                    description=item_data['description'],
                    quantity=quantity,
                    unit_price=unit_price,
                    discount=discount,
                    subtotal=subtotal
                )
                
                # Calcular impuesto (IVA 15%)
                tax_amount = fix_decimal(subtotal * Decimal('15.00') / 100, 2)
                total_subtotal += subtotal
                total_tax += tax_amount
            
            # Actualizar totales
            total_amount = total_subtotal + total_tax
            electronic_doc.subtotal_without_tax = fix_decimal(total_subtotal, 2)
            electronic_doc.total_tax = fix_decimal(total_tax, 2)
            electronic_doc.total_amount = fix_decimal(total_amount, 2)
            electronic_doc.status = 'GENERATED'
            electronic_doc.save()
            
            creation_time = time.time()
            logger.info(f" [INVOICE_COMPLETE] Step 1: Invoice {electronic_doc.id} created in {creation_time - start_time:.2f}s")
            
            # ===== PASO 2: PROCESAR (SINCRÓNICO O ASÍNCRÓNICO) =====
            send_email = data.get('send_email', True)
            
            # Verificar si se debe procesar de forma asincrónica (por colas)
            async_setting = SystemSetting.objects.filter(key='SRI_ASYNC_PROCESSING').first()
            is_async = async_setting.get_typed_value() if async_setting else True
            
            if is_async:
                logger.info(f" [INVOICE_COMPLETE] Queuing document {electronic_doc.id} for async processing")
                process_document_async.delay(electronic_doc.id)
                
                return Response(
                    {
                        'success': True,
                        'message': 'Factura recibida y puesta en cola para procesamiento (SRI asíncrono)',
                        'invoice': {
                            'id': electronic_doc.id,
                            'number': electronic_doc.document_number,
                            'access_key': electronic_doc.access_key,
                            'customer': electronic_doc.customer_name,
                            'total': float(electronic_doc.total_amount),
                            'status': 'QUEUED',
                            'date': electronic_doc.created_at.strftime("%Y-%m-%d %H:%M")
                        }
                    },
                    status=status.HTTP_201_CREATED
                )

            # PROCESAMIENTO SINCRÓNICO (TRADICIONAL)
            from apps.sri_integration.services.document_processor import DocumentProcessor
            processor = DocumentProcessor(company)
            success, message = processor.process_document(electronic_doc, send_email)
            
            process_time = time.time()
            
            if success:
                logger.info(f" [INVOICE_COMPLETE] Processing completed synchronously in {process_time - creation_time:.2f}s")
                
                # 🎯 RESPUESTA SIMPLIFICADA
                return Response(
                    {
                        'success': True,
                        'message': 'Factura creada y enviada al SRI exitosamente',
                        'invoice': {
                            'id': electronic_doc.id,
                            'number': electronic_doc.document_number,
                            'access_key': electronic_doc.access_key,
                            'customer': electronic_doc.customer_name,
                            'total': float(electronic_doc.total_amount),
                            'status': electronic_doc.get_status_display(),
                            'date': electronic_doc.created_at.strftime("%Y-%m-%d %H:%M")
                        }
                    },
                    status=status.HTTP_201_CREATED
                )
            else:
                logger.error(f" [INVOICE_COMPLETE] Synchronous processing failed: {message}")
                return Response(
                    {
                        'success': False,
                        'message': f'Factura creada pero el procesamiento falló: {message}',
                        'invoice': {
                            'id': electronic_doc.id,
                            'number': electronic_doc.document_number,
                            'access_key': electronic_doc.access_key,
                            'error_details': message
                        }
                    },
                    status=status.HTTP_201_CREATED
                )
                
        except Exception as e:
            logger.error(f" [INVOICE_COMPLETE] Critical error: {str(e)}")
            return Response(
                {
                    'error': 'INVOICE_COMPLETE_ERROR',
                    'message': f'Error en el proceso completo de factura: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    @sri_secure_endpoint(
        require_company_access=True,
        require_certificate=True,
        require_sri_config=True,
        audit_action='CREATE_AND_PROCESS_CREDIT_NOTE_COMPLETE',
        validate_fields=['customer_identification_type', 'customer_identification', 'customer_name', 'reason_description', 'original_document_access_key'],
        atomic=True
    )
    def create_and_process_credit_note_complete(self, request):
        """
         ENDPOINT COMPLETO PARA NOTAS DE CRÉDITO: Crear + Procesar completamente
         RESPUESTA SIMPLIFICADA PARA PRODUCCIÓN
        """
        try:
            from decimal import Decimal, ROUND_HALF_UP
            from apps.sri_integration.services.document_processor import DocumentProcessor
            
            start_time = time.time()
            data = request.data
            company = request.validated_company
            sri_config = request.validated_sri_config
            
            logger.info(f" [CREDIT_NOTE_COMPLETE] Creating and processing credit note for user {getattr(request.user, 'username', 'Unknown')}")
            
            # Generar número de documento
            sequence = sri_config.get_next_sequence('CREDIT_NOTE')
            document_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
            
            # Crear nota de crédito
            credit_note = CreditNote.objects.create(
                company=company,
                document_number=document_number,
                issue_date=data['issue_date'],
                customer_identification_type=data['customer_identification_type'],
                customer_identification=data['customer_identification'],
                customer_name=data['customer_name'],
                customer_address=data.get('customer_address', ''),
                customer_email=data.get('customer_email', ''),
                reason_description=data['reason_description'],
                original_document_access_key=data['original_document_access_key'],
                subtotal_without_tax=Decimal(str(data.get('subtotal_without_tax', 0))),
                total_tax=Decimal(str(data.get('total_tax', 0))),
                total_amount=Decimal(str(data.get('total_amount', 0))),
                status='DRAFT'
            )
            
            # Generar clave de acceso
            credit_note.access_key = credit_note._generate_access_key()
            credit_note.status = 'GENERATED'
            credit_note.save()
            
            # Sincronizar con ElectronicDocument
            electronic_doc = sync_document_to_electronic_document(credit_note, 'CREDIT_NOTE')
            
            creation_time = time.time()
            logger.info(f" [CREDIT_NOTE_COMPLETE] Step 1: Credit note {credit_note.id} created in {creation_time - start_time:.2f}s")
            
            # ===== PASO 2: PROCESAR (SINCRÓNICO O ASÍNCRÓNICO) =====
            send_email = data.get('send_email', True)
            
            # Verificar si se debe procesar de forma asincrónica (por colas)
            async_setting = SystemSetting.objects.filter(key='SRI_ASYNC_PROCESSING').first()
            is_async = async_setting.get_typed_value() if async_setting else True
            
            if is_async:
                logger.info(f" [CREDIT_NOTE_COMPLETE] Queuing document {electronic_doc.id} for async processing")
                process_document_async.delay(electronic_doc.id)
                
                return Response(
                    {
                        'success': True,
                        'message': 'Nota de crédito recibida y puesta en cola (SRI asíncrono)',
                        'credit_note': {
                            'id': credit_note.id,
                            'number': credit_note.document_number,
                            'access_key': credit_note.access_key,
                            'customer': credit_note.customer_name,
                            'total': float(credit_note.total_amount),
                            'status': 'QUEUED',
                            'date': credit_note.created_at.strftime("%Y-%m-%d %H:%M")
                        }
                    },
                    status=status.HTTP_201_CREATED
                )

            # PROCESAMIENTO SINCRÓNICO (TRADICIONAL)
            from apps.sri_integration.services.document_processor import DocumentProcessor
            processor = DocumentProcessor(company)
            success, message = processor.process_document(electronic_doc, send_email)
            
            process_time = time.time()
            
            if success:
                # Actualizar documento original
                credit_note.status = electronic_doc.status
                credit_note.save()
                
                logger.info(f" [CREDIT_NOTE_COMPLETE] Processing completed synchronously in {process_time - creation_time:.2f}s")
                
                # 🎯 RESPUESTA SIMPLIFICADA
                return Response(
                    {
                        'success': True,
                        'message': 'Nota de crédito creada y enviada al SRI exitosamente',
                        'credit_note': {
                            'id': credit_note.id,
                            'number': credit_note.document_number,
                            'access_key': credit_note.access_key,
                            'customer': credit_note.customer_name,
                            'total': float(credit_note.total_amount),
                            'status': credit_note.get_status_display(),
                            'date': credit_note.created_at.strftime("%Y-%m-%d %H:%M")
                        }
                    },
                    status=status.HTTP_201_CREATED
                )
            else:
                logger.error(f" [CREDIT_NOTE_COMPLETE] Synchronous processing failed: {message}")
                return Response(
                    {
                        'success': False,
                        'message': f'Nota de crédito creada pero el procesamiento falló: {message}',
                        'credit_note': {
                            'id': credit_note.id,
                            'number': credit_note.document_number,
                            'access_key': credit_note.access_key,
                            'error_details': message
                        }
                    },
                    status=status.HTTP_201_CREATED
                )
                
        except Exception as e:
            logger.error(f" [CREDIT_NOTE_COMPLETE] Critical error: {str(e)}")
            return Response(
                {
                    'error': 'CREDIT_NOTE_COMPLETE_ERROR',
                    'message': f'Error en el proceso completo de nota de crédito: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    @sri_secure_endpoint(
        require_company_access=True,
        require_certificate=True,
        require_sri_config=True,
        audit_action='CREATE_AND_PROCESS_DEBIT_NOTE_COMPLETE',
        validate_fields=['customer_identification_type', 'customer_identification', 'customer_name', 'reason_description', 'original_document_access_key'],
        atomic=True
    )
    def create_and_process_debit_note_complete(self, request):
        """
         ENDPOINT COMPLETO PARA NOTAS DE DÉBITO: Crear + Procesar completamente
         RESPUESTA SIMPLIFICADA PARA PRODUCCIÓN
        """
        try:
            from decimal import Decimal, ROUND_HALF_UP
            from apps.sri_integration.services.document_processor import DocumentProcessor
            
            start_time = time.time()
            data = request.data
            company = request.validated_company
            sri_config = request.validated_sri_config
            
            logger.info(f" [DEBIT_NOTE_COMPLETE] Creating and processing debit note for user {getattr(request.user, 'username', 'Unknown')}")
            
            # Generar número de documento
            sequence = sri_config.get_next_sequence('DEBIT_NOTE')
            document_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
            
            # Crear nota de débito
            debit_note = DebitNote.objects.create(
                company=company,
                document_number=document_number,
                issue_date=data['issue_date'],
                customer_identification_type=data['customer_identification_type'],
                customer_identification=data['customer_identification'],
                customer_name=data['customer_name'],
                customer_address=data.get('customer_address', ''),
                customer_email=data.get('customer_email', ''),
                reason_description=data['reason_description'],
                original_document_access_key=data['original_document_access_key'],
                subtotal_without_tax=Decimal(str(data.get('subtotal_without_tax', 0))),
                total_tax=Decimal(str(data.get('total_tax', 0))),
                total_amount=Decimal(str(data.get('total_amount', 0))),
                status='DRAFT'
            )
            
            # Generar clave de acceso
            debit_note.access_key = debit_note._generate_access_key()
            debit_note.status = 'GENERATED'
            debit_note.save()
            
            # Sincronizar con ElectronicDocument
            electronic_doc = sync_document_to_electronic_document(debit_note, 'DEBIT_NOTE')
            
            creation_time = time.time()
            logger.info(f" [DEBIT_NOTE_COMPLETE] Step 1: Debit note {debit_note.id} created in {creation_time - start_time:.2f}s")
            
            # ===== PASO 2: PROCESAR (SINCRÓNICO O ASÍNCRÓNICO) =====
            send_email = data.get('send_email', True)
            
            # Verificar si se debe procesar de forma asincrónica (por colas)
            async_setting = SystemSetting.objects.filter(key='SRI_ASYNC_PROCESSING').first()
            is_async = async_setting.get_typed_value() if async_setting else True
            
            if is_async:
                logger.info(f" [DEBIT_NOTE_COMPLETE] Queuing document {electronic_doc.id} for async processing")
                process_document_async.delay(electronic_doc.id)
                
                return Response(
                    {
                        'success': True,
                        'message': 'Nota de débito recibida y puesta en cola (SRI asíncrono)',
                        'debit_note': {
                            'id': debit_note.id,
                            'number': debit_note.document_number,
                            'access_key': debit_note.access_key,
                            'customer': debit_note.customer_name,
                            'total': float(debit_note.total_amount),
                            'status': 'QUEUED',
                            'date': debit_note.created_at.strftime("%Y-%m-%d %H:%M")
                        }
                    },
                    status=status.HTTP_201_CREATED
                )

            # PROCESAMIENTO SINCRÓNICO (TRADICIONAL)
            from apps.sri_integration.services.document_processor import DocumentProcessor
            processor = DocumentProcessor(company)
            success, message = processor.process_document(electronic_doc, send_email)
            
            process_time = time.time()
            
            if success:
                # Actualizar documento original
                debit_note.status = electronic_doc.status
                debit_note.save()
                
                logger.info(f" [DEBIT_NOTE_COMPLETE] Processing completed synchronously in {process_time - creation_time:.2f}s")
                
                # 🎯 RESPUESTA SIMPLIFICADA
                return Response(
                    {
                        'success': True,
                        'message': 'Nota de débito creada y enviada al SRI exitosamente',
                        'debit_note': {
                            'id': debit_note.id,
                            'number': debit_note.document_number,
                            'access_key': debit_note.access_key,
                            'customer': debit_note.customer_name,
                            'total': float(debit_note.total_amount),
                            'status': debit_note.get_status_display(),
                            'date': debit_note.created_at.strftime("%Y-%m-%d %H:%M")
                        }
                    },
                    status=status.HTTP_201_CREATED
                )
            else:
                logger.error(f" [DEBIT_NOTE_COMPLETE] Synchronous processing failed: {message}")
                return Response(
                    {
                        'success': False,
                        'message': f'Nota de débito creada pero el procesamiento falló: {message}',
                        'debit_note': {
                            'id': debit_note.id,
                            'number': debit_note.document_number,
                            'access_key': debit_note.access_key,
                            'error_details': message
                        }
                    },
                    status=status.HTTP_201_CREATED
                )
                
        except Exception as e:
            logger.error(f" [DEBIT_NOTE_COMPLETE] Critical error: {str(e)}")
            return Response(
                {
                    'error': 'DEBIT_NOTE_COMPLETE_ERROR',
                    'message': f'Error en el proceso completo de nota de débito: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    @sri_secure_endpoint(
        require_company_access=True,
        require_certificate=True,
        require_sri_config=True,
        audit_action='CREATE_AND_PROCESS_RETENTION_COMPLETE',
        validate_fields=['supplier_identification_type', 'supplier_identification', 'supplier_name', 'fiscal_period'],
        atomic=True
    )
    def create_and_process_retention_complete(self, request):
        """
         ENDPOINT COMPLETO PARA RETENCIONES: Crear + Procesar completamente
         RESPUESTA SIMPLIFICADA PARA PRODUCCIÓN
        """
        try:
            from decimal import Decimal, ROUND_HALF_UP
            from apps.sri_integration.services.document_processor import DocumentProcessor
            
            start_time = time.time()
            data = request.data
            company = request.validated_company
            sri_config = request.validated_sri_config
            
            logger.info(f" [RETENTION_COMPLETE] Creating and processing retention for user {getattr(request.user, 'username', 'Unknown')}")
            
            # Generar número de documento
            sequence = sri_config.get_next_sequence('RETENTION')
            document_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
            
            # Crear retención
            retention = Retention.objects.create(
                company=company,
                document_number=document_number,
                issue_date=data['issue_date'],
                supplier_identification_type=data['supplier_identification_type'],
                supplier_identification=data['supplier_identification'],
                supplier_name=data['supplier_name'],
                supplier_address=data.get('supplier_address', ''),
                fiscal_period=data['fiscal_period'],
                total_retained=Decimal(str(data.get('total_retained', 0))),
                status='DRAFT'
            )
            
            # Generar clave de acceso
            retention.access_key = retention._generate_access_key()
            retention.status = 'GENERATED'
            retention.save()
            
            # Crear detalles de retención si se proporcionan
            retention_details = data.get('retention_details', [])
            for detail_data in retention_details:
                RetentionDetail.objects.create(
                    retention=retention,
                    tax_code=detail_data.get('tax_code', '2'),
                    retention_code=detail_data.get('retention_code', '303'),
                    taxable_base=Decimal(str(detail_data.get('taxable_base', 0))),
                    retention_percentage=Decimal(str(detail_data.get('retention_percentage', 30))),
                    retained_amount=Decimal(str(detail_data.get('retained_amount', 0))),
                    support_document_type=detail_data.get('support_document_type', '01'),
                    support_document_number=detail_data.get('support_document_number', '001-001-000000001'),
                    support_document_date=detail_data.get('support_document_date', retention.issue_date)
                )
            
            # Sincronizar con ElectronicDocument
            electronic_doc = sync_document_to_electronic_document(retention, 'RETENTION')
            
            creation_time = time.time()
            logger.info(f" [RETENTION_COMPLETE] Step 1: Retention {retention.id} created in {creation_time - start_time:.2f}s")
            
            # Procesar completamente
            send_email = data.get('send_email', True)
            processor = DocumentProcessor(company)
            success, message = processor.process_document(electronic_doc, send_email)
            
            process_time = time.time()
            
            if success:
                # Actualizar documento original
                retention.status = electronic_doc.status
                retention.save()
                
                logger.info(f" [RETENTION_COMPLETE] Processing completed in {process_time - creation_time:.2f}s")
                
                # 🎯 RESPUESTA SIMPLIFICADA
                return Response(
                    {
                        'success': True,
                        'message': 'Retención creada y enviada al SRI exitosamente',
                        'retention': {
                            'id': retention.id,
                            'number': retention.document_number,
                            'supplier': retention.supplier_name,
                            'total': float(retention.total_retained),
                            'status': retention.get_status_display(),
                            'date': retention.created_at.strftime("%Y-%m-%d %H:%M")
                        }
                    },
                    status=status.HTTP_201_CREATED
                )
            else:
                logger.error(f" [RETENTION_COMPLETE] Processing failed: {message}")
                return Response(
                    {
                        'success': False,
                        'message': f'Retención creada pero el procesamiento falló: {message}',
                        'retention': {
                            'id': retention.id,
                            'number': retention.document_number,
                            'error_details': message
                        }
                    },
                    status=status.HTTP_201_CREATED
                )
                
        except Exception as e:
            logger.error(f" [RETENTION_COMPLETE] Critical error: {str(e)}")
            return Response(
                {
                    'error': 'RETENTION_COMPLETE_ERROR',
                    'message': f'Error en el proceso completo de retención: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    @sri_secure_endpoint(
        require_company_access=True,
        require_certificate=True,
        require_sri_config=True,
        audit_action='CREATE_AND_PROCESS_PURCHASE_SETTLEMENT_COMPLETE',
        validate_fields=['supplier_identification_type', 'supplier_identification', 'supplier_name', 'items'],
        atomic=True
    )
    def create_and_process_purchase_settlement_complete(self, request):
        """
         ENDPOINT COMPLETO PARA LIQUIDACIONES DE COMPRA: Crear + Procesar completamente
         RESPUESTA SIMPLIFICADA PARA PRODUCCIÓN
        """
        try:
            from decimal import Decimal, ROUND_HALF_UP
            from apps.sri_integration.services.document_processor import DocumentProcessor
            
            start_time = time.time()
            data = request.data
            company = request.validated_company
            sri_config = request.validated_sri_config
            
            logger.info(f" [PURCHASE_SETTLEMENT_COMPLETE] Creating and processing purchase settlement for user {getattr(request.user, 'username', 'Unknown')}")
            
            # Función para manejar decimales
            def fix_decimal(value, places=2):
                if isinstance(value, (int, float)):
                    value = Decimal(str(value))
                elif isinstance(value, str):
                    value = Decimal(value)
                quantizer = Decimal('0.' + '0' * places)
                return value.quantize(quantizer, rounding=ROUND_HALF_UP)
            
            # Generar número de documento
            sequence = sri_config.get_next_sequence('PURCHASE_SETTLEMENT')
            document_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
            
            # Crear liquidación de compra
            purchase_settlement = PurchaseSettlement.objects.create(
                company=company,
                document_number=document_number,
                issue_date=data['issue_date'],
                supplier_identification_type=data['supplier_identification_type'],
                supplier_identification=data['supplier_identification'],
                supplier_name=data['supplier_name'],
                supplier_address=data.get('supplier_address', ''),
                status='DRAFT'
            )
            
            # Generar clave de acceso
            purchase_settlement.access_key = purchase_settlement._generate_access_key()
            
            # Crear items y calcular totales
            total_subtotal = Decimal('0.00')
            total_tax = Decimal('0.00')
            
            items_data = data.get('items', [])
            for item_data in items_data:
                quantity = fix_decimal(Decimal(str(item_data['quantity'])), 6)
                unit_price = fix_decimal(Decimal(str(item_data['unit_price'])), 6)
                discount = fix_decimal(Decimal(str(item_data.get('discount', 0))), 2)
                
                subtotal = fix_decimal((quantity * unit_price) - discount, 2)
                
                PurchaseSettlementItem.objects.create(
                    purchase_settlement=purchase_settlement,
                    main_code=item_data['main_code'],
                    auxiliary_code=item_data.get('auxiliary_code', ''),
                    description=item_data['description'],
                    quantity=quantity,
                    unit_price=unit_price,
                    discount=discount,
                    subtotal=subtotal
                )
                
                # Calcular impuesto (IVA 15%)
                tax_amount = fix_decimal(subtotal * Decimal('15.00') / 100, 2)
                total_subtotal += subtotal
                total_tax += tax_amount
            
            # Actualizar totales
            total_amount = total_subtotal + total_tax
            purchase_settlement.subtotal_without_tax = fix_decimal(total_subtotal, 2)
            purchase_settlement.total_tax = fix_decimal(total_tax, 2)
            purchase_settlement.total_amount = fix_decimal(total_amount, 2)
            purchase_settlement.status = 'GENERATED'
            purchase_settlement.save()
            
            # Sincronizar con ElectronicDocument
            electronic_doc = sync_document_to_electronic_document(purchase_settlement, 'PURCHASE_SETTLEMENT')
            
            creation_time = time.time()
            logger.info(f" [PURCHASE_SETTLEMENT_COMPLETE] Step 1: Purchase settlement {purchase_settlement.id} created in {creation_time - start_time:.2f}s")
            
            # Procesar completamente
            send_email = data.get('send_email', True)
            
            processor = DocumentProcessor(company)
            success, message = processor.process_document(electronic_doc, send_email)
            
            process_time = time.time()
            
            if success:
                # Actualizar documento original
                purchase_settlement.status = electronic_doc.status
                purchase_settlement.save()
                
                logger.info(f" [PURCHASE_SETTLEMENT_COMPLETE] Processing completed in {process_time - creation_time:.2f}s")
                
                # 🎯 RESPUESTA SIMPLIFICADA
                return Response(
                    {
                        'success': True,
                        'message': 'Liquidación de compra creada y enviada al SRI exitosamente',
                        'purchase_settlement': {
                            'id': purchase_settlement.id,
                            'number': purchase_settlement.document_number,
                            'supplier': purchase_settlement.supplier_name,
                            'total': float(purchase_settlement.total_amount),
                            'status': purchase_settlement.get_status_display(),
                            'date': purchase_settlement.created_at.strftime("%Y-%m-%d %H:%M")
                        }
                    },
                    status=status.HTTP_201_CREATED
                )
            else:
                logger.error(f" [PURCHASE_SETTLEMENT_COMPLETE] Processing failed: {message}")
                return Response(
                    {
                        'success': False,
                        'message': f'Liquidación de compra creada pero el procesamiento falló: {message}',
                        'purchase_settlement': {
                            'id': purchase_settlement.id,
                            'number': purchase_settlement.document_number,
                            'error_details': message
                        }
                    },
                    status=status.HTTP_201_CREATED
                )
                
        except Exception as e:
            logger.error(f" [PURCHASE_SETTLEMENT_COMPLETE] Critical error: {str(e)}")
            return Response(
                {
                    'error': 'PURCHASE_SETTLEMENT_COMPLETE_ERROR',
                    'message': f'Error en el proceso completo de liquidación de compra: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ========== ENDPOINTS INDIVIDUALES EXISTENTES (MANTENIDOS) ==========
    
    @action(detail=False, methods=['post'])
    @sri_secure_endpoint(
        require_company_access=True,
        require_certificate=True,
        require_sri_config=True,
        audit_action='CREATE_INVOICE',
        validate_fields=['customer_identification_type', 'customer_identification', 'customer_name', 'issue_date', 'items'],
        atomic=True
    )
    def create_invoice(self, request):
        """
        Crear factura electrónica (solo creación) - MANTENIDO PARA COMPATIBILIDAD
        """
        try:
            from decimal import Decimal, ROUND_HALF_UP
            
            data = request.data
            company = request.validated_company
            sri_config = request.validated_sri_config
            
            # Generar número de documento
            sequence = sri_config.get_next_sequence('INVOICE')
            document_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
            
            # Función para manejar decimales
            def fix_decimal(value, places=2):
                if isinstance(value, (int, float)):
                    value = Decimal(str(value))
                elif isinstance(value, str):
                    value = Decimal(value)
                quantizer = Decimal('0.' + '0' * places)
                return value.quantize(quantizer, rounding=ROUND_HALF_UP)
            
            # Crear ElectronicDocument directamente
            electronic_doc = ElectronicDocument.objects.create(
                company=company,
                document_type='INVOICE',
                document_number=document_number,
                issue_date=data['issue_date'],
                customer_identification_type=data['customer_identification_type'],
                customer_identification=data['customer_identification'],
                customer_name=data['customer_name'],
                customer_address=data.get('customer_address', ''),
                customer_email=data.get('customer_email', ''),
                customer_phone=data.get('customer_phone', ''),
                status='DRAFT'
            )
            
            # Generar clave de acceso
            electronic_doc.access_key = electronic_doc._generate_access_key()
            
            # Crear items y calcular totales
            total_subtotal = Decimal('0.00')
            total_tax = Decimal('0.00')
            
            items_data = data.get('items', [])
            for item_data in items_data:
                quantity = fix_decimal(Decimal(str(item_data['quantity'])), 6)
                unit_price = fix_decimal(Decimal(str(item_data['unit_price'])), 6)
                discount = fix_decimal(Decimal(str(item_data.get('discount', 0))), 2)
                
                subtotal = fix_decimal((quantity * unit_price) - discount, 2)
                
                DocumentItem.objects.create(
                    document=electronic_doc,
                    main_code=item_data['main_code'],
                    auxiliary_code=item_data.get('auxiliary_code', ''),
                    description=item_data['description'],
                    quantity=quantity,
                    unit_price=unit_price,
                    discount=discount,
                    subtotal=subtotal
                )
                
                # Calcular impuesto (IVA 15%)
                tax_amount = fix_decimal(subtotal * Decimal('15.00') / 100, 2)
                total_subtotal += subtotal
                total_tax += tax_amount
            
            # Actualizar totales
            total_amount = total_subtotal + total_tax
            electronic_doc.subtotal_without_tax = fix_decimal(total_subtotal, 2)
            electronic_doc.total_tax = fix_decimal(total_tax, 2)
            electronic_doc.total_amount = fix_decimal(total_amount, 2)
            electronic_doc.status = 'GENERATED'
            electronic_doc.save()
            
            logger.info(f'🎉 Invoice ElectronicDocument {electronic_doc.id} created by user {getattr(request.user, "username", "Unknown")}')
            
            # Respuesta con datos de la factura
            response_data = {
                'id': electronic_doc.id,
                'company': electronic_doc.company.id,
                'company_name': electronic_doc.company.business_name,
                'document_type': electronic_doc.document_type,
                'document_number': electronic_doc.document_number,
                'access_key': electronic_doc.access_key,
                'issue_date': electronic_doc.issue_date,
                'customer_identification_type': electronic_doc.customer_identification_type,
                'customer_identification': electronic_doc.customer_identification,
                'customer_name': electronic_doc.customer_name,
                'customer_address': electronic_doc.customer_address,
                'customer_email': electronic_doc.customer_email,
                'subtotal_without_tax': str(electronic_doc.subtotal_without_tax),
                'total_tax': str(electronic_doc.total_tax),
                'total_amount': str(electronic_doc.total_amount),
                'status': electronic_doc.status,
                'status_display': electronic_doc.get_status_display(),
                'sri_authorization_code': electronic_doc.sri_authorization_code,
                'sri_authorization_date': electronic_doc.sri_authorization_date,
                'created_at': electronic_doc.created_at,
                'updated_at': electronic_doc.updated_at,
                'certificate_ready': True,
                'processing_method': 'create_invoice_only'
            }
            
            return Response(response_data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error creating invoice for user {getattr(request.user, 'username', 'Unknown')}: {str(e)}")
            return Response(
                {
                    'error': 'INTERNAL_SERVER_ERROR',
                    'message': f'Error creating invoice: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    # ========== PROCESAMIENTO INDIVIDUAL CON DECORADORES ==========
    
    @action(detail=True, methods=['post'])
    @sri_document_endpoint(
        require_certificate=False,
        audit_action='GENERATE_XML',
        atomic=False
    )
    def generate_xml(self, request, pk=None):
        """
        Generar XML del documento usando XMLGenerator CORREGIDO
        """
        document = request.validated_document
        document_type = request.validated_document_type
        electronic_doc = request.validated_electronic_doc
        
        # Verificar certificado disponible (sin bloquear)
        cert_valid, cert_message = validate_company_certificate_for_user(document.company, request.user)
        if not cert_valid:
            logger.warning(f"Certificate not ready for company {document.company.id}: {cert_message}")
        
        try:
            from apps.sri_integration.services.document_processor import DocumentProcessor
            
            processor = DocumentProcessor(document.company)
            success, result = processor._generate_xml(electronic_doc or document)
            
            if not success:
                return Response(
                    {
                        'error': 'XML_GENERATION_ERROR',
                        'message': f'Failed to generate XML: {result}'
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            xml_content = result
            
            # Actualizar ambos documentos
            if electronic_doc:
                electronic_doc.status = 'GENERATED'
                electronic_doc.save()
            
            document.status = 'GENERATED'
            document.save()
            
            return Response(
                {
                    'success': True,
                    'message': 'XML generated successfully using corrected XMLGenerator',
                    'data': {
                        'document_number': document.document_number,
                        'document_type': document_type,
                        'xml_size': len(xml_content),
                        'xml_file': str(electronic_doc.xml_file) if electronic_doc and electronic_doc.xml_file else None,
                        'access_key': document.access_key,
                        'status': document.status,
                        'ready_for_signing': cert_valid,
                        'error_35_resolved': True
                    }
                },
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error(f" Error generating XML for document {pk}: {str(e)}")
            return Response(
                {
                    'error': 'XML_GENERATION_ERROR',
                    'message': f'Failed to generate XML: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    @sri_document_endpoint(
        require_certificate=True,
        audit_action='SIGN_DOCUMENT',
        atomic=False
    )
    def sign_document(self, request, pk=None):
        """
        Firmar documento usando GlobalCertificateManager
        """
        document = request.validated_document
        document_type = request.validated_document_type
        electronic_doc = request.validated_electronic_doc
        
        # Verificar que existe XML para firmar
        if not electronic_doc.xml_file:
            return Response(
                {
                    'error': 'XML_FILE_NOT_FOUND',
                    'message': 'XML file must be generated before signing. Call generate_xml first.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from apps.sri_integration.services.document_processor import DocumentProcessor
            
            # Leer contenido XML existente
            with open(electronic_doc.xml_file.path, 'r', encoding='utf-8') as f:
                xml_content = f.read()
            
            processor = DocumentProcessor(document.company)
            success, result = processor._sign_xml_with_global_manager(electronic_doc, xml_content)
            
            if not success:
                return Response(
                    {
                        'error': 'SIGNING_ERROR',
                        'message': f'Failed to sign document: {result}'
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Actualizar documento original también
            document.status = 'SIGNED'
            document.save()
            
            # Información del certificado del gestor global
            cert_manager = get_certificate_manager()
            cert_info = cert_manager.get_company_certificate_info(document.company.id)
            
            return Response(
                {
                    'success': True,
                    'message': 'Document signed successfully with GlobalCertificateManager',
                    'data': {
                        'document_number': document.document_number,
                        'document_type': document_type,
                        'certificate_info': cert_info,
                        'signature_method': 'GlobalCertificateManager with XAdES-BES',
                        'status': electronic_doc.status,
                        'signed_xml_file': str(electronic_doc.signed_xml_file) if electronic_doc.signed_xml_file else None,
                        'password_required': False
                    }
                },
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error(f" Error signing {document_type} {pk}: {str(e)}")
            return Response(
                {
                    'error': 'SIGNING_ERROR',
                    'message': f'Error during document signing: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    @sri_document_endpoint(
        require_certificate=False,
        audit_action='SEND_TO_SRI',
        atomic=False
    )
    def send_to_sri(self, request, pk=None):
        """
        Enviar documento al SRI usando SRISOAPClient
        """
        document = request.validated_document
        document_type = request.validated_document_type
        electronic_doc = request.validated_electronic_doc
        
        # Verificar que esté firmado
        if electronic_doc.status != 'SIGNED' or not electronic_doc.signed_xml_file:
            return Response(
                {
                    'error': 'DOCUMENT_NOT_SIGNED',
                    'message': 'Document must be signed before sending to SRI',
                    'current_status': electronic_doc.status,
                    'has_signed_file': bool(electronic_doc.signed_xml_file),
                    'suggestion': 'Call sign_document endpoint first'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from apps.sri_integration.services.document_processor import DocumentProcessor
            
            # Leer XML firmado
            with open(electronic_doc.signed_xml_file.path, 'r', encoding='utf-8') as f:
                signed_xml = f.read()
            
            processor = DocumentProcessor(document.company)
            
            # Enviar al SRI
            success, message = processor._send_to_sri(electronic_doc, signed_xml)
            
            if not success:
                return Response(
                    {
                        'error': 'SRI_SUBMISSION_ERROR',
                        'message': f'Failed to send to SRI: {message}'
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Consultar autorización
            auth_success, auth_message = processor._check_authorization(electronic_doc)
            
            # Actualizar documento original también
            document.status = electronic_doc.status
            document.save()
            
            return Response(
                {
                    'success': True,
                    'message': 'Document sent to SRI successfully - ERROR 35 RESOLVED',
                    'data': {
                        'document_number': document.document_number,
                        'document_type': document_type,
                        'sri_status': electronic_doc.status,
                        'sri_message': auth_message if auth_success else message,
                        'authorization_code': electronic_doc.sri_authorization_code,
                        'authorization_date': electronic_doc.sri_authorization_date,
                        'access_key': electronic_doc.access_key,
                        'status': electronic_doc.status,
                        'authorized': auth_success,
                        'error_35_resolved': True
                    }
                },
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error(f" Error sending {document_type} {pk} to SRI: {str(e)}")
            return Response(
                {
                    'error': 'SRI_SUBMISSION_ERROR',
                    'message': f'Error sending to SRI: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    @sri_document_endpoint(
        require_certificate=True,
        audit_action='PROCESS_COMPLETE',
        atomic=False
    )
    def process_complete(self, request, pk=None):
        """
        Proceso completo usando DocumentProcessor
        """
        document = request.validated_document
        document_type = request.validated_document_type
        electronic_doc = request.validated_electronic_doc
        
        # Obtener parámetros opcionales
        send_email = request.data.get('send_email', True)
        
        try:
            # Verificar si se debe procesar de forma asincrónica (por colas)
            async_setting = SystemSetting.objects.filter(key='SRI_ASYNC_PROCESSING').first()
            is_async = async_setting.get_typed_value() if async_setting else True
            
            if is_async:
                logger.info(f" [PROCESS_COMPLETE] Queuing document {electronic_doc.id} for async processing")
                process_document_async.delay(electronic_doc.id)
                
                return Response(
                    {
                        'success': True,
                        'message': 'Documento puesto en cola para procesamiento (SRI asíncrono)',
                        'data': {
                            'document_id': pk,
                            'document_number': electronic_doc.document_number,
                            'access_key': electronic_doc.access_key,
                            'status': 'QUEUED'
                        }
                    },
                    status=status.HTTP_202_ACCEPTED
                )

            # PROCESAMIENTO SINCRÓNICO (TRADICIONAL)
            from apps.sri_integration.services.document_processor import DocumentProcessor
            processor = DocumentProcessor(company)
            success, message = processor.process_document(electronic_doc, send_email)
            
            # Actualizar documento original también
            document.status = electronic_doc.status
            document.save()
            
            if success:
                status_info = processor.get_document_status(electronic_doc)
                
                return Response(
                    {
                        'success': True,
                        'message': 'Document processed completely synchronously',
                        'data': {
                            'document_id': pk,
                            'document_type': document_type,
                            'access_key': electronic_doc.access_key,
                            'final_status': electronic_doc.status,
                            'status_info': status_info,
                            'authorized': electronic_doc.status == 'AUTHORIZED'
                        }
                    },
                    status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {
                        'success': False,
                        'message': f'Error in synchronous process: {message}',
                        'data': {
                            'document_id': pk,
                            'error_details': message
                        }
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            logger.error(f" Error in complete process for document {pk}: {str(e)}")
            return Response(
                {
                    'error': 'PROCESS_ERROR',
                    'message': f'Error in complete process: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ========== GESTIÓN DEL GlobalCertificateManager ==========
    
    @action(detail=False, methods=['get'])
    @audit_api_action(action_type='VIEW_CERTIFICATE_STATUS')
    def certificate_manager_status(self, request):
        """
        Estado del GlobalCertificateManager
        """
        try:
            cert_manager = get_certificate_manager()
            stats = cert_manager.get_stats()
            
            # Agregar información adicional
            stats['endpoints_info'] = {
                'password_required': False,
                'automatic_certificate_loading': True,
                'cache_enabled': True,
                'multi_company_support': True,
                'decorator_validation': True,
                'vsr_token_support': True,
                'error_35_resolved': True,
                'simplified_responses': True,
                'vsr_validation_endpoint': True,
                'available_endpoints': [
                    'validate_certificate_and_config (VSR only)',
                    'validation_status_summary (VSR only)',
                    'create_and_process_invoice_complete',
                    'create_and_process_credit_note_complete',
                    'create_and_process_debit_note_complete',
                    'create_and_process_retention_complete',
                    'create_and_process_purchase_settlement_complete'
                ]
            }
            
            return Response(stats, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting certificate manager status: {str(e)}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ========== VIEWSETS ADICIONALES ==========

class SRIConfigurationViewSet(viewsets.ModelViewSet):
    """
    ViewSet para configuración SRI - SOLO EMPRESAS DEL USUARIO
    """
    queryset = SRIConfiguration.objects.all()
    serializer_class = SRIConfigurationSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['company', 'environment']
    permission_classes = [permissions.IsAuthenticated, IsCompanyOwnerOrAdmin]
    
    def get_queryset(self):
        """
        Filtra configuraciones por empresas del usuario
        """
        user = self.request.user
        
        if user.is_superuser:
            return SRIConfiguration.objects.all()
        
        user_companies = get_user_companies_exact(user)
        if user_companies.exists():
            return SRIConfiguration.objects.filter(company__in=user_companies)
        
        return SRIConfiguration.objects.none()


class SRIResponseViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para respuestas del SRI - SOLO DOCUMENTOS DEL USUARIO
    """
    queryset = SRIResponse.objects.all()
    serializer_class = SRIResponseSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['document', 'operation_type', 'response_code']
    ordering_fields = ['created_at']
    ordering = ['-created_at']
    permission_classes = [permissions.IsAuthenticated, IsCompanyOwnerOrAdmin]
    
    def get_queryset(self):
        """
        Filtra respuestas por documentos de empresas del usuario
        """
        user = self.request.user
        
        if user.is_superuser:
            return SRIResponse.objects.all()
        
        user_companies = get_user_companies_exact(user)
        if user_companies.exists():
            return SRIResponse.objects.filter(document__company__in=user_companies)
        
        return SRIResponse.objects.none()


# ========== DOCUMENTACIÓN DE LA API ==========

class DocumentationViewSet(viewsets.ViewSet):
    """
    Documentación de la API con respuestas simplificadas
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    @audit_api_action(action_type='VIEW_API_DOCUMENTATION')
    def api_info(self, request):
        """
        Información general de la API con respuestas simplificadas
        """
        return Response({
            'api_name': 'SRI Integration API v2.4 FINAL - Simplified Responses + VSR Validation',
            'description': 'API completa con respuestas simplificadas para producción y endpoint de validación VSR',
            'version': '2.4.0-FINAL-SIMPLIFIED-VSR',
            'certificate_manager': 'GlobalCertificateManager',
            'error_35_status': 'RESOLVED',
            'password_required': False,
            'vsr_token_support': True,
            'user_token_support': True,
            'simplified_responses': True,
            'vsr_validation_endpoint': True,
            'validation_endpoints': {
                'certificate_validation': {
                    'endpoint': 'POST /api/sri/documents/validate_certificate_and_config/',
                    'description': 'Validar certificado y configuraciones de empresa (SOLO Token VSR)',
                    'token_required': 'Token vsr_XXXXXXXXXXXXXXXXX',
                    'response_codes': {
                        '200': 'Empresa lista para facturación',
                        '422': 'Faltan configuraciones',
                        '403': 'Token no es VSR',
                        '401': 'Token VSR inválido'
                    }
                },
                'status_summary': {
                    'endpoint': 'GET /api/sri/documents/validation_status_summary/',
                    'description': 'Resumen rápido del estado de la empresa (SOLO Token VSR)',
                    'token_required': 'Token vsr_XXXXXXXXXXXXXXXXX'
                }
            },
            'complete_process_endpoints': {
                'invoice': {
                    'endpoint': 'POST /api/sri/documents/create_and_process_invoice_complete/',
                    'description': 'Crear y procesar factura completamente en una sola llamada',
                    'required_fields': ['customer_identification_type', 'customer_identification', 'customer_name', 'issue_date', 'items'],
                    'response_example': {
                        'success': True,
                        'message': 'Factura creada y enviada al SRI exitosamente',
                        'invoice': {
                            'id': 175,
                            'number': '001-001-000001102',
                            'customer': 'VASQUEZ PINEDA CRISTIAN DAVID',
                            'total': 115.0,
                            'status': 'Enviada al SRI',
                            'date': '2025-08-04 17:39'
                        }
                    }
                },
                'credit_note': {
                    'endpoint': 'POST /api/sri/documents/create_and_process_credit_note_complete/',
                    'description': 'Crear y procesar nota de crédito completamente',
                    'required_fields': ['customer_identification_type', 'customer_identification', 'customer_name', 'reason_description', 'original_document_access_key']
                },
                'debit_note': {
                    'endpoint': 'POST /api/sri/documents/create_and_process_debit_note_complete/',
                    'description': 'Crear y procesar nota de débito completamente',
                    'required_fields': ['customer_identification_type', 'customer_identification', 'customer_name', 'reason_description', 'original_document_access_key']
                },
                'retention': {
                    'endpoint': 'POST /api/sri/documents/create_and_process_retention_complete/',
                    'description': 'Crear y procesar retención completamente',
                    'required_fields': ['supplier_identification_type', 'supplier_identification', 'supplier_name', 'fiscal_period']
                },
                'purchase_settlement': {
                    'endpoint': 'POST /api/sri/documents/create_and_process_purchase_settlement_complete/',
                    'description': 'Crear y procesar liquidación de compra completamente',
                    'required_fields': ['supplier_identification_type', 'supplier_identification', 'supplier_name', 'items']
                }
            },
            'token_usage': {
                'vsr_token': {
                    'format': 'Token vsr_XXXXXXXXXXXXXXX',
                    'company_detection': 'automatic',
                    'recommended_for': 'Single company integrations',
                    'validation_endpoints': 'YES - validate_certificate_and_config'
                },
                'user_token': {
                    'format': 'Token XXXXXXXXXXXXXXX',
                    'company_field_required': True,
                    'recommended_for': 'Multi-company integrations',
                    'validation_endpoints': 'NO - use company-specific endpoints'
                }
            },
            'features': [
                'Complete process endpoints for all document types',
                'Simplified responses for production',
                'Error 35 resolution built-in',
                'Automatic certificate management',
                'VSR token compatibility',
                'Decorator-based security',
                'Transaction safety',
                'Comprehensive audit logging',
                'VSR validation endpoint for certificate and config checking'
            ]
        })