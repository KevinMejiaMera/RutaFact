# -*- coding: utf-8 -*-
"""
Admin configuration for companies app
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    """
    Admin para empresas
    """
    list_display = [
        'business_name',
        'ruc',
        'trade_name',
        'email',
        'phone',
        'is_active',
        'sri_status',
        'certificate_status',
        'created_at'
    ]
    
    list_filter = [
        'is_active',
        'created_at',
        'updated_at'
    ]
    
    search_fields = [
        'business_name',
        'trade_name',
        'ruc',
        'email'
    ]
    
    ordering = ['business_name']
    
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Información Básica', {
            'fields': (
                'ruc',
                'business_name',
                'trade_name',
            )
        }),
        ('Información de Contacto', {
            'fields': (
                'email',
                'phone',
                'address',
            )
        }),
        ('Estado', {
            'fields': (
                'is_active',
            )
        }),
        ('Metadatos', {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',)
        }),
    )
    
    def sri_status(self, obj):
        """Estado de configuración SRI"""
        try:
            config = obj.sri_configuration
            if config.is_active:
                return format_html(
                    '<span style="color: green;">✓ Configurado ({})</span>',
                    config.get_environment_display()
                )
            else:
                return format_html('<span style="color: orange;">⚠ Inactivo</span>')
        except:
            return format_html('<span style="color: red;">✗ No configurado</span>')
    
    sri_status.short_description = 'Estado SRI'
    
    def certificate_status(self, obj):
        """Estado del certificado digital"""
        try:
            cert = obj.digital_certificate
            if cert.is_expired:
                return format_html('<span style="color: red;">✗ Expirado</span>')
            elif cert.days_until_expiration <= 30:
                return format_html(
                    '<span style="color: orange;">⚠ Expira en {} días</span>',
                    cert.days_until_expiration
                )
            else:
                return format_html('<span style="color: green;">✓ Válido</span>')
        except:
            return format_html('<span style="color: red;">✗ No configurado</span>')
    
    certificate_status.short_description = 'Certificado'
    
    actions = ['activate_companies', 'deactivate_companies']
    
    def activate_companies(self, request, queryset):
        """Activa empresas seleccionadas"""
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            f'{updated} empresa(s) activada(s) exitosamente.'
        )
    activate_companies.short_description = "Activar empresas seleccionadas"
    
    def deactivate_companies(self, request, queryset):
        """Desactiva empresas seleccionadas"""
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            f'{updated} empresa(s) desactivada(s) exitosamente.'
        )
    deactivate_companies.short_description = "Desactivar empresas seleccionadas"