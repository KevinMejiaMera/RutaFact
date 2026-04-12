# apps/custom_admin/apps.py
from django.apps import AppConfig

class CustomAdminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.custom_admin'
    verbose_name = 'Panel Administrativo'