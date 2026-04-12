# -*- coding: utf-8 -*-
"""
Core views - VERSIÓN COMPLETA CON TOKENS, EDICIÓN DE EMPRESA Y CERTIFICADOS
Todas las vistas validadas con decoradores personalizados
"""

import logging
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils import timezone
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from datetime import datetime, timedelta
from functools import wraps

from apps.companies.models import Company, CompanyAPIToken

# Importar DigitalCertificate de forma segura
try:
    from apps.certificates.models import DigitalCertificate
except ImportError:
    try:
        from apps.core.models import DigitalCertificate
    except ImportError:
        # Si no existe el modelo, crear una clase dummy
        class DigitalCertificate:
            objects = None
            
            class DoesNotExist:
                pass

# Importar User del sistema de autenticación de Django
from django.contrib.auth import get_user_model
User = get_user_model()

# ========== IMPORTAR DECORADORES DEL SISTEMA ==========
try:
    from apps.api.views.sri_views import (
        audit_api_action,
        get_user_company_by_id
    )
except ImportError:
    # Si no existen, crear versiones simples
    def audit_api_action(action):
        def decorator(func):
            return func
        return decorator
    
    def get_user_company_by_id(company_id, user):
        try:
            company = Company.objects.get(id=company_id, is_active=True)
            if user.is_staff or user.is_superuser:
                return company
            # Verificar si el usuario tiene acceso a la empresa
            user_companies = get_user_companies_secure(user)
            if user_companies.filter(id=company.id).exists():
                return company
            return None
        except Company.DoesNotExist:
            return None

logger = logging.getLogger(__name__)

# ========== DECORADORES PARA VISTAS HTML CON TOKENS ==========

def require_company_access_html_token(view_func):
    """
    Decorador para vistas HTML que requieren validación de empresa CON TOKENS
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Obtener token del parámetro GET o kwargs
        token_param = request.GET.get('token') or kwargs.get('company_token')
        
        if token_param:
            # 🔑 VALIDACIÓN CON TOKEN: Buscar empresa por token
            try:
                user_companies = get_user_companies_secure(request.user)
                company_token = CompanyAPIToken.objects.get(
                    key=token_param,
                    company__in=user_companies,
                    is_active=True
                )
                company = company_token.company
                
                # Agregar empresa y token validados al request
                request.validated_company = company
                request.validated_token = company_token
                
                logger.info(f"✅ TOKEN HTML: User {request.user.username} validated access to company {company.business_name} via token {token_param[:20]}...")
                
            except CompanyAPIToken.DoesNotExist:
                logger.warning(f"🚫 TOKEN HTML SECURITY: User {request.user.username} denied access with invalid token {token_param[:20]}...")
                messages.error(request, f'Token de empresa inválido o sin permisos.')
                
                # Redirigir a dashboard sin token
                return redirect('core:dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper


def require_company_access_html(view_func):
    """
    Decorador LEGACY para vistas HTML que requieren validación de empresa POR ID
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Obtener company_id del parámetro GET o kwargs
        company_id = request.GET.get('company') or kwargs.get('company_id')
        
        if company_id:
            # 🔒 VALIDACIÓN CRÍTICA: Solo empresas del usuario
            company = get_user_company_by_id(company_id, request.user)
            
            if not company:
                logger.warning(f"🚫 HTML SECURITY: User {request.user.username} denied access to company {company_id}")
                messages.error(request, f'You do not have access to company {company_id}.')
                
                # Redirigir a dashboard sin company parameter
                return redirect('core:dashboard')
            
            # Agregar empresa validada al request
            request.validated_company = company
            logger.info(f"✅ HTML: User {request.user.username} validated access to company {company_id}")
        
        return view_func(request, *args, **kwargs)
    return wrapper


