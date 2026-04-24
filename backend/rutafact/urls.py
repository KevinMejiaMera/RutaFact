# -*- coding: utf-8 -*-
"""
URLs principales para RutaFact_SRI con OAuth + DUAL TOKEN AUTHENTICATION
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.core import views as core_views
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.views import LoginView
from django.contrib.auth import logout
from django.views.generic import TemplateView

# ==========================================
# VISTAS PRINCIPALES (API-ONLY)
# ==========================================

def health_check(request):
    """Endpoint de salud para monitoreo"""
    return JsonResponse({
        'status': 'ok',
        'service': 'RutaFact_SRI API',
        'database': 'connected',
        'endpoints': {
            'api_auth': '/api/auth/',
            'api_companies': '/api/companies/'
        }
    })

# ==========================================
# CONFIGURACIÓN DE URLs
# ==========================================

urlpatterns = [
    # ADMIN
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    
    # SALUD DEL SISTEMA
    path('health/', health_check, name='health_check'),
    path('', lambda r: redirect('admin_dashboard'), name='home'),
    path('dashboard/', core_views.admin_dashboard, name='admin_dashboard'),
    path('dashboard/config/', core_views.admin_config_sri, name='admin_config_sri'),
    path('dashboard/pos/', core_views.admin_pos_view, name='admin_pos'),
    path('dashboard/customers/add_ajax/', core_views.admin_add_customer_ajax, name='admin_add_customer_ajax'),
    path('dashboard/invoices/', core_views.admin_invoices_view, name='admin_invoices'),
    path('dashboard/invoices/<int:pk>/retry/', core_views.admin_retry_invoice, name='admin_retry_invoice'),
    path('dashboard/suppliers/', core_views.admin_providers_view, name='admin_suppliers'),
    path('dashboard/suppliers/<int:provider_id>/edit/', core_views.admin_edit_provider, name='admin_edit_provider'),
    path('dashboard/suppliers/<int:provider_id>/delete/', core_views.admin_delete_provider, name='admin_delete_provider'),
    path('dashboard/purchases/', core_views.admin_purchases_view, name='admin_purchases'),
    path('dashboard/purchases/<int:purchase_id>/delete/', core_views.admin_delete_purchase, name='admin_delete_purchase'),
    path('dashboard/inventory/', core_views.admin_inventory_view, name='admin_inventory'),
    path('dashboard/inventory/<int:stock_id>/adjust/', core_views.admin_adjust_stock, name='admin_adjust_stock'),
    path('dashboard/inventory/product/<int:product_id>/edit/', core_views.admin_edit_product, name='admin_edit_product'),
    path('dashboard/users/', core_views.admin_users_view, name='admin_users'),
    path('dashboard/users/<int:user_id>/delete/', core_views.admin_delete_user, name='admin_delete_user'),
    path('dashboard/users/<int:user_id>/toggle/', core_views.toggle_user_assignment, name='toggle_user_assignment'),
    path('dashboard/users/<int:user_id>/update_role/', core_views.update_user_role, name='update_user_role'),
    path('dashboard/users/<int:user_id>/update_status/', core_views.update_user_status, name='update_user_status'),
    path('dashboard/users/<int:user_id>/toggle_tracking/', core_views.toggle_user_tracking, name='toggle_user_tracking'),
    
    # 📍 TRACKING URLs
    path('dashboard/tracking/', include([
        path('', include('apps.tracking.urls')),
    ])),
    
    # 🔑 API CON DUAL TOKEN AUTHENTICATION - ACTIVADA
    path('api/', include('apps.api.urls')),
    
    
    # APLICACIONES LOCALES - APIs
    path('companies/', include('apps.companies.urls')),
    path('invoicing/', include('apps.invoicing.urls')),
    path('certificates/', include('apps.certificates.urls')),
    path('notifications/', include('apps.notifications.urls')),
    path('sri/', include('apps.sri_integration.urls')),
    
    # 📱 PWA / Service Worker (Dummy path to avoid 404 noise)
    path('serviceworker.js', lambda r: HttpResponse("// dummy sw", content_type="application/javascript"), name='serviceworker'),
]

# ==========================================
# ARCHIVOS ESTÁTICOS Y MEDIA (DESARROLLO)
# ==========================================

if settings.DEBUG:
    print("[CONFIG] Configurando URLs para DESARROLLO...")
    
    # Django Debug Toolbar
    if 'debug_toolbar' in settings.INSTALLED_APPS:
        try:
            import debug_toolbar
            urlpatterns = [
                path('__debug__/', include(debug_toolbar.urls)),
            ] + urlpatterns
            print("[OK] Debug Toolbar activado en /__debug__/")
        except ImportError:
            print("[WARN] Debug Toolbar configurado pero no instalado")
    
    # Servir archivos media y static en desarrollo
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    
    print(f"[OK] Archivos estaticos servidos desde: {settings.STATIC_URL}")
    print(f"[OK] Archivos media servidos desde: {settings.MEDIA_URL}")

# ==========================================
# CONFIGURACIÓN PARA PRODUCCIÓN
# ==========================================

else:  # if not settings.DEBUG
    print("[CONFIG] Configurando URLs para PRODUCCION...")
    
    # Health checks para load balancers
    urlpatterns += [
        path('ping/', lambda request: HttpResponse("pong", content_type='text/plain'), name='ping'),
        path('status/', lambda request: HttpResponse("active", content_type='text/plain'), name='status'),
    ]
    
    print("[OK] URLs de produccion configuradas")

# ==========================================
# ==========================================
# INFO (MANTENIDA POR SI ES ÚTIL EN LOGS)
# ==========================================
print("[OK] Configuraciones de URLs solo API OK")