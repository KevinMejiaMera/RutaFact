# -*- coding: utf-8 -*-
"""
Vistas para sistema de planes y facturación
apps/billing/views.py
"""

import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q

from apps.api.user_company_helper import get_user_companies_exact
from .models import Plan, CompanyBillingProfile, PlanPurchase, InvoiceConsumption
from .forms import PlanPurchaseForm

logger = logging.getLogger(__name__)


@login_required
def plans_list_view(request):
    """
    Vista principal de planes disponibles
    """
    user = request.user
    user_companies = get_user_companies_exact(user)
    
    if not user_companies.exists():
        messages.error(request, 'No tienes empresas asignadas. Contacta al administrador.')
        return redirect('core:dashboard')
    
    # Obtener empresa seleccionada
    company_id = request.GET.get('company')
    selected_company = None
    
    if company_id:
        try:
            selected_company = user_companies.get(id=company_id)
        except:
            selected_company = user_companies.first()
    else:
        selected_company = user_companies.first()
    
    # Obtener o crear perfil de facturación
    billing_profile, created = CompanyBillingProfile.objects.get_or_create(
        company=selected_company,
        defaults={
            'available_invoices': 0,
            'total_invoices_purchased': 0,
            'total_invoices_consumed': 0,
        }
    )
    
    # Obtener planes activos
    plans = Plan.objects.filter(is_active=True).order_by('sort_order', 'price')
    
    # Obtener historial de compras recientes
    recent_purchases = PlanPurchase.objects.filter(
        company=selected_company
    ).order_by('-created_at')[:5]
    
    context = {
        'user_companies': user_companies,
        'selected_company': selected_company,
        'billing_profile': billing_profile,
        'plans': plans,
        'recent_purchases': recent_purchases,
        'page_title': 'Planes de Facturación',
    }
    
    return render(request, 'billing/plans_list.html', context)


@login_required
def plan_purchase_view(request, plan_id):
    """
    Vista para comprar un plan específico
    """
    user = request.user
    user_companies = get_user_companies_exact(user)
    
    if not user_companies.exists():
        messages.error(request, 'No tienes empresas asignadas.')
        return redirect('core:dashboard')
    
    plan = get_object_or_404(Plan, id=plan_id, is_active=True)
    
    # Obtener empresa seleccionada
    company_id = request.GET.get('company')
    selected_company = None
    
    if company_id:
        try:
            selected_company = user_companies.get(id=company_id)
        except:
            selected_company = user_companies.first()
    else:
        selected_company = user_companies.first()
    
    if request.method == 'POST':
        form = PlanPurchaseForm(request.POST, request.FILES)
        if form.is_valid():
            purchase = form.save(commit=False)
            purchase.company = selected_company
            purchase.plan = plan
            
            # Guardar datos del plan al momento de la compra
            purchase.plan_name = plan.name
            purchase.plan_invoice_limit = plan.invoice_limit
            purchase.plan_price = plan.price
            
            purchase.save()
            
            logger.info(f"✅ New plan purchase: {selected_company.business_name} bought {plan.name}")
            
            messages.success(
                request, 
                f'¡Solicitud de compra enviada exitosamente! '
                f'Tu solicitud para el {plan.name} está siendo revisada. '
                f'Te notificaremos cuando sea aprobada.'
            )
            
            return redirect('billing:purchase_success', purchase_id=purchase.purchase_id)
    else:
        form = PlanPurchaseForm(initial={
            'payment_amount': plan.price,
            'payment_date': timezone.now().date(),
        })
    
    context = {
        'plan': plan,
        'form': form,
        'selected_company': selected_company,
        'user_companies': user_companies,
        'page_title': f'Comprar {plan.name}',
    }
    
    return render(request, 'billing/plan_purchase.html', context)


@login_required
def purchase_success_view(request, purchase_id):
    """
    Vista de confirmación de compra exitosa
    """
    user = request.user
    user_companies = get_user_companies_exact(user)
    
    purchase = get_object_or_404(
        PlanPurchase, 
        purchase_id=purchase_id,
        company__in=user_companies
    )
    
    context = {
        'purchase': purchase,
        'page_title': 'Compra Exitosa',
    }
    
    return render(request, 'billing/purchase_success.html', context)


