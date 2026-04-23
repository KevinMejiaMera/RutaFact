# -*- coding: utf-8 -*-
"""
Core views - API ONLY VERSION
apps/core/views.py
"""

import logging
from django.db import models
from django.shortcuts import get_object_or_404, render, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from apps.companies.models import Company
from apps.sri_integration.models import SRIConfiguration, ElectronicDocument
from apps.certificates.models import DigitalCertificate
from django.contrib.auth import get_user_model
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

User = get_user_model()

def notify_user_update(user):
    """Notificar al usuario vía WebSocket sobre cambios en su perfil"""
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'user_{user.id}',
            {
                'type': 'user_update',
                'data': {
                    'id': user.id,
                    'can_track': user.can_track,
                    'user_status': user.user_status,
                    'role': user.role,
                    'is_active': user.is_active
                }
            }
        )
    except Exception as e:
        logger.error(f"Error notifying user via WS: {e}")

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
        'frontend': 'Web Dashboard Matrix Ready',
    })

# ==========================================
# VISTAS PARA EL DASHBOARD WEB (MATRIZ)
# ==========================================

def is_admin(user):
    return user.is_staff or user.is_superuser

@login_required
@user_passes_test(is_admin)
def admin_dashboard(request):
    """Vista principal del Dashboard de Administración"""
    # Usamos tu lógica segura para obtener la empresa matriz
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    # Estadísticas básicas
    from django.utils import timezone
    first_day = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    invoices_count = ElectronicDocument.objects.filter(company=company, created_at__gte=first_day).count() if company else 0

    context = {
        'companies': companies,
        'company': company,
        'user': request.user,
        'companies_count': companies.count(),
        'invoices_month': invoices_count,
    }
    return render(request, 'admin/dashboard.html', context)

@login_required
@user_passes_test(is_admin)
def admin_config_sri(request):
    """Vista de configuración del SRI y Firma Electrónica"""
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    config = None
    certificate = None
    
    if company:
        config = SRIConfiguration.objects.filter(company=company, is_active=True).first()
        certificate = DigitalCertificate.objects.filter(company=company, is_active=True).first()
    
    # Obtener usuarios vinculados a esta empresa (Usuarios del Móvil)
    mobile_users = []
    if company:
        # 1. Usuarios con vínculo directo
        # 2. Usuarios asignados vía UserCompanyAssignment (ManyToManyField)
        mobile_users = User.objects.filter(
            models.Q(company=company) | 
            models.Q(company_assignment__assigned_companies=company)
        ).distinct().order_by('email')

    context = {
        'company': company,
        'config': config,
        'certificate': certificate,
        'mobile_users': mobile_users,
        'user': request.user,
    }
    return render(request, 'admin/config_sri.html', context)

@login_required
@user_passes_test(is_admin)
def admin_users_view(request):
    """Vista dedicada para la gestión de Usuarios y Roles"""
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    # Traemos a TODOS los usuarios del sistema para poder asignarlos
    all_users = User.objects.all().order_by('email')

    context = {
        'company': company,
        'mobile_users': all_users, # Ahora enviamos a todos
        'user': request.user,
    }
    return render(request, 'admin/users.html', context)

@login_required
@user_passes_test(is_admin)
def admin_invoices_view(request):
    """Vista para listar todos los comprobantes de la empresa con trazabilidad de usuario"""
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    invoices = []
    if company:
        # Cargamos las facturas y seleccionamos al usuario creador para optimizar la consulta
        invoices = ElectronicDocument.objects.filter(
            company=company
        ).select_related('created_by').order_by('-created_at')

    context = {
        'company': company,
        'invoices': invoices,
        'user': request.user,
    }
    return render(request, 'admin/invoices.html', context)

