# -*- coding: utf-8 -*-
"""
Apps configuration for users app
"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class UsersConfig(AppConfig):
    """Configuración de la app users"""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.users'
    verbose_name = _('Users')
    
    def ready(self):
        """Se ejecuta cuando la app está lista"""
        try:
            import apps.users.signals  # noqa F401
        except ImportError:
            pass