def audit_html_action(action_type):
    """
    Decorador de auditoría para vistas HTML
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            start_time = timezone.now()
            
            logger.info(f"🌐 [{action_type}] User {request.user.username} - {view_func.__name__} - Started")
            
            try:
                response = view_func(request, *args, **kwargs)
                execution_time = (timezone.now() - start_time).total_seconds()
                logger.info(f"✅ [{action_type}] User {request.user.username} - SUCCESS - {execution_time:.2f}s")
                return response
            except Exception as e:
                execution_time = (timezone.now() - start_time).total_seconds()
                logger.error(f"❌ [{action_type}] User {request.user.username} - ERROR: {str(e)} - {execution_time:.2f}s")
                raise
        return wrapper
    return decorator


def get_user_companies_secure(user):
    """
    Función auxiliar SEGURA - Obtiene las empresas del usuario
    """
    # Intentar usar el helper si existe
    try:
        from apps.api.user_company_helper import get_user_companies_exact
        return get_user_companies_exact(user)
    except ImportError:
        pass
    
    # Si es admin, puede ver todas las empresas
    if user.is_staff or user.is_superuser:
        return Company.objects.filter(is_active=True)
    
    # Para usuarios normales, intentar diferentes formas de obtener las empresas
    
    # Opción 1: Si el usuario tiene un campo 'companies' (ManyToMany)
    if hasattr(user, 'companies'):
        return user.companies.filter(is_active=True)
    
    # Opción 2: Si existe un modelo UserCompany en algún lado
    try:
        from apps.users.models import UserCompany
        user_company_ids = UserCompany.objects.filter(
            user=user,
            is_active=True
        ).values_list('company_id', flat=True)
        return Company.objects.filter(id__in=user_company_ids, is_active=True)
    except ImportError:
        pass
    
    # Opción 3: Si existe una relación a través del modelo User
    try:
        # Django permite acceso a través de relaciones reversas
        if hasattr(User, 'companies'):
            through_model = User.companies.through
            user_company_ids = through_model.objects.filter(
                user=user
            ).values_list('company_id', flat=True)
            return Company.objects.filter(id__in=user_company_ids, is_active=True)
    except:
        pass
    
    # Opción 4: Por defecto, devolver la primera empresa activa
    # Esto es temporal - deberías implementar la lógica correcta para tu caso
    logger.warning(f"No se pudo determinar las empresas del usuario {user.username}, usando empresa por defecto")
    return Company.objects.filter(is_active=True)[:1]


# ========== VISTAS PRINCIPALES CON TOKENS ==========

@login_required
def dashboard(request):
    """
    Vista principal del dashboard que redirige según el tipo de usuario
    """
    if request.user.is_staff:
        return admin_dashboard_view(request)
    else:
        return user_dashboard(request)


@login_required
@audit_html_action('VIEW_DASHBOARD')
def dashboard_view(request):
    """Alias para compatibilidad"""
    return dashboard(request)


@login_required
@audit_html_action('VIEW_USER_DASHBOARD')
def user_dashboard(request):
    """
    Dashboard mejorado para usuarios con toda la información necesaria
    """
    user = request.user
    
    # Verificar si es admin
    if user.is_staff or user.is_superuser:
        return redirect('/admin/')
    
    # Obtener empresas del usuario de forma SEGURA
    user_companies = get_user_companies_secure(user)
    
    # Si no tiene empresas, mostrar mensaje
    if not user_companies.exists():
        logger.warning(f"User {user.username} has no accessible companies")
        return render(request, 'dashboard/no_companies.html', {'user': user})
    
    # 🔄 MODO INTELIGENTE: Detectar ?company=X y redirigir a token
    company_id_param = request.GET.get('company')
    token_param = request.GET.get('token')
    
    if company_id_param and not token_param:
        logger.info(f"🔄 SMART MODE: Detected ?company={company_id_param}, redirecting to token...")
        
        try:
            company_id = int(company_id_param)
            target_company = user_companies.filter(id=company_id).first()
            
            if target_company:
                # Obtener/crear token para esta empresa
                company_token, created = CompanyAPIToken.objects.get_or_create(
                    company=target_company,
                    defaults={
                        'name': f'Auto-generated token for {target_company.business_name}',
                        'is_active': True
                    }
                )
                
                if created:
                    logger.info(f"🔑 Token created automatically for smart redirect: {target_company.business_name}")
                
                # Construir URL de redirección con token
                redirect_url = f"/dashboard/?token={company_token.key}"
                
                # Preservar otros parámetros de la URL original
                other_params = []
                for key, value in request.GET.items():
                    if key != 'company' and value:
                        other_params.append(f"{key}={value}")
                
                if other_params:
                    redirect_url += "&" + "&".join(other_params)
                
                logger.info(f"✅ SMART REDIRECT: {company_id_param} -> {company_token.key[:20]}...")
                return redirect(redirect_url)
            
            else:
                logger.warning(f"🚫 SMART MODE: User {user.username} denied access to company {company_id_param}")
                messages.error(request, f'No tienes acceso a la empresa solicitada.')
                return redirect('core:dashboard')
                
        except (ValueError, TypeError):
            logger.warning(f"🚫 SMART MODE: Invalid company ID format: {company_id_param}")
            messages.error(request, 'ID de empresa inválido.')
            return redirect('core:dashboard')
    
    # 🔑 MODO TOKEN: Validar token si está presente
    selected_company = None
    selected_token = None
    
    if token_param:
        try:
            company_token = CompanyAPIToken.objects.get(
                key=token_param,
                company__in=user_companies,
                is_active=True
            )
            selected_company = company_token.company
            selected_token = company_token
            
            logger.info(f"✅ TOKEN MODE: User {user.username} validated access to {selected_company.business_name} via token {token_param[:20]}...")
            
        except CompanyAPIToken.DoesNotExist:
            logger.warning(f"🚫 TOKEN MODE: User {user.username} denied access with invalid token {token_param[:20]}...")
            messages.error(request, f'Token de empresa inválido o sin permisos.')
            return redirect('core:dashboard')
    
    # 🏢 MODO DEFAULT: Sin parámetros - usar primera empresa y redirigir a su token
    if not selected_company:
        default_company = user_companies.first()
        logger.info(f"🏢 DEFAULT MODE: Using default company {default_company.business_name} for user {user.username}")
        
        # Obtener/crear token para la empresa por defecto
        try:
            default_token, created = CompanyAPIToken.objects.get_or_create(
                company=default_company,
                defaults={
                    'name': f'Auto-generated token for {default_company.business_name}',
                    'is_active': True
                }
            )
            
            if created:
                logger.info(f"🔑 Token created automatically for default company: {default_company.business_name}")
            
            # Redirigir a URL con token
            logger.info(f"🔄 DEFAULT REDIRECT: Redirecting to token for {default_company.business_name}")
            return redirect(f"/dashboard/?token={default_token.key}")
            
        except Exception as e:
            logger.error(f"❌ Error creating default token: {e}")
            # Fallback: continuar sin redirección
            selected_company = default_company
            selected_token = None
    
    # 🔑 Preparar tokens disponibles para el selector
    available_companies_with_tokens = []
    for company in user_companies:
        try:
            # Obtener/crear token para cada empresa
            company_token, created = CompanyAPIToken.objects.get_or_create(
                company=company,
                defaults={
                    'name': f'Auto-generated token for {company.business_name}',
                    'is_active': True
                }
            )
            
            available_companies_with_tokens.append({
                'company': company,
                'token': company_token,
                'is_selected': company.id == selected_company.id,
                'dashboard_url': f"/dashboard/?token={company_token.key}",
                'api_test_url': f"/api/companies/",
                'token_display': f"{company_token.key[:20]}...",
            })
            
        except Exception as e:
            logger.error(f"❌ Error obtaining token for {company.business_name}: {e}")
    
    # ==================== INFORMACIÓN DEL CERTIFICADO ====================
    has_certificate = False
    certificate_info = {}
    
    if selected_company and hasattr(DigitalCertificate, 'objects') and DigitalCertificate.objects is not None:
        try:
            certificate = DigitalCertificate.objects.filter(
                company=selected_company,
                status='ACTIVE'
            ).first()
            
            if certificate:
                has_certificate = True
                certificate_info = {
                    'issuer': certificate.issuer_name,
                    'subject': certificate.subject_name,
                    'expiry': certificate.valid_to,
                    'days_left': getattr(certificate, 'days_until_expiration', 0),
                    'expired': getattr(certificate, 'is_expired', False),
                    'serial': certificate.serial_number
                }
        except Exception as e:
            logger.error(f"Error obteniendo certificado: {e}")
    elif selected_company:
        logger.warning("DigitalCertificate model not available - certificate info disabled")
    
    # ==================== BILLING ====================
    current_plan = None
    all_plans = []
    recent_purchases = []
    billing_profile = None
    
    try:
        from apps.billing.models import Plan, CompanyBillingProfile, PlanPurchase
        BILLING_AVAILABLE = True
    except ImportError:
        try:
            # Intentar con nombre alternativo
            from apps.billing.models import Plan, BillingProfile as CompanyBillingProfile, PlanPurchase
            BILLING_AVAILABLE = True
        except ImportError:
            BILLING_AVAILABLE = False
            logger.warning("Billing models not available")
    
    if BILLING_AVAILABLE and selected_company:
        try:
            # Asegurar que existe el billing profile
            billing_profile, created = CompanyBillingProfile.objects.get_or_create(
                company=selected_company,
                defaults={
                    'available_invoices': 0,
                    'total_invoices_purchased': 0,
                    'total_invoices_consumed': 0,
                }
            )
            
            if created:
                logger.info(f"💳 Billing profile created for {selected_company.business_name}")
            
            # Obtener plan actual
            last_purchase = PlanPurchase.objects.filter(
                company=selected_company,
                payment_status='approved'
            ).order_by('-created_at').first()
            
            if last_purchase:
                current_plan = last_purchase.plan
                # Hotfix: Sincronizar estado ilimitado y verificar expiración
                if not billing_profile.last_purchase_date or billing_profile.last_purchase_date != last_purchase.created_at:
                    billing_profile.last_purchase_date = last_purchase.created_at
                    billing_profile.save(update_fields=['last_purchase_date'])

                if current_plan.is_unlimited:
                    # Si el plan ilimitado ya expiró (30 días), lo desactivamos
                    if billing_profile.is_expired:
                        if billing_profile.is_unlimited:
                            billing_profile.is_unlimited = False
                            billing_profile.save()
                    elif not billing_profile.is_unlimited:
                        # Si es ilimitado y no ha expirado, asegurar que esté activo
                        billing_profile.is_unlimited = True
                        billing_profile.save()
                else:
                    if billing_profile.is_unlimited:
                        billing_profile.is_unlimited = False
                        billing_profile.save()
            
            # Obtener todos los planes activos
            all_plans = Plan.objects.filter(is_active=True).order_by('price')
            
            # Obtener compras recientes
            recent_purchases = PlanPurchase.objects.filter(
                company=selected_company
            ).order_by('-created_at')[:5]
        except Exception as e:
            logger.error(f"Error loading billing data: {e}")
            BILLING_AVAILABLE = False

    # ==================== ESTADÍSTICAS CORREGIDAS ====================
    stats = {
        'total_invoices': 0,
        'authorized_invoices': 0,
        'pending_invoices': 0,
        'rejected_invoices': 0,
        'total_amount': 0,
        'month_1': 0, 'month_2': 0, 'month_3': 0, 'month_4': 0, 'month_5': 0, 'month_6': 0
    }
    
    recent_invoices = []
    document_stats = {
        'facturas': 0,
        'retenciones': 0,
        'liquidaciones': 0,
        'notas_credito': 0,
        'notas_debito': 0,
    }
    
    if selected_company:
        try:
            # Intentar obtener SRIConfiguration de la empresa
            sri_config = None
            try:
                from apps.sri_integration.models import SRIConfiguration
                sri_config = SRIConfiguration.objects.filter(company=selected_company).first()
            except ImportError:
                logger.warning("SRIConfiguration model not available")
            
            # Intentar usar el modelo ElectronicDocument si existe
            try:
                from apps.sri_integration.models import ElectronicDocument
                
                all_documents = ElectronicDocument.objects.filter(
                    company=selected_company
                )
                
                # Estadísticas generales
                stats = {
                    'total_invoices': all_documents.count(),
                    'authorized_invoices': all_documents.filter(status='AUTHORIZED').count(),
                    'pending_invoices': all_documents.filter(
                        status__in=['DRAFT', 'GENERATED', 'SIGNED', 'SENT']
                    ).count(),
                    'rejected_invoices': all_documents.filter(
                        status__in=['REJECTED', 'ERROR']
                    ).count(),
                    'total_amount': all_documents.filter(
                        status='AUTHORIZED'
                    ).aggregate(total=Sum('total_amount'))['total'] or 0,
                    'month_1': 0, 'month_2': 0, 'month_3': 0, 'month_4': 0, 'month_5': 0, 'month_6': 0
                }
                
                # Estadísticas por tipo
                document_stats = {
                    'facturas': all_documents.filter(document_type='INVOICE').count(),
                    'retenciones': all_documents.filter(document_type='RETENTION').count(),
                    'liquidaciones': all_documents.filter(document_type='PURCHASE_SETTLEMENT').count(),
                    'notas_credito': all_documents.filter(document_type='CREDIT_NOTE').count(),
                    'notas_debito': all_documents.filter(document_type='DEBIT_NOTE').count(),
                }
                
                # Documentos recientes
                recent_docs = all_documents.order_by('-created_at')[:50]
                
                for doc in recent_docs:
                    # Mapear tipos para el template
                    type_mapping = {
                        'INVOICE': 'factura',
                        'RETENTION': 'retencion', 
                        'PURCHASE_SETTLEMENT': 'liquidacion',
                        'CREDIT_NOTE': 'nota_credito',
                        'DEBIT_NOTE': 'nota_debito',
                    }
                    
                    # Crear objeto compatible con el template
                    doc_data = {
                        'id': doc.id,
                        'document_type': doc.document_type,
                        'mapped_type': type_mapping.get(doc.document_type, 'factura'),
                        'document_number': getattr(doc, 'document_number', None) or getattr(doc, 'sequence_number', str(doc.id)),
                        'client_name': getattr(doc, 'customer_name', None) or getattr(doc, 'supplier_name', 'Cliente'),
                        'total_amount': float(getattr(doc, 'total_amount', 0) or 0),
                        'status': 'PENDIENTE' if doc.status in ['DRAFT', 'GENERATED', 'SIGNED', 'SENT'] else doc.status,
                        'created_at': doc.created_at,
                        'company': doc.company,
                        'environment': doc.environment,
                    }
                    recent_invoices.append(type('Document', (), doc_data)())
                
            except ImportError:
                logger.info("ElectronicDocument model not available, trying individual models...")
                
                # Fallback: usar modelos individuales si ElectronicDocument no existe
                all_documents = []
                
                try:
                    from apps.sri_integration.models import Invoice
                    if sri_config:
                        facturas = Invoice.objects.filter(sri_config=sri_config)
                    else:
                        facturas = Invoice.objects.filter(company=selected_company)
                    
                    document_stats['facturas'] = facturas.count()
                    
                    for factura in facturas.order_by('-created_at')[:20]:
                        doc_data = {
                            'id': factura.id,
                            'document_type': 'INVOICE',
                            'mapped_type': 'factura',
                            'document_number': getattr(factura, 'sequence_number', str(factura.id)),
                            'client_name': getattr(factura, 'customer_name', 'Cliente'),
                            'total_amount': float(getattr(factura, 'total_amount', 0) or 0),
                            'status': 'PENDIENTE' if factura.status in ['DRAFT', 'GENERATED', 'SIGNED', 'SENT'] else factura.status,
                            'created_at': factura.created_at,
                            'company': selected_company,
                            'environment': 'TEST' if getattr(factura, 'access_key', '') and len(getattr(factura, 'access_key', '')) >= 24 and factura.access_key[23] == '1' else 'PRODUCTION',
                        }
                        all_documents.append(doc_data)
                except ImportError:
                    logger.warning("Invoice model not available")
                
                try:
                    from apps.sri_integration.models import Retention
                    if sri_config:
                        retenciones = Retention.objects.filter(sri_config=sri_config)
                    else:
                        retenciones = Retention.objects.filter(company=selected_company)
                    
                    document_stats['retenciones'] = retenciones.count()
                    
                    for retencion in retenciones.order_by('-created_at')[:10]:
                        doc_data = {
                            'id': retencion.id,
                            'document_type': 'RETENTION',
                            'mapped_type': 'retencion',
                            'document_number': getattr(retencion, 'sequence_number', str(retencion.id)),
                            'client_name': getattr(retencion, 'supplier_name', 'Proveedor'),
                            'total_amount': float(getattr(retencion, 'total_amount', 0) or 0),
                            'status': 'PENDIENTE' if retencion.status in ['DRAFT', 'GENERATED', 'SIGNED', 'SENT'] else retencion.status,
                            'created_at': retencion.created_at,
                            'company': selected_company,
                            'environment': 'TEST' if getattr(retencion, 'access_key', '') and len(getattr(retencion, 'access_key', '')) >= 24 and retencion.access_key[23] == '1' else 'PRODUCTION',
                        }
                        all_documents.append(doc_data)
                except ImportError:
                    logger.warning("Retention model not available")
                
                try:
                    from apps.sri_integration.models import PurchaseSettlement
                    if sri_config:
                        liquidaciones = PurchaseSettlement.objects.filter(sri_config=sri_config)
                    else:
                        liquidaciones = PurchaseSettlement.objects.filter(company=selected_company)
                    
                    document_stats['liquidaciones'] = liquidaciones.count()
                    
                    for liquidacion in liquidaciones.order_by('-created_at')[:10]:
                        doc_data = {
                            'id': liquidacion.id,
                            'document_type': 'PURCHASE_SETTLEMENT',
                            'mapped_type': 'liquidacion',
                            'document_number': getattr(liquidacion, 'sequence_number', str(liquidacion.id)),
                            'client_name': getattr(liquidacion, 'supplier_name', 'Proveedor'),
                            'total_amount': float(getattr(liquidacion, 'total_amount', 0) or 0),
                            'status': liquidacion.status,
                            'created_at': liquidacion.created_at,
                            'company': selected_company,
                            'environment': 'TEST' if getattr(liquidacion, 'access_key', '') and len(getattr(liquidacion, 'access_key', '')) >= 24 and liquidacion.access_key[23] == '1' else 'PRODUCTION',
                        }
                        all_documents.append(doc_data)
                except ImportError:
                    logger.warning("PurchaseSettlement model not available")
                
                try:
                    from apps.sri_integration.models import CreditNote
                    if sri_config:
                        notas_credito = CreditNote.objects.filter(sri_config=sri_config)
                    else:
                        notas_credito = CreditNote.objects.filter(company=selected_company)
                    
                    document_stats['notas_credito'] = notas_credito.count()
                    
                    for nota in notas_credito.order_by('-created_at')[:10]:
                        doc_data = {
                            'id': nota.id,
                            'document_type': 'CREDIT_NOTE',
                            'mapped_type': 'nota_credito',
                            'document_number': getattr(nota, 'sequence_number', str(nota.id)),
                            'client_name': getattr(nota, 'customer_name', 'Cliente'),
                            'total_amount': float(getattr(nota, 'total_amount', 0) or 0),
                            'status': nota.status,
                            'created_at': nota.created_at,
                            'company': selected_company,
                            'environment': 'TEST' if getattr(nota, 'access_key', '') and len(getattr(nota, 'access_key', '')) >= 24 and nota.access_key[23] == '1' else 'PRODUCTION',
                        }
                        all_documents.append(doc_data)
                except ImportError:
                    logger.warning("CreditNote model not available")
                
                try:
                    from apps.sri_integration.models import DebitNote
                    if sri_config:
                        notas_debito = DebitNote.objects.filter(sri_config=sri_config)
                    else:
                        notas_debito = DebitNote.objects.filter(company=selected_company)
                    
                    document_stats['notas_debito'] = notas_debito.count()
                    
                    for nota in notas_debito.order_by('-created_at')[:10]:
                        doc_data = {
                            'id': nota.id,
                            'document_type': 'DEBIT_NOTE',
                            'mapped_type': 'nota_debito',
                            'document_number': getattr(nota, 'sequence_number', str(nota.id)),
                            'client_name': getattr(nota, 'customer_name', 'Cliente'),
                            'total_amount': float(getattr(nota, 'total_amount', 0) or 0),
                            'status': nota.status,
                            'created_at': nota.created_at,
                            'company': selected_company,
                            'environment': 'TEST' if getattr(nota, 'access_key', '') and len(getattr(nota, 'access_key', '')) >= 24 and nota.access_key[23] == '1' else 'PRODUCTION',
                        }
                        all_documents.append(doc_data)
                except ImportError:
                    logger.warning("DebitNote model not available")
                
                # Ordenar todos los documentos por fecha
                all_documents.sort(key=lambda x: x['created_at'], reverse=True)
                
                # Convertir a objetos para compatibilidad con template
                for doc_data in all_documents[:50]:
                    recent_invoices.append(type('Document', (), doc_data)())
                
                # Calcular estadísticas generales
                total_docs = len(all_documents)
                authorized_docs = len([d for d in all_documents if d['status'] == 'AUTHORIZED'])
                pending_docs = len([d for d in all_documents if d['status'] in ['DRAFT', 'GENERATED', 'SIGNED', 'SENT']])
                rejected_docs = len([d for d in all_documents if d['status'] in ['REJECTED', 'ERROR']])
                total_amount = sum(d['total_amount'] for d in all_documents if d['status'] == 'AUTHORIZED')
                
                stats = {
                    'total_invoices': total_docs,
                    'authorized_invoices': authorized_docs,
                    'pending_invoices': pending_docs,
                    'rejected_invoices': rejected_docs,
                    'total_amount': total_amount
                }
                
        except Exception as e:
            logger.error(f"Error obteniendo estadísticas para empresa {selected_company.business_name}: {e}")
            # Mantener valores por defecto en caso de error

    # ==================== DOCUMENTOS EN COLA (PERSISTENCIA) ====================
    queue_documents = []
    if selected_company:
        # Definimos "en cola" como documentos no finalizados O finalizados hace menos de 15 min
        time_threshold = timezone.now() - timedelta(minutes=15)
        
        try:
            from apps.sri_integration.models import ElectronicDocument
            active_docs = ElectronicDocument.objects.filter(
                company=selected_company
            ).filter(
                Q(status__in=['DRAFT', 'GENERATED', 'SIGNED', 'SENT']) | 
                Q(status__in=['AUTHORIZED', 'REJECTED', 'ERROR'], updated_at__gte=time_threshold)
            ).order_by('-updated_at')[:10]
            
            type_mapping = {
                'INVOICE': 'Factura',
                'RETENTION': 'Retención',
                'PURCHASE_SETTLEMENT': 'Liquidación',
                'CREDIT_NOTE': 'Nota de Crédito',
                'DEBIT_NOTE': 'Nota de Débito',
            }
            
            for doc in active_docs:
                # Determinar paso actual para el stepper (0-5)
                step = 0
                if doc.status == 'GENERATED': step = 1
                elif doc.status == 'SIGNED': step = 2
                elif doc.status == 'SENT': step = 3
                elif doc.status == 'AUTHORIZED': step = 5
                elif doc.status in ['ERROR', 'REJECTED']: step = 5
                
                queue_documents.append({
                    'id': doc.id,
                    'number': doc.document_number or f"ID: {doc.id}",
                    'type': type_mapping.get(doc.document_type, 'Documento'),
                    'status': doc.status,
                    'step': step,
                    'time': doc.updated_at.strftime('%H:%M:%S'),
                    'is_final': doc.status in ['AUTHORIZED', 'REJECTED', 'ERROR']
                })
        except Exception as e:
            logger.error(f"Error fetching queue documents: {e}")

    # ==================== PREPARAR CONTEXTO FINAL ====================
    context = {
        'user': user,
        'user_companies': user_companies,
        'selected_company': selected_company,
        'selected_token': selected_token,
        'available_companies_with_tokens': available_companies_with_tokens,
        'queue_documents': queue_documents,
        'has_certificate': has_certificate,
        'certificate_info': certificate_info,
        'stats': stats,
        'document_stats': document_stats,
        'recent_invoices': recent_invoices,
        'current_plan': current_plan,
        'all_plans': all_plans,
        'recent_purchases': recent_purchases,
        'billing_profile': billing_profile,
        'certificate_expiry': certificate_info.get('expiry'),
        'certificate_issuer': certificate_info.get('issuer'),
        'certificate_days_left': certificate_info.get('days_left'),
        'certificate_expired': certificate_info.get('expired', False),
        'billing_available': BILLING_AVAILABLE,
        'page_title': 'Dashboard Principal',
        'security_validation': {
            'token_system_enabled': True,
            'user_access_confirmed': True,
            'company_validated': selected_company is not None,
        }
    }
    
    return render(request, 'dashboard/user_dashboard.html', context)
@login_required
@audit_html_action('UPDATE_COMPANY')
@require_POST
def company_update(request, company_id):
    """
    Vista AJAX para actualizar información de la empresa - VERSIÓN CORREGIDA
    """
    company = get_object_or_404(Company, id=company_id)
    
    # Verificar permisos
    user_companies = get_user_companies_secure(request.user)
    if not user_companies.filter(id=company.id).exists() and not request.user.is_staff:
        return JsonResponse({
            'success': False,
            'errors': {'general': 'No tienes permisos para editar esta empresa'}
        }, status=403)
    
    try:
        with transaction.atomic():
            # Validar datos obligatorios
            required_fields = {
                'business_name': 'La razón social es obligatoria',
                'email': 'El email es obligatorio',
                'address': 'La dirección es obligatoria',
                'codigo_establecimiento': 'El código de establecimiento es obligatorio',
                'codigo_punto_emision': 'El código de punto emisión es obligatorio',
            }
            
            errors = {}
            for field, error_msg in required_fields.items():
                value = request.POST.get(field, '').strip()
                if not value:
                    errors[field] = [error_msg]
            
            if errors:
                return JsonResponse({
                    'success': False,
                    'errors': errors
                }, status=400)
            
            # Actualizar campos básicos
            company.ruc = request.POST.get('ruc', company.ruc).strip()
            company.business_name = request.POST.get('business_name', '').strip()
            company.trade_name = request.POST.get('trade_name', '').strip()
            company.email = request.POST.get('email', '').strip().lower()
            company.phone = request.POST.get('phone', '').strip()
            company.address = request.POST.get('address', '').strip()
            
            # Campos geográficos
            company.ciudad = request.POST.get('ciudad', '').strip().title()
            company.provincia = request.POST.get('provincia', '').strip().title()
            company.codigo_postal = request.POST.get('codigo_postal', '').strip()
            company.website = request.POST.get('website', '').strip()
            
            # Campos SRI
            company.tipo_contribuyente = request.POST.get('tipo_contribuyente', company.tipo_contribuyente)
            company.obligado_contabilidad = request.POST.get('obligado_contabilidad', company.obligado_contabilidad)
            
            contribuyente_especial = request.POST.get('contribuyente_especial', '').strip()
            company.contribuyente_especial = contribuyente_especial if contribuyente_especial else None
            
            company.codigo_establecimiento = request.POST.get('codigo_establecimiento', '001').strip()
            company.codigo_punto_emision = request.POST.get('codigo_punto_emision', '001').strip()
            company.ambiente_sri = request.POST.get('ambiente_sri', company.ambiente_sri)
            company.tipo_emision = request.POST.get('tipo_emision', company.tipo_emision)

            # Campos de Secuenciales (NUEVO)
            if 'secuencial_factura' in request.POST:
                company.secuencial_factura = int(request.POST.get('secuencial_factura', 1))
            if 'secuencial_nota_credito' in request.POST:
                company.secuencial_nota_credito = int(request.POST.get('secuencial_nota_credito', 1))
            if 'secuencial_retencion' in request.POST:
                company.secuencial_retencion = int(request.POST.get('secuencial_retencion', 1))
            
            # Manejar logo si se subió
            if 'logo' in request.FILES:
                logo_file = request.FILES['logo']
                valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
                file_extension = logo_file.name.lower()[logo_file.name.rfind('.'):]
                
                if file_extension not in valid_extensions:
                    return JsonResponse({
                        'success': False,
                        'errors': {'logo': ['Solo se permiten archivos de imagen']}
                    }, status=400)
                
                if logo_file.size > 5 * 1024 * 1024:
                    return JsonResponse({
                        'success': False,
                        'errors': {'logo': ['El archivo no puede superar los 5MB']}
                    }, status=400)
                
                company.logo = logo_file
            
            # Guardar Company primero
            company.full_clean()
            company.save()
            
            logger.info(f"✅ Company {company.business_name} saved successfully")
            
            # SINCRONIZACIÓN CON SRICONFIGURATION
            sri_config_message = ""
            try:
                from apps.sri_integration.models import SRIConfiguration
                
                # Buscar o crear SRIConfiguration
                sri_config, created = SRIConfiguration.objects.get_or_create(
                    company=company,
                    defaults={
                        'is_active': True,
                    }
                )
                
                # Actualizar TODOS los campos de SRIConfiguration
                sri_config.environment = 'TEST' if company.ambiente_sri == '1' else 'PRODUCTION'
                sri_config.establishment_code = company.codigo_establecimiento
                sri_config.emission_point = company.codigo_punto_emision
                sri_config.accounting_required = (company.obligado_contabilidad == 'SI')
                
                # Sincronizar secuenciales
                sri_config.invoice_sequence = company.secuencial_factura
                sri_config.credit_note_sequence = company.secuencial_nota_credito
                sri_config.retention_sequence = company.secuencial_retencion
                
                # Manejar contribuyente especial
                if company.contribuyente_especial:
                    sri_config.special_taxpayer = True
                    sri_config.special_taxpayer_number = company.contribuyente_especial
                else:
                    sri_config.special_taxpayer = False
                    sri_config.special_taxpayer_number = ''
                
                # Guardar SRIConfiguration
                sri_config.save()
                
                sri_config_message = " (SRI Config sincronizada)"
                logger.info(f"✅ SRIConfiguration {'created' if created else 'updated'} for {company.business_name}")
                logger.info(f"   - Environment: {sri_config.environment}")
                logger.info(f"   - Establishment: {sri_config.establishment_code}")
                logger.info(f"   - Emission Point: {sri_config.emission_point}")
                logger.info(f"   - Accounting Required: {sri_config.accounting_required}")
                logger.info(f"   - Special Taxpayer: {sri_config.special_taxpayer}")
                
            except ImportError:
                logger.warning("SRIConfiguration model not available")
            except Exception as e:
                logger.error(f"Error updating SRIConfiguration: {e}")
                # No fallar toda la operación por esto
            
            # Manejar certificado si se subió
            certificate_message = ""
            if 'certificate_file' in request.FILES and request.POST.get('certificate_password'):
                try:
                    certificate = handle_certificate_upload(
                        company=company,
                        file=request.FILES['certificate_file'],
                        password=request.POST.get('certificate_password', ''),
                        alias=request.POST.get('certificate_alias', 'Certificado Principal'),
                        user=request.user
                    )
                    certificate_message = " y certificado actualizado"
                except Exception as cert_error:
                    logger.error(f"Error actualizando certificado: {cert_error}")
                    certificate_message = " (error al actualizar certificado)"
            
            return JsonResponse({
                'success': True,
                'message': f'Información actualizada correctamente{sri_config_message}{certificate_message}',
                'data': {
                    'business_name': company.business_name,
                    'trade_name': company.trade_name,
                    'ciudad': company.ciudad,
                    'provincia': company.provincia,
                    'email': company.email,
                    'phone': company.phone,
                    'address': company.address,
                }
            })
            
    except ValidationError as e:
        logger.error(f"Validation error: {e}")
        error_dict = {}
        if hasattr(e, 'message_dict'):
            error_dict = e.message_dict
        else:
            error_dict = {'general': str(e)}
        
        return JsonResponse({
            'success': False,
            'errors': error_dict
        }, status=400)
        
    except Exception as e:
        logger.error(f"Error updating company {company_id}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        return JsonResponse({
            'success': False,
            'errors': {'general': f'Error interno: {str(e)}'}
        }, status=500)
    
@login_required
@audit_html_action('UPLOAD_CERTIFICATE')
def certificate_upload(request, company_id):
    """
    Vista dedicada para subir/actualizar certificado digital
    """
    company = get_object_or_404(Company, id=company_id)
    
    # Verificar permisos
    user_companies = get_user_companies_secure(request.user)
    if not user_companies.filter(id=company.id).exists() and not request.user.is_staff:
        return JsonResponse({
            'success': False,
            'errors': {'general': 'No tienes permisos para gestionar certificados de esta empresa'}
        }, status=403)
    
    if request.method == 'POST':
        try:
            certificate = handle_certificate_upload(
                company=company,
                file=request.FILES.get('certificate_file'),
                password=request.POST.get('certificate_password', ''),
                alias=request.POST.get('certificate_alias', ''),
                user=request.user
            )
            
            messages.success(request, 'Certificado cargado exitosamente')
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Certificado cargado correctamente',
                    'certificate': {
                        'id': certificate.id,
                        'issuer': certificate.issuer_name,
                        'subject': certificate.subject_name,
                        'valid_from': certificate.valid_from.strftime('%d/%m/%Y'),
                        'valid_to': certificate.valid_to.strftime('%d/%m/%Y'),
                        'days_until_expiration': certificate.days_until_expiration,
                        'is_active': certificate.status == 'ACTIVE'
                    }
                })
            
            # Obtener token para redirección
            try:
                company_token = CompanyAPIToken.objects.get(company=company, is_active=True)
                return redirect(f'/dashboard/?token={company_token.key}')
            except:
                return redirect('core:dashboard')
            
        except Exception as e:
            error_msg = f'Error al procesar certificado: {str(e)}'
            messages.error(request, error_msg)
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'errors': {'certificate_file': error_msg}
                }, status=400)
    
    return redirect('core:dashboard')


def handle_certificate_upload(company, file, password, alias, user):
    """
    Maneja la carga y procesamiento del certificado digital
    """
    # Verificar si el modelo DigitalCertificate está disponible
    if not hasattr(DigitalCertificate, 'objects') or DigitalCertificate.objects is None:
        raise ValueError("El sistema de certificados no está disponible. Contacte al administrador.")
    
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    import hashlib
    
    if not file:
        raise ValueError("No se proporcionó archivo de certificado")
    
    try:
        # Leer el archivo
        cert_data = file.read()
        
        # Intentar cargar el certificado para validarlo
        try:
            private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
                cert_data,
                password.encode() if password else None,
                backend=default_backend()
            )
        except Exception as e:
            raise ValueError(f"No se pudo leer el certificado. Verifique que el archivo y contraseña sean correctos: {str(e)}")
        
        if not certificate:
            raise ValueError("El archivo no contiene un certificado válido")
        
        # Extraer información del certificado
        subject = certificate.subject
        issuer = certificate.issuer
        
        # Formatear nombres
        subject_name = ", ".join([f"{attr.oid._name}={attr.value}" for attr in subject])
        issuer_name = ", ".join([f"{attr.oid._name}={attr.value}" for attr in issuer])
        
        # Desactivar certificados anteriores
        DigitalCertificate.objects.filter(
            company=company,
            status='ACTIVE'
        ).update(status='INACTIVE')
        
        # Crear nuevo certificado
        new_cert = DigitalCertificate(
            company=company,
            subject_name=subject_name[:255],
            issuer_name=issuer_name[:255],
            serial_number=str(certificate.serial_number)[:100],
            valid_from=certificate.not_valid_before,
            valid_to=certificate.not_valid_after,
            status='ACTIVE',
            created_by=user,
        )
        
        # Solo agregar environment si el campo existe
        if hasattr(new_cert, 'environment'):
            new_cert.environment = 'TEST' if company.ambiente_sri == '1' else 'PRODUCTION'
        
        # Establecer contraseña hasheada si el método existe
        if hasattr(new_cert, 'set_password'):
            new_cert.set_password(password)
        
        # Guardar archivo
        file.seek(0)  # Volver al inicio del archivo
        new_cert.certificate_file.save(f"{company.ruc}_cert.p12", file)
        
        # Guardar certificado
        new_cert.save()
        
        logger.info(f"✅ Certificate uploaded for company {company.business_name} by {user.username}")
        
        return new_cert
        
    except Exception as e:
        logger.error(f"Error processing certificate: {str(e)}")
        raise ValueError(f"Error al procesar el certificado: {str(e)}")


@login_required
def company_info_modal(request, company_id):
    """
    Vista para obtener información de la empresa para el modal de edición
    """
    company = get_object_or_404(Company, id=company_id)
    
    # Verificar permisos
    user_companies = get_user_companies_secure(request.user)
    if not user_companies.filter(id=company.id).exists() and not request.user.is_staff:
        return JsonResponse({'error': 'Sin permisos'}, status=403)
    
    # Obtener información del certificado si existe
    certificate_info = None
    if hasattr(DigitalCertificate, 'objects') and DigitalCertificate.objects is not None:
        try:
            certificate = DigitalCertificate.objects.filter(
                company=company,
                status='ACTIVE'
            ).first()
            
            if certificate:
                certificate_info = {
                    'has_certificate': True,
                    'issuer': certificate.issuer_name,
                    'valid_until': certificate.valid_to.strftime('%d/%m/%Y'),
                    'days_left': getattr(certificate, 'days_until_expiration', 0),
                    'is_expired': getattr(certificate, 'is_expired', False),
                    'is_active': certificate.status == 'ACTIVE'
                }
            else:
                certificate_info = {'has_certificate': False}
        except Exception as e:
            logger.error(f"Error getting certificate info: {e}")
            certificate_info = {'has_certificate': False}
    else:
        certificate_info = {'has_certificate': False}
    
    # Preparar datos para el formulario
    data = {
        'company': {
            'id': company.id,
            'ruc': company.ruc,
            'business_name': company.business_name,
            'trade_name': company.trade_name,
            'email': company.email,
            'phone': company.phone,
            'address': company.address,
            'ciudad': company.ciudad,
            'provincia': company.provincia,
            'codigo_postal': company.codigo_postal,
            'website': company.website,
            'tipo_contribuyente': company.tipo_contribuyente,
            'obligado_contabilidad': company.obligado_contabilidad,
            'contribuyente_especial': company.contribuyente_especial,
            'codigo_establecimiento': company.codigo_establecimiento,
            'codigo_punto_emision': company.codigo_punto_emision,
            'ambiente_sri': company.ambiente_sri,
            'tipo_emision': company.tipo_emision,
            'logo_url': company.logo.url if company.logo else None
        },
        'certificate': certificate_info,
        'tipo_contribuyente_choices': list(Company.TIPO_CONTRIBUYENTE_CHOICES),
        'obligado_contabilidad_choices': list(Company.OBLIGADO_CONTABILIDAD_CHOICES)
    }
    
    return JsonResponse(data)


@login_required
def company_select(request, company_id):
    """
    Cambia la empresa seleccionada - redirige con token
    """
    company = get_object_or_404(Company, id=company_id, is_active=True)
    
    # Verificar que el usuario tenga acceso
    user_companies = get_user_companies_secure(request.user)
    if user_companies.filter(id=company.id).exists() or request.user.is_staff:
        # Obtener o crear token para la empresa
        try:
            company_token, created = CompanyAPIToken.objects.get_or_create(
                company=company,
                defaults={
                    'name': f'Auto-generated token for {company.business_name}',
                    'is_active': True
                }
            )
            
            messages.success(request, f'Empresa cambiada a: {company.display_name}')
            return redirect(f'/dashboard/?token={company_token.key}')
            
        except Exception as e:
            logger.error(f"Error getting token for company selection: {e}")
            messages.error(request, 'Error al cambiar de empresa')
    else:
        messages.error(request, 'No tienes acceso a esta empresa')
    
    return redirect('core:dashboard')


@login_required
def company_dashboard(request, company_id):
    """
    Dashboard específico de una empresa - redirige con token
    """
    company = get_object_or_404(Company, id=company_id, is_active=True)
    
    # Verificar acceso
    user_companies = get_user_companies_secure(request.user)
    if user_companies.filter(id=company.id).exists() or request.user.is_staff:
        # Obtener o crear token y redirigir
        try:
            company_token, created = CompanyAPIToken.objects.get_or_create(
                company=company,
                defaults={
                    'name': f'Auto-generated token for {company.business_name}',
                    'is_active': True
                }
            )
            
            return redirect(f'/dashboard/?token={company_token.key}')
            
        except Exception as e:
            logger.error(f"Error in company_dashboard: {e}")
            messages.error(request, 'Error al acceder al dashboard de la empresa')
    else:
        messages.error(request, 'No tienes acceso a esta empresa')
    
    return redirect('core:dashboard')


# ========== VISTAS ADMINISTRATIVAS ==========

@login_required
@audit_html_action('VIEW_ADMIN_DASHBOARD')
def admin_dashboard_view(request):
    """
    🔒 DASHBOARD ADMINISTRATIVO SEGURO
    """
    if not (request.user.is_staff or request.user.is_superuser):
        logger.warning(f"Non-admin user {request.user.username} tried to access admin dashboard")
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('core:dashboard')
    
    # Estadísticas generales para admins
    total_users = User.objects.filter(is_staff=False, is_superuser=False).count()
    total_companies = Company.objects.count()
    total_tokens = CompanyAPIToken.objects.filter(is_active=True).count()
    
    # Valores por defecto
    waiting_users = 0
    assigned_users = total_users
    unread_notifications = 0
    recent_notifications = []
    recent_waiting = []
    total_invoices = 0
    pending_invoices = 0
    
    # Estadísticas de tokens más utilizados
    try:
        top_tokens = CompanyAPIToken.objects.filter(
            is_active=True
        ).select_related('company').order_by('-total_requests')[:5]
    except Exception as e:
        logger.error(f"Error getting token stats: {e}")
        top_tokens = []
    
    admin_stats = {
        'total_users': total_users,
        'waiting_users': waiting_users,
        'assigned_users': assigned_users,
        'total_companies': total_companies,
        'total_tokens': total_tokens,
        'total_invoices': total_invoices,
        'pending_invoices': pending_invoices,
        'unread_notifications': unread_notifications,
    }
    
    context = {
        'is_admin': True,
        'admin_stats': admin_stats,
        'top_tokens': top_tokens,
        'recent_notifications': recent_notifications,
        'recent_waiting': recent_waiting,
        'assignments_available': False,
        'invoices_available': False,
        'security_validation': {
            'admin_access_confirmed': True,
            'user': request.user.username,
            'token_system_enabled': True,
        }
    }
    
    return render(request, 'dashboard/admin_dashboard.html', context)


# ========== APIs CON TOKENS ==========

@login_required
@audit_html_action('SWITCH_COMPANY_TOKEN')
def switch_company_token_ajax(request):
    """
    Cambio de empresa vía AJAX - USA TOKENS
    
    POST /dashboard/api/switch-company/
    {"token": "vsr_ABC123..."}
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        token = data.get('token')
        
        if not token:
            return JsonResponse({'error': 'Token required'}, status=400)
        
        # Verificar que el usuario tenga acceso a este token
        user_companies = get_user_companies_secure(request.user)
        
        try:
            company_token = CompanyAPIToken.objects.get(
                key=token,
                company__in=user_companies,
                is_active=True
            )
            
            logger.info(f"✅ User {request.user.username} switching to company {company_token.company.business_name} via token")
            
            return JsonResponse({
                'success': True,
                'company_id': company_token.company.id,
                'company_name': company_token.company.business_name,
                'token': company_token.key,
                'redirect_url': f'/dashboard/?token={token}',
                'security_validation': {
                    'token_validated': True,
                    'user_access_confirmed': True
                }
            })
            
        except CompanyAPIToken.DoesNotExist:
            logger.warning(f"🚫 User {request.user.username} tried invalid token {token[:20]}...")
            return JsonResponse({'error': 'Invalid token or no permissions'}, status=403)
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"❌ Error en switch_company_token_ajax: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@login_required
@audit_html_action('API_COMPANY_INVOICES_TOKEN')
@require_company_access_html_token
def company_invoices_api_token(request):
    """
    🔒 API SEGURA para obtener facturas de empresa por TOKEN (AJAX)
    
    GET /dashboard/api/invoices/?token=vsr_ABC123...
    """
    # La empresa ya está validada por el decorador CON TOKEN
    company = request.validated_company
    company_token = request.validated_token
    
    try:
        from apps.invoicing.models import Invoice
        INVOICES_AVAILABLE = True
    except ImportError:
        INVOICES_AVAILABLE = False
    
    if INVOICES_AVAILABLE:
        # FILTRAR SOLO FACTURAS DE LA EMPRESA VALIDADA POR TOKEN
        invoices = Invoice.objects.filter(company=company).order_by('-created_at')
        
        invoices_data = []
        for invoice in invoices[:50]:  # Limitar para performance
            invoices_data.append({
                'id': invoice.id,
                'invoice_number': getattr(invoice, 'invoice_number', ''),
                'total_amount': float(invoice.total_amount or 0),
                'status': invoice.status,
                'status_display': invoice.get_status_display() if hasattr(invoice, 'get_status_display') else invoice.status,
                'created_at': invoice.created_at.strftime('%d/%m/%Y %H:%M'),
                'client_name': getattr(invoice, 'client_name', ''),
            })
        
        return JsonResponse({
            'success': True,
            'company_name': getattr(company, 'business_name', company.trade_name),
            'company_token': company_token.key[:20] + '...',
            'invoices': invoices_data,
            'total_count': invoices.count(),
            'security_validation': {
                'validated_by_token': True,
                'token_validated': True,
                'user_access_confirmed': True
            }
        })
    
    else:
        return JsonResponse({
            'success': False,
            'error': 'El módulo de facturación no está disponible',
            'company_name': getattr(company, 'business_name', company.trade_name),
            'company_token': company_token.key[:20] + '...',
            'invoices': [],
            'total_count': 0,
            'security_validation': {
                'validated_by_token': True,
                'token_validated': True,
                'user_access_confirmed': True
            }
        })


