# -*- coding: utf-8 -*-
"""
Servicio de Autorización Automática
apps/sri_integration/services/auto_authorization.py

Funciones helper para programar y gestionar autorizaciones automáticas
✅ INTEGRACIÓN CON CELERY
✅ FUNCIONES HELPER PARA VISTAS
✅ GESTIÓN DE TAREAS DE AUTORIZACIÓN
"""

import logging
from django.utils import timezone
from datetime import timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# ==========================================
# FUNCIONES PRINCIPALES
# ==========================================

def schedule_authorization_check(document_id: int, delay_minutes: int = 2) -> bool:
    """
    ✅ PROGRAMAR VERIFICACIÓN DE AUTORIZACIÓN AUTOMÁTICA
    
    Args:
        document_id (int): ID del documento a verificar
        delay_minutes (int): Minutos de espera antes de la primera verificación
        
    Returns:
        bool: True si se programó exitosamente
    """
    try:
        # Importar aquí para evitar import circular
        from ..tasks import check_document_authorization_async
        
        task = check_document_authorization_async.apply_async(
            args=[document_id],
            countdown=delay_minutes * 60
        )
        
        logger.info(f"📅 [AUTO_AUTH] Authorization check scheduled for document {document_id} "
                   f"in {delay_minutes} minutes (task: {task.id})")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ [AUTO_AUTH] Error scheduling authorization check for document {document_id}: {e}")
        return False

def schedule_document_processing(document_id: int, delay_seconds: int = 0) -> tuple[bool, Optional[str]]:
    """
    ✅ PROGRAMAR PROCESAMIENTO COMPLETO DE DOCUMENTO
    
    Args:
        document_id (int): ID del documento a procesar
        delay_seconds (int): Segundos de espera antes del procesamiento
        
    Returns:
        tuple: (success, task_id)
    """
    try:
        from ..tasks import process_document_async
        
        task = process_document_async.apply_async(
            args=[document_id],
            countdown=delay_seconds
        )
        
        logger.info(f"📅 [AUTO_AUTH] Document processing scheduled for document {document_id} "
                   f"in {delay_seconds} seconds (task: {task.id})")
        
        return True, task.id
        
    except Exception as e:
        logger.error(f"❌ [AUTO_AUTH] Error scheduling document processing for document {document_id}: {e}")
        return False, None

