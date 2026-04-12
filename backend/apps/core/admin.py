# -*- coding: utf-8 -*-
"""
Admin configuration for core app
"""

from django.contrib import admin
from django.utils.html import format_html
from django.db import models
from django.forms import TextInput, Textarea
from .models import AuditLog, SystemConfiguration, FileUpload


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """
    Admin para logs de auditoría
    """
    list_display = [
        'created_at',
        'user_display',
        'action',
        'model_name',
        'object_representation',
        'ip_address'
    ]
    
    list_filter = [
        'action',
        'model_name',
        'created_at'
    ]
    
    search_fields = [
        'user__email',
        'object_representation',
        'model_name',
        'ip_address'
    ]
    
    readonly_fields = [
        'user',
        'action',
        'model_name',
        'object_id',
        'object_representation',
        'changes',
        'ip_address',
        'user_agent',
        'additional_data',
        'created_at'
    ]
    
    ordering = ['-created_at']
    
    date_hierarchy = 'created_at'
    
    def user_display(self, obj):
        """Muestra el usuario de manera más amigable"""
        if obj.user:
            return obj.user.email
        return "Sistema"
    
    user_display.short_description = 'Usuario'
    
    def has_add_permission(self, request):
        """No permitir agregar logs manualmente"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """No permitir editar logs"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Solo superusuarios pueden eliminar logs"""
        return request.user.is_superuser


@admin.register(SystemConfiguration)
class SystemConfigurationAdmin(admin.ModelAdmin):
    """
    Admin para configuración del sistema
    """
    list_display = [
        'key',
        'config_type',
        'description_short',
        'is_sensitive',
        'is_active',
        'updated_at'
    ]
    
    list_filter = [
        'config_type',
        'is_sensitive',
        'is_active'
    ]
    
    search_fields = [
        'key',
        'description'
    ]
    
    ordering = ['config_type', 'key']
    
    fieldsets = (
        ('Información Básica', {
            'fields': (
                'key',
                'config_type',
                'description',
            )
        }),
        ('Valor', {
            'fields': (
                'value',
            )
        }),
        ('Configuración', {
            'fields': (
                'is_sensitive',
                'is_active',
            )
        }),
        ('Metadatos', {
            'fields': (
                'created_at',
                'updated_at',
                'created_by',
                'updated_by',
            ),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at', 'created_by', 'updated_by']
    
    def description_short(self, obj):
        """Descripción corta"""
        if obj.description:
            return obj.description[:50] + '...' if len(obj.description) > 50 else obj.description
        return '-'
    
    description_short.short_description = 'Descripción'
    
    def get_form(self, request, obj=None, **kwargs):
        """Personaliza el formulario según el tipo de configuración"""
        form = super().get_form(request, obj, **kwargs)
        
        if obj and obj.is_sensitive:
            form.base_fields['value'].widget = TextInput(attrs={'type': 'password'})
        
        return form
