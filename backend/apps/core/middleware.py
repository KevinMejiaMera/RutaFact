"""
Middleware de seguridad para dashboard y vistas HTML
Intercepta accesos con company parameter no válidos
"""

import logging
from django.shortcuts import redirect
from django.contrib import messages
from apps.api.views.sri_views import get_user_company_by_id

logger = logging.getLogger(__name__)


class DashboardSecurityMiddleware:
    """
    🔒 Middleware que intercepta accesos inseguros al dashboard
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
        # Rutas que requieren validación de company parameter
        self.protected_paths = [
            '/dashboard/',
            '/core/',
        ]
    
    def __call__(self, request):
        # Solo aplicar a rutas protegidas con usuario autenticado
        if (any(request.path.startswith(path) for path in self.protected_paths) and 
            'company' in request.GET and 
            request.user.is_authenticated):
            
            company_id = request.GET.get('company')
            
            # 🔒 VALIDACIÓN CRÍTICA
            company = get_user_company_by_id(company_id, request.user)
            
            if not company:
                logger.warning(f"🚨 MIDDLEWARE SECURITY: User {request.user.username} blocked from company {company_id}")
                
                # Remover company parameter y redirigir
                messages.error(request, f'You do not have access to company {company_id}.')
                
                # Construir URL sin company parameter
                base_url = request.path
                return redirect(base_url)
            
            # Si es válido, agregar empresa al request
            request.validated_company = company
            logger.info(f"✅ MIDDLEWARE: User {request.user.username} validated for company {company_id}")
        
        response = self.get_response(request)
        return response