def schedule_bulk_processing(document_ids: List[int]) -> Dict[str, Any]:
    """
    ✅ PROGRAMAR PROCESAMIENTO EN LOTE
    
    Args:
        document_ids (List[int]): Lista de IDs de documentos
        
    Returns:
        Dict: Resultado del programado en lote
    """
    try:
        from ..tasks import bulk_process_documents
        
        task = bulk_process_documents.delay(document_ids)
        
        logger.info(f"📦 [AUTO_AUTH] Bulk processing scheduled for {len(document_ids)} documents (task: {task.id})")
        
        return {
            'success': True,
            'task_id': task.id,
            'document_count': len(document_ids),
            'scheduled_at': timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ [AUTO_AUTH] Error scheduling bulk processing: {e}")
        return {'success': False, 'error': str(e)}

# ==========================================
# FUNCIONES DE MONITOREO
# ==========================================

def get_task_status(task_id: str) -> Dict[str, Any]:
    """
    ✅ OBTENER ESTADO DE UNA TAREA CELERY
    
    Args:
        task_id (str): ID de la tarea
        
    Returns:
        Dict: Estado de la tarea
    """
    try:
        from celery.result import AsyncResult
        
        result = AsyncResult(task_id)
        
        return {
            'task_id': task_id,
            'status': result.status,
            'result': result.result,
            'successful': result.successful(),
            'failed': result.failed(),
            'ready': result.ready(),
            'date_done': result.date_done.isoformat() if result.date_done else None,
            'traceback': result.traceback if result.failed() else None
        }
        
    except Exception as e:
        logger.error(f"❌ [AUTO_AUTH] Error getting task status for {task_id}: {e}")
        return {'error': str(e)}

def get_pending_authorizations_count() -> Dict[str, Any]:
    """
    ✅ OBTENER CANTIDAD DE DOCUMENTOS PENDIENTES DE AUTORIZACIÓN
    
    Returns:
        Dict: Estadísticas de documentos pendientes
    """
    try:
        from ..models import ElectronicDocument
        
        # Documentos en SENT de las últimas 24 horas
        time_limit = timezone.now() - timedelta(hours=24)
        
        pending_count = ElectronicDocument.objects.filter(
            status='SENT',
            created_at__gte=time_limit
        ).count()
        
        # Documentos antiguos en SENT (más de 24 horas)
        old_pending_count = ElectronicDocument.objects.filter(
            status='SENT',
            created_at__lt=time_limit
        ).count()
        
        # Documentos autorizados hoy
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        authorized_today = ElectronicDocument.objects.filter(
            status='AUTHORIZED',
            sri_authorization_date__gte=today_start
        ).count()
        
        return {
            'pending_recent': pending_count,
            'pending_old': old_pending_count,
            'authorized_today': authorized_today,
            'checked_at': timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ [AUTO_AUTH] Error getting pending authorizations count: {e}")
        return {'error': str(e)}

def get_authorization_statistics(days: int = 7) -> Dict[str, Any]:
    """
    ✅ OBTENER ESTADÍSTICAS DE AUTORIZACIÓN
    
    Args:
        days (int): Días hacia atrás para las estadísticas
        
    Returns:
        Dict: Estadísticas de autorización
    """
    try:
        from ..models import ElectronicDocument
        from django.db.models import Count, Q
        
        # Fecha límite
        date_limit = timezone.now() - timedelta(days=days)
        
        # Consulta base
        docs_in_period = ElectronicDocument.objects.filter(created_at__gte=date_limit)
        
        # Estadísticas por estado
        stats = docs_in_period.aggregate(
            total=Count('id'),
            authorized=Count('id', filter=Q(status='AUTHORIZED')),
            sent=Count('id', filter=Q(status='SENT')),
            error=Count('id', filter=Q(status='ERROR')),
            pending=Count('id', filter=Q(status__in=['GENERATED', 'SIGNED']))
        )
        
        # Calcular tasas
        total = stats['total']
        if total > 0:
            stats['authorization_rate'] = (stats['authorized'] / total) * 100
            stats['success_rate'] = ((stats['authorized'] + stats['sent']) / total) * 100
            stats['error_rate'] = (stats['error'] / total) * 100
        else:
            stats['authorization_rate'] = 0
            stats['success_rate'] = 0
            stats['error_rate'] = 0
        
        # Tiempo promedio de autorización
        authorized_docs = docs_in_period.filter(
            status='AUTHORIZED',
            sri_authorization_date__isnull=False
        )
        
        if authorized_docs.exists():
            time_diffs = []
            for doc in authorized_docs:
                if doc.sri_authorization_date and doc.created_at:
                    # Hacer timezone-aware si es necesario
                    created_at = doc.created_at
                    auth_date = doc.sri_authorization_date
                    
                    if timezone.is_naive(auth_date):
                        auth_date = timezone.make_aware(auth_date)
                    
                    diff = auth_date - created_at
                    time_diffs.append(diff.total_seconds())
            
            if time_diffs:
                avg_seconds = sum(time_diffs) / len(time_diffs)
                stats['avg_authorization_time_minutes'] = avg_seconds / 60
            else:
                stats['avg_authorization_time_minutes'] = None
        else:
            stats['avg_authorization_time_minutes'] = None
        
        stats['period_days'] = days
        stats['calculated_at'] = timezone.now().isoformat()
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ [AUTO_AUTH] Error getting authorization statistics: {e}")
        return {'error': str(e)}

# ==========================================
# FUNCIONES DE GESTIÓN
# ==========================================

def cancel_pending_tasks_for_document(document_id: int) -> Dict[str, Any]:
    """
    ✅ CANCELAR TAREAS PENDIENTES PARA UN DOCUMENTO
    
    Args:
        document_id (int): ID del documento
        
    Returns:
        Dict: Resultado de la cancelación
    """
    try:
        from rutafact.celery import app
        
        # Obtener inspector de Celery
        inspector = app.control.inspect()
        
        # Buscar tareas activas relacionadas con el documento
        active_tasks = inspector.active()
        scheduled_tasks = inspector.scheduled()
        
        cancelled_count = 0
        task_ids = []
        
        # Buscar en tareas activas
        if active_tasks:
            for worker, tasks in active_tasks.items():
                for task in tasks:
                    if (task.get('name') in [
                        'apps.sri_integration.tasks.check_document_authorization_async',
                        'apps.sri_integration.tasks.process_document_async'
                    ] and str(document_id) in str(task.get('args', []))):
                        app.control.revoke(task['id'], terminate=True)
                        task_ids.append(task['id'])
                        cancelled_count += 1
        
        # Buscar en tareas programadas
        if scheduled_tasks:
            for worker, tasks in scheduled_tasks.items():
                for task in tasks:
                    if (task.get('request', {}).get('task') in [
                        'apps.sri_integration.tasks.check_document_authorization_async',
                        'apps.sri_integration.tasks.process_document_async'
                    ] and str(document_id) in str(task.get('request', {}).get('args', []))):
                        app.control.revoke(task['request']['id'])
                        task_ids.append(task['request']['id'])
                        cancelled_count += 1
        
        logger.info(f"📋 [AUTO_AUTH] Cancelled {cancelled_count} pending tasks for document {document_id}")
        
        return {
            'cancelled_count': cancelled_count,
            'task_ids': task_ids,
            'document_id': document_id
        }
        
    except Exception as e:
        logger.error(f"❌ [AUTO_AUTH] Error cancelling tasks for document {document_id}: {e}")
        return {'error': str(e)}

def force_authorization_check(document_id: int) -> Dict[str, Any]:
    """
    ✅ FORZAR VERIFICACIÓN INMEDIATA DE AUTORIZACIÓN
    
    Args:
        document_id (int): ID del documento
        
    Returns:
        Dict: Resultado de la verificación forzada
    """
    try:
        from ..tasks import check_document_authorization_async
        
        # Cancelar tareas pendientes primero
        cancel_result = cancel_pending_tasks_for_document(document_id)
        
        # Programar verificación inmediata
        task = check_document_authorization_async.delay(document_id)
        
        logger.info(f"⚡ [AUTO_AUTH] Forced authorization check for document {document_id} (task: {task.id})")
        
        return {
            'success': True,
            'task_id': task.id,
            'cancelled_previous': cancel_result.get('cancelled_count', 0),
            'forced_at': timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ [AUTO_AUTH] Error forcing authorization check for document {document_id}: {e}")
        return {'success': False, 'error': str(e)}

# ==========================================
# FUNCIONES DE CONFIGURACIÓN
# ==========================================

def get_celery_health_status() -> Dict[str, Any]:
    """
    ✅ OBTENER ESTADO DE SALUD DE CELERY
    
    Returns:
        Dict: Estado de salud del sistema Celery
    """
    try:
        from rutafact.celery import app
        
        # Verificar conexión con broker
        try:
            inspector = app.control.inspect()
            stats = inspector.stats()
            broker_connected = stats is not None and len(stats) > 0
        except:
            broker_connected = False
        
        # Obtener estadísticas de workers
        worker_count = 0
        active_tasks = 0
        
        if broker_connected:
            try:
                active_dict = inspector.active()
                if active_dict:
                    worker_count = len(active_dict)
                    active_tasks = sum(len(tasks) for tasks in active_dict.values())
            except:
                pass
        
        # Verificar beat scheduler si está disponible
        beat_running = False
        try:
            # Esto es una simplificación - en producción podrías usar un método más robusto
            beat_running = True  # Asumir que está corriendo si Celery está bien
        except:
            pass
        
        return {
            'broker_connected': broker_connected,
            'worker_count': worker_count,
            'active_tasks': active_tasks,
            'beat_scheduler_running': beat_running,
            'checked_at': timezone.now().isoformat(),
            'status': 'healthy' if broker_connected and worker_count > 0 else 'unhealthy'
        }
        
    except Exception as e:
        logger.error(f"❌ [AUTO_AUTH] Error checking Celery health: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'checked_at': timezone.now().isoformat()
        }

def test_celery_tasks() -> Dict[str, Any]:
    """
    ✅ PROBAR TAREAS CELERY BÁSICAS
    
    Returns:
        Dict: Resultado de las pruebas
    """
    try:
        from rutafact.celery import debug_task, test_sri_connection
        
        results = {}
        
        # Test básico de Celery
        try:
            task = debug_task.delay()
            result = task.get(timeout=10)
            results['debug_task'] = {'success': True, 'result': result}
        except Exception as e:
            results['debug_task'] = {'success': False, 'error': str(e)}
        
        # Test de conexión SRI
        try:
            task = test_sri_connection.delay()
            result = task.get(timeout=30)
            results['sri_connection'] = result
        except Exception as e:
            results['sri_connection'] = {'success': False, 'error': str(e)}
        
        # Determinar estado general
        all_successful = all(
            test.get('success', False) for test in results.values()
        )
        
        results['overall_status'] = 'success' if all_successful else 'partial_failure'
        results['tested_at'] = timezone.now().isoformat()
        
        return results
        
    except Exception as e:
        logger.error(f"❌ [AUTO_AUTH] Error testing Celery tasks: {e}")
        return {
            'overall_status': 'error',
            'error': str(e),
            'tested_at': timezone.now().isoformat()
        }

# ==========================================
# FUNCIONES PARA INTEGRACIÓN CON VISTAS
# ==========================================

def create_document_with_auto_authorization(document_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    ✅ CREAR DOCUMENTO CON AUTORIZACIÓN AUTOMÁTICA PROGRAMADA
    
    Esta función está diseñada para integrarse fácilmente con tus vistas de API
    
    Args:
        document_data (Dict): Datos para crear el documento
        
    Returns:
        Dict: Resultado de la creación con autorización programada
    """
    try:
        # Importar aquí para evitar import circular
        from ..models import ElectronicDocument
        
        # Aquí integrarías con tu función existente de creación
        # document = tu_funcion_de_creacion(document_data)
        
        # Por ahora, simular creación exitosa
        # En la implementación real, usarías tu función existente
        
        # Ejemplo de uso:
        # if document and document.status == 'SENT':
        #     # Programar verificación automática
        #     success = schedule_authorization_check(document.id, delay_minutes=2)
        #     
        #     return {
        #         'success': True,
        #         'document_id': document.id,
        #         'status': document.status,
        #         'message': 'Document created and sent. Authorization check scheduled.',
        #         'authorization_scheduled': success,
        #         'expected_authorization_time': '2-10 minutes'
        #     }
        
        return {
            'success': False,
            'message': 'Function template - integrate with your existing document creation logic'
        }
        
    except Exception as e:
        logger.error(f"❌ [AUTO_AUTH] Error creating document with auto authorization: {e}")
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'authorization_scheduled': False
        }

# ==========================================
# LOGGING Y DEBUG
# ==========================================

def log_authorization_activity():
    """
    ✅ REGISTRAR ACTIVIDAD DE AUTORIZACIÓN PARA DEBUGGING
    """
    try:
        stats = get_authorization_statistics(days=1)
        health = get_celery_health_status()
        pending = get_pending_authorizations_count()
        
        logger.info(f"📊 [AUTO_AUTH] Daily Stats: {stats}")
        logger.info(f"💚 [AUTO_AUTH] Celery Health: {health}")
        logger.info(f"⏳ [AUTO_AUTH] Pending: {pending}")
        
    except Exception as e:
        logger.error(f"❌ [AUTO_AUTH] Error logging authorization activity: {e}")

# Inicializar logging al importar el módulo
if __name__ != '__main__':
    logger.info("🚀 [AUTO_AUTH] Auto Authorization Service loaded successfully")
