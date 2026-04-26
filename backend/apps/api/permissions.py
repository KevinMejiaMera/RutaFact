# -*- coding: utf-8 -*-
"""
Custom permissions for API - VERSIÓN MEJORADA Y CORREGIDA
apps/api/permissions.py
"""

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework import status
from functools import wraps
import logging
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


def _user_has_company_access(user, company_id=None):
    """
    Función auxiliar centralizada: verifica si un usuario tiene acceso a una empresa.
    Soporta el sistema de empresa única (FK directo user.company_id) y el sistema
    M2M (UserCompanyAssignment) para compatibilidad.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    
    # ✅ Soporte para VirtualCompanyUser (Tokens VSR)
    if hasattr(user, '__class__') and 'Virtual' in user.__class__.__name__:
        if company_id:
            try:
                return int(company_id) == user.company.id
            except:
                return False
        return True

    # Obtener todas las empresas a las que el usuario tiene acceso
    from apps.api.user_company_helper import get_user_companies_exact
    accessible_companies = get_user_companies_exact(user)
    
    if not accessible_companies.exists():
        return False

    # Si se pide una empresa específica, verificar que esté entre las accesibles
    if company_id is not None:
        try:
            return accessible_companies.filter(id=int(company_id)).exists()
        except (ValueError, TypeError):
            return False

    # Si no se pide específica, solo verificar que tenga al menos una
    return True


class IsCompanyOwnerOrAdmin(permissions.BasePermission):
    """
    Permiso que permite acceso solo a propietarios de empresa o administradores.
    Soporta sistema de empresa única (sin relación M2M).
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            logger.warning("Access denied: User not authenticated")
            return False
        result = _user_has_company_access(request.user)
        if not result:
            logger.warning(f"Access denied for user {getattr(request.user, 'username', 'Unknown')}")
        return result
    
    def has_object_permission(self, request, view, obj):
        """
        Verifica permisos a nivel de objeto
        """
        # Los superusuarios tienen acceso total
        if request.user.is_superuser:
            return True
        
        # ✅ NUEVO: VirtualCompanyUser siempre tiene acceso (ya validado por token VSR)
        if hasattr(request.user, '__class__') and 'Virtual' in request.user.__class__.__name__:
            logger.info(f"VirtualCompanyUser granted object access")
            return True
        
        # Determinar la empresa relacionada con el objeto
        company = self._get_related_company(obj)
        
        if not company:
            logger.warning(f"No related company found for object {type(obj).__name__}")
            return False
        
        # Verificar si el usuario tiene acceso a la empresa
        if hasattr(request.user, 'companies'):
            has_access = company in request.user.companies.filter(is_active=True)
            
            if not has_access:
                logger.warning(f"User {request.user.username} denied access to company {company.id}")
            else:
                logger.info(f"User {request.user.username} granted access to company {company.id}")
            
            return has_access
        else:
            logger.warning(f"User {getattr(request.user, 'username', 'Unknown')} has no companies attribute")
            return False
    
    def _get_related_company(self, obj):
        """
        Obtiene la empresa relacionada con el objeto - MEJORADO
        """
        # Si el objeto tiene directamente una empresa
        if hasattr(obj, 'company'):
            return obj.company
        
        # Si el objeto es una empresa
        if hasattr(obj, 'ruc') and hasattr(obj, 'business_name'):  # Más específico
            return obj
        
        # Si el objeto tiene un documento relacionado
        if hasattr(obj, 'document') and hasattr(obj.document, 'company'):
            return obj.document.company
        
        # Si el objeto tiene un certificado relacionado
        if hasattr(obj, 'certificate') and hasattr(obj.certificate, 'company'):
            return obj.certificate.company
        
        # ✅ NUEVO: Para ElectronicDocument y modelos SRI
        if hasattr(obj, 'original_document') and hasattr(obj.original_document, 'company'):
            return obj.original_document.company
        
        # ✅ NUEVO: Para items de documentos
        if hasattr(obj, 'settlement') and hasattr(obj.settlement, 'company'):
            return obj.settlement.company
        
        # ✅ NUEVO: Para detalles de retención
        if hasattr(obj, 'retention') and hasattr(obj.retention, 'company'):
            return obj.retention.company
        
        return None


