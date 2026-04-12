# -*- coding: utf-8 -*-
"""
Core views - API ONLY VERSION
apps/core/views.py
"""

import logging
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from apps.companies.models import Company

logger = logging.getLogger(__name__)

def get_user_companies_secure(user):
    """
    Función auxiliar SEGURA - Obtiene las empresas del usuario.
    Utilizada por WebSockets y otros módulos de la API.
    """
    try:
        from apps.api.user_company_helper import get_user_companies_exact
        return get_user_companies_exact(user)
    except ImportError:
        pass
    
    # Si es admin, puede ver todas las empresas
    if user.is_staff or user.is_superuser:
        return Company.objects.filter(is_active=True)
    
    # Intento de obtener empresas vía relación ManyToMany si existe
    if hasattr(user, 'companies'):
        return user.companies.filter(is_active=True)
        
    return Company.objects.none()

def get_user_company_by_id(company_id, user):
    """
    Verifica si un usuario tiene acceso a una empresa específica por ID.
    """
    try:
        company = Company.objects.get(id=company_id, is_active=True)
        if user.is_staff or user.is_superuser:
            return company
            
        user_companies = get_user_companies_secure(user)
        if user_companies.filter(id=company.id).exists():
            return company
        return None
    except Company.DoesNotExist:
        return None

def health_check(request):
    """
    Endpoint de salud del sistema.
    """
    return JsonResponse({
        'status': 'OK',
        'message': 'RutaFact Core API is running',
        'frontend': 'Flutter (Dart) - No HTML remnants in core',
    })
