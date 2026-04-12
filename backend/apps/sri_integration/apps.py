from django.apps import AppConfig

class SriIntegrationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.sri_integration'
    verbose_name = 'Integración SRI'
    
    def ready(self):
        """Importar signals cuando la app esté lista"""
        try:
            import apps.sri_integration.signals  # noqa F401
        except ImportError:
            pass