class IsAdminUser(permissions.BasePermission):
    """
    Permiso solo para administradores - MEJORADO
    """
    
    def has_permission(self, request, view):
        is_admin = request.user and request.user.is_superuser
        
        if not is_admin:
            logger.warning(f"Admin access denied for user: {getattr(request.user, 'username', 'Anonymous')}")
        else:
            logger.info(f"Admin access granted for user: {request.user.username}")
        
        return is_admin


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Permiso que permite edición solo al propietario, lectura para otros - MEJORADO
    """
    
    def has_object_permission(self, request, view, obj):
        # Permisos de lectura para cualquier request
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # ✅ MEJORADO: Verificar diferentes campos de propietario
        owner_fields = ['created_by', 'user', 'owner']
        
        for field in owner_fields:
            if hasattr(obj, field):
                owner = getattr(obj, field)
                is_owner = owner == request.user
                
                if not is_owner:
                    logger.warning(f"User {getattr(request.user, 'username', 'Unknown')} denied edit access to {type(obj).__name__}")
                
                return is_owner
        
        # Si no hay campo de propietario, denegar
        logger.warning(f"No owner field found for {type(obj).__name__}")
        return False


class IsCompanyMember(permissions.BasePermission):
    """
    Permiso para miembros de la empresa - MEJORADO CON VALIDACIÓN ESTRICTA Y SOPORTE VSR
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # ✅ NUEVO: VirtualCompanyUser siempre pasa (token VSR ya validado)
        if hasattr(request.user, '__class__') and 'Virtual' in request.user.__class__.__name__:
            logger.info(f"VirtualCompanyUser granted permission")
            return True
        
        # ✅ MEJORADO: Múltiples formas de obtener company_id
        company_id = self._extract_company_id(request, view)
        
        if not company_id:
            return True  # Será validado a nivel de objeto o endpoint
        
        # ✅ NUEVO: Validación estricta
        return self._validate_company_access(request.user, company_id)
    
    def _extract_company_id(self, request, view):
        """
        Extrae company_id de múltiples fuentes
        """
        # Del body (POST/PUT/PATCH)
        if hasattr(request, 'data') and request.data:
            company_id = request.data.get('company') or request.data.get('company_id')
            if company_id:
                return company_id
        
        # De query params (GET)
        company_id = request.query_params.get('company') or request.query_params.get('company_id')
        if company_id:
            return company_id
        
        # Del path (si es un detail view)
        if hasattr(view, 'get_object'):
            try:
                obj = view.get_object()
                if hasattr(obj, 'company'):
                    return obj.company.id
            except:
                pass
        
        return None
    
    def _validate_company_access(self, user, company_id):
        """Valida acceso del usuario a la empresa usando sistema de empresa única."""
        return _user_has_company_access(user, company_id)


# ========== NUEVOS PERMISOS ESPECÍFICOS PARA SRI ==========

