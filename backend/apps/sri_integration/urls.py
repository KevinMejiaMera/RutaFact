# -*- coding: utf-8 -*-
"""
apps/sri_integration/urls.py - URLs COMPLETAS CON APIS DE CELERY
URLs for sri_integration app con descarga de documentos y monitoreo Celery
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SRIConfigurationViewSet, ElectronicDocumentViewSet,
    DocumentItemViewSet, SRIResponseViewSet,
    # Vistas de descarga existentes
    download_document_pdf, download_document_xml, 
    check_document_files, generate_missing_files,
    # Nuevas vistas de Celery
    celery_status, document_task_status, trigger_document_processing,
    stop_document_processing, get_user_active_tasks, get_task_status,
    get_queue_stats, get_documents_with_task_status, 
    process_document_with_celery, dashboard_with_celery_stats,
    test_celery_connection
)

app_name = 'sri_integration'

router = DefaultRouter()
router.register(r'configurations', SRIConfigurationViewSet)
router.register(r'documents', ElectronicDocumentViewSet)
router.register(r'items', DocumentItemViewSet)
router.register(r'responses', SRIResponseViewSet)

urlpatterns = [
    # ==========================================
    # API ROUTER - FUNCIONALIDAD EXISTENTE
    # ==========================================
    path('api/', include(router.urls)),
    path('', include(router.urls)),
    
    # ==========================================
    # DESCARGA DE DOCUMENTOS (EXISTENTES)
    # ==========================================
    
    # Descarga directa de archivos
    path('documents/<int:document_id>/download/pdf/', 
         download_document_pdf, 
         name='download_document_pdf'),
    
    path('documents/<int:document_id>/download/xml/', 
         download_document_xml, 
         name='download_document_xml'),
    
    # Verificación de archivos disponibles
    path('documents/<int:document_id>/files/check/', 
         check_document_files, 
         name='check_document_files'),
    
    # Generación de archivos faltantes
    path('documents/<int:document_id>/files/generate/', 
         generate_missing_files, 
         name='generate_missing_files'),
    
    # ==========================================
    # NUEVAS APIS DE MONITOREO CELERY
    # ==========================================
    
    # Estado general de Celery
    path('api/sri/celery/status/', 
         celery_status, 
         name='celery_status'),
    
    # Estado de una tarea específica
    path('api/sri/celery/task/<str:task_id>/status/', 
         get_task_status, 
         name='get_task_status'),
    
    # Estadísticas de colas de Celery
    path('api/sri/celery/queue-stats/', 
         get_queue_stats, 
         name='get_queue_stats'),
    
    # Tareas activas del usuario actual
    path('api/sri/celery/my-tasks/', 
         get_user_active_tasks, 
         name='get_user_active_tasks'),
    
    # Test de conexión con Celery
    path('api/sri/celery/test/', 
         test_celery_connection, 
         name='test_celery_connection'),
    
    # ==========================================
    # PROCESAMIENTO ASÍNCRONO DE DOCUMENTOS
    # ==========================================
    
    # Estado de procesamiento de un documento específico
    path('api/sri/documents/<int:document_id>/task-status/', 
         document_task_status, 
         name='document_task_status'),
    
    # Disparar procesamiento asíncrono genérico
    path('api/sri/documents/<int:document_id>/trigger-processing/', 
         trigger_document_processing, 
         name='trigger_document_processing'),
    
    # Detener procesamiento activo
    path('api/sri/documents/<int:document_id>/stop-processing/', 
         stop_document_processing, 
         name='stop_document_processing'),
    
    # ENDPOINT PRINCIPAL - Procesar documento completo con Celery
    path('api/sri/documents/<int:document_id>/process-celery/', 
         process_document_with_celery, 
         name='process_document_with_celery'),
    
    # ==========================================
    # DASHBOARD Y ESTADÍSTICAS CON CELERY
    # ==========================================
    
    # Dashboard con estadísticas que incluye información de Celery
    path('api/sri/dashboard-stats/', 
         dashboard_with_celery_stats, 
         name='dashboard_with_celery_stats'),
    
    # Documentos con estado de tareas asíncronas
    path('api/sri/documents/with-tasks/', 
         get_documents_with_task_status, 
         name='get_documents_with_task_status'),
    
    # ==========================================
    # ALIASES PARA COMPATIBILIDAD (EXISTENTES)
    # ==========================================
    
    # Rutas alternativas que el template podría usar
    path('download/pdf/<int:document_id>/', 
         download_document_pdf, 
         name='download_pdf'),
    
    path('download/xml/<int:document_id>/', 
         download_document_xml, 
         name='download_xml'),
]

# ==========================================
# RESUMEN DE NUEVOS ENDPOINTS DISPONIBLES:
# ==========================================
"""
MONITOREO GENERAL:
- GET  /api/sri/celery/status/           -> Estado de Celery
- GET  /api/sri/celery/queue-stats/      -> Estadísticas de colas
- GET  /api/sri/celery/my-tasks/         -> Mis tareas activas
- POST /api/sri/celery/test/             -> Test de conexión

PROCESAMIENTO DE DOCUMENTOS:
- GET  /api/sri/documents/{id}/task-status/      -> Estado de procesamiento
- POST /api/sri/documents/{id}/trigger-processing/ -> Iniciar procesamiento
- POST /api/sri/documents/{id}/process-celery/   -> PRINCIPAL: Procesar completo
- POST /api/sri/documents/{id}/stop-processing/  -> Detener procesamiento

DASHBOARD Y ESTADÍSTICAS:
- GET  /api/sri/dashboard-stats/         -> Dashboard con datos de Celery
- GET  /api/sri/documents/with-tasks/    -> Documentos con estado de tareas

TAREAS ESPECÍFICAS:
- GET  /api/sri/celery/task/{task_id}/status/ -> Estado de tarea específica
"""