@login_required
@audit_html_action('API_COMPANY_INVOICES_LEGACY')
@require_company_access_html
def company_invoices_api(request, company_id):
    """
    🚨 LEGACY: API para obtener facturas por company_id (MANTENIDO POR COMPATIBILIDAD)
    """
    # La empresa ya está validada por el decorador original
    company = request.validated_company
    
    try:
        from apps.invoicing.models import Invoice
        INVOICES_AVAILABLE = True
    except ImportError:
        INVOICES_AVAILABLE = False
    
    if INVOICES_AVAILABLE:
        invoices = Invoice.objects.filter(company=company).order_by('-created_at')
        
        invoices_data = []
        for invoice in invoices[:50]:
            invoices_data.append({
                'id': invoice.id,
                'invoice_number': getattr(invoice, 'invoice_number', ''),
                'total_amount': float(invoice.total_amount or 0),
                'status': invoice.status,
                'status_display': invoice.get_status_display() if hasattr(invoice, 'get_status_display') else invoice.status,
                'created_at': invoice.created_at.strftime('%d/%m/%Y %H:%M'),
                'client_name': getattr(invoice, 'client_name', ''),
            })
        
        return JsonResponse({
            'success': True,
            'company_name': getattr(company, 'business_name', company.trade_name),
            'invoices': invoices_data,
            'total_count': invoices.count(),
            'warning': 'DEPRECATED: Use token-based API instead',
            'security_validation': {
                'validated_by_decorator': True,
                'user_access_confirmed': True,
                'legacy_api': True
            }
        })
    
    return JsonResponse({
        'success': False,
        'error': 'El módulo de facturación no está disponible',
        'warning': 'DEPRECATED: Use token-based API instead'
    })


