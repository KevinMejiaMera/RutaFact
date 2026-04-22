# -*- coding: utf-8 -*-
"""
Configuración principal de Celery para RutaFact_SRI
rutafact_sri/celery.py

Configuración de Celery con Redis como broker
✅ CONFIGURACIÓN PARA AUTORIZACIÓN AUTOMÁTICA
✅ TAREAS PERIÓDICAS CONFIGURADAS
✅ ROUTING Y QUEUES OPTIMIZADOS
"""

import os
from celery import Celery
from django.conf import settings

# Configurar Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rutafact.settings')

# Crear aplicación Celery
app = Celery('rutafact')

# Configuración desde Django settings con prefijo CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-descubrir tareas en todas las apps Django
app.autodiscover_tasks()

# ==========================================
# CONFIGURACIÓN ADICIONAL DE CELERY
# ==========================================

# Configuración de la aplicación
app.conf.update(
    # Configuración de workers
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    worker_max_tasks_per_child=1000,
    
    # Configuración de tareas
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone=settings.TIME_ZONE,
    enable_utc=True,
    
    # Configuración de routing
    task_routes={
        'apps.sri_integration.tasks.check_document_authorization_async': {
            'queue': 'sri_authorization',
            'routing_key': 'sri.authorization',
        },
        'apps.sri_integration.tasks.process_document_async': {
            'queue': 'sri_processing',
            'routing_key': 'sri.processing',
        },
        'apps.sri_integration.tasks.check_all_pending_authorizations': {
            'queue': 'sri_maintenance',
            'routing_key': 'sri.maintenance',
        },
        'apps.sri_integration.tasks.cleanup_old_sri_responses': {
            'queue': 'sri_maintenance',
            'routing_key': 'sri.maintenance',
        },
        'apps.sri_integration.tasks.send_authorization_notification_email': {
            'queue': 'sri_notifications',
            'routing_key': 'sri.notifications',
        },
        'apps.sri_integration.tasks.bulk_process_documents': {
            'queue': 'sri_bulk',
            'routing_key': 'sri.bulk',
        },
        'apps.sri_integration.tasks.retry_failed_documents': {
            'queue': 'sri_maintenance',
            'routing_key': 'sri.maintenance',
        },
        'apps.sri_integration.tasks.generate_daily_report': {
            'queue': 'sri_reports',
            'routing_key': 'sri.reports',
        },
    },
    
    # Configuración de colas
    task_default_queue='celery',  # ✅ Solo una vez aquí
    task_default_exchange='default',
    task_default_exchange_type='direct',
    task_default_routing_key='default',
    
    # TTL para resultados
    result_expires=3600,  # 1 hora
    
    # Configuración de reintentos por defecto
    task_default_max_retries=3,
    task_default_retry_delay=60,
    
    # Configuración de monitoreo
    worker_send_task_events=True,
    task_send_sent_event=True,
    
    # Configuración de logging
    worker_hijack_root_logger=False,
    # ❌ ELIMINADO: task_default_queue='celery', - era duplicado
    
    # Configuración de beat schedule (tareas periódicas)
    beat_schedule={
        # Verificar autorizaciones pendientes cada 5 minutos
        'check-pending-authorizations': {
            'task': 'apps.sri_integration.tasks.check_all_pending_authorizations',
            'schedule': 300.0,  # 5 minutos
            'options': {'queue': 'sri_maintenance'}
        },
        
        # Limpiar respuestas SRI antiguas cada 24 horas a las 02:00
        'cleanup-old-sri-responses': {
            'task': 'apps.sri_integration.tasks.cleanup_old_sri_responses',
            'schedule': 86400.0,  # 24 horas
            'options': {'queue': 'sri_maintenance'}
        },
        
        # Reintentar documentos fallidos cada 2 horas
        'retry-failed-documents': {
            'task': 'apps.sri_integration.tasks.retry_failed_documents',
            'schedule': 7200.0,  # 2 horas
            'options': {'queue': 'sri_maintenance'}
        },
        
        # Generar reporte diario a las 23:00
        'generate-daily-report': {
            'task': 'apps.sri_integration.tasks.generate_daily_report',
            'schedule': 86400.0,  # 24 horas
            'options': {'queue': 'sri_reports'}
        },
    },
    
    # Configuración de timezone para beat
    beat_scheduler='celery.beat:PersistentScheduler',
)

# ==========================================
# TAREAS DE DEBUG Y TESTING
# ==========================================

@app.task(bind=True)
def debug_task(self):
    """Tarea de debug para verificar que Celery funciona"""
    print(f'Request: {self.request!r}')
    return f'Debug task executed successfully at {settings.TIME_ZONE}'

@app.task
def test_sri_connection():
    """Tarea de test para verificar conexión con SRI"""
    try:
        from apps.sri_integration.services.soap_client import SRISOAPClient
        from apps.companies.models import Company
        
        # Obtener primera empresa activa
        company = Company.objects.filter(is_active=True).first()
        
        if not company:
            return {'success': False, 'message': 'No active company found'}
        
        # Test de conexión
        sri_client = SRISOAPClient(company)
        results = sri_client.test_connection()
        
        return {
            'success': True,
            'results': results,
            'company': company.business_name
        }
        
    except Exception as e:
        return {'success': False, 'error': str(e)}

# ==========================================
# CONFIGURACIÓN DE LOGGING PARA CELERY
# ==========================================

@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Configurar tareas periódicas adicionales si es necesario"""
    # Aquí puedes agregar tareas periódicas adicionales dinámicamente
    pass

@app.on_after_finalize.connect
def setup_queues(sender, **kwargs):
    """Configurar colas adicionales si es necesario"""
    # Configuración adicional de colas
    pass

# ==========================================
# SIGNALS Y HANDLERS
# ==========================================

from celery.signals import task_prerun, task_postrun, task_failure

@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds):
    """Handler ejecutado antes de cada tarea"""
    print(f'[CELERY] Starting task {task.name} with ID {task_id}')

@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **kwds):
    """Handler ejecutado después de cada tarea"""
    print(f'[CELERY] Completed task {task.name} with ID {task_id} - State: {state}')

@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, einfo=None, **kwds):
    """Handler ejecutado cuando una tarea falla"""
    print(f'[CELERY] Task {sender.name} with ID {task_id} failed: {exception}')

# ==========================================
# FUNCIÓN DE INICIALIZACIÓN
# ==========================================

def initialize_celery():
    """
    Función para inicializar Celery con verificaciones de salud
    """
    try:
        # Verificar conexión con broker
        inspector = app.control.inspect()
        stats = inspector.stats()
        
        if stats:
            print("Celery broker connection successful")
            return True
        else:
            print("Celery broker connection failed")
            return False
            
    except Exception as e:
        print(f"Error initializing Celery: {e}")
        return False

# ==========================================
# CONFIGURACIÓN PARA DESARROLLO
# ==========================================

if settings.DEBUG:
    # En desarrollo, configuraciones más permisivas
    app.conf.update(
        task_always_eager=getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False),
        task_eager_propagates=True,
        task_store_eager_result=True,
    )
    
    print("Celery configured for development mode")
else:
    print("Celery configured for production mode")

# ==========================================
# INFORMACIÓN DE CONFIGURACIÓN
# ==========================================

print(f"Celery App: {app.main}")
print(f"Broker: {app.conf.broker_url}")
print(f"Result Backend: {app.conf.result_backend}")
print(f"Timezone: {app.conf.timezone}")
print(f"Beat Schedule: {len(app.conf.beat_schedule)} periodic tasks configured")

# Exportar la aplicación para uso en manage.py y otros lugares
celery_app = app
