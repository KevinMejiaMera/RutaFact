from django.apps import AppConfig

class SettingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.settings'
    verbose_name = 'Configuración'
    
    def ready(self):
        """Importar signals y cargar configuraciones desde la BD"""
        try:
            import apps.settings.signals  # noqa F401
        except ImportError:
            pass
            
        # Cargar configuraciones de la BD a settings de Django
        try:
            from django.conf import settings
            from .models import SystemSetting
            import logging
            
            logger = logging.getLogger(__name__)
            
            # Solo si no estamos en medio de migraciones o testing
            import sys
            if 'migrate' not in sys.argv and 'makemigrations' not in sys.argv:
                # Usar .all() pero con cuidado si la tabla no existe aún
                for setting in SystemSetting.objects.filter(is_active=True):
                    key = setting.key.upper()
                    val = setting.get_typed_value()
                    setattr(settings, key, val)
                    # logger.debug(f"Loaded setting {key}: {val}")
        except Exception as e:
            # Fallar silenciosamente si la base de datos no está lista
            pass