@login_required
@audit_html_action('VIEW_INVOICE_DETAIL')
def invoice_detail_view(request, invoice_id):
    """
    🔒 VISTA SEGURA de detalle de documento electrónico / factura
    """
    from apps.sri_integration.models import ElectronicDocument
    # CompanyAPIToken ya está importado globalmente desde apps.companies.models
    
    # Obtener empresas del usuario
    user_companies = get_user_companies_secure(request.user)
    
    if not user_companies.exists():
        logger.warning(f"❌ User {request.user.username} has no companies for document access")
        from django.http import Http404
        raise Http404("No tienes empresas asociadas")
    
    document = None
    company = None
    
    # 1. Intentar obtener de sri_integration (ElectronicDocument)
    try:
        document = ElectronicDocument.objects.select_related('company').get(
            id=invoice_id,
            company__in=user_companies
        )
        company = document.company
        logger.info(f"✅ User {request.user.username} accessing ElectronicDocument {invoice_id}")
    except ElectronicDocument.DoesNotExist:
        # 2. Intentar obtener de invoicing (Invoice) como fallback
        try:
            from apps.invoicing.models import Invoice
            document = Invoice.objects.select_related('company').get(
                id=invoice_id,
                company__in=user_companies
            )
            company = document.company
            logger.info(f"✅ User {request.user.username} accessing Invoice {invoice_id}")
        except (ImportError, Exception):
            # Si no existe cualquiera de los dos, error
            logger.warning(f"❌ Document {invoice_id} not found for user {request.user.username}")
            from django.http import Http404
            raise Http404("Documento no encontrado o sin permisos")
    
    # Obtener token de la empresa para navegación
    try:
        company_token = CompanyAPIToken.objects.get(
            company=company,
            is_active=True
        )
        dashboard_token_url = f"/dashboard/?token={company_token.key}"
    except CompanyAPIToken.DoesNotExist:
        dashboard_token_url = "/dashboard/"
    
    context = {
        'document': document,
        'company': company,
        'dashboard_token_url': dashboard_token_url,
        'is_admin': request.user.is_staff or request.user.is_superuser,
        'security_validation': {
            'validated_by_query_filter': True,
            'user_access_confirmed': True,
            'token_url_generated': True,
        }
    }
    
    return render(request, 'dashboard/invoice_detail.html', context)