class SRIDocumentPermission(permissions.BasePermission):
    """
    Permiso específico para documentos SRI - CORREGIDO PARA VSR
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # ✅ NUEVO: VirtualCompanyUser siempre pasa
        if hasattr(request.user, '__class__') and 'Virtual' in request.user.__class__.__name__:
            logger.info(f"VirtualCompanyUser granted SRI permission")
            return True
        
        # Para creación de documentos, validar company_id
        if request.method == 'POST':
            company_id = request.data.get('company')
            if company_id:
                return self._validate_company_access(request.user, company_id)
        
        return True  # Validación a nivel de objeto
    
    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        
        # ✅ NUEVO: VirtualCompanyUser siempre tiene acceso
        if hasattr(request.user, '__class__') and 'Virtual' in request.user.__class__.__name__:
            return True
        
        # Obtener empresa del documento
        company = None
        if hasattr(obj, 'company'):
            company = obj.company
        elif hasattr(obj, 'document') and hasattr(obj.document, 'company'):
            company = obj.document.company
        
        if not company:
            return False
        
        if hasattr(request.user, 'companies'):
            return company in request.user.companies.filter(is_active=True)
        else:
            return False
    
    def _validate_company_access(self, user, company_id):
        """Valida acceso del usuario a la empresa usando sistema de empresa única."""
        return _user_has_company_access(user, company_id)


class CertificatePermission(permissions.BasePermission):
    """
    Permiso específico para certificados digitales - CORREGIDO PARA VSR
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # ✅ NUEVO: VirtualCompanyUser puede gestionar certificados
        if hasattr(request.user, '__class__') and 'Virtual' in request.user.__class__.__name__:
            logger.info(f"VirtualCompanyUser granted certificate permission")
            return True
        
        # Solo superuser y usuarios con empresas pueden gestionar certificados
        if request.user.is_superuser:
            return True
        
        if hasattr(request.user, 'companies'):
            return request.user.companies.filter(is_active=True).exists()
        else:
            return False
    
    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        
        # ✅ NUEVO: VirtualCompanyUser siempre tiene acceso
        if hasattr(request.user, '__class__') and 'Virtual' in request.user.__class__.__name__:
            return True
        
        # Solo el propietario de la empresa puede gestionar sus certificados
        if hasattr(obj, 'company') and hasattr(request.user, 'companies'):
            return obj.company in request.user.companies.filter(is_active=True)
        
        return False


# ========== DECORADORES MEJORADOS ==========

