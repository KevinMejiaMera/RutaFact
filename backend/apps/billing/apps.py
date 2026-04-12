# -*- coding: utf-8 -*-
"""
Configuración de la app billing
apps/billing/apps.py
"""

from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.billing'
    verbose_name = 'Sistema de Facturación y Planes'
    
    def ready(self):
        # Importar signals para auto-crear perfiles de facturación
        import apps.billing.signals