@login_required
@audit_html_action('API_DASHBOARD_STATS')
def dashboard_stats_api(request):
    """
    🔒 API SEGURA para estadísticas del dashboard
    """
    # Obtener empresas del usuario de forma SEGURA
    user_companies = get_user_companies_secure(request.user)
    
    if not user_companies.exists():
        return JsonResponse({
            'error': 'No accessible companies',
            'security_validation': {
                'user_access_confirmed': False,
                'companies_count': 0
            }
        })
    
    try:
        from apps.invoicing.models import Invoice
        INVOICES_AVAILABLE = True
    except ImportError:
        INVOICES_AVAILABLE = False
    
    if INVOICES_AVAILABLE:
        # ESTADÍSTICAS SOLO DE EMPRESAS DEL USUARIO
        last_30_days = timezone.now() - timedelta(days=30)
        invoices_last_30 = Invoice.objects.filter(
            company__in=user_companies,
            created_at__gte=last_30_days
        )
        
        # Facturas por día (últimos 7 días)
        daily_stats = []
        for i in range(7):
            date = timezone.now().date() - timedelta(days=i)
            count = invoices_last_30.filter(created_at__date=date).count()
            daily_stats.append({
                'date': date.strftime('%d/%m'),
                'count': count
            })
        
        # Facturas por estado
        status_distribution = invoices_last_30.values('status').annotate(
            count=Count('id')
        )
        
        # Facturas por empresa (solo empresas del usuario) - CON TOKENS
        company_stats = []
        for company in user_companies:
            company_invoices = invoices_last_30.filter(company=company)
            if company_invoices.exists():
                try:
                    company_token = CompanyAPIToken.objects.get(
                        company=company,
                        is_active=True
                    )
                    token_display = company_token.key[:10] + '...'
                except CompanyAPIToken.DoesNotExist:
                    token_display = 'No token'
                
                company_stats.append({
                    'company_name': company.trade_name or company.business_name,
                    'token_display': token_display,
                    'count': company_invoices.count(),
                    'total_amount': company_invoices.aggregate(
                        total=Sum('total_amount')
                    )['total'] or 0
                })
        
        # Ordenar por cantidad de facturas
        company_stats = sorted(company_stats, key=lambda x: x['count'], reverse=True)[:5]
        
        return JsonResponse({
            'daily_stats': list(reversed(daily_stats)),
            'status_distribution': list(status_distribution),
            'company_stats': company_stats,
            'total_last_30': invoices_last_30.count(),
            'security_validation': {
                'filtered_by_user_companies': True,
                'companies_count': user_companies.count(),
                'user': request.user.username,
                'token_system_enabled': True,
            }
        })
        
    else:
        return JsonResponse({
            'daily_stats': [],
            'status_distribution': [],
            'company_stats': [],
            'total_last_30': 0,
            'error': 'Módulo de facturación no disponible',
            'security_validation': {
                'filtered_by_user_companies': True,
                'companies_count': user_companies.count(),
                'user': request.user.username,
                'token_system_enabled': True,
            }
        })