@login_required
def purchase_history_view(request):
    """
    Vista del historial de compras
    """
    user = request.user
    user_companies = get_user_companies_exact(user)
    
    if not user_companies.exists():
        messages.error(request, 'No tienes empresas asignadas.')
        return redirect('core:dashboard')
    
    # Obtener empresa seleccionada
    company_id = request.GET.get('company')
    selected_company = None
    
    if company_id:
        try:
            selected_company = user_companies.get(id=company_id)
        except:
            selected_company = user_companies.first()
    else:
        selected_company = user_companies.first()
    
    # Filtros
    status_filter = request.GET.get('status', '')
    
    # Obtener compras
    purchases = PlanPurchase.objects.filter(company=selected_company)
    
    if status_filter:
        purchases = purchases.filter(payment_status=status_filter)
    
    purchases = purchases.order_by('-created_at')
    
    # Paginación
    paginator = Paginator(purchases, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Obtener perfil de facturación
    billing_profile, created = CompanyBillingProfile.objects.get_or_create(
        company=selected_company,
        defaults={'available_invoices': 0}
    )
    
    context = {
        'selected_company': selected_company,
        'user_companies': user_companies,
        'billing_profile': billing_profile,
        'page_obj': page_obj,
        'status_filter': status_filter,
        'status_choices': PlanPurchase.PAYMENT_STATUS_CHOICES,
        'page_title': 'Historial de Compras',
    }
    
    return render(request, 'billing/purchase_history.html', context)


@login_required
def consumption_history_view(request):
    """
    Vista del historial de consumo de facturas
    """
    user = request.user
    user_companies = get_user_companies_exact(user)
    
    if not user_companies.exists():
        messages.error(request, 'No tienes empresas asignadas.')
        return redirect('core:dashboard')
    
    # Obtener empresa seleccionada
    company_id = request.GET.get('company')
    selected_company = None
    
    if company_id:
        try:
            selected_company = user_companies.get(id=company_id)
        except:
            selected_company = user_companies.first()
    else:
        selected_company = user_companies.first()
    
    # Filtros
    invoice_type_filter = request.GET.get('type', '')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    # Obtener consumos
    consumptions = InvoiceConsumption.objects.filter(company=selected_company)
    
    if invoice_type_filter:
        consumptions = consumptions.filter(invoice_type=invoice_type_filter)
    
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            consumptions = consumptions.filter(consumed_at__date__gte=date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            consumptions = consumptions.filter(consumed_at__date__lte=date_to_obj)
        except ValueError:
            pass
    
    consumptions = consumptions.order_by('-consumed_at')
    
    # Paginación
    paginator = Paginator(consumptions, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Obtener perfil de facturación
    billing_profile, created = CompanyBillingProfile.objects.get_or_create(
        company=selected_company,
        defaults={'available_invoices': 0}
    )
    
    context = {
        'selected_company': selected_company,
        'user_companies': user_companies,
        'billing_profile': billing_profile,
        'page_obj': page_obj,
        'invoice_type_filter': invoice_type_filter,
        'date_from': date_from,
        'date_to': date_to,
        'page_title': 'Historial de Consumo',
    }
    
    return render(request, 'billing/consumption_history.html', context)


@login_required
def billing_dashboard_view(request):
    """
    Dashboard principal de facturación
    """
    user = request.user
    user_companies = get_user_companies_exact(user)
    
    if not user_companies.exists():
        messages.error(request, 'No tienes empresas asignadas.')
        return redirect('core:dashboard')
    
    # Obtener empresa seleccionada
    company_id = request.GET.get('company')
    selected_company = None
    
    if company_id:
        try:
            selected_company = user_companies.get(id=company_id)
        except:
            selected_company = user_companies.first()
    else:
        selected_company = user_companies.first()
    
    # Obtener perfil de facturación
    billing_profile, created = CompanyBillingProfile.objects.get_or_create(
        company=selected_company,
        defaults={'available_invoices': 0}
    )
    
    # Estadísticas rápidas
    stats = {
        'available_invoices': billing_profile.available_invoices,
        'total_purchased': billing_profile.total_invoices_purchased,
        'total_consumed': billing_profile.total_invoices_consumed,
        'total_spent': billing_profile.total_spent,
        'usage_percentage': billing_profile.usage_percentage,
        'is_low_balance': billing_profile.is_low_balance,
    }
    
    # Compras recientes
    recent_purchases = PlanPurchase.objects.filter(
        company=selected_company
    ).order_by('-created_at')[:5]
    
    # Consumos recientes
    recent_consumptions = InvoiceConsumption.objects.filter(
        company=selected_company
    ).order_by('-consumed_at')[:10]
    
    # Planes disponibles
    featured_plans = Plan.objects.filter(is_active=True, is_featured=True)[:3]
    
    context = {
        'selected_company': selected_company,
        'user_companies': user_companies,
        'billing_profile': billing_profile,
        'stats': stats,
        'recent_purchases': recent_purchases,
        'recent_consumptions': recent_consumptions,
        'featured_plans': featured_plans,
        'page_title': 'Dashboard de Facturación',
    }
    
    return render(request, 'billing/dashboard.html', context)


@login_required 
def billing_api_status(request):
    """
    API endpoint para obtener estado de facturación (AJAX)
    """
    user = request.user
    user_companies = get_user_companies_exact(user)
    
    company_id = request.GET.get('company_id')
    
    if not company_id or not user_companies.filter(id=company_id).exists():
        return JsonResponse({'error': 'Company not found or no access'}, status=404)
    
    try:
        company = user_companies.get(id=company_id)
        billing_profile, created = CompanyBillingProfile.objects.get_or_create(
            company=company,
            defaults={'available_invoices': 0}
        )
        
        return JsonResponse({
            'success': True,
            'company_id': company.id,
            'company_name': company.business_name or company.trade_name,
            'available_invoices': billing_profile.available_invoices,
            'total_purchased': billing_profile.total_invoices_purchased,
            'total_consumed': billing_profile.total_invoices_consumed,
            'is_low_balance': billing_profile.is_low_balance,
            'low_balance_threshold': billing_profile.low_balance_threshold,
            'usage_percentage': round(billing_profile.usage_percentage, 2),
        })
        
    except Exception as e:
        logger.error(f"Error getting billing status: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)