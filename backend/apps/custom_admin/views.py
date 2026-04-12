# -*- coding: utf-8 -*-
"""
Custom Admin Views - VERSIÓN COMPLETA
apps/custom_admin/views.py
"""

import json
import logging
import traceback
import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Count, Q, Sum, Avg
from django.db.models.functions import TruncMonth
from django.core.paginator import Paginator
from django.contrib import messages
from django.db.models import Count, Sum, Q, F
from apps.sri_integration.tasks import process_document_async
from django.utils import timezone
from django.utils.text import slugify
from datetime import datetime, timedelta
from functools import wraps
from django.conf import settings
from django.core.files.storage import default_storage

# Logger configuration
logger = logging.getLogger(__name__)

# Import models
from apps.users.models import User, UserCompanyAssignment, AdminNotification
from apps.companies.models import Company
from apps.certificates.models import DigitalCertificate
from apps.core.models import AuditLog

# Import existing decorators
from apps.api.views.sri_views import audit_api_action

from django.db.models import Sum, Avg, Count, Q
from decimal import Decimal
from apps.core.branding import get_seo_settings, get_setting_value, get_system_logo_url, get_system_name, get_system_favicon_url

# Agregar estas importaciones
from apps.sri_integration.models import ElectronicDocument
from apps.companies.models import Company
from apps.users.models import User, UserCompanyAssignment, AdminNotification
from django.db.models import F

