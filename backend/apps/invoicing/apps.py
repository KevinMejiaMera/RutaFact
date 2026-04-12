from django.apps import AppConfig

class InvoicingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.invoicing'
    verbose_name = 'Facturación'
    
    def ready(self):
        """Importar signals cuando la app esté lista"""
        try:
            import apps.invoicing.signals  # noqa F401
        except ImportError:
            pass