def require_company_access(func):
    """
    Decorador que valida acceso a empresa - MEJORADO CON SOPORTE VSR
    """
    @wraps(func)
    def wrapper(self, request, *args, **kwargs):
        # ✅ NUEVO: VirtualCompanyUser siempre pasa
        if hasattr(request.user, '__class__') and 'Virtual' in request.user.__class__.__name__:
            logger.info(f"VirtualCompanyUser bypassing company access check")
            return func(self, request, *args, **kwargs)
        
        # Extraer company_id de múltiples fuentes
        company_id = None
        
        if request.method in ['POST', 'PUT', 'PATCH']:
            company_id = request.data.get('company_id') or request.data.get('company')
        elif request.method == 'GET':
            company_id = request.query_params.get('company_id') or request.query_params.get('company')
        
        if not company_id:
            return Response({
                'error': 'VALIDATION_ERROR',
                'message': 'company_id is required',
                'code': 'MISSING_COMPANY_ID'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validar acceso con logging mejorado
        if not _validate_user_company_access_with_logging(request.user, company_id):
            return Response({
                'error': 'COMPANY_ACCESS_DENIED',
                'message': 'You do not have permission to access this company',
                'code': 'FORBIDDEN_COMPANY_ACCESS',
                'company_id': str(company_id),
                'user': getattr(request.user, 'username', 'Unknown') if request.user else None,
                'timestamp': timezone.now().isoformat()
            }, status=status.HTTP_403_FORBIDDEN)
        
        return func(self, request, *args, **kwargs)
    return wrapper


def require_admin_access(func):
    """
    Decorador que requiere acceso de administrador
    """
    @wraps(func)
    def wrapper(self, request, *args, **kwargs):
        if not request.user or not request.user.is_superuser:
            logger.warning(f"Admin access denied for user: {getattr(request.user, 'username', 'Anonymous')}")
            return Response({
                'error': 'ADMIN_ACCESS_REQUIRED',
                'message': 'This action requires administrator privileges',
                'code': 'FORBIDDEN_ADMIN_ONLY'
            }, status=status.HTTP_403_FORBIDDEN)
        
        logger.info(f"Admin access granted for user: {request.user.username}")
        return func(self, request, *args, **kwargs)
    return wrapper


# ========== FUNCIONES AUXILIARES MEJORADAS ==========

def _validate_user_company_access_with_logging(user, company_id):
    """
    Validación con logging detallado. Usa sistema de empresa única.
    """
    result = _user_has_company_access(user, company_id)
    if result:
        logger.info(f"✅ Acceso concedido a empresa {company_id} para {getattr(user, 'username', 'Unknown')}")
    else:
        logger.warning(f"❌ Acceso denegado a empresa {company_id} para {getattr(user, 'username', 'Unknown')}")
    return result


def get_user_accessible_companies(user):
    """
    Obtiene las empresas accesibles para el usuario - CORREGIDO PARA VSR
    """
    if not user or not user.is_authenticated:
        return []
    
    if user.is_superuser:
        from apps.companies.models import Company
        return Company.objects.filter(is_active=True)
    
    # ✅ NUEVO: VirtualCompanyUser puede acceder a todas las empresas activas
    if hasattr(user, '__class__') and 'Virtual' in user.__class__.__name__:
        from apps.companies.models import Company
        return Company.objects.filter(is_active=True)
    
    if hasattr(user, 'companies'):
        return user.companies.filter(is_active=True)
    
    return []


def check_company_permission(user, company_id, action='access'):
    """
    Verificación centralizada de permisos de empresa - CORREGIDO PARA VSR
    """
    if not user or not user.is_authenticated:
        return False, "User not authenticated"
    
    if user.is_superuser:
        return True, "Superuser access granted"
    
    # ✅ NUEVO: VirtualCompanyUser siempre tiene acceso
    if hasattr(user, '__class__') and 'Virtual' in user.__class__.__name__:
        return True, "VirtualCompanyUser access granted"
    
    try:
        company_id = int(company_id)
        from apps.companies.models import Company
        
        try:
            company = Company.objects.get(id=company_id, is_active=True)
        except Company.DoesNotExist:
            return False, f"Company {company_id} does not exist"
        
        if hasattr(user, 'companies'):
            has_access = company in user.companies.filter(is_active=True)
            if has_access:
                return True, f"User has {action} permission for company {company_id}"
            else:
                return False, f"User does not have {action} permission for company {company_id}"
        
        return False, "User has no company relationships"
        
    except (ValueError, TypeError):
        return False, f"Invalid company_id format: {company_id}"


# ========== CLASE DE PERMISOS COMBINADOS ==========

class VendoSRIPermission(permissions.BasePermission):
    """
    Permiso combinado para todo el sistema RutaFact SRI - CORREGIDO PARA VSR
    """
    
    def has_permission(self, request, view):
        # Autenticación requerida
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Superuser tiene acceso total
        if request.user.is_superuser:
            return True
        
        # ✅ NUEVO: VirtualCompanyUser siempre pasa
        if hasattr(request.user, '__class__') and 'Virtual' in request.user.__class__.__name__:
            logger.info(f"VirtualCompanyUser granted VendoSRI permission")
            return True
        
        # Para acciones que requieren empresa específica
        company_id = self._extract_company_id(request, view)
        if company_id:
            is_valid, message = check_company_permission(request.user, company_id)
            if not is_valid:
                logger.warning(f"Permission denied: {message}")
            return is_valid
        
        # Para listados generales, verificar que tenga al menos una empresa
        if hasattr(request.user, 'companies'):
            return request.user.companies.filter(is_active=True).exists()
        else:
            return False
    
    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        
        # ✅ NUEVO: VirtualCompanyUser siempre tiene acceso a objetos
        if hasattr(request.user, '__class__') and 'Virtual' in request.user.__class__.__name__:
            return True
        
        # Usar el permiso existente IsCompanyOwnerOrAdmin
        company_permission = IsCompanyOwnerOrAdmin()
        return company_permission.has_object_permission(request, view, obj)
    
    def _extract_company_id(self, request, view):
        """Extrae company_id usando la misma lógica de IsCompanyMember"""
        member_permission = IsCompanyMember()
        return member_permission._extract_company_id(request, view)


class CompanySecurityMiddleware(MiddlewareMixin):
    """
    Middleware de seguridad para empresas - SIN CAMBIOS
    """
    def process_request(self, request):
        return None
    
    def process_response(self, request, response):
        return response