@login_required
@audit_html_action('VIEW_COMPANY_TOKENS')
def company_tokens_view(request):
    """
    🔑 NUEVA: Vista para gestionar los tokens de las empresas del usuario
    
    GET /dashboard/tokens/
    """
    user = request.user
    user_companies = get_user_companies_secure(user)
    
    companies_with_tokens = []
    
    for company in user_companies:
        try:
            # Obtener todos los tokens de esta empresa
            company_tokens = CompanyAPIToken.objects.filter(
                company=company,
                is_active=True
            ).order_by('-created_at')
            
            # Si no tiene tokens, crear uno automáticamente
            if not company_tokens.exists():
                auto_token = CompanyAPIToken.objects.create(
                    company=company,
                    name=f'Auto-generated token for {company.business_name}',
                    is_active=True
                )
                company_tokens = [auto_token]
            
            companies_with_tokens.append({
                'company': company,
                'tokens': company_tokens,
                'primary_token': company_tokens.first(),
                'dashboard_url': f"/dashboard/?token={company_tokens.first().key}",
                'api_test_url': f"/api/companies/",
                'token_display': company_tokens.first().key[:20] + '...',
            })
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo tokens para {company.business_name}: {e}")
    
    context = {
        'user': user,
        'companies_with_tokens': companies_with_tokens,
        'page_title': 'Gestión de Tokens de Empresa',
        'security_validation': {
            'user_access_confirmed': True,
            'token_system_enabled': True,
        }
    }
    
    return render(request, 'dashboard/company_tokens.html', context)


