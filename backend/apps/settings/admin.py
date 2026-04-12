# -*- coding: utf-8 -*-
"""
Admin configuration for settings app
"""

from django.contrib import admin
from django.utils.html import format_html
from django.forms import TextInput
from .models import (
    SystemSetting,
    CompanySetting,
    UserPreference,
    BackupConfiguration,
    MaintenanceMode
)


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    """
    Admin para configuraciones del sistema
    """
    list_display = [
        'name',
        'key',
        'category',
        'setting_type',
        'is_sensitive',
        'requires_restart',
        'is_active'
    ]
    
    list_filter = [
        'category',
        'setting_type',
        'is_sensitive',
        'requires_restart',
        'is_active'
    ]
    
    search_fields = [
        'name',
        'key',
        'description'
    ]
    
    ordering = ['category', 'name']
    
    fieldsets = (
        ('Información Básica', {
            'fields': (
                'key',
                'name',
                'description',
                'category',
                'setting_type',
            )
        }),
        ('Valor', {
            'fields': (
                'value',
                'default_value',
            )
        }),
        ('Configuración', {
            'fields': (
                'is_sensitive',
                'requires_restart',
                'validation_regex',
            )
        }),
        ('Estado', {
            'fields': (
                'is_active',
            )
        }),
    )
    
    def get_form(self, request, obj=None, **kwargs):
        """Personaliza el formulario para campos sensibles"""
        form = super().get_form(request, obj, **kwargs)
        
        if obj and obj.is_sensitive:
            form.base_fields['value'].widget = TextInput(attrs={'type': 'password'})
        
        return form
    
    def get_readonly_fields(self, request, obj=None):
        """Campos de solo lectura según permisos"""
        readonly = ['created_at', 'updated_at']
        
        if not request.user.is_superuser:
            readonly.extend(['key', 'setting_type', 'is_sensitive'])
        
        return readonly


@admin.register(CompanySetting)
class CompanySettingAdmin(admin.ModelAdmin):
    """
    Admin para configuraciones de empresa
    """
    list_display = [
        'name',
        'company',
        'key',
        'setting_type',
        'is_active'
    ]
    
    list_filter = [
        'company',
        'setting_type',
        'is_active'
    ]
    
    search_fields = [
        'name',
        'key',
        'company__business_name'
    ]
    
    ordering = ['company', 'name']


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    """
    Admin para preferencias de usuario
    """
    list_display = [
        'user',
        'theme',
        'language',
        'default_company',
        'email_notifications',
        'items_per_page'
    ]
    
    list_filter = [
        'theme',
        'language',
        'email_notifications',
        'browser_notifications',
        'notification_frequency'
    ]
    
    search_fields = [
        'user__email',
        'user__first_name',
        'user__last_name'
    ]
    
    ordering = ['user__email']


@admin.register(BackupConfiguration)
class BackupConfigurationAdmin(admin.ModelAdmin):
    """
    Admin para configuración de respaldos
    """
    list_display = [
        'name',
        'backup_type',
        'frequency',
        'storage_type',
        'last_backup_status_display',
        'last_backup',
        'enabled'
    ]
    
    list_filter = [
        'backup_type',
        'frequency',
        'storage_type',
        'enabled',
        'last_backup_status'
    ]
    
    search_fields = [
        'name'
    ]
    
    ordering = ['name']
    
    readonly_fields = [
        'last_backup',
        'last_backup_status'
    ]
    
    fieldsets = (
        ('Configuración Básica', {
            'fields': (
                'name',
                'backup_type',
                'frequency',
                'enabled',
            )
        }),
        ('Almacenamiento', {
            'fields': (
                'storage_type',
                'storage_config',
            )
        }),
        ('Retención', {
            'fields': (
                'retention_days',
                'max_backups',
            )
        }),
        ('Contenido', {
            'fields': (
                'include_media',
                'include_logs',
                'exclude_tables',
            ),
            'classes': ('collapse',)
        }),
        ('Estado', {
            'fields': (
                'last_backup',
                'last_backup_status',
            ),
            'classes': ('collapse',)
        }),
    )
    
    def last_backup_status_display(self, obj):
        """Estado del último respaldo con colores"""
        if not obj.last_backup_status:
            return format_html('<span style="color: gray;">-</span>')
        
        colors = {
            'SUCCESS': 'green',
            'FAILED': 'red',
            'RUNNING': 'orange'
        }
        color = colors.get(obj.last_backup_status, 'black')
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_last_backup_status_display()
        )
    
    last_backup_status_display.short_description = 'Estado'


@admin.register(MaintenanceMode)
class MaintenanceModeAdmin(admin.ModelAdmin):
    """
    Admin para modo de mantenimiento
    """
    list_display = [
        'is_enabled',
        'start_time',
        'estimated_end_time',
        'allowed_ips_count'
    ]
    
    readonly_fields = [
        'start_time'
    ]
    
    def allowed_ips_count(self, obj):
        """Número de IPs permitidas"""
        return len(obj.allowed_ips) if obj.allowed_ips else 0
    
    allowed_ips_count.short_description = 'IPs Permitidas'
    
    def has_add_permission(self, request):
        """Solo permitir una instancia"""
        if MaintenanceMode.objects.exists():
            return False
        return super().has_add_permission(request)