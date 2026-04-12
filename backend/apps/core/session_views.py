# -*- coding: utf-8 -*-
"""
Session Management Views
Endpoints para gestión de sesión y heartbeat
"""

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
import json


@login_required
@require_http_methods(["POST"])
def session_heartbeat(request):
    """
    Endpoint para mantener la sesión activa (heartbeat)
    El cliente JavaScript llama a este endpoint periódicamente
    """
    try:
        # Actualizar última actividad
        request.session['last_activity'] = timezone.now().isoformat()
        
        # Calcular tiempo restante
        timeout = getattr(settings, 'SESSION_COOKIE_AGE', 3600)
        
        return JsonResponse({
            'status': 'ok',
            'session_active': True,
            'timeout_seconds': timeout,
            'server_time': timezone.now().isoformat()
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def check_session_status(request):
    """
    Verificar el estado de la sesión y tiempo restante
    """
    try:
        # Obtener última actividad
        last_activity_str = request.session.get('last_activity')
        timeout = getattr(settings, 'SESSION_COOKIE_AGE', 3600)
        warning_time = getattr(settings, 'SESSION_TIMEOUT_WARNING', 300)
        
        if last_activity_str:
            last_activity = timezone.datetime.fromisoformat(last_activity_str)
            elapsed = (timezone.now() - last_activity).total_seconds()
            time_remaining = max(0, timeout - elapsed)
            
            # Determinar estado
            if time_remaining <= 0:
                status = 'expired'
            elif time_remaining <= warning_time:
                status = 'warning'
            else:
                status = 'active'
            
            return JsonResponse({
                'status': status,
                'time_remaining': int(time_remaining),
                'timeout_seconds': timeout,
                'warning_seconds': warning_time,
                'last_activity': last_activity_str,
                'show_warning': time_remaining <= warning_time and time_remaining > 0
            })
        else:
            # Primera actividad
            request.session['last_activity'] = timezone.now().isoformat()
            return JsonResponse({
                'status': 'active',
                'time_remaining': timeout,
                'timeout_seconds': timeout,
                'warning_seconds': warning_time,
                'show_warning': False
            })
            
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def extend_session(request):
    """
    Extender la sesión cuando el usuario lo solicite
    """
    try:
        # Resetear el tiempo de actividad
        request.session['last_activity'] = timezone.now().isoformat()
        request.session['session_extended'] = True
        
        timeout = getattr(settings, 'SESSION_COOKIE_AGE', 3600)
        
        return JsonResponse({
            'status': 'success',
            'message': 'Sesión extendida exitosamente',
            'new_timeout': timeout,
            'extended_at': timezone.now().isoformat()
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_session_info(request):
    """
    Obtener información detallada de la sesión
    """
    try:
        timeout = getattr(settings, 'SESSION_COOKIE_AGE', 3600)
        warning_time = getattr(settings, 'SESSION_TIMEOUT_WARNING', 300)
        
        # Información de actividad
        last_activity_str = request.session.get('last_activity')
        last_real_activity_str = request.session.get('last_real_activity')
        activity_log = request.session.get('activity_log', [])
        
        info = {
            'user': {
                'id': request.user.id,
                'email': request.user.email,
                'full_name': request.user.get_full_name(),
                'is_staff': request.user.is_staff
            },
            'session': {
                'timeout_seconds': timeout,
                'warning_seconds': warning_time,
                'last_activity': last_activity_str,
                'last_real_activity': last_real_activity_str,
                'session_extended': request.session.get('session_extended', False),
                'activity_count': len(activity_log)
            },
            'settings': {
                'auto_logout_enabled': True,
                'show_warnings': True,
                'heartbeat_interval': 60  # segundos
            }
        }
        
        # Calcular tiempo restante si hay actividad
        if last_activity_str:
            last_activity = timezone.datetime.fromisoformat(last_activity_str)
            elapsed = (timezone.now() - last_activity).total_seconds()
            info['session']['time_remaining'] = max(0, timeout - elapsed)
        
        return JsonResponse(info)
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)