@login_required
@user_passes_test(is_admin)
def toggle_user_assignment(request, user_id):
    """Vincular o desvincular un usuario de la empresa matriz"""
    if request.method == 'POST':
        target_user = get_object_or_404(User, id=user_id)
        companies = get_user_companies_secure(request.user)
        company = companies.first()
        
        if not company:
            return JsonResponse({'status': 'error', 'message': 'No se detectó empresa matriz'}, status=400)
            
        # Lógica de toggle
        if target_user.company == company:
            target_user.company = None
            message = f"Acceso revocado para {target_user.email}"
            status_text = "revoked"
        else:
            target_user.company = company
            message = f"Acceso concedido para {target_user.email}"
            status_text = "granted"
        
        target_user.save()
        notify_user_update(target_user)
        return JsonResponse({
            'status': 'success', 
            'message': message,
            'assignment': status_text
        })
    
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'}, status=405)
@login_required
@user_passes_test(is_admin)
def update_user_role(request, user_id):
    """Actualizar el rol de un usuario (admin, dispatcher, seller, driver, client)"""
    if request.method == 'POST':
        import json
        try:
            data = json.loads(request.body)
            new_role = data.get('role')
            
            target_user = get_object_or_404(User, id=user_id)
            
            # Validar rol
            if new_role not in dict(User.USER_ROLE_CHOICES):
                return JsonResponse({'status': 'error', 'message': f'Rol inválido: {new_role}'}, status=400)
            
            # Solo permitir si el usuario pertenece a la misma empresa, no tiene empresa, o el admin es superusuario
            companies = get_user_companies_secure(request.user)
            company = companies.first()
            
            if not request.user.is_superuser and target_user.company and target_user.company != company:
                 return JsonResponse({'status': 'error', 'message': 'No tienes permiso para editar este usuario (ya pertenece a otra empresa)'}, status=403)
            
            target_user.role = new_role
            target_user.save()
            notify_user_update(target_user)
            
            return JsonResponse({
                'status': 'success', 
                'message': f'Rol de {target_user.email} actualizado a {target_user.get_role_display()}'
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
            
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'}, status=405)

@login_required
@user_passes_test(is_admin)
def update_user_status(request, user_id):
    """Actualizar el estado del usuario (active, waiting, suspended, rejected)"""
    if request.method == 'POST':
        import json
        try:
            data = json.loads(request.body)
            new_status = data.get('status')
            
            target_user = get_object_or_404(User, id=user_id)
            
            # Validar estado
            if new_status not in dict(User.USER_STATUS_CHOICES):
                return JsonResponse({'status': 'error', 'message': f'Estado inválido: {new_status}'}, status=400)
            
            # Solo permitir si el admin tiene permiso sobre la empresa o es superusuario
            companies = get_user_companies_secure(request.user)
            company = companies.first()
            
            if not request.user.is_superuser and target_user.company and target_user.company != company:
                 return JsonResponse({'status': 'error', 'message': 'No tienes permiso para editar este usuario'}, status=403)
            
            target_user.user_status = new_status
            
            # Sincronizar con is_active de Django si es necesario
            if new_status == 'active':
                target_user.is_active = True
            elif new_status in ['suspended', 'rejected']:
                target_user.is_active = False
                
            target_user.save()
            notify_user_update(target_user)
            
            return JsonResponse({
                'status': 'success', 
                'message': f'Estado de {target_user.email} actualizado a {target_user.get_user_status_display()}'
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
            
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'}, status=405)

@login_required
@user_passes_test(is_admin)
def toggle_user_tracking(request, user_id):
    """Activar/Desactivar permiso de rastreo GPS"""
    if request.method == 'POST':
        target_user = get_object_or_404(User, id=user_id)
        
        # Validar permisos (admin de empresa o superusuario)
        companies = get_user_companies_secure(request.user)
        company = companies.first()
        
        if not request.user.is_superuser and target_user.company and target_user.company != company:
             return JsonResponse({'status': 'error', 'message': 'No tienes permiso para editar este usuario'}, status=403)
        
        target_user.can_track = not target_user.can_track
        target_user.save()
        notify_user_update(target_user)
        
        return JsonResponse({
            'status': 'success', 
            'message': f'Rastreo {"activado" if target_user.can_track else "desactivado"} para {target_user.email}',
            'can_track': target_user.can_track
        })
        
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'}, status=405)