@login_required  
@audit_html_action('CREATE_COMPANY_TOKEN')
@require_POST
def create_company_token(request, company_id):
    """
    🔑 API para crear nuevo token para una empresa
    
    POST /dashboard/companies/{company_id}/tokens/create/
    """
    company = get_object_or_404(Company, id=company_id)
    
    # Verificar permisos
    user_companies = get_user_companies_secure(request.user)
    if not user_companies.filter(id=company.id).exists() and not request.user.is_staff:
        return JsonResponse({
            'success': False,
            'error': 'No tienes permisos para crear tokens de esta empresa'
        }, status=403)
    
    try:
        # Obtener nombre del token del request
        token_name = request.POST.get('name', f'Token para {company.business_name}')
        
        # Crear nuevo token
        new_token = CompanyAPIToken.objects.create(
            company=company,
            name=token_name,
            is_active=True
        )
        
        logger.info(f"✅ New token created for company {company.business_name} by {request.user.username}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Token creado exitosamente',
                'token': {
                    'id': new_token.id,
                    'key': new_token.key,
                    'name': new_token.name,
                    'created_at': new_token.created_at.strftime('%d/%m/%Y %H:%M'),
                    'is_active': new_token.is_active,
                    'dashboard_url': f"/dashboard/?token={new_token.key}",
                    'token_display': new_token.key[:20] + '...'
                }
            })
        
        messages.success(request, f'Token creado exitosamente para {company.business_name}')
        return redirect('core:dashboard')
        
    except Exception as e:
        logger.error(f"Error creating token for company {company_id}: {str(e)}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f'Error al crear token: {str(e)}'
            }, status=500)
        
        messages.error(request, f'Error al crear token: {str(e)}')
        return redirect('core:dashboard')


@login_required
@audit_html_action('DEACTIVATE_COMPANY_TOKEN')
@require_POST
def deactivate_company_token(request, token_id):
    """
    🔑 API para desactivar un token específico
    
    POST /dashboard/tokens/{token_id}/deactivate/
    """
    token = get_object_or_404(CompanyAPIToken, id=token_id)
    
    # Verificar permisos
    user_companies = get_user_companies_secure(request.user)
    if not user_companies.filter(id=token.company.id).exists() and not request.user.is_staff:
        return JsonResponse({
            'success': False,
            'error': 'No tienes permisos para gestionar tokens de esta empresa'
        }, status=403)
    
    try:
        # Verificar que no sea el único token activo
        active_tokens = CompanyAPIToken.objects.filter(
            company=token.company,
            is_active=True
        ).count()
        
        if active_tokens == 1:
            return JsonResponse({
                'success': False,
                'error': 'No puedes desactivar el único token activo. Crea otro token primero.'
            }, status=400)
        
        # Desactivar token
        token.is_active = False
        token.save()
        
        logger.info(f"✅ Token {token.key[:20]}... deactivated by {request.user.username}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Token desactivado exitosamente'
            })
        
        messages.success(request, 'Token desactivado exitosamente')
        return redirect('core:dashboard')
        
    except Exception as e:
        logger.error(f"Error deactivating token {token_id}: {str(e)}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f'Error al desactivar token: {str(e)}'
            }, status=500)
        
        messages.error(request, f'Error al desactivar token: {str(e)}')
        return redirect('core:dashboard')


# ========== VISTAS DE UTILIDAD ==========

@login_required
def test_api_connection(request):
    """
    🔧 Vista de prueba para validar conexión API con tokens
    """
    user_companies = get_user_companies_secure(request.user)
    
    test_results = []
    
    for company in user_companies:
        try:
            # Obtener token de la empresa
            company_token = CompanyAPIToken.objects.filter(
                company=company,
                is_active=True
            ).first()
            
            if company_token:
                test_result = {
                    'company_name': company.business_name,
                    'company_id': company.id,
                    'token_available': True,
                    'token_display': company_token.key[:20] + '...',
                    'api_url': f"/api/companies/?token={company_token.key}",
                    'dashboard_url': f"/dashboard/?token={company_token.key}",
                    'status': 'OK'
                }
            else:
                test_result = {
                    'company_name': company.business_name,
                    'company_id': company.id,
                    'token_available': False,
                    'token_display': 'N/A',
                    'api_url': 'N/A',
                    'dashboard_url': 'N/A',
                    'status': 'ERROR: No token available'
                }
            
            test_results.append(test_result)
            
        except Exception as e:
            test_results.append({
                'company_name': company.business_name,
                'company_id': company.id,
                'token_available': False,
                'token_display': 'ERROR',
                'api_url': 'N/A',
                'dashboard_url': 'N/A',
                'status': f'ERROR: {str(e)}'
            })
    
    context = {
        'test_results': test_results,
        'user': request.user,
        'total_companies': user_companies.count(),
        'page_title': 'Test de Conexión API'
    }
    
    return render(request, 'dashboard/api_test.html', context)


@login_required
def health_check(request):
    """
    🏥 Health check para verificar el estado del sistema
    """
    try:
        # Verificar conexión a base de datos
        db_status = "OK"
        try:
            User.objects.count()
        except Exception as e:
            db_status = f"ERROR: {str(e)}"
        
        # Verificar modelos principales
        models_status = {}
        try:
            models_status['companies'] = Company.objects.count()
            models_status['tokens'] = CompanyAPIToken.objects.count()
            models_status['certificates'] = DigitalCertificate.objects.count()
        except Exception as e:
            models_status['error'] = str(e)
        
        # Verificar funciones críticas
        functions_status = {}
        try:
            test_companies = get_user_companies_secure(request.user)
            functions_status['get_user_companies'] = f"OK - {test_companies.count()} companies"
        except Exception as e:
            functions_status['get_user_companies'] = f"ERROR: {str(e)}"
        
        health_data = {
            'status': 'OK' if db_status == 'OK' else 'ERROR',
            'timestamp': timezone.now().isoformat(),
            'user': request.user.username,
            'database': db_status,
            'models': models_status,
            'functions': functions_status,
            'version': '2.0.0-tokens'
        }
        
        return JsonResponse(health_data)
        
    except Exception as e:
        return JsonResponse({
            'status': 'ERROR',
            'timestamp': timezone.now().isoformat(),
            'error': str(e)
        }, status=500)


# ========== MANEJADORES DE ERRORES ==========

def handler404(request, exception):
    """
    Manejador personalizado para errores 404
    """
    logger.warning(f"404 Error: {request.path} requested by {getattr(request.user, 'username', 'anonymous')}")
    
    context = {
        'error_code': '404',
        'error_message': 'Página no encontrada',
        'error_description': 'La página que buscas no existe o ha sido movida',
        'user': request.user if request.user.is_authenticated else None,
    }
    
    return render(request, 'errors/404.html', context, status=404)


def handler500(request):
    """
    Manejador personalizado para errores 500
    """
    logger.error(f"500 Error: {request.path} requested by {getattr(request.user, 'username', 'anonymous')}")
    
    context = {
        'error_code': '500',
        'error_message': 'Error interno del servidor',
        'error_description': 'Ha ocurrido un error interno. El equipo técnico ha sido notificado.',
        'user': request.user if request.user.is_authenticated else None,
    }
    
    return render(request, 'errors/500.html', context, status=500)
def prepare_documents_for_template(all_documents):
    """
    Prepara los documentos para el template asegurando que tengan todos los campos necesarios
    """
    prepared_documents = []
    
    for doc in all_documents:
        try:
            # Determinar si es un objeto o diccionario
            if hasattr(doc, '__dict__'):
                # Es un objeto del modelo
                doc_data = {
                    'id': getattr(doc, 'id', 0),
                    'document_type': getattr(doc, 'document_type', 'UNKNOWN'),
                    'mapped_type': _get_mapped_type(getattr(doc, 'document_type', 'UNKNOWN')),
                    'document_number': getattr(doc, 'document_number', str(getattr(doc, 'id', 'N/A'))),
                    'client_name': _get_client_name(doc),
                    'total_amount': float(getattr(doc, 'total_amount', 0) or 0),
                    'status': getattr(doc, 'status', 'UNKNOWN'),
                    'created_at': getattr(doc, 'created_at', None),
                }
            else:
                # Es un diccionario
                doc_data = {
                    'id': doc.get('id', 0),
                    'document_type': doc.get('document_type', 'UNKNOWN'),
                    'mapped_type': _get_mapped_type(doc.get('document_type', 'UNKNOWN')),
                    'document_number': doc.get('document_number', str(doc.get('id', 'N/A'))),
                    'client_name': doc.get('client_name', 'Cliente'),
                    'total_amount': float(doc.get('total_amount', 0) or 0),
                    'status': doc.get('status', 'UNKNOWN'),
                    'created_at': doc.get('created_at', None),
                }
            
            # Crear objeto tipo documento para compatibilidad con template
            document_obj = type('Document', (), doc_data)()
            prepared_documents.append(document_obj)
            
        except Exception as e:
            logger.error(f"Error preparando documento para template: {e}")
            # Crear documento por defecto en caso de error
            fallback_doc = type('Document', (), {
                'id': getattr(doc, 'id', 0) if hasattr(doc, 'id') else doc.get('id', 0),
                'document_type': 'UNKNOWN',
                'mapped_type': 'unknown',
                'document_number': 'ERROR',
                'client_name': 'Error',
                'total_amount': 0.0,
                'status': 'ERROR',
                'created_at': None,
            })()
            prepared_documents.append(fallback_doc)
    
    return prepared_documents


