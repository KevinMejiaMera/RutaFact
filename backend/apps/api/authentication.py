# -*- coding: utf-8 -*-
"""
Dual Token Authentication System
Sistema de Autenticación Dual para RutaFact_SRI

Maneja dos tipos de tokens:
1. Tokens de Usuario (DRF estándar) - Para dashboard web
2. Tokens de Empresa (custom) - Para APIs externas
"""

import logging
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth import get_user_model
from apps.companies.models import CompanyAPIToken
from rest_framework.authtoken.models import Token

logger = logging.getLogger(__name__)
User = get_user_model()


class DualTokenAuthentication(BaseAuthentication):
    """
    Authentication que maneja tanto tokens de usuario como de empresa
    
    Proceso:
    1. Recibe header: Authorization: Token XXXXXXX
    2. Si token empieza con 'vsr_' → Token de empresa
    3. Si no → Token de usuario estándar DRF
    """
    
    def authenticate(self, request):
        """
        Método principal de autenticación
        """
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        
        if not auth_header:
            return None
            
        logger.debug(f"🔍 [DualAuth] Header recibido: {auth_header[:20]}...")
        
        if not auth_header.startswith('Token '):
            return None
        
        try:
            token_key = auth_header.split(' ')[1]
        except IndexError:
            logger.warning("🚨 [DualAuth] Header malformado (sin token)")
            return None
        
        # 🔍 DETERMINAR TIPO DE TOKEN
        if token_key.startswith('vsr_'):
            logger.info(f"🔑 [DualAuth] Company token detectado: {token_key[:12]}...")
            return self.authenticate_company_token(request, token_key)
        else:
            logger.info(f"👤 [DualAuth] User token detectado (posible DRF o JWT): {token_key[:12]}...")
            return self.authenticate_user_token(request, token_key)
    
    def authenticate_company_token(self, request, token_key):
        """
        Autenticar con token de empresa
        
        Returns:
            (VirtualCompanyUser, CompanyAPIToken)
        """
        try:
            company_token = CompanyAPIToken.objects.select_related('company').get(
                key=token_key
            )
            
            # Verificar validez del token
            if not company_token.is_valid():
                logger.warning(f"🚨 Invalid company token: {token_key[:12]}...")
                raise AuthenticationFailed('Token de empresa inválido o expirado')
            
            # Obtener IP del cliente para estadísticas
            client_ip = self.get_client_ip(request)
            
            # Incrementar estadísticas de uso
            company_token.increment_usage(ip_address=client_ip)
            
            # Crear usuario virtual para la empresa
            virtual_user = VirtualCompanyUser(company_token.company)
            
            # 🎯 ADJUNTAR INFORMACIÓN CRÍTICA A LA REQUEST
            request.company_token = company_token
            request.target_company = company_token.company
            request.token_type = 'company'
            request.token_permissions = company_token.get_permissions()
            
            logger.info(f"✅ Company token authenticated: {company_token.company.business_name}")
            
            return (virtual_user, company_token)
            
        except CompanyAPIToken.DoesNotExist:
            logger.warning(f"🚨 Company token not found: {token_key[:12]}...")
            raise AuthenticationFailed('Token de empresa no encontrado')
        except Exception as e:
            logger.error(f"❌ Error authenticating company token: {e}")
            raise AuthenticationFailed('Error en autenticación de empresa')
    
    def authenticate_user_token(self, request, token_key):
        """
        Autenticar con token de usuario estándar DRF
        
        Returns:
            (User, Token)
        """
        try:
            from rest_framework.authtoken.models import Token
            user_token = Token.objects.select_related('user').get(key=token_key)
            logger.info(f"✅ [DualAuth] Token DRF válido para: {user_token.user.username}")
            
            # Verificar que el usuario esté activo
            if not user_token.user.is_active:
                logger.warning(f"🚨 Inactive user token: {user_token.user.email}")
                raise AuthenticationFailed('Usuario inactivo')
            
            # Para tokens de usuario, NO establecer target_company
            # (se maneja con el sistema de asignaciones UserCompanyAssignment)
            request.company_token = None
            request.target_company = None
            request.token_type = 'user'
            request.token_permissions = None
            
            logger.info(f"✅ User token authenticated: {user_token.user.email}")
            
            return (user_token.user, user_token)
            
        except Token.DoesNotExist:
            logger.warning(f"🚨 User token not found: {token_key[:12]}...")
            raise AuthenticationFailed('Token de usuario no encontrado')
        except Exception as e:
            logger.error(f"❌ Error authenticating user token: {e}")
            raise AuthenticationFailed('Error en autenticación de usuario')
    
    def get_client_ip(self, request):
        """
        Obtener IP real del cliente (considerando proxies)
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class VirtualCompanyUser:
    """
    Usuario virtual que representa una empresa para tokens de empresa
    
    Permite que el sistema de permisos de Django funcione
    con tokens de empresa como si fueran usuarios normales.
    """
    
    def __init__(self, company):
        self.company = company
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False
        self.is_staff = False
        self.is_superuser = False
        
        # Identificadores únicos
        self.pk = f"company_{company.id}"
        self.id = f"company_{company.id}"
        self.username = f"company_{company.id}"
        self.email = f"api@{self._clean_company_name(company.business_name)}.com"
        
        # Información descriptiva
        self.first_name = "API"
        self.last_name = f"Company {company.id}"
        self.full_name = f"API for {company.business_name}"
    
    def _clean_company_name(self, name):
        """
        Limpiar nombre de empresa para email
        """
        import re
        # Remover caracteres especiales y espacios
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', name.lower())
        return clean_name[:20]  # Limitar longitud
    
    def __str__(self):
        return f"API User for {self.company.business_name}"
    
    def __repr__(self):
        return f"<VirtualCompanyUser: {self.company.business_name}>"
    
    # ================================================================
    # MÉTODOS REQUERIDOS POR DJANGO AUTH SYSTEM
    # ================================================================
    
    def has_perm(self, perm, obj=None):
        """
        Verificar permisos - Siempre True para tokens de empresa
        (permisos se manejan a nivel de token)
        """
        return True
    
    def has_module_perms(self, app_label):
        """
        Verificar permisos de módulo - Siempre True para tokens de empresa
        """
        return True
    
    def get_username(self):
        """
        Obtener username para compatibilidad
        """
        return self.username
    
    def natural_key(self):
        """
        Natural key para serialización
        """
        return (self.username,)
    
    # ================================================================
    # MÉTODOS PARA COMPATIBILIDAD CON SISTEMAS EXTERNOS
    # ================================================================
    
    def get_full_name(self):
        """
        Nombre completo del 'usuario'
        """
        return self.full_name
    
    def get_short_name(self):
        """
        Nombre corto del 'usuario'
        """
        return f"Company {self.company.id}"
    
    def get_company(self):
        """
        Obtener empresa asociada
        """
        return self.company


# ================================================================
# UTILIDADES ADICIONALES
# ================================================================

def get_token_info(request):
    """
    Utilidad para obtener información del token actual en la request
    
    Returns:
        dict: Información del token o None si no hay token
    """
    if not hasattr(request, 'token_type'):
        return None
    
    if request.token_type == 'company':
        return {
            'type': 'company',
            'company_id': request.target_company.id,
            'company_name': request.target_company.business_name,
            'permissions': request.token_permissions,
            'token_key': request.company_token.key[:12] + '...',
        }
    elif request.token_type == 'user':
        return {
            'type': 'user',
            'user_id': request.user.id,
            'user_email': request.user.email,
            'token_key': request.auth.key[:12] + '...' if hasattr(request, 'auth') else 'N/A',
        }
    
    return None


def require_company_permission(permission_name):
    """
    Decorator para verificar permisos específicos en tokens de empresa
    
    Usage:
        @require_company_permission('create_documents')
        def create_invoice(self, request):
            ...
    """
    def decorator(view_func):
        def wrapper(self, request, *args, **kwargs):
            if hasattr(request, 'token_type') and request.token_type == 'company':
                permissions = request.token_permissions or {}
                if not permissions.get(permission_name, False):
                    from rest_framework.response import Response
                    return Response({
                        'error': 'PERMISSION_DENIED',
                        'message': f'Token does not have {permission_name} permission',
                        'required_permission': permission_name,
                        'available_permissions': list(permissions.keys())
                    }, status=403)
            
            return view_func(self, request, *args, **kwargs)
        return wrapper
    return decorator