# -*- coding: utf-8 -*-
"""
Views for users app
Vistas para gestión de usuarios y sala de espera
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone
from django.contrib.auth import logout
import datetime
from .models import UserCompanyAssignment, AdminNotification


@login_required
def waiting_room_view(request):
    """Vista de sala de espera para usuarios no asignados"""
    
    # Si es admin/staff, redirigir al admin
    if request.user.is_staff or request.user.is_superuser:
        return redirect('admin:index')
    
    # Obtener o crear asignación del usuario
    assignment, created = UserCompanyAssignment.objects.get_or_create(
        user=request.user,
        defaults={'status': 'waiting'}
    )
    
    # Si ya está asignado, redirigir al dashboard
    if assignment.is_assigned():
        return redirect('core:dashboard')
    
    # Si está rechazado, mostrar mensaje
    if assignment.status == 'rejected':
        context = {
            'status': 'rejected',
            'message': 'Tu solicitud de acceso ha sido rechazada.',
            'notes': assignment.notes
        }
        return render(request, 'users/waiting_room.html', context)
    
    # Si está suspendido
    if assignment.status == 'suspended':
        context = {
            'status': 'suspended',
            'message': 'Tu cuenta ha sido suspendida.',
            'notes': assignment.notes
        }
        return render(request, 'users/waiting_room.html', context)
    
    # Sala de espera normal
    context = {
        'status': 'waiting',
        'message': 'Tu solicitud está siendo procesada.',
        'assignment': assignment,
        'user': request.user
    }
    
    return render(request, 'users/waiting_room.html', context)


@login_required
@require_http_methods(["GET"])
def check_assignment_status(request):
    """API para verificar el estado de asignación (AJAX)"""
    
    if request.user.is_staff or request.user.is_superuser:
        return JsonResponse({'status': 'admin', 'redirect': '/admin/'})
    
    try:
        assignment = UserCompanyAssignment.objects.get(user=request.user)
        
        if assignment.is_assigned():
            return JsonResponse({
                'status': 'assigned',
                'redirect': '/dashboard/',
                'companies': [str(comp) for comp in assignment.get_assigned_companies()]
            })
        
        return JsonResponse({
            'status': assignment.status,
            'message': assignment.notes if assignment.notes else None
        })
        
    except UserCompanyAssignment.DoesNotExist:
        # Crear asignación si no existe
        UserCompanyAssignment.objects.create(user=request.user, status='waiting')
        return JsonResponse({'status': 'waiting'})


class CheckUserAccessMiddleware(MiddlewareMixin):
    """Middleware para verificar acceso de usuarios"""
    
    def process_request(self, request):
        # Rutas que no requieren verificación
        exempt_paths = [
            '/accounts/',
            '/admin/',
            '/users/waiting-room/',
            '/users/api/check-assignment/',
            '/health/',
            '/static/',
            '/media/',
            '/__debug__/'
        ]
        
        # Si la ruta está exenta, continuar
        if any(request.path.startswith(path) for path in exempt_paths):
            return None
        
        # Si no está autenticado, continuar (será manejado por @login_required)
        if not request.user.is_authenticated:
            return None
        
        # Si es admin/staff, continuar
        if request.user.is_staff or request.user.is_superuser:
            return None
        
        # Verificar asignación para usuarios normales
        try:
            assignment = UserCompanyAssignment.objects.get(user=request.user)
            
            # Si no está asignado, redirigir a sala de espera
            if not assignment.is_assigned():
                return redirect('users:waiting_room')
                
        except UserCompanyAssignment.DoesNotExist:
            # Si no tiene asignación, crear una y redirigir a sala de espera
            UserCompanyAssignment.objects.create(user=request.user, status='waiting')
            return redirect('users:waiting_room')
        
        return None
    
class SimpleSessionTimeoutMiddleware(MiddlewareMixin):
    """Middleware simple para timeout de sesión"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Rutas exentas del timeout
        exempt_paths = [
            '/accounts/login/',
            '/accounts/logout/',
            '/users/login/',
            '/static/',
            '/media/',
            '/admin/login/',
        ]
        
        # DEBUG: Imprimir ruta actual
        print(f"[SESSION DEBUG] Path: {request.path}")
        
        # Si la ruta está exenta, continuar
        if any(request.path.startswith(path) for path in exempt_paths):
            response = self.get_response(request)
            return response
        
        # Solo verificar para usuarios autenticados
        if request.user.is_authenticated:
            print(f"[SESSION DEBUG] Usuario autenticado: {request.user.email}")
            
            # Obtener última actividad
            last_activity = request.session.get('last_activity')
            print(f"[SESSION DEBUG] Última actividad: {last_activity}")
            
            # Si hay última actividad, verificar timeout
            if last_activity:
                try:
                    # Convertir string ISO a datetime
                    last_activity_time = datetime.datetime.fromisoformat(last_activity)
                    # Hacer timezone-aware si es necesario
                    if timezone.is_naive(last_activity_time):
                        last_activity_time = timezone.make_aware(last_activity_time)
                    
                    time_since_activity = timezone.now() - last_activity_time
                    seconds_since = time_since_activity.total_seconds()
                    
                    print(f"[SESSION DEBUG] Segundos desde última actividad: {seconds_since}")
                    
                    # Verificar si excedió el tiempo
                    if seconds_since > 3600:
                        print("[SESSION DEBUG] ¡SESIÓN EXPIRADA! Cerrando sesión...")
                        
                        # Cerrar sesión
                        logout(request)
                        
                        # Agregar mensaje
                        messages.warning(
                            request, 
                            'Tu sesión ha expirado por inactividad. Por favor, inicia sesión nuevamente.'
                        )
                        
                        # Si es AJAX, retornar JSON
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({
                                'session_expired': True,
                                'redirect_url': '/accounts/login/'
                            }, status=401)
                        
                        # Si no es AJAX, redirigir
                        return redirect('account_login')
                        
                except (ValueError, TypeError) as e:
                    # Si hay error parseando la fecha, resetear
                    print(f"[SESSION DEBUG] Error parseando last_activity: {e}")
                    request.session['last_activity'] = timezone.now().isoformat()
            
            # Actualizar última actividad
            request.session['last_activity'] = timezone.now().isoformat()
            request.session.modified = True  # Forzar guardado de sesión
            print(f"[SESSION DEBUG] Actualizando última actividad: {request.session['last_activity']}")
        
        response = self.get_response(request)
        return response