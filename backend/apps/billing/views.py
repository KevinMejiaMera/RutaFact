# -*- coding: utf-8 -*-
"""
Vistas para sistema de planes y facturación - API ONLY
apps/billing/views.py
"""

import logging
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from apps.api.user_company_helper import get_user_companies_exact
from .models import CompanyBillingProfile

logger = logging.getLogger(__name__)

@login_required 
def billing_api_status(request):
    """
    API endpoint para obtener estado de facturación (AJAX).
    Compatible con el frontend en Flutter para mostrar créditos restantes.
    """
    user = request.user
    user_companies = get_user_companies_exact(user)
    
    company_id = request.GET.get('company_id')
    
    if not company_id:
        # Si no se envía ID, intentar con la primera empresa
        if user_companies.exists():
            company = user_companies.first()
        else:
            return JsonResponse({'error': 'No companies assigned'}, status=404)
    else:
        try:
            company = user_companies.get(id=company_id)
        except:
            return JsonResponse({'error': 'Company not found or no access'}, status=404)
    
    try:
        billing_profile, created = CompanyBillingProfile.objects.get_or_create(
            company=company,
            defaults={'available_invoices': 0}
        )
        
        return JsonResponse({
            'success': True,
            'company_id': company.id,
            'company_name': company.business_name or company.trade_name,
            'available_invoices': billing_profile.available_invoices,
            'is_unlimited': billing_profile.is_unlimited,
            'total_purchased': billing_profile.total_invoices_purchased,
            'total_consumed': billing_profile.total_invoices_consumed,
            'is_low_balance': billing_profile.is_low_balance,
            'usage_percentage': round(billing_profile.usage_percentage, 2),
        })
        
    except Exception as e:
        logger.error(f"Error getting billing status: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

# El resto de vistas basadas en HTML han sido removidas para la migración a Flutter.
# La gestión de planes y compras se integrará directamente en apps.api en versiones futuras.