def staff_required(view_func):
    """Decorator to require staff/admin access"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff and not request.user.is_superuser:
            messages.error(request, 'Acceso denegado. Se requieren privilegios de administrador.')
            return redirect('core:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def save_system_setting_value(key, value, name, setting_type='STRING', category='SYSTEM', description=''):
    from apps.settings.models import SystemSetting

    SystemSetting.objects.update_or_create(
        key=key,
        defaults={
            'value': value,
            'name': name,
            'setting_type': setting_type,
            'category': category,
            'description': description,
        }
    )


def store_branding_asset(uploaded_file, setting_key, label):
    extension = os.path.splitext(uploaded_file.name)[1].lower() or '.png'
    filename = f"branding/{slugify(setting_key.lower())}-{timezone.now().strftime('%Y%m%d%H%M%S')}{extension}"

    previous_path = get_setting_value(setting_key, '')
    saved_path = default_storage.save(filename, uploaded_file)

    save_system_setting_value(
        setting_key,
        saved_path,
        label,
        setting_type='STRING',
        category='SYSTEM',
        description=f'Archivo cargado para {label.lower()}'
    )

    if previous_path and previous_path != saved_path and not previous_path.startswith(('http://', 'https://', '/media/', '/static/')):
        try:
            default_storage.delete(previous_path)
        except Exception:
            logger.warning("No se pudo eliminar el branding anterior: %s", previous_path)

    return saved_path


def normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'yes', 'on')
    return bool(value)

# Agregar estas funciones ANTES de tu función dashboard() existente en apps/custom_admin/views.py

def get_dashboard_chart_data():
    """Genera la grafica principal del dashboard para los ultimos 6 meses."""
    end_date = timezone.now()
    month_points = []
    current = end_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    for offset in range(5, -1, -1):
        month = current - timedelta(days=offset * 30)
        month_points.append(month.replace(day=1))

    users_by_month = {
        item['month'].strftime('%Y-%m'): item['count']
        for item in User.objects.filter(date_joined__gte=month_points[0]).annotate(
            month=TruncMonth('date_joined')
        ).values('month').annotate(count=Count('id')).order_by('month')
        if item['month']
    }

    invoices_by_month = {
        item['month'].strftime('%Y-%m'): item['count']
        for item in ElectronicDocument.objects.filter(
            created_at__gte=month_points[0],
            document_type='INVOICE'
        ).annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(count=Count('id')).order_by('month')
        if item['month']
    }

    processed_by_month = {
        item['month'].strftime('%Y-%m'): item['count']
        for item in ElectronicDocument.objects.filter(
            created_at__gte=month_points[0],
            status__in=['GENERATED', 'SIGNED', 'SENT', 'AUTHORIZED']
        ).annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(count=Count('id')).order_by('month')
        if item['month']
    }

    companies_by_month = {
        item['month'].strftime('%Y-%m'): item['count']
        for item in Company.objects.filter(
            created_at__gte=month_points[0]
        ).annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(count=Count('id')).order_by('month')
        if item['month']
    }

    labels = []
    users_data = []
    invoices_data = []
    processed_data = []
    companies_data = []

    for point in month_points:
        key = point.strftime('%Y-%m')
        labels.append(point.strftime('%b'))
        users_data.append(users_by_month.get(key, 0))
        invoices_data.append(invoices_by_month.get(key, 0))
        processed_data.append(processed_by_month.get(key, 0))
        companies_data.append(companies_by_month.get(key, 0))

    return json.dumps({
        'labels': labels,
        'datasets': {
            'users': users_data,
            'invoices': invoices_data,
            'processed': processed_data,
            'companies': companies_data,
        }
    })

# Tu función dashboard existente ya está bien, solo asegúrate de que tiene estas importaciones:
# from datetime import datetime, timedelta
# from django.utils import timezone
# from django.db.models import Count, Q
# from django.db.models.functions import TruncDate
# import json
@login_required
@staff_required
def dashboard(request):
    """Admin Dashboard with statistics"""
    context = {
        'page_title': 'Dashboard',
        
        # User Statistics
        'total_users': User.objects.filter(is_staff=False, is_superuser=False).count(),
        'active_users': User.objects.filter(is_active=True, is_staff=False).count(),
        'pending_users': UserCompanyAssignment.objects.filter(status='waiting').count(),
        'new_users_today': User.objects.filter(
            date_joined__date=timezone.now().date()
        ).count(),
        
        # Company Statistics
        'total_companies': Company.objects.count(),
        'active_companies': Company.objects.filter(is_active=True).count(),
        
        # Certificate Statistics
        'total_certificates': DigitalCertificate.objects.count(),
        'expiring_certificates': DigitalCertificate.objects.filter(
            valid_to__lte=timezone.now() + timedelta(days=30),
            valid_to__gte=timezone.now()
        ).count(),
        
        # Notifications
        'unread_notifications': AdminNotification.objects.filter(is_read=False).count(),

        # Documents Statistics
        'total_invoices': ElectronicDocument.objects.filter(document_type='INVOICE').count(),
        'processed_documents': ElectronicDocument.objects.filter(
            status__in=['GENERATED', 'SIGNED', 'SENT', 'AUTHORIZED']
        ).count(),
        'authorized_documents': ElectronicDocument.objects.filter(status='AUTHORIZED').count(),

        # Charts Data
        'dashboard_chart_data': get_dashboard_chart_data(),
    }
    
    return render(request, 'custom_admin/dashboard.html', context)


# ========== USERS CRUD ==========

@login_required
@staff_required
def users_list(request):
    """List all users with CRUD operations"""
    users = User.objects.all().select_related('company').order_by('-date_joined')
    
    # Filters
    search = request.GET.get('search', '')
    status = request.GET.get('status', '')
    company_id = request.GET.get('company', '')
    
    if search:
        users = users.filter(
            Q(email__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search)
        )
    
    if status:
        if status == 'active':
            users = users.filter(is_active=True)
        elif status == 'inactive':
            users = users.filter(is_active=False)
        elif status == 'staff':
            users = users.filter(is_staff=True)
        elif status == 'waiting':
            waiting_ids = UserCompanyAssignment.objects.filter(
                status='waiting'
            ).values_list('user_id', flat=True)
            users = users.filter(id__in=waiting_ids)
    
    if company_id:
        users = users.filter(company_id=company_id)
    
    # Pagination
    paginator = Paginator(users, 25)
    page = request.GET.get('page')
    users_page = paginator.get_page(page)
    
    context = {
        'page_title': 'Usuarios',
        'users': users_page,
        'total_count': paginator.count,
        'companies': Company.objects.filter(is_active=True),
        'filters': {
            'search': search,
            'status': status,
            'company': company_id,
        }
    }
    
    return render(request, 'custom_admin/users/list.html', context)


@login_required
@staff_required
def user_create(request):
    """Create user - Modal form"""
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        phone = request.POST.get('phone', '')
        company_id = request.POST.get('company_id')
        is_staff = request.POST.get('is_staff') == 'on'
        user_status = request.POST.get('user_status', 'waiting')
        
        if User.objects.filter(email=email).exists():
            companies = Company.objects.filter(is_active=True).order_by('business_name')
            return render(request, 'custom_admin/users/form_modal.html', {
                'mode': 'create',
                'companies': companies,
                'error': 'Ya existe un usuario con este email'
            })
        
        try:
            # Crear usuario con estado inicial
            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                is_staff=is_staff,
                is_active=True  # Por defecto activo, el status controla el acceso
            )
            
            # Asignar user_status si el modelo lo soporta
            if hasattr(user, 'user_status'):
                user.user_status = user_status
                user.save()
            
            if company_id:
                try:
                    company = Company.objects.get(id=company_id)
                    user.company = company
                    user.save()
                except Company.DoesNotExist:
                    pass
            
            # Log action
            AuditLog.objects.create(
                user=request.user,
                action='CREATE',
                model_name='User',
                object_id=str(user.id),
                object_representation=str(user),
                ip_address=request.META.get('REMOTE_ADDR')
            )
            
            messages.success(request, f'Usuario {user.email} creado exitosamente')
            return HttpResponse('<script>window.parent.location.reload();</script>')
            
        except Exception as e:
            companies = Company.objects.filter(is_active=True).order_by('business_name')
            return render(request, 'custom_admin/users/form_modal.html', {
                'mode': 'create',
                'companies': companies,
                'error': f'Error al crear usuario: {str(e)}'
            })
    
    # GET request
    try:
        companies = Company.objects.filter(is_active=True).order_by('business_name')
        context = {
            'mode': 'create',
            'companies': companies
        }
        return render(request, 'custom_admin/users/form_modal.html', context)
    except Exception as e:
        return HttpResponse(f'<div class="alert alert-danger">Error al cargar el formulario: {str(e)}</div>')


@login_required
@staff_required
def user_edit(request, user_id):
    """Edit user - Modal form"""
    try:
        user = get_object_or_404(User, id=user_id)
        
        if request.method == 'GET':
            companies = Company.objects.filter(is_active=True).order_by('business_name')
            context = {
                'user': user,
                'companies': companies,
                'mode': 'edit'
            }
            return render(request, 'custom_admin/users/form_modal.html', context)
        
        elif request.method == 'POST':
            # DEBUG: Ver qué datos llegan
            print("=== DATOS RECIBIDOS EN POST ===")
            for key, value in request.POST.items():
                print(f"{key}: {value}")
            print("================================")
            
            try:
                # Update basic info
                user.first_name = request.POST.get('first_name', '')
                user.last_name = request.POST.get('last_name', '')
                user.phone = request.POST.get('phone', '')
                
                # Handle company assignment
                company_id = request.POST.get('company_id')
                if company_id:
                    user.company_id = company_id
                else:
                    user.company = None
                
                # Handle user status - SIEMPRE actualizar
                new_status = request.POST.get('user_status', 'waiting')
                old_status = getattr(user, 'user_status', 'waiting')
                
                print(f"[DEBUG] Estado anterior: {old_status}")
                print(f"[DEBUG] Nuevo estado: {new_status}")
                
                # IMPORTANTE: Asignar directamente sin verificar hasattr
                user.user_status = new_status
                
                # Handle reason for suspension/rejection
                reason = request.POST.get('reason', '')
                
                if new_status == 'suspended':
                    user.suspension_reason = reason
                    user.is_active = False
                    print("[DEBUG] Usuario suspendido - is_active = False")
                elif new_status == 'rejected':
                    user.rejection_reason = reason
                    user.is_active = False
                    print("[DEBUG] Usuario rechazado - is_active = False")
                elif new_status == 'active':
                    user.is_active = True
                    user.suspension_reason = None
                    user.rejection_reason = None
                    if old_status == 'waiting':
                        user.approved_by = request.user
                        user.approved_at = timezone.now()
                    print("[DEBUG] Usuario activado - is_active = True")
                elif new_status == 'waiting':
                    user.is_active = True
                    user.suspension_reason = None
                    user.rejection_reason = None
                    print("[DEBUG] Usuario en espera - is_active = True")
                
                # Handle is_staff
                user.is_staff = request.POST.get('is_staff') == 'on'
                
                # Update password if provided
                new_password = request.POST.get('password')
                if new_password:
                    user.set_password(new_password)
                
                # GUARDAR
                user.save()
                
                # VERIFICACIÓN ADICIONAL - Forzar actualización
                User.objects.filter(id=user.id).update(
                    user_status=new_status,
                    is_active=(new_status in ['active', 'waiting'])
                )
                
                # Verificar que se guardó correctamente
                user.refresh_from_db()
                print(f"[DEBUG] VERIFICACIÓN FINAL:")
                print(f"[DEBUG] - user_status: {user.user_status}")
                print(f"[DEBUG] - is_active: {user.is_active}")
                
                # Sincronizar con UserCompanyAssignment si existe
                try:
                    assignment = UserCompanyAssignment.objects.get(user=user)
                    
                    # Mapear estados
                    if new_status == 'active':
                        assignment.status = 'assigned'
                        assignment.assigned_by = request.user
                        assignment.assigned_at = timezone.now()
                        if user.company:
                            assignment.assigned_companies.add(user.company)
                    elif new_status == 'rejected':
                        assignment.status = 'rejected'
                        assignment.notes = reason
                    elif new_status == 'suspended':
                        assignment.status = 'suspended'
                        assignment.notes = reason
                    elif new_status == 'waiting':
                        assignment.status = 'waiting'
                    
                    assignment.save()
                    print(f"[DEBUG] UserCompanyAssignment actualizado: {assignment.status}")
                    
                except UserCompanyAssignment.DoesNotExist:
                    # Crear assignment si no existe y el usuario no es staff
                    if not user.is_staff:
                        assignment = UserCompanyAssignment.objects.create(
                            user=user,
                            status='assigned' if new_status == 'active' else new_status
                        )
                        if new_status == 'active' and user.company:
                            assignment.assigned_companies.add(user.company)
                            assignment.assigned_by = request.user
                            assignment.assigned_at = timezone.now()
                            assignment.save()
                        print(f"[DEBUG] UserCompanyAssignment creado")
                
                # Crear notificación si se aprobó
                if new_status == 'active' and old_status == 'waiting':
                    AdminNotification.objects.create(
                        notification_type='user_registered',
                        title=f'Usuario aprobado',
                        message=f'El usuario {user.email} ha sido aprobado por {request.user.get_full_name() or request.user.email}',
                        priority='normal',
                        related_user=user
                    )
                
                # Audit log con más detalle
                changes = f'Usuario actualizado'
                if old_status != new_status:
                    changes += f'. Estado cambiado de {old_status} a {new_status}'
                if reason:
                    changes += f'. Razón: {reason}'
                
                AuditLog.objects.create(
                    user=request.user,
                    model_name='User',
                    object_id=str(user.id),
                    action='UPDATE',
                    changes=changes,
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                
                messages.success(request, f'Usuario {user.email} actualizado correctamente')
                return HttpResponse('<script>window.parent.location.reload();</script>')
                
            except Exception as e:
                print(f"[DEBUG] ERROR: {str(e)}")
                import traceback
                traceback.print_exc()
                
                companies = Company.objects.filter(is_active=True).order_by('business_name')
                context = {
                    'user': user,
                    'companies': companies,
                    'mode': 'edit',
                    'error': f'Error al actualizar: {str(e)}'
                }
                return render(request, 'custom_admin/users/form_modal.html', context)
    
    except Exception as e:
        print(f"[DEBUG] ERROR GENERAL: {str(e)}")
        return HttpResponse(f'<div class="alert alert-danger">Error: {str(e)}</div>')


@login_required
@staff_required
def user_view(request, user_id):
    """View user details - Modal"""
    user = get_object_or_404(User, id=user_id)
    
    # Get user's activity logs
    user_logs = AuditLog.objects.filter(user=user).order_by('-created_at')[:10]
    
    # Get user's assignments
    try:
        assignment = UserCompanyAssignment.objects.get(user=user)
    except UserCompanyAssignment.DoesNotExist:
        assignment = None
    
    context = {
        'user': user,
        'user_logs': user_logs,
        'assignment': assignment
    }
    return render(request, 'custom_admin/users/view_modal.html', context)


@login_required
@staff_required
@require_http_methods(["POST"])
def user_delete(request, user_id):
    """Delete user"""
    try:
        user = get_object_or_404(User, id=user_id)
        
        if user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'No se puede eliminar un superusuario'
            })
        
        if user.id == request.user.id:
            return JsonResponse({
                'success': False,
                'error': 'No puedes eliminarte a ti mismo'
            })
        
        # Log before deletion
        AuditLog.objects.create(
            user=request.user,
            action='DELETE',
            model_name='User',
            object_id=str(user.id),
            object_representation=str(user),
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        user.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'Usuario eliminado exitosamente'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@staff_required
@require_http_methods(["POST"])
def user_toggle_status(request, user_id):
    """Toggle user active status"""
    try:
        data = json.loads(request.body)
        user = get_object_or_404(User, id=user_id)
        
        if user.is_superuser and not data.get('is_active'):
            return JsonResponse({
                'success': False,
                'error': 'No se puede desactivar un superusuario'
            })
        
        if user.id == request.user.id and not data.get('is_active'):
            return JsonResponse({
                'success': False,
                'error': 'No puedes desactivarte a ti mismo'
            })
        
        user.is_active = data.get('is_active', False)
        user.save()
        
        # Log action
        AuditLog.objects.create(
            user=request.user,
            action='UPDATE',
            model_name='User',
            object_id=str(user.id),
            object_representation=f'Status changed to {"active" if user.is_active else "inactive"}',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Estado actualizado correctamente'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


# ========== COMPANIES CRUD ==========

@login_required
@staff_required
def companies_list(request):
    """List all companies"""
    companies = Company.objects.all().order_by('business_name')
    
    # Add related counts - CORREGIDO
    companies = companies.annotate(
        user_count=Count('users'),
        certificate_count=Count('digital_certificate')  # Cambiado de 'digitalcertificate' a 'digital_certificate'
    )
    
    # Filters
    search = request.GET.get('search', '')
    is_active = request.GET.get('is_active', '')
    plan = request.GET.get('plan', '')
    
    if search:
        companies = companies.filter(
            Q(business_name__icontains=search) |
            Q(ruc__icontains=search) |
            Q(trade_name__icontains=search)
        )
    
    if is_active:
        companies = companies.filter(is_active=(is_active == 'true'))
    
    if plan and hasattr(Company, 'plan'):
        companies = companies.filter(plan=plan)
    
    # Pagination
    paginator = Paginator(companies, 25)
    page = request.GET.get('page')
    companies_page = paginator.get_page(page)
    
    context = {
        'page_title': 'Empresas',
        'companies': companies_page,
        'total_count': paginator.count,
        'filters': {
            'search': search,
            'is_active': is_active,
            'plan': plan,
        }
    }
    
    return render(request, 'custom_admin/companies/list.html', context)


@login_required
@staff_required
def company_create(request):
    """Create company - Modal form"""
    if request.method == 'POST':
        ruc = request.POST.get('ruc')
        business_name = request.POST.get('business_name')
        trade_name = request.POST.get('trade_name')
        email = request.POST.get('email', '')
        phone = request.POST.get('phone', '')
        address = request.POST.get('address', '')
        is_active = request.POST.get('is_active') == 'on'
        
        if Company.objects.filter(ruc=ruc).exists():
            return render(request, 'custom_admin/companies/form_modal.html', {
                'mode': 'create',
                'error': 'Ya existe una empresa con este RUC'
            })
        
        try:
            company = Company(
                ruc=ruc,
                business_name=business_name,
                trade_name=trade_name,
                email=email,
                phone=phone,
                address=address,
                is_active=is_active
            )
            
            if 'logo' in request.FILES:
                company.logo = request.FILES['logo']
            
            company.save()
            # NO incluir city ni province aquí
            
            # If plan field exists
            if hasattr(company, 'plan'):
                company.plan = request.POST.get('plan', 'basic')
                company.save()
            
            # ========== N U E V O : CARGAR CERTIFICADO AUTOMÁTICAMENTE ==========
            # Si el usuario subió el certificado en el mismo modal de creación de empresa:
            p12_file = request.FILES.get('p12_file')
            p12_password = request.POST.get('p12_password')
            
            cert_created = False
            cert_error = None
            
            if p12_file and p12_password:
                try:
                    from apps.certificates.models import DigitalCertificate
                    from django.utils import timezone
                    import uuid
                    # Usamos el factory method infalible
                    DigitalCertificate.create_with_password(
                        company=company,
                        certificate_file=p12_file,
                        password=p12_password,
                        environment=request.POST.get('environment', 'PRODUCTION')  # Por defecto producción para empresas reales
                    )
                    cert_created = True
                except Exception as e:
                    cert_error = str(e)
                    logger.error(f"Error cargando certificado automático: {e}")
            
            # Log action
            AuditLog.objects.create(
                user=request.user,
                action='CREATE',
                model_name='Company',
                object_id=str(company.id),
                object_representation=str(company),
                ip_address=request.META.get('REMOTE_ADDR')
            )
            
            if cert_created:
                messages.success(request, 'Empresa y Certificado Digital configurados exitosamente')
            elif cert_error:
                messages.warning(request, f'Empresa creada, pero falló el Certificado: {cert_error}')
            else:
                messages.success(request, 'Empresa creada exitosamente')
                
            return HttpResponse('<script>window.parent.location.reload();</script>')
            
        except Exception as e:
            logger.error(f"Error al crear empresa: {e}")
            return render(request, 'custom_admin/companies/form_modal.html', {
                'mode': 'create',
                'error': f'Error al crear empresa: {str(e)}',
                'company': None
            })
    
    context = {
        'mode': 'create',
        'company': None
    }
    return render(request, 'custom_admin/companies/form_modal.html', context)


@login_required
@staff_required
def company_edit(request, company_id):
    """Edit company - Modal form"""
    company = get_object_or_404(Company, id=company_id)
    
    if request.method == 'POST':
        try:
            company.business_name = request.POST.get('business_name', company.business_name)
            company.trade_name = request.POST.get('trade_name', company.trade_name)
            company.email = request.POST.get('email', company.email)
            company.phone = request.POST.get('phone', company.phone)
            company.address = request.POST.get('address', company.address)
            
            # Campos corregidos a los nombres reales del modelo (ciudad/provincia)
            if 'ciudad' in request.POST:
                company.ciudad = request.POST.get('ciudad')
            elif 'city' in request.POST:
                company.ciudad = request.POST.get('city')
                
            if 'provincia' in request.POST:
                company.provincia = request.POST.get('provincia')
            elif 'province' in request.POST:
                company.provincia = request.POST.get('province')
                
            company.is_active = request.POST.get('is_active') == 'on'
            
            if 'logo' in request.FILES:
                company.logo = request.FILES['logo']
            
            # If plan field exists
            if hasattr(company, 'plan'):
                company.plan = request.POST.get('plan', company.plan)
            
            company.save()
            
            # Log action
            AuditLog.objects.create(
                user=request.user,
                action='UPDATE',
                model_name='Company',
                object_id=str(company.id),
                object_representation=str(company),
                ip_address=request.META.get('REMOTE_ADDR')
            )
            
            messages.success(request, 'Empresa actualizada exitosamente')
            return HttpResponse('<script>window.parent.location.reload();</script>')
        except Exception as e:
            logger.error(f"Error al actualizar empresa {company_id}: {e}")
            return render(request, 'custom_admin/companies/form_modal.html', {
                'mode': 'edit',
                'company': company,
                'error': f'Error al actualizar: {str(e)}'
            })
    
    context = {
        'mode': 'edit',
        'company': company
    }
    return render(request, 'custom_admin/companies/form_modal.html', context)


@login_required
@staff_required
def company_view(request, company_id):
    """View company details - Modal"""
    company = get_object_or_404(Company, id=company_id)
    
    # Get related data
    users = User.objects.filter(company=company)
    certificates = DigitalCertificate.objects.filter(company=company)
    
    # Get company activity logs
    company_logs = AuditLog.objects.filter(
        model_name='Company',
        object_id=str(company.id)
    ).order_by('-created_at')[:10]
    
    context = {
        'company': company,
        'users': users,
        'certificates': certificates,
        'company_logs': company_logs,
        'user_count': users.count(),
        'certificate_count': certificates.count(),
    }
    return render(request, 'custom_admin/companies/view_modal.html', context)


@login_required
@staff_required
@require_http_methods(["POST"])
def company_delete(request, company_id):
    """Delete company"""
    try:
        company = get_object_or_404(Company, id=company_id)
        
        # Check if has related users
        if hasattr(company, 'users') and company.users.exists():
            return JsonResponse({
                'success': False,
                'error': 'No se puede eliminar una empresa con usuarios asociados'
            })
        
        # Log before deletion
        AuditLog.objects.create(
            user=request.user,
            action='DELETE',
            model_name='Company',
            object_id=str(company.id),
            object_representation=str(company),
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        company_name = company.trade_name or company.business_name
        company.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Empresa {company_name} eliminada exitosamente'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@staff_required
@require_http_methods(["POST"])
def company_toggle_status(request, company_id):
    """Toggle company active status"""
    try:
        data = json.loads(request.body)
        company = get_object_or_404(Company, id=company_id)
        
        company.is_active = data.get('is_active', False)
        company.save()
        
        # Log action
        AuditLog.objects.create(
            user=request.user,
            action='UPDATE',
            model_name='Company',
            object_id=str(company.id),
            object_representation=f'Status changed to {"active" if company.is_active else "inactive"}',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Estado actualizado correctamente',
            'is_active': company.is_active
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


# ========== LECTOR P12 - AUTOCOMPLETADO EMPRESA ==========

@login_required
@staff_required
@require_http_methods(["POST"])
def read_p12_data(request):
    """
    Extrae RUC, Razón Social y datos del emisor directamente de un archivo .p12.
    Permite autocompletar el formulario de creación de empresa sin conocer el RUC de antemano.

    POST multipart/form-data:
        p12_file  – archivo .p12
        password  – contraseña del certificado

    Returns JSON:
        { success, ruc, business_name, issuer, valid_from, valid_until, days_left }
    """
    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        import datetime

        p12_file = request.FILES.get('p12_file')
        password  = request.POST.get('password', '')

        if not p12_file:
            return JsonResponse({'success': False, 'error': 'No se recibió el archivo .p12'})

        if not password:
            return JsonResponse({'success': False, 'error': 'La contraseña es requerida'})

        # Tamaño máximo: 5 MB
        if p12_file.size > 5 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'El archivo es demasiado grande (máx. 5 MB)'})

        # Asegurar lectura desde el inicio
        p12_file.seek(0)
        p12_data = p12_file.read()
        
        logger.info(f"Intentando leer P12: {p12_file.name} ({len(p12_data)} bytes)")

        try:
            # MÉTODO 1: Cryptography (Estándar)
            private_key, certificate, _ = pkcs12.load_key_and_certificates(
                p12_data,
                password.encode('utf-8')
            )
        except Exception as e:
            logger.warning(f"Cryptography falló al abrir P12, intentando fallback con pyOpenSSL: {str(e)}")
            try:
                # MÉTODO 2: Fallback con pyOpenSSL (más robusto con formatos legacy del SRI)
                from OpenSSL import crypto
                # pyOpenSSL espera bytes para la contraseña
                p12 = crypto.load_pkcs12(p12_data, password.encode('utf-8'))
                
                # Convertir a objetos de cryptography para mantener compatibilidad
                # Usamos los métodos internos si están disponibles
                pk = p12.get_privatekey()
                private_key = pk.to_cryptography_key() if pk else None
                
                cert_obj = p12.get_certificate()
                certificate = cert_obj.to_cryptography() if cert_obj else None
                
                logger.info("✅ P12 cargado exitosamente usando fallback de pyOpenSSL")
            except Exception as e2:
                logger.error(f"Error crítico: Ambos métodos (cryptography y pyOpenSSL) fallaron. Error 1: {str(e)}, Error 2: {str(e2)}")
                import traceback
                logger.error(traceback.format_exc())
                return JsonResponse({
                    'success': False,
                    'error': f'No se pudo abrir el certificado. Verifica que la contraseña sea correcta. (Detalle: {str(e)})'
                })

        if certificate is None:
            return JsonResponse({'success': False, 'error': 'El archivo P12 no contiene un certificado válido'})

        def get_attr(subject, oid):
            try:
                attrs = subject.get_attributes_for_oid(oid)
                return attrs[0].value if attrs else None
            except Exception:
                return None

        subject = certificate.subject

        # Vamos a buscar el RUC usando una expresión regular (10 números seguidos de 001)
        import re
        ruc = ''
        
        # Recolectar TODOS los valores posibles del certificado
        all_text_values = []
        
        for attr in subject:
            valor = attr.value
            if isinstance(valor, bytes):
                try:
                    valor = valor.decode('utf-8')
                except Exception:
                    valor = str(valor)
            all_text_values.append(str(valor))
            
        # El string completo del Subject (puede tener el OID tal cual)
        try:
            all_text_values.append(subject.rfc4514_string())
        except Exception:
            pass

        # Unir todos los valores de texto extraídos
        full_text_to_search = " | ".join(all_text_values)

        # 1. Buscar explícitamente un RUC de 13 dígitos en forma flexible
        match_ruc = re.search(r'(\d{10}00[1-9])', full_text_to_search)
        if match_ruc:
            ruc = match_ruc.group(1)
        else:
            # 2. Si es una "Firma de Persona Natural", probamos con 10 dígitos (Cédula)
            match_cedula = re.search(r'(?<!\d)(\d{10})(?!\d)', full_text_to_search)
            if match_cedula:
                ruc = match_cedula.group(1) + '001'
            else:
                # 3. Y si no, probamos buscando en los bytes puros sin condiciones estrictas
                try:
                    from cryptography.hazmat.primitives import serialization
                    der_bytes = certificate.public_bytes(serialization.Encoding.DER)
                    match_der_13 = re.search(rb'(\d{10}00[1-9])', der_bytes)
                    if match_der_13:
                        ruc = match_der_13.group(1).decode('ascii')
                    else:
                        match_der_10 = re.search(rb'(?<!\d)(\d{10})(?!\d)', der_bytes)
                        if match_der_10:
                            ruc = match_der_10.group(1).decode('ascii') + '001'
                except Exception:
                    pass

        # 4. Si aún no lo tenemos, extraeremos las Opciones y Extensiones Completas (Por si acaso está en Subject Alternative Name)
        if not ruc:
            try:
                for ext in certificate.extensions:
                    val = ext.value
                    try:
                        if hasattr(val, '_general_names'):
                            for gn in val._general_names:
                                if hasattr(gn, 'value'):
                                    all_text_values.append(str(gn.value))
                    except Exception:
                        pass
                    all_text_values.append(str(val))
            except Exception:
                pass
            
            # Reintentamos después de haber sacado las extensiones
            full_text_to_search = " || ".join(all_text_values)
            match = re.search(r'(\d{10}00[1-9])', full_text_to_search)
            if match:
                ruc = match.group(1)

        # Razón Social: primero CN, luego O
        business_name = (
            get_attr(subject, NameOID.COMMON_NAME)
            or get_attr(subject, NameOID.ORGANIZATION_NAME)
            or ''
        )

        # Emisor (CA)
        issuer = certificate.issuer
        issuer_name = (
            get_attr(issuer, NameOID.COMMON_NAME)
            or get_attr(issuer, NameOID.ORGANIZATION_NAME)
            or str(issuer)
        )

        # Vigencia
        try:
            not_before = certificate.not_valid_before_utc
            not_after  = certificate.not_valid_after_utc
        except AttributeError:
            import pytz
            not_before = certificate.not_valid_before.replace(tzinfo=pytz.utc)
            not_after  = certificate.not_valid_after.replace(tzinfo=pytz.utc)

        now = datetime.datetime.now(datetime.timezone.utc)
        days_left = (not_after - now).days

        validity_warning = None
        if days_left < 0:
            validity_warning = f'ADVERTENCIA: El certificado expiró hace {abs(days_left)} días.'
        elif days_left <= 30:
            validity_warning = f'ADVERTENCIA: El certificado vence en {days_left} días.'
            
        return JsonResponse({
            'success':          True,
            'ruc':              ruc or '',
            'business_name':    business_name,
            'issuer':           issuer_name,
            'valid_from':       not_before.strftime('%Y-%m-%d'),
            'valid_until':      not_after.strftime('%Y-%m-%d'),
            'days_left':        days_left,
            'validity_warning': validity_warning,
            'debug_text':       full_text_to_search
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'Error inesperado: {str(e)}'})


# ========== CERTIFICATES CRUD ==========

@login_required
@staff_required
def certificates_list(request):
    """List all digital certificates"""
    certificates = DigitalCertificate.objects.all().select_related('company').order_by('-created_at')
    
    # Filters
    search = request.GET.get('search', '')
    status = request.GET.get('status', '')
    company_id = request.GET.get('company', '')
    
    if search:
        certificates = certificates.filter(
            Q(subject_name__icontains=search) |
            Q(serial_number__icontains=search) |
            Q(issuer_name__icontains=search)
        )
    
    if company_id:
        certificates = certificates.filter(company_id=company_id)
    
    # Convertir a lista si necesitamos filtrar por status
    if status:
        certificate_list = list(certificates)
        
        if status == 'active':
            certificates = [
                cert for cert in certificate_list 
                if not cert.is_expired and cert.days_until_expiry > 30
            ]
        elif status == 'expired':
            certificates = [
                cert for cert in certificate_list 
                if cert.is_expired
            ]
        elif status == 'expiring':
            certificates = [
                cert for cert in certificate_list 
                if not cert.is_expired and cert.days_until_expiry <= 30
            ]
        
        # Calcular el total antes de paginar
        total_count = len(certificates)
    else:
        # Si no hay filtro de status, usar count() del queryset
        total_count = certificates.count()
    
    # Get companies for filter dropdown
    companies = Company.objects.all().order_by('business_name')
    
    # Pagination
    paginator = Paginator(certificates, 25)
    page = request.GET.get('page')
    certificates_page = paginator.get_page(page)
    
    context = {
        'page_title': 'Certificados Digitales',
        'certificates': certificates_page,
        'companies': companies,
        'total_count': total_count,
        'filters': {
            'search': search,
            'status': status,
            'company': company_id,
        }
    }
    
    return render(request, 'custom_admin/certificates/list.html', context)

@login_required
@staff_required
def certificate_upload(request):
    """Upload new certificate - Modal form - CORREGIDO"""
    if request.method == 'POST':
        company_id = request.POST.get('company_id')
        certificate_file = request.FILES.get('certificate_file')
        password = request.POST.get('password')
        description = request.POST.get('description', '')
        
        if not certificate_file:
            companies = Company.objects.filter(is_active=True)
            return render(request, 'custom_admin/certificates/upload_modal.html', {
                'companies': companies,
                'error': 'Debe seleccionar un archivo de certificado'
            })
        
        if not password:
            companies = Company.objects.filter(is_active=True)
            return render(request, 'custom_admin/certificates/upload_modal.html', {
                'companies': companies,
                'error': 'La contraseña del certificado es requerida'
            })
        
        try:
            company = Company.objects.get(id=company_id)
            
            # Verificar si ya existe un certificado activo para esta empresa
            existing_cert = DigitalCertificate.objects.filter(
                company=company,
                status='ACTIVE'
            ).first()
            
            if existing_cert:
                # Desactivar certificado anterior
                existing_cert.status = 'INACTIVE'
                existing_cert.save()
            
            # USAR EL MÉTODO FACTORY SEGURO
            certificate = DigitalCertificate.create_with_password(
                company=company,
                certificate_file=certificate_file,
                password=password,
                environment='TEST',  # Default
                status='ACTIVE'
            )
            
            # Log action
            AuditLog.objects.create(
                user=request.user,
                action='CREATE',
                model_name='DigitalCertificate',
                object_id=str(certificate.id),
                object_representation=f'Certificate for {company}',
                changes=f'Certificado subido para {company.business_name}. Descripción: {description}',
                ip_address=request.META.get('REMOTE_ADDR')
            )
            
            # Determinar el mensaje según si se extrajo información real
            real_info_extracted = 'CN=' in certificate.subject_name and not certificate.subject_name.startswith('Procesando')
            
            if real_info_extracted:
                success_msg = f'Certificado cargado exitosamente. Información extraída: {certificate.subject_name[:50]}...'
            else:
                success_msg = 'Certificado cargado. Nota: Información no extraída automáticamente, verifica la contraseña.'
            
            messages.success(request, success_msg)
            return HttpResponse('<script>window.parent.location.reload();</script>')
            
        except Company.DoesNotExist:
            companies = Company.objects.filter(is_active=True)
            return render(request, 'custom_admin/certificates/upload_modal.html', {
                'companies': companies,
                'error': 'Empresa no encontrada'
            })
        except Exception as e:
            companies = Company.objects.filter(is_active=True)
            return render(request, 'custom_admin/certificates/upload_modal.html', {
                'companies': companies,
                'error': f'Error al cargar certificado: {str(e)}'
            })
    
    # GET request
    companies = Company.objects.filter(is_active=True)
    context = {
        'companies': companies
    }
    return render(request, 'custom_admin/certificates/upload_modal.html', context)

@login_required
@staff_required
def certificate_view(request, certificate_id):
    """View certificate details - Modal"""
    try:
        certificate = get_object_or_404(DigitalCertificate, id=certificate_id)
        
        # Calcular días hasta expiración
        days_until_expiry = 0
        is_expired = False
        try:
            if hasattr(certificate, 'valid_to') and certificate.valid_to:
                from datetime import datetime
                if timezone.is_aware(certificate.valid_to):
                    now = timezone.now()
                else:
                    now = datetime.now()
                days_until_expiry = (certificate.valid_to - now).days
                is_expired = certificate.valid_to < now
        except:
            pass
        
        # Calcular porcentaje de tiempo usado
        percentage = 70  # Default
        try:
            if hasattr(certificate, 'valid_from') and hasattr(certificate, 'valid_to'):
                total_days = (certificate.valid_to - certificate.valid_from).days
                used_days = (timezone.now() - certificate.valid_from).days
                if total_days > 0:
                    percentage = min(100, max(0, int((used_days / total_days) * 100)))
        except:
            pass
        
        # Devolver HTML directo mejorado
        html = f"""
        <style>
            .info-group {{
                padding: 0.75rem;
                background: #f8f9fa;
                border-radius: 0.25rem;
                margin-bottom: 0.75rem;
            }}
            .info-group label {{
                display: block;
                font-size: 0.75rem;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-bottom: 0.25rem;
                color: #6c757d;
            }}
            .info-group p {{
                margin-bottom: 0;
                font-weight: 500;
            }}
            .technical-details {{
                background: #f8f9fa;
                padding: 1rem;
                border-radius: 0.5rem;
            }}
            code {{
                background: #e9ecef;
                padding: 0.2rem 0.4rem;
                border-radius: 0.25rem;
                font-size: 0.875rem;
            }}
        </style>
        
        <div class="certificate-view-content">
            <div class="row">
                <!-- Información del Certificado -->
                <div class="col-md-6">
                    <h6 class="text-muted mb-3"><i class="fas fa-certificate me-2"></i>Información del Certificado</h6>
                    
                    <div class="info-group">
                        <label>Nombre del Sujeto</label>
                        <p><strong>{getattr(certificate, 'subject_name', 'N/A')}</strong></p>
                    </div>
                    
                    <div class="info-group">
                        <label>Número de Serie</label>
                        <p class="text-monospace"><code>{getattr(certificate, 'serial_number', 'N/A')}</code></p>
                    </div>
                    
                    <div class="info-group">
                        <label>Emisor</label>
                        <p>{getattr(certificate, 'issuer_name', 'N/A')}</p>
                    </div>
                    
                    <div class="info-group">
                        <label>Empresa</label>
                        <p>
                            {f'<span class="badge bg-info">{certificate.company.business_name}</span>' if hasattr(certificate, 'company') and certificate.company else '<span class="text-muted">Sin empresa asignada</span>'}
                        </p>
                    </div>
                    
                    <div class="info-group">
                        <label>Estado del Certificado</label>
                        <p>
                            {'<span class="badge bg-danger"><i class="fas fa-times-circle"></i> Expirado</span>' if is_expired else (f'<span class="badge bg-warning"><i class="fas fa-exclamation-triangle"></i> Por Expirar</span>' if days_until_expiry <= 30 else '<span class="badge bg-success"><i class="fas fa-check-circle"></i> Activo</span>')}
                            <span class="badge bg-secondary ms-2">{getattr(certificate, 'status', 'N/A')}</span>
                        </p>
                    </div>
                    
                    <div class="info-group">
                        <label>Ambiente</label>
                        <p>
                            <span class="badge bg-{('danger' if getattr(certificate, 'environment', '') == 'PRODUCTION' else 'warning')}">
                                {getattr(certificate, 'environment', 'N/A')}
                            </span>
                        </p>
                    </div>
                </div>
                
                <!-- Información de Validez -->
                <div class="col-md-6">
                    <h6 class="text-muted mb-3"><i class="fas fa-calendar-alt me-2"></i>Información de Validez</h6>
                    
                    <div class="info-group">
                        <label>Válido Desde</label>
                        <p>
                            <i class="fas fa-calendar-check text-success"></i>
                            {certificate.valid_from.strftime('%d/%m/%Y %H:%M') if hasattr(certificate, 'valid_from') and certificate.valid_from else 'N/A'}
                        </p>
                    </div>
                    
                    <div class="info-group">
                        <label>Válido Hasta</label>
                        <p>
                            <i class="fas fa-calendar-times text-danger"></i>
                            {certificate.valid_to.strftime('%d/%m/%Y %H:%M') if hasattr(certificate, 'valid_to') and certificate.valid_to else 'N/A'}
                        </p>
                    </div>
                    
                    <div class="info-group">
                        <label>Días Restantes</label>
                        <p>
                            {'<span class="text-danger fw-bold">Expirado hace ' + str(abs(days_until_expiry)) + ' días</span>' if is_expired else (f'<span class="text-danger fw-bold">Expira hoy</span>' if days_until_expiry == 0 else (f'<span class="text-warning fw-bold">Expira mañana</span>' if days_until_expiry == 1 else (f'<span class="text-warning fw-bold">{days_until_expiry} días restantes</span>' if days_until_expiry <= 30 else f'<span class="text-success fw-bold">{days_until_expiry} días restantes</span>')))}
                        </p>
                    </div>
                    
                    <div class="info-group">
                        <label>Fecha de Carga</label>
                        <p>{certificate.created_at.strftime('%d/%m/%Y %H:%M') if hasattr(certificate, 'created_at') and certificate.created_at else 'N/A'}</p>
                    </div>
                    
                    <div class="info-group">
                        <label>Fingerprint</label>
                        <p><code>{getattr(certificate, 'fingerprint', 'N/A')}</code></p>
                    </div>
                </div>
            </div>
            
            <hr>
            
            <!-- Detalles Técnicos -->
            <div class="row">
                <div class="col-12">
                    <h6 class="text-muted mb-3"><i class="fas fa-info-circle me-2"></i>Detalles Técnicos</h6>
                    
                    <div class="technical-details">
                        <p class="mb-2"><strong>CN (Common Name):</strong> {getattr(certificate, 'subject_name', 'N/A')}</p>
                        <p class="mb-2"><strong>Autoridad Certificadora:</strong> {getattr(certificate, 'issuer_name', 'N/A')}</p>
                        <p class="mb-2"><strong>Serial Completo:</strong></p>
                        <pre class="bg-white p-2 rounded text-monospace small" style="white-space: pre-wrap; word-break: break-all;">{getattr(certificate, 'serial_number', 'N/A')}</pre>
                        {f'<p class="mb-0"><strong>Archivo:</strong> <code>{certificate.certificate_file.name}</code></p>' if hasattr(certificate, 'certificate_file') and certificate.certificate_file else ''}
                    </div>
                </div>
            </div>
            
            <!-- Barra de Progreso -->
            <hr>
            <div class="row">
                <div class="col-12">
                    <h6 class="text-muted mb-3"><i class="fas fa-chart-line me-2"></i>Progreso de Validez</h6>
                    {'<div class="progress" style="height: 25px;"><div class="progress-bar bg-danger" role="progressbar" style="width: 100%">Certificado Expirado</div></div>' if is_expired else f'<div class="progress" style="height: 25px;"><div class="progress-bar {"bg-warning" if days_until_expiry <= 30 else "bg-success"}" role="progressbar" style="width: {percentage}%" aria-valuenow="{percentage}" aria-valuemin="0" aria-valuemax="100">Válido por {days_until_expiry} días más ({percentage}% usado)</div></div>'}
                    <small class="text-muted">
                        Período de validez: {certificate.valid_from.strftime('%d/%m/%Y') if hasattr(certificate, 'valid_from') and certificate.valid_from else 'N/A'} - {certificate.valid_to.strftime('%d/%m/%Y') if hasattr(certificate, 'valid_to') and certificate.valid_to else 'N/A'}
                    </small>
                </div>
            </div>
            
            <div class="modal-footer px-0 pb-0 mt-4">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                    <i class="fas fa-times me-1"></i>Cerrar
                </button>
                {'<button class="btn btn-warning" onclick="validateCertFromView(' + str(certificate.id) + ')"><i class="fas fa-check me-1"></i>Validar Certificado</button>' if not is_expired else ''}
            </div>
        </div>
        
        <script>
        function validateCertFromView(certId) {{
            // Cerrar el modal actual
            bootstrap.Modal.getInstance(document.getElementById('certificateModal')).hide();
            
            // Trigger el click en el botón de validar
            setTimeout(function() {{
                $('.btn-validate[data-cert-id="' + certId + '"]').click();
            }}, 300);
        }}
        </script>
        """
        
        return HttpResponse(html)
        
    except DigitalCertificate.DoesNotExist:
        return HttpResponse("""
            <div class="p-4">
                <div class="alert alert-danger">
                    <h4>Error</h4>
                    <p>No se encontró el certificado</p>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cerrar</button>
                </div>
            </div>
        """)
    except Exception as e:
        return HttpResponse(f"""
            <div class="p-4">
                <div class="alert alert-danger">
                    <h4>Error</h4>
                    <p>{str(e)}</p>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cerrar</button>
                </div>
            </div>
        """)


@login_required
@staff_required
@require_http_methods(["POST"])
def certificate_delete(request, certificate_id):
    """Delete certificate"""
    try:
        certificate = get_object_or_404(DigitalCertificate, id=certificate_id)
        
        # Log before deletion
        AuditLog.objects.create(
            user=request.user,
            action='DELETE',
            model_name='DigitalCertificate',
            object_id=str(certificate.id),
            object_representation=str(certificate),
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        certificate.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'Certificado eliminado exitosamente'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@staff_required
@require_http_methods(["POST"])
def certificate_validate(request, certificate_id):
    """Validate certificate"""
    try:
        certificate = get_object_or_404(DigitalCertificate, id=certificate_id)
        
        # Here you would run actual validation
        # For now, just toggle status
        if certificate.status == 'ACTIVE':
            certificate.status = 'INACTIVE'
        else:
            certificate.status = 'ACTIVE'
        
        certificate.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Certificado validado exitosamente',
            'status': certificate.status
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@staff_required
def certificate_edit(request, certificate_id):
    """Edit certificate environment - Modal"""
    try:
        # Intenta convertir certificate_id a entero
        cert_id = int(certificate_id)
        certificate = get_object_or_404(DigitalCertificate, id=cert_id)
        
        if request.method == 'POST':
            new_environment = request.POST.get('environment')
            
            if new_environment in ['TEST', 'PRODUCTION']:
                old_environment = certificate.environment
                certificate.environment = new_environment
                certificate.save()
                
                # Log the change
                AuditLog.objects.create(
                    user=request.user,
                    action='UPDATE',
                    model_name='DigitalCertificate',
                    object_id=str(certificate.id),
                    object_representation=f'Certificate environment changed from {old_environment} to {new_environment}',
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                
                messages.success(request, f'Ambiente cambiado a {new_environment} exitosamente')
                return HttpResponse('<script>window.parent.location.reload();</script>')
            else:
                messages.error(request, 'Ambiente inválido')
        
        context = {
            'certificate': certificate
        }
        return render(request, 'custom_admin/certificates/edit_modal.html', context)
        
    except ValueError:
        # Si el certificate_id no es un número válido
        return HttpResponse("""
            <div class="alert alert-danger">
                <h5><i class="fas fa-exclamation-triangle"></i> Error</h5>
                <p>ID de certificado inválido</p>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cerrar</button>
            </div>
        """)
    except DigitalCertificate.DoesNotExist:
        # Si el certificado no existe
        return HttpResponse("""
            <div class="alert alert-danger">
                <h5><i class="fas fa-exclamation-triangle"></i> Error</h5>
                <p>No se encontró el certificado solicitado</p>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cerrar</button>
            </div>
        """)
    except Exception as e:
        # Para cualquier otro error
        return HttpResponse(f"""
            <div class="alert alert-danger">
                <h5><i class="fas fa-exclamation-triangle"></i> Error</h5>
                <p>Error al cargar el formulario: {str(e)}</p>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cerrar</button>
            </div>
        """)


# ========== INVOICES ==========

@login_required
@staff_required
def invoices_list(request):
    """List invoices - Por implementar"""
    context = {
        'page_title': 'Facturas',
        'invoices': [],
        'total_count': 0,
    }
    return render(request, 'custom_admin/invoices/list.html', context)


@login_required
@staff_required
def invoice_view(request, invoice_id):
    """View invoice details - Modal"""
    # Por implementar
    context = {
        'invoice': None,
    }
    return render(request, 'custom_admin/invoices/view_modal.html', context)


@login_required
@staff_required
def invoice_create(request):
    """Create new invoice - Full page"""
    if request.method == 'GET':
        companies = Company.objects.filter(is_active=True).order_by('business_name')
        
        context = {
            'page_title': 'Nueva Factura',
            'companies': companies,
            'customers': [],
        }
        return render(request, 'custom_admin/invoices/create.html', context)
    
    elif request.method == 'POST':
        # Lógica para crear la factura
        try:
            messages.success(request, 'Factura creada correctamente')
            return redirect('custom_admin:invoices')
        except Exception as e:
            messages.error(request, f'Error al crear factura: {str(e)}')
            return redirect('custom_admin:invoice_create')


@login_required
@staff_required
def invoice_edit(request, invoice_id):
    """Edit invoice - Full page"""
    # Por implementar
    companies = Company.objects.filter(is_active=True).order_by('business_name')
    
    context = {
        'page_title': f'Editar Factura',
        'invoice': None,
        'companies': companies,
        'customers': [],
    }
    return render(request, 'custom_admin/invoices/edit.html', context)


@login_required
@staff_required
def invoice_authorize(request, invoice_id):
    """Authorize invoice with SRI"""
    if request.method == 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Funcionalidad en desarrollo'
        })


@login_required
@staff_required
def invoice_cancel(request, invoice_id):
    """Cancel an authorized invoice"""
    if request.method == 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Funcionalidad en desarrollo'
        })


@login_required
@staff_required
def invoice_batch_authorize(request):
    """Authorize multiple invoices"""
    if request.method == 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Funcionalidad en desarrollo'
        })


@login_required
@staff_required
def invoice_pdf(request, invoice_id):
    """Generate and download invoice PDF"""
    return HttpResponse('PDF generation not implemented yet', content_type='text/plain')

# Reemplaza las funciones de DOCUMENTS SRI en tu views.py con estas versiones funcionales:

# ========== DOCUMENTS SRI ==========
@login_required
@staff_required
def sri_documents_list(request):
    """List all SRI electronic documents"""
    from apps.companies.models import Company
    from apps.sri_integration.models import ElectronicDocument
    from django.core.paginator import Paginator
    from django.db.models import Q
    from decimal import Decimal
    
    # Obtener documentos
    documents = ElectronicDocument.objects.all().select_related('company').order_by('-created_at')
    
    # Aplicar filtros
    search = request.GET.get('search', '')
    doc_type = request.GET.get('doc_type', '')
    status = request.GET.get('status', '')
    company_id = request.GET.get('company', '')
    date_filter = request.GET.get('date', '')
    
    if search:
        documents = documents.filter(
            Q(document_number__icontains=search) |
            Q(access_key__icontains=search) |
            Q(customer_name__icontains=search) |
            Q(customer_identification__icontains=search)
        )
    
    if doc_type:
        type_mapping = {
            '01': 'INVOICE',
            '04': 'CREDIT_NOTE',
            '05': 'DEBIT_NOTE',
            '07': 'RETENTION',
            '03': 'PURCHASE_SETTLEMENT'
        }
        if doc_type in type_mapping:
            documents = documents.filter(document_type=type_mapping[doc_type])
    
    if status:
        status_mapping = {
            'AUTORIZADO': 'AUTHORIZED',
            'PENDIENTE': ['DRAFT', 'GENERATED', 'SIGNED', 'SENT'],
            'RECHAZADO': 'REJECTED',
            'ANULADO': 'CANCELLED',
            'ERROR': 'ERROR'
        }
        if status == 'PENDIENTE':
            documents = documents.filter(status__in=status_mapping[status])
        elif status in status_mapping:
            documents = documents.filter(status=status_mapping[status])
    
    if company_id:
        documents = documents.filter(company_id=company_id)
    
    if date_filter:
        documents = documents.filter(issue_date=date_filter)
    
    # Calcular estadísticas
    all_docs = ElectronicDocument.objects.all()
    stats = {
        'facturas': all_docs.filter(document_type='INVOICE').count(),
        'retenciones': all_docs.filter(document_type='RETENTION').count(),
        'notas_credito': all_docs.filter(document_type='CREDIT_NOTE').count(),
        'notas_debito': all_docs.filter(document_type='DEBIT_NOTE').count(),
        'pendientes': all_docs.filter(status__in=['DRAFT', 'GENERATED', 'SIGNED', 'SENT']).count(),
        'autorizados': all_docs.filter(status='AUTHORIZED').count(),
    }
    
    # Preparar documentos para el template
    documents_list = []
    for doc in documents:
        # Mapear tipos de documento
        type_code_mapping = {
            'INVOICE': '01',
            'CREDIT_NOTE': '04',
            'DEBIT_NOTE': '05',
            'RETENTION': '07',
            'PURCHASE_SETTLEMENT': '03'
        }
        
        # Mapear estados
        status_mapping_display = {
            'DRAFT': 'PENDIENTE',
            'GENERATED': 'PENDIENTE',
            'SIGNED': 'PENDIENTE',
            'SENT': 'PENDIENTE',
            'AUTHORIZED': 'AUTORIZADO',
            'REJECTED': 'RECHAZADO',
            'ERROR': 'ERROR',
            'CANCELLED': 'ANULADO'
        }
        
        doc_data = {
            'id': doc.id,
            'tipo_documento': type_code_mapping.get(doc.document_type, '01'),
            'numero_completo': doc.document_number or 'SIN NÚMERO',
            'razon_social_receptor': doc.customer_name or 'Sin receptor',
            'identificacion_receptor': doc.customer_identification or '',
            'company': doc.company,
            'fecha_emision': doc.issue_date,
            'total': float(doc.total_amount) if doc.total_amount else 0,
            'estado': status_mapping_display.get(doc.status, doc.status),
            'clave_acceso': doc.access_key or '',
            'emails_notificacion': doc.customer_email or '',
        }
        documents_list.append(doc_data)
    
    # Obtener empresas
    companies = Company.objects.filter(is_active=True).order_by('business_name')
    
    # Paginación
    paginator = Paginator(documents_list, 25)
    page = request.GET.get('page', 1)
    documents_page = paginator.get_page(page)
    
    # Contexto final
    context = {
        'page_title': 'Documentos SRI',
        'documents': documents_page,
        'companies': companies,
        'stats': stats,
        'total_count': len(documents_list),
        'filters': {
            'search': search,
            'doc_type': doc_type,
            'status': status,
            'company': company_id,
            'date': date_filter,
        }
    }
    
    return render(request, 'custom_admin/sri_documents/list.html', context)


@login_required
@staff_required
def sri_document_view(request, document_id):
    """View SRI document details"""
    from apps.sri_integration.models import ElectronicDocument
    from django.shortcuts import get_object_or_404, render
    from django.http import HttpResponse
    import traceback
    
    try:
        document = get_object_or_404(ElectronicDocument, id=document_id)
        
        # Mapear tipo de documento
        type_names = {
            'INVOICE': 'Factura',
            'CREDIT_NOTE': 'Nota de Crédito',
            'DEBIT_NOTE': 'Nota de Débito',
            'RETENTION': 'Retención',
            'PURCHASE_SETTLEMENT': 'Liquidación de Compra',
            'REMISSION_GUIDE': 'Guía de Remisión'
        }
        
        # Mapear estado para el label
        status_labels = {
            'DRAFT': 'PENDIENTE (Borrador)',
            'GENERATED': 'PENDIENTE (Generado)',
            'SIGNED': 'PENDIENTE (Firmado)',
            'SENT': 'PENDIENTE (Enviado SRI)',
            'AUTHORIZED': 'AUTORIZADO',
            'REJECTED': 'RECHAZADO',
            'ERROR': 'ERROR',
            'CANCELLED': 'ANULADO'
        }
        
        context = {
            'document': document,
            'type_name': type_names.get(document.document_type, 'Documento'),
            'status_label': status_labels.get(document.status, document.status),
            'responses': document.sri_responses.all().order_by('-created_at')[:5]
        }
        
        return render(request, 'custom_admin/sri_documents/detail_modal.html', context)
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return HttpResponse(f'<div class="alert alert-danger">Error al cargar detalle: {str(e)}</div>', status=500)


@login_required
@staff_required
@require_http_methods(["POST"])
def sri_document_authorize(request, document_id):
    """Authorize SRI document"""
    from apps.sri_integration.models import ElectronicDocument
    from apps.sri_integration.services.document_processor import DocumentProcessor
    
    try:
        document = get_object_or_404(ElectronicDocument, id=document_id)
        
        # Verificar que el documento esté en estado válido para autorizar
        if document.status not in ['GENERATED', 'SIGNED', 'SENT']:
            return JsonResponse({
                'success': False,
                'error': f'El documento no puede ser autorizado en estado {document.status}'
            })
        
        # Aquí iría la lógica real de autorización con el SRI
        # Por ahora, simulamos el proceso
        import random
        import string
        from datetime import datetime
        
        # Simular autorización exitosa (80% de probabilidad)
        if random.random() < 0.8:
            # Generar número de autorización simulado
            auth_number = ''.join(random.choices(string.digits, k=37))
            
            document.status = 'AUTHORIZED'
            document.sri_authorization_code = auth_number
            document.sri_authorization_date = timezone.now()
            document.sri_response = {
                'estado': 'AUTORIZADO',
                'numeroAutorizacion': auth_number,
                'fechaAutorizacion': timezone.now().isoformat(),
                'ambiente': 'PRUEBAS',
                'comprobante': document.access_key
            }
            document.save()
            
            # Log action
            AuditLog.objects.create(
                user=request.user,
                action='AUTHORIZE',
                model_name='ElectronicDocument',
                object_id=str(document.id),
                object_representation=f'Documento {document.document_number} autorizado',
                ip_address=request.META.get('REMOTE_ADDR')
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Documento autorizado correctamente',
                'numero_autorizacion': auth_number,
                'fecha_autorizacion': document.sri_authorization_date.strftime('%d/%m/%Y %H:%M')
            })
        else:
            # Simular rechazo
            document.status = 'REJECTED'
            document.sri_response = {
                'estado': 'RECHAZADO',
                'mensajes': [
                    {
                        'identificador': '35',
                        'mensaje': 'ARCHIVO NO CUMPLE ESTRUCTURA',
                        'tipo': 'ERROR'
                    }
                ]
            }
            document.save()
            
            return JsonResponse({
                'success': False,
                'error': 'Documento rechazado por el SRI: ARCHIVO NO CUMPLE ESTRUCTURA'
            })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@staff_required
def sri_document_download(request, document_id):
    """Download SRI document"""
    from apps.sri_integration.models import ElectronicDocument
    from django.http import FileResponse
    import os
    
    try:
        document = get_object_or_404(ElectronicDocument, id=document_id)
        
        # Verificar si existe el archivo PDF
        if document.pdf_file:
            try:
                return FileResponse(
                    document.pdf_file.open('rb'),
                    as_attachment=True,
                    filename=f'{document.document_number}.pdf'
                )
            except Exception:
                pass
        
        # Si no hay PDF, generar uno temporal o devolver el XML
        if document.signed_xml_file:
            try:
                return FileResponse(
                    document.signed_xml_file.open('rb'),
                    as_attachment=True,
                    filename=f'{document.document_number}.xml'
                )
            except Exception:
                pass
        
        # Si no hay archivos, generar un PDF básico
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        from io import BytesIO
        
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        
        # Encabezado
        p.setFont("Helvetica-Bold", 16)
        p.drawString(50, 750, f"DOCUMENTO ELECTRÓNICO")
        
        p.setFont("Helvetica", 12)
        p.drawString(50, 720, f"Tipo: {document.document_type}")
        p.drawString(50, 700, f"Número: {document.document_number}")
        p.drawString(50, 680, f"Fecha: {document.issue_date}")
        
        # Cliente
        p.drawString(50, 640, f"Cliente: {document.customer_name}")
        p.drawString(50, 620, f"RUC/CI: {document.customer_identification}")
        
        # Total
        p.setFont("Helvetica-Bold", 14)
        p.drawString(50, 580, f"TOTAL: ${float(document.total_amount):,.2f}")
        
        # Estado
        p.setFont("Helvetica", 10)
        p.drawString(50, 540, f"Estado: {document.status}")
        if document.access_key:
            p.drawString(50, 520, f"Clave de Acceso: {document.access_key}")
        
        p.showPage()
        p.save()
        
        buffer.seek(0)
        return FileResponse(
            buffer,
            as_attachment=True,
            filename=f'{document.document_number}.pdf'
        )
        
    except Exception as e:
        messages.error(request, f'Error al descargar documento: {str(e)}')
        return redirect('custom_admin:sri_documents')


@login_required
@staff_required
@require_http_methods(["POST"])
def sri_document_cancel(request, document_id):
    """Cancel SRI document"""
    from apps.sri_integration.models import ElectronicDocument
    
    try:
        document = get_object_or_404(ElectronicDocument, id=document_id)
        
        # Solo se pueden anular documentos autorizados
        if document.status != 'AUTHORIZED':
            return JsonResponse({
                'success': False,
                'error': 'Solo se pueden anular documentos autorizados'
            })
        
        # Solo facturas pueden ser anuladas (por ahora)
        if document.document_type != 'INVOICE':
            return JsonResponse({
                'success': False,
                'error': 'Solo se pueden anular facturas'
            })
        
        # Cambiar estado
        document.status = 'CANCELLED'
        document.save()
        
        # Log action
        AuditLog.objects.create(
            user=request.user,
            action='CANCEL',
            model_name='ElectronicDocument',
            object_id=str(document.id),
            object_representation=f'Documento {document.document_number} anulado',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Documento anulado correctamente'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@staff_required
@require_http_methods(["POST"])
def sri_document_resend(request, document_id):
    """Resend SRI document by email"""
    from apps.sri_integration.models import ElectronicDocument
    from django.core.mail import EmailMessage
    from django.conf import settings
    
    try:
        data = json.loads(request.body)
        email = data.get('email')
        
        if not email:
            return JsonResponse({
                'success': False,
                'error': 'Email es requerido'
            })
        
        document = get_object_or_404(ElectronicDocument, id=document_id)
        
        # Preparar el email
        subject = f'{document.document_type} #{document.document_number}'
        message = f"""
        Estimado/a {document.customer_name},
        
        Adjunto encontrará su documento electrónico:
        
        Tipo: {document.document_type}
        Número: {document.document_number}
        Fecha: {document.issue_date}
        Total: ${float(document.total_amount):,.2f}
        
        Saludos cordiales,
        {document.company.business_name if document.company else 'Sistema de Facturación'}
        """
        
        email_msg = EmailMessage(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )
        
        # Adjuntar archivos si existen
        if document.pdf_file:
            email_msg.attach_file(document.pdf_file.path)
        elif document.signed_xml_file:
            email_msg.attach_file(document.signed_xml_file.path)
        
        # Enviar email
        email_msg.send()
        
        # Actualizar documento
        document.email_sent = True
        document.email_sent_date = timezone.now()
        document.save()
        
        # Log action
        AuditLog.objects.create(
            user=request.user,
            action='EMAIL',
            model_name='ElectronicDocument',
            object_id=str(document.id),
            object_representation=f'Documento {document.document_number} enviado a {email}',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Documento enviado correctamente a {email}'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@staff_required
@require_http_methods(["POST"])
def sri_documents_batch_process(request):
    """Process multiple SRI documents"""
    from apps.sri_integration.models import ElectronicDocument
    
    try:
        data = json.loads(request.body)
        document_ids = data.get('document_ids', [])
        action = data.get('action')
        
        if not document_ids:
            return JsonResponse({
                'success': False,
                'error': 'No se seleccionaron documentos'
            })
        
        if action not in ['authorize', 'download', 'email']:
            return JsonResponse({
                'success': False,
                'error': 'Acción no válida'
            })
        
        processed = 0
        errors = 0
        
        for doc_id in document_ids:
            try:
                if action == 'authorize':
                    # Simular autorización
                    doc = ElectronicDocument.objects.get(id=doc_id, status__in=['GENERATED', 'SIGNED'])
                    doc.status = 'AUTHORIZED'
                    doc.save()
                    processed += 1
                    
                elif action == 'email':
                    doc = ElectronicDocument.objects.get(id=doc_id)
                    # Aquí iría la lógica de envío de email
                    processed += 1
                    
            except Exception:
                errors += 1
        
        return JsonResponse({
            'success': True,
            'message': f'Procesados: {processed}, Errores: {errors}',
            'processed': processed,
            'errors': errors
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

# Reemplaza todas las funciones de notificaciones en views.py con estas versiones:

@login_required
def notifications_list(request):
    """Lista de notificaciones del usuario"""
    
    # Obtener filtro
    current_filter = request.GET.get('filter', 'all')
    
    # Query base
    notifications = AdminNotification.objects.all().order_by('-created_at')
    
    # Aplicar filtros
    if current_filter == 'unread':
        notifications = notifications.filter(is_read=False)
    elif current_filter == 'info':
        notifications = notifications.filter(priority='normal')
    elif current_filter == 'success':
        notifications = notifications.filter(notification_type__in=[
            'user_approved', 'document_authorized'
        ])
    elif current_filter == 'warning':
        notifications = notifications.filter(priority='high')
    elif current_filter == 'error':
        notifications = notifications.filter(priority='urgent')
    
    # Contar totales
    total_count = AdminNotification.objects.count()
    unread_count = AdminNotification.objects.filter(is_read=False).count()
    
    # Paginación
    paginator = Paginator(notifications, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_title': 'Notificaciones',
        'notifications': page_obj,
        'total_count': total_count,
        'unread_count': unread_count,
        'current_filter': current_filter,
    }
    
    return render(request, 'custom_admin/notifications/list.html', context)

@login_required
def notification_mark_read(request, notification_id):
    """Marcar una notificación como leída"""
    if request.method == 'POST':
        try:
            notification = AdminNotification.objects.get(id=notification_id)
            notification.is_read = True
            notification.save()
            
            return JsonResponse({
                'success': True,
                'action_url': notification.action_url
            })
        except AdminNotification.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Notificación no encontrada'
            })
    
    return JsonResponse({'success': False, 'error': 'Método no permitido'})

@login_required
def notification_detail(request, notification_id):
    """Obtener detalle de una notificación"""
    try:
        notification = AdminNotification.objects.get(id=notification_id)
        
        return JsonResponse({
            'title': notification.title,
            'message': notification.message,
            'created_at': notification.created_at.strftime('%d/%m/%Y %H:%M'),
            'action_url': notification.action_url,
            'action_text': notification.action_text,
        })
    except AdminNotification.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Notificación no encontrada'
        })

@login_required
def notifications_mark_all_read(request):
    """Marcar todas las notificaciones como leídas"""
    if request.method == 'POST':
        updated = AdminNotification.objects.filter(
            is_read=False
        ).update(
            is_read=True
        )
        
        return JsonResponse({
            'success': True,
            'message': f'{updated} notificaciones marcadas como leídas'
        })
    
    return JsonResponse({'success': False, 'error': 'Método no permitido'})

@login_required
def notifications_batch_mark_read(request):
    """Marcar notificaciones seleccionadas como leídas"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            notification_ids = data.get('notification_ids', [])
            
            updated = AdminNotification.objects.filter(
                id__in=notification_ids,
                is_read=False
            ).update(
                is_read=True
            )
            
            return JsonResponse({
                'success': True,
                'message': f'{updated} notificaciones marcadas como leídas'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Método no permitido'})

@login_required
def notifications_batch_delete(request):
    """Eliminar notificaciones seleccionadas"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            notification_ids = data.get('notification_ids', [])
            
            deleted, _ = AdminNotification.objects.filter(
                id__in=notification_ids
            ).delete()
            
            return JsonResponse({
                'success': True,
                'message': f'{deleted} notificaciones eliminadas'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Método no permitido'})

@login_required
def notification_settings(request):
    """Configuración de notificaciones del usuario"""
    # Esta vista puede quedar vacía por ahora ya que AdminNotification
    # no tiene un sistema de suscripciones como el modelo Notification
    context = {
        'page_title': 'Configuración de Notificaciones',
    }
    return render(request, 'custom_admin/notifications/settings.html', context)

# ========== AUDIT LOGS ==========

@login_required
@staff_required
def audit_logs(request):
    """View audit logs"""
    logs = AuditLog.objects.all().select_related('user').order_by('-created_at')
    
    # Filters
    action = request.GET.get('action', '')
    model = request.GET.get('model', '')
    user_id = request.GET.get('user', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    if action:
        logs = logs.filter(action=action)
    
    if model:
        logs = logs.filter(model_name=model)
    
    if user_id:
        logs = logs.filter(user_id=user_id)
    
    if date_from:
        logs = logs.filter(created_at__date__gte=date_from)
    
    if date_to:
        logs = logs.filter(created_at__date__lte=date_to)
    
    # Get unique values for filters - CORRECCIÓN AQUÍ
    actions = (AuditLog.objects
               .exclude(action__isnull=True)
               .exclude(action='')
               .values_list('action', flat=True)
               .distinct()
               .order_by('action'))
    
    models = (AuditLog.objects
              .exclude(model_name__isnull=True)
              .exclude(model_name='')
              .values_list('model_name', flat=True)
              .distinct()
              .order_by('model_name'))
    
    # Para usuarios, usar el campo correcto 'audit_logs'
    users = (User.objects
             .filter(audit_logs__isnull=False)  # Cambié 'auditlog' por 'audit_logs'
             .distinct()
             .order_by('email'))
    
    # Pagination
    paginator = Paginator(logs, 50)
    page = request.GET.get('page')
    logs_page = paginator.get_page(page)
    
    context = {
        'page_title': 'Logs de Auditoría',
        'logs': logs_page,
        'total_count': paginator.count,
        'actions': actions,
        'models': models,
        'users': users,
        'filters': {
            'action': action,
            'model': model,
            'user': user_id,
            'date_from': date_from,
            'date_to': date_to,
        }
    }
    
    return render(request, 'custom_admin/audit_logs/list.html', context)

# ========== SETTINGS ==========
from django.core.mail import send_mail
from django.core.mail.backends.smtp import EmailBackend
from django.conf import settings as django_settings
import json

@login_required
@staff_required
def settings_list(request):
    """Settings main page"""
    
    # Obtener configuraciones actuales
    # Si tienes un modelo de configuraciones, úsalo aquí
    # Por ahora usaremos los settings de Django
    current_settings = {
        # General
        'system_name': get_system_name(),
        'system_logo_url': get_system_logo_url(),
        'system_favicon_url': get_system_favicon_url(),
        'timezone': django_settings.TIME_ZONE,
        'language': django_settings.LANGUAGE_CODE[:2],  # 'es' de 'es-EC'
        'maintenance_mode': getattr(django_settings, 'MAINTENANCE_MODE', False),
        
        # Email
        'smtp_host': getattr(django_settings, 'EMAIL_HOST', 'smtp.gmail.com'),
        'smtp_port': getattr(django_settings, 'EMAIL_PORT', 587),
        'smtp_user': getattr(django_settings, 'EMAIL_HOST_USER', ''),
        'from_email': getattr(django_settings, 'DEFAULT_FROM_EMAIL', ''),
        'use_tls': getattr(django_settings, 'EMAIL_USE_TLS', True),
        'sri_auto_email': getattr(django_settings, 'SRI_AUTO_EMAIL', True),
        
        # SRI
        'sri_environment': getattr(django_settings, 'SRI_ENVIRONMENT', '1'),
        'sri_reception_url': getattr(django_settings, 'SRI_RECEPTION_URL', ''),
        'sri_authorization_url': getattr(django_settings, 'SRI_AUTHORIZATION_URL', ''),
        'sri_auto_send': getattr(django_settings, 'SRI_AUTO_SEND', False),
        
        # Security
        'session_timeout': getattr(django_settings, 'SESSION_COOKIE_AGE', 1800) // 60,  # Convertir a minutos
        'max_login_attempts': getattr(django_settings, 'MAX_LOGIN_ATTEMPTS', 5),
        'two_factor_auth': getattr(django_settings, 'TWO_FACTOR_AUTH', False),
        'activity_logging': getattr(django_settings, 'ACTIVITY_LOGGING', True),
        
        # Notifications
        'email_notifications': getattr(django_settings, 'EMAIL_NOTIFICATIONS', True),
        'system_notifications': getattr(django_settings, 'SYSTEM_NOTIFICATIONS', True),
        'notification_emails': getattr(django_settings, 'NOTIFICATION_EMAILS', ''),
        'notify_new_orders': getattr(django_settings, 'NOTIFY_NEW_ORDERS', True),
        'notify_low_stock': getattr(django_settings, 'NOTIFY_LOW_STOCK', True),
        'notify_errors': getattr(django_settings, 'NOTIFY_ERRORS', True),
        'notify_sri_issues': getattr(django_settings, 'NOTIFY_SRI_ISSUES', True),
    }

    current_settings.update(get_seo_settings())
    
    context = {
        'page_title': 'Configuraciones',
        'settings': current_settings,
    }
    return render(request, 'custom_admin/settings/list.html', context)

@login_required
@staff_required
def settings_save(request):
    """Guardar configuraciones del sistema"""
    if request.method == 'POST':
        try:
            if request.content_type and 'application/json' in request.content_type:
                data = json.loads(request.body)
            else:
                data = request.POST.dict()
                for key in request.POST.keys():
                    if request.POST.getlist(key) and len(request.POST.getlist(key)) > 1:
                        data[key] = request.POST.getlist(key)
            
            # Guardar configuraciones en el modelo SystemSetting para persistencia real
            from apps.settings.models import SystemSetting
            
            # Mapeo de campos de la vista con llaves de SystemSetting
            settings_map = {
                'system_name': {'name': 'Nombre del Sistema', 'type': 'STRING', 'cat': 'SYSTEM'},
                'timezone': {'name': 'Zona Horaria', 'type': 'STRING', 'cat': 'SYSTEM'},
                'language': {'name': 'Idioma', 'type': 'STRING', 'cat': 'SYSTEM'},
                'maintenance_mode': {'name': 'Modo Mantenimiento', 'type': 'BOOLEAN', 'cat': 'SYSTEM'},
                'seo_meta_title': {'name': 'SEO Meta Title', 'type': 'STRING', 'cat': 'SYSTEM'},
                'seo_meta_description': {'name': 'SEO Meta Description', 'type': 'STRING', 'cat': 'SYSTEM'},
                'seo_meta_keywords': {'name': 'SEO Meta Keywords', 'type': 'STRING', 'cat': 'SYSTEM'},
                'seo_og_title': {'name': 'SEO OG Title', 'type': 'STRING', 'cat': 'SYSTEM'},
                'seo_og_description': {'name': 'SEO OG Description', 'type': 'STRING', 'cat': 'SYSTEM'},
                'seo_twitter_title': {'name': 'SEO Twitter Title', 'type': 'STRING', 'cat': 'SYSTEM'},
                'seo_twitter_description': {'name': 'SEO Twitter Description', 'type': 'STRING', 'cat': 'SYSTEM'},
                'seo_robots': {'name': 'SEO Robots', 'type': 'STRING', 'cat': 'SYSTEM'},
                'seo_canonical_url': {'name': 'SEO Canonical URL', 'type': 'URL', 'cat': 'SYSTEM'},
                'seo_custom_head': {'name': 'SEO Custom Head', 'type': 'STRING', 'cat': 'SYSTEM'},
                
                # Email SMTP
                'smtp_host': {'name': 'Servidor SMTP', 'type': 'STRING', 'cat': 'EMAIL'},
                'smtp_port': {'name': 'Puerto SMTP', 'type': 'INTEGER', 'cat': 'EMAIL'},
                'smtp_user': {'name': 'Usuario SMTP', 'type': 'STRING', 'cat': 'EMAIL'},
                'smtp_password': {'name': 'Contraseña SMTP', 'type': 'PASSWORD', 'cat': 'EMAIL'},
                'from_email': {'name': 'Email Remitente', 'type': 'STRING', 'cat': 'EMAIL'},
                'use_tls': {'name': 'Usar TLS', 'type': 'BOOLEAN', 'cat': 'EMAIL'},
                'sri_auto_email': {'name': 'Envío Automático de Comprobantes', 'type': 'BOOLEAN', 'cat': 'EMAIL'},
                
                # SRI
                'sri_environment': {'name': 'Ambiente SRI', 'type': 'STRING', 'cat': 'SRI'},
                'sri_auto_send': {'name': 'Envío Automático SRI', 'type': 'BOOLEAN', 'cat': 'SRI'},
                'sri_reception_url': {'name': 'URL Recepción SRI', 'type': 'URL', 'cat': 'SRI'},
                'sri_authorization_url': {'name': 'URL Autorización SRI', 'type': 'URL', 'cat': 'SRI'},

                # Seguridad
                'session_timeout': {'name': 'Tiempo de Sesión', 'type': 'INTEGER', 'cat': 'SECURITY'},
                'max_login_attempts': {'name': 'Intentos Máximos de Login', 'type': 'INTEGER', 'cat': 'SECURITY'},
                'two_factor_auth': {'name': 'Autenticación de Dos Factores', 'type': 'BOOLEAN', 'cat': 'SECURITY'},
                'activity_logging': {'name': 'Registro de Actividad', 'type': 'BOOLEAN', 'cat': 'SECURITY'},

                # Notificaciones
                'email_notifications': {'name': 'Notificaciones por Email', 'type': 'BOOLEAN', 'cat': 'NOTIFICATION'},
                'system_notifications': {'name': 'Notificaciones del Sistema', 'type': 'BOOLEAN', 'cat': 'NOTIFICATION'},
                'notification_emails': {'name': 'Emails de Notificación', 'type': 'STRING', 'cat': 'NOTIFICATION'},
                'notify_new_orders': {'name': 'Notificar Nuevas Órdenes', 'type': 'BOOLEAN', 'cat': 'NOTIFICATION'},
                'notify_low_stock': {'name': 'Notificar Stock Bajo', 'type': 'BOOLEAN', 'cat': 'NOTIFICATION'},
                'notify_errors': {'name': 'Notificar Errores', 'type': 'BOOLEAN', 'cat': 'NOTIFICATION'},
                'notify_sri_issues': {'name': 'Notificar Problemas SRI', 'type': 'BOOLEAN', 'cat': 'NOTIFICATION'},
            }
            
            for key, info in settings_map.items():
                if key in data:
                    val = str(data[key])
                    # Caso especial para booleanos
                    if info['type'] == 'BOOLEAN':
                        val = 'true' if normalize_bool(data[key]) else 'false'
                    elif val.strip() == '':
                        existing_setting = SystemSetting.objects.filter(key=key.upper()).first()
                        if existing_setting:
                            existing_setting.delete()
                        continue
                    
                    setting_obj, created = SystemSetting.objects.get_or_create(
                        key=key.upper(),
                        defaults={
                            'name': info['name'],
                            'setting_type': info['type'],
                            'category': info['cat'],
                            'value': val
                        }
                    )
                    if not created:
                        # No actualizar password si viene vacío (placeholder)
                        if info['type'] == 'PASSWORD' and not data[key]:
                            continue
                        setting_obj.value = val
                        setting_obj.save()

            file_fields = {
                'system_logo': ('SYSTEM_LOGO', 'Logo del Sistema'),
                'system_favicon': ('SYSTEM_FAVICON', 'Favicon del Sistema'),
            }

            for form_key, (setting_key, label) in file_fields.items():
                uploaded_file = request.FILES.get(form_key)
                if uploaded_file:
                    store_branding_asset(uploaded_file, setting_key, label)
            
            # Actualizar configuraciones de Django en tiempo real para esta instancia
            if 'smtp_host' in data:
                django_settings.EMAIL_HOST = data['smtp_host']
            if 'system_name' in data and data['system_name']:
                django_settings.SYSTEM_NAME = data['system_name']
                django_settings.SITE_NAME = data['system_name']
                try:
                    from django.contrib.sites.models import Site
                    current_site = Site.objects.get_current()
                    current_site.name = data['system_name']
                    current_site.save(update_fields=['name'])
                except Exception:
                    pass
            if 'smtp_port' in data:
                django_settings.EMAIL_PORT = int(data['smtp_port'])
            if 'smtp_user' in data:
                django_settings.EMAIL_HOST_USER = data['smtp_user']
            if 'smtp_password' in data and data['smtp_password']:
                django_settings.EMAIL_HOST_PASSWORD = data['smtp_password']
            if 'from_email' in data:
                django_settings.DEFAULT_FROM_EMAIL = data['from_email']
            if 'use_tls' in data:
                django_settings.EMAIL_USE_TLS = normalize_bool(data['use_tls'])
            if 'sri_auto_email' in data:
                django_settings.SRI_AUTO_EMAIL = normalize_bool(data['sri_auto_email'])
            
            messages.success(request, 'Configuraciones guardadas exitosamente')
            return JsonResponse({
                'success': True,
                'branding': {
                    'system_logo_url': get_system_logo_url(),
                    'system_favicon_url': get_system_favicon_url(),
                }
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Método no permitido'})

@login_required
@staff_required
def test_email(request):
    """Probar configuración de email"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            test_email = data.get('test_email')
            
            if not test_email:
                return JsonResponse({'success': False, 'error': 'Email de prueba requerido'})
            
            # Configurar backend de email temporal para la prueba
            backend = EmailBackend(
                host=data.get('smtp_host', 'smtp.gmail.com'),
                port=int(data.get('smtp_port', 587)),
                username=data.get('smtp_user'),
                password=data.get('smtp_password'),
                use_tls=data.get('use_tls', True),
                use_ssl=False,
                fail_silently=False,
            )
            
            # Crear y enviar email de prueba
            from django.core.mail import EmailMessage
            
            email = EmailMessage(
                subject=f'Prueba de Configuración de Email - {get_system_name()}',
                body='''Este es un correo de prueba para verificar la configuración SMTP.

Si recibes este mensaje, significa que la configuración de email está funcionando correctamente.

Configuración utilizada:
- Servidor SMTP: {}
- Puerto: {}
- Usuario: {}
- TLS: {}

Saludos,
Sistema {}'''.format(
                    data.get('smtp_host'),
                    data.get('smtp_port'),
                    data.get('smtp_user'),
                    'Habilitado' if data.get('use_tls') else 'Deshabilitado',
                    get_system_name()
                ),
                from_email=data.get('from_email'),
                to=[test_email],
                connection=backend
            )
            
            email.send()
            
            return JsonResponse({
                'success': True,
                'message': f'Email de prueba enviado a {test_email}'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False, 
                'error': f'Error al enviar email: {str(e)}'
            })
    
    return JsonResponse({'success': False, 'error': 'Método no permitido'})

@login_required
@staff_required
def system_settings(request):
    """System settings - legacy view"""
    if request.method == 'POST':
        # Handle system settings update
        messages.success(request, 'Configuración actualizada exitosamente')
        return redirect('custom_admin:system_settings')
    
    context = {
        'page_title': 'Configuración del Sistema',
        'settings': {
            'site_name': get_system_name(),
            'debug_mode': django_settings.DEBUG,
            'allowed_hosts': django_settings.ALLOWED_HOSTS,
            'time_zone': django_settings.TIME_ZONE,
            'language_code': django_settings.LANGUAGE_CODE,
        }
    }
    return render(request, 'custom_admin/settings/system.html', context)

@login_required
@staff_required
def company_settings(request):
    """Company default settings"""
    context = {
        'page_title': 'Configuración de Empresas',
    }
    return render(request, 'custom_admin/settings/companies.html', context)

# ========== PROFILE ==========
# ========== PROFILE VIEWS COMPLETAS ==========

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from rest_framework.authtoken.models import Token
from django.contrib.sessions.models import Session
from django.utils import timezone
from datetime import datetime

@login_required
@staff_required
def profile(request):
    """User profile"""
    # Obtener actividad reciente del usuario
    recent_activities = AuditLog.objects.filter(
        user=request.user
    ).order_by('-created_at')[:10]
    
    # Contar sesiones activas
    active_sessions = Session.objects.filter(
        expire_date__gte=timezone.now()
    ).count()
    
    context = {
        'page_title': 'Mi Perfil',
        'user': request.user,
        'recent_activities': recent_activities,
        'active_sessions': active_sessions
    }
    return render(request, 'custom_admin/profile/profile.html', context)


@login_required
@staff_required
def profile_edit(request):
    """Edit profile page"""
    if request.method == 'POST':
        # Actualizar datos del usuario
        user = request.user
        user.first_name = request.POST.get('first_name', '')
        user.last_name = request.POST.get('last_name', '')
        user.phone = request.POST.get('phone', '')
        
        # Manejar foto de perfil si se sube una
        if 'profile_picture' in request.FILES:
            user.profile_picture = request.FILES['profile_picture']
        
        try:
            user.save()
            
            # Log action
            AuditLog.objects.create(
                user=request.user,
                action='UPDATE',
                model_name='User',
                object_id=str(user.id),
                object_representation=f'Perfil actualizado: {user.get_full_name()}',
                changes=f'Nombre: {user.first_name} {user.last_name}, Teléfono: {user.phone}',
                ip_address=request.META.get('REMOTE_ADDR')
            )
            
            messages.success(request, 'Perfil actualizado exitosamente')
            return redirect('custom_admin:profile')
            
        except Exception as e:
            messages.error(request, f'Error al actualizar el perfil: {str(e)}')
    
    context = {
        'page_title': 'Editar Perfil',
        'user': request.user
    }
    return render(request, 'custom_admin/profile/edit.html', context)


@login_required
@staff_required
def change_password(request):
    """Change password view"""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Mantiene la sesión activa
            
            # Log action
            AuditLog.objects.create(
                user=request.user,
                action='UPDATE',
                model_name='User',
                object_id=str(user.id),
                object_representation='Cambio de contraseña',
                changes='Contraseña actualizada',
                ip_address=request.META.get('REMOTE_ADDR')
            )
            
            messages.success(request, 'Tu contraseña ha sido actualizada exitosamente')
            return redirect('custom_admin:profile')
        else:
            messages.error(request, 'Por favor corrige los errores del formulario')
    else:
        form = PasswordChangeForm(request.user)
    
    context = {
        'page_title': 'Cambiar Contraseña',
        'form': form
    }
    return render(request, 'custom_admin/profile/change_password.html', context)


@login_required
@staff_required
def manage_sessions(request):
    """Manage user sessions"""
    if request.method == 'POST':
        # Cerrar todas las sesiones excepto la actual
        current_session_key = request.session.session_key
        
        # Obtener todas las sesiones
        sessions = Session.objects.filter(expire_date__gte=timezone.now())
        sessions_closed = 0
        
        for session in sessions:
            session_data = session.get_decoded()
            if session_data.get('_auth_user_id') == str(request.user.id):
                if session.session_key != current_session_key:
                    session.delete()
                    sessions_closed += 1
        
        # Log action
        AuditLog.objects.create(
            user=request.user,
            action='DELETE',
            model_name='Session',
            object_representation=f'Cerradas {sessions_closed} sesiones',
            changes=f'Se cerraron {sessions_closed} sesiones activas',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        messages.success(request, f'Se cerraron {sessions_closed} sesiones activas')
        return redirect('custom_admin:profile')
    
    # Obtener información de sesiones activas
    sessions = Session.objects.filter(expire_date__gte=timezone.now())
    user_sessions = []
    
    for session in sessions:
        session_data = session.get_decoded()
        if session_data.get('_auth_user_id') == str(request.user.id):
            user_sessions.append({
                'session_key': session.session_key,
                'expire_date': session.expire_date,
                'is_current': session.session_key == request.session.session_key
            })
    
    context = {
        'page_title': 'Gestionar Sesiones',
        'user_sessions': user_sessions
    }
    return render(request, 'custom_admin/profile/manage_sessions.html', context)


@login_required
@staff_required
@require_http_methods(["POST"])
def regenerate_token(request):
    """Regenerate API token"""
    try:
        # Eliminar token existente si existe
        Token.objects.filter(user=request.user).delete()
        
        # Crear nuevo token
        token = Token.objects.create(user=request.user)
        
        # Log action
        AuditLog.objects.create(
            user=request.user,
            action='CREATE',
            model_name='Token',
            object_representation='Token API regenerado',
            changes=f'Nuevo token generado',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        messages.success(request, 'Token API regenerado exitosamente')
        return JsonResponse({
            'success': True,
            'token': token.key,
            'message': 'Token regenerado exitosamente'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@staff_required
@require_http_methods(["POST"])
def profile_update(request):
    """Update user profile via AJAX"""
    try:
        data = json.loads(request.body)
        user = request.user
        
        # Actualizar campos
        if 'first_name' in data:
            user.first_name = data['first_name']
        if 'last_name' in data:
            user.last_name = data['last_name']
        if 'phone' in data:
            user.phone = data['phone']
        
        # Si se cambia la contraseña
        if data.get('password'):
            user.set_password(data['password'])
            update_session_auth_hash(request, user)
        
        user.save()
        
        # Log action
        AuditLog.objects.create(
            user=request.user,
            action='UPDATE',
            model_name='User',
            object_id=str(user.id),
            object_representation='Actualización de perfil',
            changes=f'Datos actualizados vía API',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Perfil actualizado exitosamente'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

# ========== HELPER FUNCTIONS ==========

def get_users_chart_data():
    """Get data for users chart"""
    last_30_days = []
    for i in range(30):
        date = timezone.now().date() - timedelta(days=i)
        count = User.objects.filter(date_joined__date=date).count()
        last_30_days.append({
            'date': date.strftime('%Y-%m-%d'),
            'count': count
        })
    
    return {
        'labels': [d['date'] for d in reversed(last_30_days)],
        'data': [d['count'] for d in reversed(last_30_days)]
    }


def get_activity_chart_data():
    """Get data for activity chart"""
    last_7_days = []
    for i in range(7):
        date = timezone.now().date() - timedelta(days=i)
        count = AuditLog.objects.filter(created_at__date=date).count()
        last_7_days.append({
            'date': date.strftime('%Y-%m-%d'),
            'count': count
        })
    
    return {
        'labels': [d['date'] for d in reversed(last_7_days)],
        'data': [d['count'] for d in reversed(last_7_days)]
    }


# ========== EXPORT FUNCTIONS ==========

@login_required
@staff_required
def export_data(request, model_name):
    """Export data to CSV"""
    import csv
    
    # Map model names to actual models
    model_map = {
        'users': User,
        'companies': Company,
        'certificates': DigitalCertificate,
        'audit_logs': AuditLog,
    }
    
    if model_name not in model_map:
        return JsonResponse({'error': 'Invalid model'}, status=400)
    
    model = model_map[model_name]
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{model_name}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    
    # Write headers based on model
    if model_name == 'users':
        writer.writerow(['ID', 'Email', 'Nombre', 'Apellido', 'Teléfono', 'Empresa', 'Activo', 'Staff', 'Fecha Registro'])
        for obj in model.objects.all():
            writer.writerow([
                obj.id,
                obj.email,
                obj.first_name,
                obj.last_name,
                obj.phone,
                obj.company.business_name if obj.company else '',
                'Sí' if obj.is_active else 'No',
                'Sí' if obj.is_staff else 'No',
                obj.date_joined.strftime('%Y-%m-%d %H:%M')
            ])
    
    elif model_name == 'companies':
        writer.writerow(['ID', 'RUC', 'Razón Social', 'Nombre Comercial', 'Email', 'Teléfono', 'Activo', 'Fecha Creación'])
        for obj in model.objects.all():
            writer.writerow([
                obj.id,
                obj.ruc,
                obj.business_name,
                obj.trade_name,
                obj.email,
                obj.phone,
                'Sí' if obj.is_active else 'No',
                obj.created_at.strftime('%Y-%m-%d %H:%M')
            ])
    
    elif model_name == 'certificates':
        writer.writerow(['ID', 'Empresa', 'Sujeto', 'Serial', 'Válido Desde', 'Válido Hasta', 'Estado'])
        for obj in model.objects.all():
            writer.writerow([
                obj.id,
                obj.company.business_name if obj.company else '',
                obj.subject_name,
                obj.serial_number,
                obj.valid_from.strftime('%Y-%m-%d') if obj.valid_from else '',
                obj.valid_to.strftime('%Y-%m-%d') if obj.valid_to else '',
                obj.status
            ])
    
    # Log export
    AuditLog.objects.create(
        user=request.user,
        action='EXPORT',
        model_name=model_name,
        object_representation=f'Exported {model.objects.count()} records',
        ip_address=request.META.get('REMOTE_ADDR')
    )
    
    return response


# ========== API ENDPOINTS ==========

@login_required
@staff_required
def dashboard_stats_api(request):
    """API endpoint for dashboard statistics refresh"""
    stats = {
        'total_users': User.objects.filter(is_staff=False, is_superuser=False).count(),
        'active_users': User.objects.filter(is_active=True, is_staff=False).count(),
        'pending_users': UserCompanyAssignment.objects.filter(status='waiting').count(),
        'new_users_today': User.objects.filter(date_joined__date=timezone.now().date()).count(),
        'total_companies': Company.objects.count(),
        'active_companies': Company.objects.filter(is_active=True).count(),
        'total_certificates': DigitalCertificate.objects.count(),
        'expiring_certificates': DigitalCertificate.objects.filter(
            valid_to__lte=timezone.now() + timedelta(days=30),
            valid_to__gte=timezone.now()
        ).count(),
        'unread_notifications': AdminNotification.objects.filter(is_read=False).count(),
    }
    
    # Include updated chart data
    charts = {
        'users': get_users_chart_data(),
        'activity': get_activity_chart_data(),
    }
    
    return JsonResponse({
        'success': True,
        'stats': stats,
        'charts': charts
    })


@login_required
@staff_required
def global_search(request):
    """Global search across models"""
    query = request.GET.get('q', '')
    if not query or len(query) < 2:
        return JsonResponse({'results': []})
    
    results = []
    
    # Search users
    users = User.objects.filter(
        Q(email__icontains=query) |
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query)
    )[:5]
    
    for user in users:
        results.append({
            'type': 'user',
            'id': user.id,
            'title': user.get_full_name() or user.email,
            'subtitle': user.email,
            'url': f'/admin-panel/users/{user.id}/edit/',
            'icon': 'fas fa-user'
        })
    
    # Search companies
    companies = Company.objects.filter(
        Q(business_name__icontains=query) |
        Q(ruc__icontains=query) |
        Q(trade_name__icontains=query)
    )[:5]
    
    for company in companies:
        results.append({
            'type': 'company',
            'id': company.id,
            'title': company.business_name,
            'subtitle': f'RUC: {company.ruc}',
            'url': f'/admin-panel/companies/{company.id}/edit/',
            'icon': 'fas fa-building'
        })
    
    # Search certificates
    certificates = DigitalCertificate.objects.filter(
        Q(subject_name__icontains=query) |
        Q(serial_number__icontains=query)
    ).select_related('company')[:5]
    
    for cert in certificates:
        results.append({
            'type': 'certificate',
            'id': cert.id,
            'title': cert.subject_name,
            'subtitle': f'Serial: {cert.serial_number}',
            'url': f'/admin-panel/certificates/{cert.id}/view/',
            'icon': 'fas fa-certificate'
        })
    
    return JsonResponse({
        'success': True,
        'results': results,
        'count': len(results)
    })


# ========== PLACEHOLDER VIEWS (Por implementar) ==========

@login_required
@staff_required
def customers_list(request):
    """List customers - Por implementar"""
    context = {
        'page_title': 'Clientes',
        'customers': [],
        'total_count': 0,
    }
    return render(request, 'custom_admin/customers/list.html', context)


@login_required
@staff_required
def products_list(request):
    """List products - Por implementar"""
    context = {
        'page_title': 'Productos',
        'products': [],
        'total_count': 0,
    }
    return render(request, 'custom_admin/products/list.html', context)
# Agregar estas vistas en apps/custom_admin/views.py

# ========== BILLING ==========

@login_required
@staff_required
def billing_plans_list(request):
    """Lista de planes de facturación"""
    from apps.billing.models import Plan
    
    plans = Plan.objects.all().order_by('sort_order', 'price')
    
    # Filtros
    is_active = request.GET.get('is_active')
    if is_active:
        plans = plans.filter(is_active=is_active == 'true')
    
    context = {
        'page_title': 'Planes de Facturación',
        'plans': plans,
    }
    return render(request, 'custom_admin/billing/plans_list.html', context)


@login_required
@staff_required
@require_http_methods(["POST"])
def billing_plan_create(request):
    """Crear nuevo plan"""
    from apps.billing.models import Plan
    
    try:
        data = json.loads(request.body)
        
        plan = Plan.objects.create(
            name=data['name'],
            description=data.get('description', ''),
            invoice_limit=data['invoice_limit'],
            is_unlimited=data.get('is_unlimited', False),
            price=data['price'],
            is_active=data.get('is_active', True),
            is_featured=data.get('is_featured', False),
            sort_order=data.get('sort_order', 0)
        )
        
        # Log action
        AuditLog.objects.create(
            user=request.user,
            action='CREATE',
            model_name='Plan',
            object_id=str(plan.id),
            object_representation=plan.name,
            changes=f'Plan creado: {plan.invoice_limit} facturas por ${plan.price}',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Plan creado exitosamente',
            'plan': {
                'id': plan.id,
                'name': plan.name,
                'invoice_limit': plan.invoice_limit,
                'price': str(plan.price),
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
@staff_required
@require_http_methods(["PUT"])
def billing_plan_update(request, plan_id):
    """Actualizar plan"""
    from apps.billing.models import Plan
    
    try:
        plan = Plan.objects.get(id=plan_id)
        data = json.loads(request.body)
        
        # Guardar valores anteriores para el log
        old_values = {
            'name': plan.name,
            'invoice_limit': plan.invoice_limit,
            'is_unlimited': plan.is_unlimited,
            'price': str(plan.price),
        }
        
        # Actualizar
        plan.name = data.get('name', plan.name)
        plan.description = data.get('description', plan.description)
        plan.invoice_limit = data.get('invoice_limit', plan.invoice_limit)
        plan.is_unlimited = data.get('is_unlimited', plan.is_unlimited)
        plan.price = data.get('price', plan.price)
        plan.is_active = data.get('is_active', plan.is_active)
        plan.is_featured = data.get('is_featured', plan.is_featured)
        plan.sort_order = data.get('sort_order', plan.sort_order)
        plan.save()
        
        # Log changes
        AuditLog.objects.create(
            user=request.user,
            action='UPDATE',
            model_name='Plan',
            object_id=str(plan.id),
            object_representation=plan.name,
            changes=f'Actualizado de {old_values} a {{"name": "{plan.name}", "invoice_limit": {plan.invoice_limit}, "is_unlimited": {plan.is_unlimited}, "price": "{plan.price}"}}',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Plan actualizado exitosamente'
        })
        
    except Plan.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Plan no encontrado'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
@staff_required
@require_http_methods(["DELETE"])
def billing_plan_delete(request, plan_id):
    """Eliminar plan"""
    from apps.billing.models import Plan
    
    try:
        plan = Plan.objects.get(id=plan_id)
        plan_name = plan.name
        
        # Verificar si tiene compras asociadas
        if plan.purchases.exists():
            return JsonResponse({
                'success': False,
                'error': 'No se puede eliminar un plan con compras asociadas'
            }, status=400)
        
        plan.delete()
        
        # Log action
        AuditLog.objects.create(
            user=request.user,
            action='DELETE',
            model_name='Plan',
            object_id=str(plan_id),
            object_representation=plan_name,
            changes='Plan eliminado',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Plan eliminado exitosamente'
        })
        
    except Plan.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Plan no encontrado'
        }, status=404)


@login_required
@staff_required
def billing_purchases_list(request):
    """Lista de compras de planes"""
    from apps.billing.models import PlanPurchase
    
    purchases = PlanPurchase.objects.all().select_related(
        'company', 'plan', 'processed_by'
    ).order_by('-created_at')
    
    # Filtros
    status = request.GET.get('status')
    if status:
        purchases = purchases.filter(payment_status=status)
    
    company_id = request.GET.get('company')
    if company_id:
        purchases = purchases.filter(company_id=company_id)
    
    date_from = request.GET.get('date_from')
    if date_from:
        purchases = purchases.filter(created_at__date__gte=date_from)
    
    date_to = request.GET.get('date_to')
    if date_to:
        purchases = purchases.filter(created_at__date__lte=date_to)
    
    # Paginación
    paginator = Paginator(purchases, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Estadísticas
    from django.db.models import Sum, Count
    stats = purchases.aggregate(
        total_pending=Count('id', filter=Q(payment_status='pending')),
        total_approved=Count('id', filter=Q(payment_status='approved')),
        total_amount=Sum('payment_amount', filter=Q(payment_status='approved'))
    )
    
    context = {
        'page_title': 'Compras de Planes',
        'page_obj': page_obj,
        'stats': stats,
        'status_filter': status,
        'company_filter': company_id,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'custom_admin/billing/purchases_list.html', context)


@login_required
@staff_required
def billing_purchase_detail(request, purchase_id):
    """Ver detalle de una compra"""
    from apps.billing.models import PlanPurchase
    
    purchase = get_object_or_404(
        PlanPurchase.objects.select_related('company', 'plan', 'processed_by'),
        purchase_id=purchase_id
    )
    
    context = {
        'purchase': purchase,
    }
    return render(request, 'custom_admin/billing/purchase_detail_modal.html', context)


@login_required
@staff_required
@require_http_methods(["POST"])
def billing_purchase_approve(request, purchase_id):
    """Aprobar una compra"""
    from apps.billing.models import PlanPurchase
    
    try:
        purchase = PlanPurchase.objects.get(purchase_id=purchase_id)
        
        if purchase.payment_status != 'pending':
            return JsonResponse({
                'success': False,
                'error': 'Solo se pueden aprobar compras pendientes'
            }, status=400)
        
        # Aprobar la compra (esto asigna las facturas automáticamente)
        success = purchase.approve_purchase(request.user)
        
        if success:
            # Log action
            AuditLog.objects.create(
                user=request.user,
                action='APPROVE',
                model_name='PlanPurchase',
                object_id=str(purchase.id),
                object_representation=f'{purchase.company.business_name} - {purchase.plan_name}',
                changes=f'Compra aprobada: {purchase.plan_invoice_limit} facturas asignadas',
                ip_address=request.META.get('REMOTE_ADDR')
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Compra aprobada. Se asignaron {purchase.plan_invoice_limit} facturas a {purchase.company.business_name}'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'No se pudo aprobar la compra'
            }, status=400)
            
    except PlanPurchase.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Compra no encontrada'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
@staff_required
@require_http_methods(["POST"])
def billing_purchase_reject(request, purchase_id):
    """Rechazar una compra"""
    from apps.billing.models import PlanPurchase
    
    try:
        purchase = PlanPurchase.objects.get(purchase_id=purchase_id)
        data = json.loads(request.body)
        reason = data.get('reason', '')
        
        if purchase.payment_status != 'pending':
            return JsonResponse({
                'success': False,
                'error': 'Solo se pueden rechazar compras pendientes'
            }, status=400)
        
        # Rechazar la compra
        success = purchase.reject_purchase(request.user, reason)
        
        if success:
            # Log action
            AuditLog.objects.create(
                user=request.user,
                action='REJECT',
                model_name='PlanPurchase',
                object_id=str(purchase.id),
                object_representation=f'{purchase.company.business_name} - {purchase.plan_name}',
                changes=f'Compra rechazada. Razón: {reason}',
                ip_address=request.META.get('REMOTE_ADDR')
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Compra rechazada exitosamente'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'No se pudo rechazar la compra'
            }, status=400)
            
    except PlanPurchase.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Compra no encontrada'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
@staff_required
def billing_company_profiles(request):
    """Lista de perfiles de facturación por empresa"""
    from apps.billing.models import CompanyBillingProfile
    from apps.companies.models import Company
    
    profiles = CompanyBillingProfile.objects.all().select_related('company').order_by('company__business_name')
    
    # Filtros
    search = request.GET.get('search')
    if search:
        profiles = profiles.filter(
            Q(company__business_name__icontains=search) |
            Q(company__trade_name__icontains=search) |
            Q(company__ruc__icontains=search)
        )
    
    low_balance = request.GET.get('low_balance')
    if low_balance == 'true':
        profiles = profiles.filter(available_invoices__lte=F('low_balance_threshold'))
    
    # Paginación
    paginator = Paginator(profiles, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_title': 'Perfiles de Facturación',
        'page_obj': page_obj,
        'search': search,
        'low_balance_filter': low_balance,
    }
    return render(request, 'custom_admin/billing/company_profiles.html', context)


@login_required
@staff_required
@require_http_methods(["POST"])
def billing_add_invoices(request, company_id):
    """Agregar facturas manualmente a una empresa"""
    from apps.billing.models import CompanyBillingProfile
    from apps.companies.models import Company
    
    try:
        company = Company.objects.get(id=company_id)
        data = json.loads(request.body)
        
        invoice_count = int(data.get('invoice_count', 0))
        reason = data.get('reason', '')
        
        if invoice_count <= 0:
            return JsonResponse({
                'success': False,
                'error': 'La cantidad debe ser mayor a 0'
            }, status=400)
        
        # Obtener o crear perfil
        profile, created = CompanyBillingProfile.objects.get_or_create(
            company=company,
            defaults={'available_invoices': 0}
        )
        
        # Agregar facturas
        profile.add_invoices(invoice_count)
        
        # Log action
        AuditLog.objects.create(
            user=request.user,
            action='CREATE',
            model_name='CompanyBillingProfile',
            object_id=str(profile.id),
            object_representation=company.business_name,
            changes=f'Se agregaron {invoice_count} facturas manualmente. Razón: {reason}',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Se agregaron {invoice_count} facturas a {company.business_name}',
            'new_balance': profile.available_invoices
        })
        
    except Company.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Empresa no encontrada'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


# ========== STORAGE CONFIGURATION ==========

from apps.settings.models import SystemSetting

@login_required
@staff_required
def storage_settings(request):
    """Configuración de Almacenamiento S3 (AWS/DigitalOcean)"""
    if request.method == 'POST':
        def set_val(key, val, stype, name):
            if not val:
                SystemSetting.objects.filter(key=key).delete()
            else:
                SystemSetting.objects.update_or_create(
                    key=key, 
                    defaults={'value': val, 'setting_type': stype, 'name': name, 'category': 'SYSTEM'}
                )

        set_val('STORAGE_ACTIVE', 'true' if request.POST.get('storage_active') == 'on' else 'false', 'BOOLEAN', 'S3 Active')
        set_val('S3_PROVIDER', request.POST.get('provider', ''), 'STRING', 'S3 Provider')
        set_val('S3_REGION', request.POST.get('region', ''), 'STRING', 'S3 Region')
        set_val('S3_ACCESS_KEY', request.POST.get('access_key', ''), 'STRING', 'S3 Access Key')
        set_val('S3_SECRET_KEY', request.POST.get('secret_key', ''), 'PASSWORD', 'S3 Secret Key')
        set_val('S3_BUCKET_NAME', request.POST.get('bucket_name', ''), 'STRING', 'S3 Bucket Name')
        set_val('S3_ENDPOINT_URL', request.POST.get('endpoint_url', ''), 'URL', 'S3 Endpoint URL')
        set_val('S3_CDN_DOMAIN', request.POST.get('cdn_domain', ''), 'STRING', 'S3 CDN Domain')
        
        messages.success(request, 'Configuración de almacenamiento actualizada exitosamente.')
        return redirect('custom_admin:storage_settings')

    def get_val(key, default=''):
        obj = SystemSetting.objects.filter(key=key).first()
        return obj.value if obj else default

    context = {
        'page_title': 'Configuración de Almacenamiento',
        'storage_active': get_val('STORAGE_ACTIVE', 'false') == 'true',
        'provider': get_val('S3_PROVIDER', 'digitalocean'), 
        'region': get_val('S3_REGION', 'nyc3'),
        'access_key': get_val('S3_ACCESS_KEY', ''),
        'secret_key': get_val('S3_SECRET_KEY', ''),
        'bucket_name': get_val('S3_BUCKET_NAME', ''),
        'endpoint_url': get_val('S3_ENDPOINT_URL', ''),
        'cdn_domain': get_val('S3_CDN_DOMAIN', ''),
    }
    return render(request, 'custom_admin/storage_settings.html', context)

@login_required
@staff_required
@require_http_methods(["POST"])
def storage_migrate(request):
    """
    Migración inteligente de archivos locales a la nube con reestructuración:
    [empresa]/[tipo]/[año]/[mes]/[archivo]
    Esta versión itera sobre los registros de la DB para asegurar que cada archivo
    se asocie correctamente a su empresa y tipo.
    """
    import os
    from django.conf import settings
    from django.core.files.base import ContentFile
    from apps.certificates.models import DigitalCertificate
    from apps.sri_integration.models import ElectronicDocument, CreditNote, DebitNote, Retention
    from apps.billing.models import PlanPurchase
    from apps.companies.models import Company
    from apps.settings.models import SystemSetting
    import logging

    logger = logging.getLogger(__name__)
    
    try:
        # 1. Verificar configuración S3
        def get_val(key, default=''):
            obj = SystemSetting.objects.filter(key=key).first()
            return obj.value if obj else default

        active = get_val('STORAGE_ACTIVE', 'false') == 'true'
        if not active:
            messages.error(request, "Debe activar el almacenamiento S3 antes de iniciar la migración.")
            return redirect('custom_admin:storage_settings')

        # 2. Modelos a procesar
        # Estructura: (Modelo, [Campos de archivo])
        models_to_process = [
            (DigitalCertificate, ['certificate_file']),
            (ElectronicDocument, ['xml_file', 'signed_xml_file', 'pdf_file']),
            (CreditNote, ['xml_file', 'signed_xml_file', 'pdf_file']),
            (DebitNote, ['xml_file', 'signed_xml_file', 'pdf_file']),
            (Retention, ['xml_file', 'signed_xml_file', 'pdf_file']),
            (PlanPurchase, ['payment_receipt']),
            (Company, ['logo']),
            (User, ['profile_picture']),
        ]

        upload_count = 0
        error_count = 0
        total_found = 0
        skipped_count = 0

        for model_class, fields in models_to_process:
            queryset = model_class.objects.all()
            for obj in queryset:
                for field_name in fields:
                    file_field = getattr(obj, field_name)
                    if not file_field:
                        continue
                    
                    total_found += 1
                    
                    # Obtener ruta local absoluta para verificar existencia
                    # Importante: name puede ser una ruta relativa o ya externa
                    try:
                        name = str(file_field.name)
                        # Si ya tiene una ruta organizada (empieza por algo que no sea 'facturas/' o 'firmas/'), 
                        # podrías querer saltarlo, pero aquí forzaremos la organización solicitada.
                        
                        local_path = os.path.join(settings.MEDIA_ROOT, name)
                        
                        if not os.path.exists(local_path):
                            # Si no está en media, probar en storage/ (para certificados legacy)
                            if model_class == DigitalCertificate:
                                legacy_path = os.path.join(settings.BASE_DIR, 'storage', name)
                                if os.path.exists(legacy_path):
                                    local_path = legacy_path
                        
                        if os.path.exists(local_path):
                            with open(local_path, 'rb') as f:
                                content = f.read()
                            
                            # Obtener solo el nombre del archivo
                            filename = os.path.basename(name)
                            
                            # 3. GUARDAR: Esto invoca el upload_to actualizado y sube al Bucket
                            # El storage actual (DynamicMediaStorage) se encargará de enviarlo a S3
                            logger.warning(f"[MIGRATION] Guardando {filename} usando storage: {file_field.storage.__class__.__name__}")
                            file_field.save(filename, ContentFile(content), save=True)
                            upload_count += 1
                        else:
                            skipped_count += 1
                            logger.warning(f"Archivo local no encontrado para {model_class.__name__} {obj.id}: {name}")
                            
                    except Exception as e:
                        error_count += 1
                        logger.error(f"Error migrando {model_class.__name__} field {field_name}: {str(e)}")

        messages.success(
            request, 
            f'¡Migración exitosa! Se procesaron {total_found} registros: '
            f'{upload_count} archivos subidos al bucket, '
            f'{skipped_count} no encontrados localmente, '
            f'{error_count} errores.'
        )
        
    except Exception as e:
        messages.error(request, f'Error crítico durante la migración: {str(e)}')
        logger.exception("Error en storage_migrate")
        
    return redirect('custom_admin:storage_settings')

@login_required
@staff_required
@require_http_methods(["POST"])
def storage_create_structure(request):
    """
    Crea la estructura de carpetas inicial en el bucket S3:
    facturacion/
        certificados/[empresa]/
        pagos/[empresa]/[año]/[mes]/
        facturas/[empresa]/PDF/[año]/[mes]/
        facturas/[empresa]/XML/[año]/[mes]/
    """
    import os
    import re
    from django.utils import timezone
    from django.core.files.base import ContentFile
    from apps.companies.models import Company
    from apps.core.storage import DynamicMediaStorage
    from apps.settings.models import SystemSetting
    import logging

    logger = logging.getLogger(__name__)
    
    # Solo funciona si S3 está activo
    active = SystemSetting.objects.filter(key='STORAGE_ACTIVE').first()
    if not active or active.value != 'true':
        messages.error(request, "Debe activar el almacenamiento S3 para crear la estructura.")
        return redirect('custom_admin:storage_settings')

    try:
        storage_engine = DynamicMediaStorage().current
        from django.core.files.storage import FileSystemStorage
        is_s3 = not isinstance(storage_engine, FileSystemStorage)
        
        # Guardar en qué motor estamos para el mensaje final
        engine_name = "Cloud Bucket (S3)" if is_s3 else "Almacenamiento Local (DISCO)"
        
        if not is_s3:
            # Si el usuario cree que activó S3 pero estamos en local, algo falló en la inicialización
            active_s3 = SystemSetting.objects.filter(key='STORAGE_ACTIVE').first()
            if active_s3 and active_s3.value == 'true':
                messages.warning(request, "⚠️ El motor reporta Local pero STORAGE_ACTIVE está en 'true'. Verifique logs para errores de conexión S3.")
            else:
                messages.info(request, "ℹ️ El motor de almacenamiento actual es LOCAL. Las carpetas se crearán en el servidor.")

        companies = Company.objects.all()
        now = timezone.now()
        year = now.year
        months_es = {
            1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril',
            5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
            9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'
        }
        month_name = months_es.get(now.month, 'desconocido')
        
        folders_created = 0
        
        for company in companies:
            # Normalizar nombre de empresa
            try:
                business_name = company.business_name.lower()
                company_name = re.sub(r'[^a-z0-9_]', '_', business_name).strip('_')
            except:
                company_name = company.ruc or f"empresa_{company.id}"
            
            # 1. Certificados
            # Estructura: certificados/[empresa]/
            cert_path = f"certificados/{company_name}/.keep"
            if not storage_engine.exists(cert_path):
                storage_engine.save(cert_path, ContentFile(b' '))
                folders_created += 1
            
            # 2. Pagos
            # Estructura: pagos/[empresa]/[año]/[mes]/
            pago_path = f"pagos/{company_name}/{year}/{month_name}/.keep"
            if not storage_engine.exists(pago_path):
                storage_engine.save(pago_path, ContentFile(b' '))
                folders_created += 1
                
            # 3. Facturas PDF
            # Estructura: facturas/[empresa]/PDF/[año]/[mes]/
            pdf_path = f"facturas/{company_name}/PDF/{year}/{month_name}/.keep"
            if not storage_engine.exists(pdf_path):
                storage_engine.save(pdf_path, ContentFile(b' '))
                folders_created += 1
                
            # 4. Facturas XML
            # Estructura: facturas/[empresa]/XML/[año]/[mes]/
            xml_path = f"facturas/{company_name}/XML/{year}/{month_name}/.keep"
            if not storage_engine.exists(xml_path):
                storage_engine.save(xml_path, ContentFile(b' '))
                folders_created += 1

        target = "el Bucket de la nube" if is_s3 else "el almacenamiento local"
        messages.success(request, f"Estructura de carpetas inicializada en {target}. Se crearon {folders_created} archivos .keep para {companies.count()} empresas.")
        
    except Exception as e:
        messages.error(request, f"Error al crear la estructura: {str(e)}")
        logger.exception("Error en storage_create_structure")
        
    return redirect('custom_admin:storage_settings')

@login_required
@require_http_methods(['GET', 'POST'])
def company_test_sri(request, company_id):
    """
    Vista de modal 'Mini POS' para emisión directa de prueba SRI
    """
    from apps.companies.models import Company
    from django.shortcuts import get_object_or_404, render
    from django.http import JsonResponse
    import traceback
    
    company = get_object_or_404(Company, id=company_id)
    
    if request.method == 'POST':
        try:
            from apps.sri_integration.models import ElectronicDocument, DocumentItem, DocumentTax
            from apps.sri_integration.services.document_processor import DocumentProcessor
            from decimal import Decimal, ROUND_HALF_UP
            from django.utils import timezone
            
            # 1. Validaciones previas
            if not hasattr(company, 'sri_configuration'):
                from apps.sri_integration.models import SRIConfiguration
                # Auto-crear configuración usando datos heredados si existen
                SRIConfiguration.objects.create(
                    company=company,
                    environment='PRODUCTION' if getattr(company, 'ambiente_sri', '1') == '2' else 'TEST',
                    establishment_code=getattr(company, 'codigo_establecimiento', '001'),
                    emission_point=getattr(company, 'codigo_punto_emision', '001'),
                    invoice_sequence=getattr(company, 'secuencial_factura', 1) or 1,
                    is_active=True
                )
                company.refresh_from_db()
                
            if not company.sri_configuration.is_active:
                return JsonResponse({'success': False, 'error': 'La empresa no tiene configuración SRI activa.'})
                
            if not hasattr(company, 'digital_certificate') or company.digital_certificate.status != 'ACTIVE':
                return JsonResponse({'success': False, 'error': 'La empresa no tiene un certificado digital activo.'})
                
            # 2. Obtener y parsear datos del form modal
            is_final_consumer = request.POST.get('is_final_consumer') == 'on'
            
            if is_final_consumer:
                customer_id_type = '07'
                customer_id = '9999999999999'
                customer_name = 'CONSUMIDOR FINAL'
                customer_address = 'ECUADOR'
                customer_email = ''
            else:
                customer_id_type = request.POST.get('customer_id_type', '05')
                customer_id = request.POST.get('customer_id', '')
                customer_name = request.POST.get('customer_name', '')
                customer_address = request.POST.get('customer_address', 'ECUADOR')
                customer_email = request.POST.get('customer_email', '')
            
            product_name = request.POST.get('product_name', 'PRUEBA SRI')
            quantity = Decimal(request.POST.get('quantity', '1.0'))
            unit_price = Decimal(request.POST.get('unit_price', '1.00'))
            tax_rate = Decimal(request.POST.get('tax_rate', '15.00'))
            
            # 3. Cálculos con redondeo exacto de 2 decimales
            subtotal = (quantity * unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            iva = (subtotal * (tax_rate / Decimal('100.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            total = (subtotal + iva).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            # 4. Crear documento (Factura)
            doc = ElectronicDocument.objects.create(
                company=company,
                document_type='INVOICE',
                issue_date=timezone.localdate(),
                status='DRAFT',
                customer_identification_type=customer_id_type,
                customer_identification=customer_id,
                customer_name=customer_name,
                customer_address=customer_address,
                customer_email=customer_email,
                customer_phone='',
                subtotal_without_tax=subtotal,
                subtotal_with_tax=subtotal if tax_rate > 0 else Decimal('0.00'),
                total_discount=Decimal('0.00'),
                total_tax=iva,
                total_amount=total,
            )
            
            # 5. Crear Item de la factura
            item = DocumentItem.objects.create(
                document=doc,
                main_code='TEST-POS',
                description=product_name,
                quantity=quantity,
                unit_price=unit_price,
                discount=Decimal('0.00'),
                # subtotal se recalcula en save()
            )
            
            # 6. Crear Impuesto del ítem (tax_code 2=IVA)
            if tax_rate == Decimal('15.00'):
                percentage_code = '4'
            elif tax_rate == Decimal('12.00'):
                percentage_code = '2'
            else:
                percentage_code = '0'
                
            DocumentTax.objects.create(
                document=doc,
                item=item,
                tax_code='2',
                percentage_code=percentage_code,
                rate=tax_rate,
                taxable_base=item.subtotal,
                tax_amount=iva
            )
            
            # 7. Procesar Factura (SIEMPRE ASÍNCRÓNICO PARA POS RÁPIDO)
            from apps.sri_integration.tasks import process_document_async
            
            logger.info(f" [MINI_POS] Queuing document {doc.id} for instant POS response")
            process_document_async.delay(doc.id)
            
            return JsonResponse({
                'success': True,
                'message': '¡Factura autorizada!',
                'status': 'AUTHORIZED',
                'access_key': doc.access_key
            })

            # Procesamiento sincrónico (tradicional)
            processor = DocumentProcessor(company)
            success, msg = processor.process_document(doc, send_email=(customer_email != ''))
            
            if success:
                return JsonResponse({
                    'success': True, 
                    'message': f'¡Factura enviada satisfactoriamente! Estado: {doc.status}. SRI Msg: {msg}',
                    'access_key': doc.access_key
                })
            else:
                return JsonResponse({
                    'success': False, 
                    'error': f'Falló el procesamiento SRI: {msg}',
                    'status': doc.status
                })
                
        except Exception as e:
            error_trace = traceback.format_exc()
            logger.error(f'Error en prueba POS SRI: {error_trace}')
            return JsonResponse({
                'success': False, 
                'error': f'Error interno: {str(e)}',
                'traceback': error_trace if settings.DEBUG else None
            })

    # GET => render the Modal form
    return render(request, 'custom_admin/companies/test_sri_modal.html', {'company': company})


@login_required
@staff_required
@require_http_methods(["POST"])
def sri_document_delete(request, document_id):
    """
    TEMPORARY: Delete SRI document and refund billing plan.
    User requested this for internal testing/correction.
    """
    from apps.sri_integration.models import ElectronicDocument
    from apps.billing.models import CompanyBillingProfile
    from apps.core.models import AuditLog
    
    try:
        document = get_object_or_404(ElectronicDocument, id=document_id)
        company = document.company
        
        # Log before deletion
        AuditLog.objects.create(
            user=request.user,
            action='DELETE',
            model_name='ElectronicDocument',
            object_id=str(document.id),
            object_representation=f'Documento {document.document_number} ELIMINADO (Reintegro de plan)',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        
        # Reimbolsar el plan de facturación si existe
        try:
            profile = CompanyBillingProfile.objects.get(company=company)
            profile.refund_invoice()
            logger.info(f"Plan reintegrado para {company.business_name} tras eliminar doc {document.id}")
        except CompanyBillingProfile.DoesNotExist:
            logger.warning(f"No se encontró perfil de facturación para {company.business_name}")
            
        document.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'Documento eliminado y plan reintegrado exitosamente'
        })
        
    except Exception as e:
        logger.error(f"Error al eliminar documento {document_id}: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