def _get_mapped_type(document_type):
    """Mapea el tipo de documento al formato esperado por el template"""
    type_mapping = {
        'INVOICE': 'factura',
        'RETENTION': 'retencion', 
        'PURCHASE_SETTLEMENT': 'liquidacion',
        'CREDIT_NOTE': 'nota_credito',
        'DEBIT_NOTE': 'nota_debito',
        'REMISSION_GUIDE': 'guia_remision',
    }
    return type_mapping.get(document_type, 'documento')


def _get_client_name(doc):
    """Obtiene el nombre del cliente según el tipo de documento"""
    # Lista de posibles campos de nombre de cliente
    client_fields = [
        'customer_name', 'client_name', 'supplier_name', 
        'customer', 'client', 'supplier'
    ]
    
    for field in client_fields:
        value = getattr(doc, field, None)
        if value:
            return value
    
    return 'Cliente'
# Al final de apps/core/views.py agregar:

def public_landing_view(request):
    """
    Vista PÚBLICA para la landing page - NO requiere autenticación
    """
    import json
    from apps.core.branding import get_system_name

    try:
        from apps.billing.models import Plan

        app_name = get_system_name()
        
        # Obtener planes activos NORMALES (consulta pública) - Excluye ilimitados
        all_plans = Plan.objects.filter(is_active=True, is_unlimited=False).order_by('sort_order', 'price')
        
        # Serializar para JavaScript igual que el dashboard
        plans_data = []
        for plan in all_plans:
            plans_data.append({
                'id': plan.id,
                'name': plan.name,
                'description': plan.description or f'Plan {plan.name}',
                'invoice_limit': plan.invoice_limit,
                'price': float(plan.price),
                'is_featured': plan.is_featured,
                'is_unlimited': plan.is_unlimited,
            })
        
        context = {
            'plans_data': json.dumps(plans_data),
            'total_plans': len(plans_data),
            'page_title': f'{app_name} - Sistema de Facturación Electrónica SRI Ecuador',
            'app_name': app_name,
        }
        
    except Exception as e:
        # Si hay error, mostrar página sin planes
        app_name = get_system_name()
        context = {
            'plans_data': json.dumps([]),
            'total_plans': 0,
            'page_title': f'{app_name} - Sistema de Facturación Electrónica SRI Ecuador',
            'app_name': app_name,
        }
    
    return render(request, 'landing/index.html', context)
    

def premium_plans_view(request):
    """
    Vista PÚBLICA "oculta" para planes premium ilimitados
    """
    import json
    from apps.core.branding import get_system_name
    from apps.billing.models import Plan

    app_name = get_system_name()
    
    try:
        # Obtener SOLO planes activos ILIMITADOS
        premium_plans = Plan.objects.filter(is_active=True, is_unlimited=True).order_by('sort_order', 'price')
        
        plans_data = []
        for plan in premium_plans:
            plans_data.append({
                'id': plan.id,
                'name': plan.name,
                'description': plan.description or f'Plan {plan.name}',
                'invoice_limit': plan.invoice_limit,
                'price': float(plan.price),
                'is_featured': plan.is_featured,
                'is_unlimited': plan.is_unlimited,
            })
        
        context = {
            'plans_data': json.dumps(plans_data),
            'total_plans': len(plans_data),
            'page_title': f'Planes Premium - {app_name}',
            'app_name': app_name,
        }
        
    except Exception:
        context = {
            'plans_data': json.dumps([]),
            'total_plans': 0,
            'page_title': f'Planes Premium - {app_name}',
            'app_name': app_name,
        }
    
    return render(request, 'landing/premium_plans.html', context)


# ==========================================
# NUEVAS VISTAS PARA DASHBOARD DE CLIENTE (MODAL Y ENVIO MASIVO)
# ==========================================

@login_required
def invoice_detail_modal_api(request, invoice_id):
    """
    API específica para el modal de detalle en el dashboard de cliente.
    Retorna JSON con todos los detalles requeridos del documento.
    """
    from apps.sri_integration.models import ElectronicDocument
    
    # Obtener empresas del usuario de forma SEGURA
    user_companies = get_user_companies_secure(request.user)
    
    try:
        document = ElectronicDocument.objects.select_related('company').get(
            id=invoice_id,
            company__in=user_companies
        )
    except ElectronicDocument.DoesNotExist:
        # Intentar obtener de invoicing (Invoice) como fallback
        try:
            from apps.invoicing.models import Invoice
            invoice = Invoice.objects.select_related('company').get(
                id=invoice_id,
                company__in=user_companies
            )
            # Mapear datos básicos si es Invoice legacy
            data = {
                'success': True,
                'document': {
                    'id': invoice.id,
                    'number': getattr(invoice, 'invoice_number', str(invoice.id)),
                    'type': 'Factura',
                    'status': invoice.status,
                    'status_display': invoice.get_status_display() if hasattr(invoice, 'get_status_display') else invoice.status,
                    'date': invoice.created_at.strftime('%d/%m/%Y'),
                    'hour': invoice.created_at.strftime('%H:%M'),
                    'total': float(invoice.total_amount or 0),
                    'client_name': getattr(invoice, 'client_name', 'N/A'),
                    'client_ruc': getattr(invoice, 'client_identification', 'N/A'),
                    'can_resend': False,
                    'legacy': True
                },
                'company': {
                    'name': invoice.company.business_name,
                    'ruc': invoice.company.ruc,
                }
            }
            return JsonResponse(data)
        except:
            return JsonResponse({'error': 'Documento no encontrado o sin permisos'}, status=404)
        
    company = document.company
    
    # Obtener los últimos mensajes de respuesta del SRI
    sri_messages = []
    if document.sri_response:
        if isinstance(document.sri_response, dict):
            sri_messages = document.sri_response.get('mensajes', [])
        elif isinstance(document.sri_response, str):
            try:
                res_dict = json.loads(document.sri_response)
                sri_messages = res_dict.get('mensajes', [])
            except:
                pass
                
        if not isinstance(sri_messages, list):
            sri_messages = [sri_messages]

    data = {
        'success': True,
        'document': {
            'id': document.id,
            'number': document.document_number,
            'type': document.get_document_type_display(),
            'status': document.status,
            'status_display': document.get_status_display(),
            'date': document.created_at.strftime('%d/%m/%Y'),
            'hour': document.created_at.strftime('%H:%M'),
            'access_key': document.access_key,
            'total': float(document.total_amount or 0),
            'sri_authorization_date': document.sri_authorization_date.strftime('%d/%m/%Y %H:%M') if document.sri_authorization_date else None,
            'sri_messages': sri_messages,
            'can_resend': document.status not in ['AUTHORIZED', 'SENT'],
            'client_name': document.customer_name,
            'client_ruc': document.customer_identification,
        },
        'company': {
            'name': company.business_name or company.trade_name,
            'ruc': company.ruc,
            'address': company.address,
        }
    }
    
    return JsonResponse(data)

@login_required
def bulk_email_list_api(request):
    """
    Retorna lista de documentos autorizados para envío masivo.
    """
    from apps.sri_integration.models import ElectronicDocument
    
    token = request.GET.get('token')
    if not token:
        return JsonResponse({'error': 'Token de empresa requerido'}, status=400)
        
    user_companies = get_user_companies_secure(request.user)
    try:
        company_token = CompanyAPIToken.objects.get(key=token, company__in=user_companies, is_active=True)
        company = company_token.company
    except CompanyAPIToken.DoesNotExist:
        return JsonResponse({'error': 'Empresa no encontrada o sin permisos'}, status=403)
        
    # Filtrar documentos autorizados
    documents = ElectronicDocument.objects.filter(
        company=company,
        status='AUTHORIZED'
    ).order_by('-created_at')[:100]
    
    docs_data = []
    for doc in documents:
        docs_data.append({
            'id': doc.id,
            'number': doc.document_number,
            'client': doc.customer_name,
            'email': doc.customer_email,
            'date': doc.created_at.strftime('%d/%m/%Y'),
            'total': float(doc.total_amount or 0),
            'email_sent': getattr(doc, 'email_sent', False),
            'can_send': bool(doc.customer_email)
        })
        
    return JsonResponse({
        'success': True,
        'documents': docs_data,
        'company_name': company.business_name
    })

@login_required
@require_POST
def bulk_email_send_api(request):
    """
    Procesa el envío masivo de emails.
    """
    from apps.sri_integration.models import ElectronicDocument
    from apps.sri_integration.services.email_service import EmailService
    
    try:
        data = json.loads(request.body)
        document_ids = data.get('document_ids', [])
        
        if not document_ids:
            return JsonResponse({'error': 'No se seleccionaron documentos'}, status=400)
            
        user_companies = get_user_companies_secure(request.user)
        documents = ElectronicDocument.objects.filter(
            id__in=document_ids,
            company__in=user_companies,
            status='AUTHORIZED'
        )
        
        results = {
            'success_count': 0,
            'failed_count': 0,
            'details': []
        }
        
        # Agrupar por empresa
        companies_docs = {}
        for doc in documents:
            if doc.company_id not in companies_docs:
                companies_docs[doc.company_id] = []
            companies_docs[doc.company_id].append(doc)
            
        for company_id, docs in companies_docs.items():
            company = docs[0].company
            email_service = EmailService(company)
            
            for doc in docs:
                if not doc.customer_email:
                    results['failed_count'] += 1
                    results['details'].append({'id': doc.id, 'success': False, 'error': 'Sin email configurado'})
                    continue
                    
                success, message = email_service.send_document_email(doc)
                if success:
                    results['success_count'] += 1
                    results['details'].append({'id': doc.id, 'success': True})
                else:
                    results['failed_count'] += 1
                    results['details'].append({'id': doc.id, 'success': False, 'error': message})
                    
        return JsonResponse({
            'success': True,
            'message': f"Proceso completado. Enviados: {results['success_count']}, Fallidos: {results['failed_count']}",
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Error en bulk_email_send_api: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
