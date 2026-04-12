# -*- coding: utf-8 -*-
"""
URLs para sistema de planes y facturación
apps/billing/urls.py
"""

from django.urls import path
from . import views

app_name = 'billing'

urlpatterns = [
    # Estado de facturación para API (Usado por Flutter)
    path('api/status/', views.billing_api_status, name='api_status'),
]

# ==========================================
# DOCUMENTACIÓN DE URLs
# ==========================================

"""
ENDPOINTS DISPONIBLES DEL SISTEMA DE FACTURACIÓN:

=== 📊 DASHBOARD ===
GET  /billing/                                   # Dashboard principal de facturación

=== 💳 PLANES ===
GET  /billing/plans/                             # Ver planes disponibles
GET  /billing/plans/<id>/buy/                    # Formulario de compra de plan
POST /billing/plans/<id>/buy/                    # Procesar compra de plan
GET  /billing/purchase/success/<uuid>/           # Confirmación de compra

=== 📋 HISTORIAL ===
GET  /billing/purchases/                         # Historial de compras
GET  /billing/consumption/                       # Historial de consumo de facturas

=== 🔌 APIs ===
GET  /billing/api/status/?company_id=X           # Estado de facturación (AJAX)

=== EJEMPLOS DE USO ===

# Ver planes disponibles
http://localhost:8000/billing/plans/

# Comprar plan ID 1
http://localhost:8000/billing/plans/1/buy/

# Ver historial de una empresa específica
http://localhost:8000/billing/purchases/?company=1

# Obtener estado de facturación vía AJAX
fetch('/billing/api/status/?company_id=1')
  .then(response => response.json())
  .then(data => console.log(data));

=== FLUJO COMPLETO DE COMPRA ===

1. Usuario va a /billing/plans/
2. Selecciona plan y hace clic en "Comprar"
3. Llena formulario en /billing/plans/<id>/buy/
4. Sube comprobante de pago
5. Sistema redirige a /billing/purchase/success/<uuid>/
6. Admin valida en panel de administración
7. Sistema activa automáticamente las facturas

=== PARÁMETROS URL ===

?company=X          # Filtrar por empresa específica
?status=pending     # Filtrar compras por estado
?type=invoice       # Filtrar consumo por tipo de documento
?date_from=YYYY-MM-DD  # Filtrar por fecha desde
?date_to=YYYY-MM-DD    # Filtrar por fecha hasta
?page=N             # Paginación

=== ESTADOS DE COMPRA ===

- pending: Pendiente de validación
- approved: Aprobado (facturas activadas)
- rejected: Rechazado
- expired: Expirado

=== MÉTODOS DE PAGO SOPORTADOS ===

- bank_transfer: Transferencia bancaria
- deposit: Depósito bancario  
- other: Otro método

=== TIPOS DE DOCUMENTO CONSUMIBLES ===

- invoice: Facturas
- credit_note: Notas de crédito
- debit_note: Notas de débito
- retention: Retenciones
- purchase_settlement: Liquidaciones de compra
"""