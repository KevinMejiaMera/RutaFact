# -*- coding: utf-8 -*-
"""
Admin para sistema de planes y facturación
apps/billing/admin.py
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import Plan, CompanyBillingProfile, PlanPurchase, InvoiceConsumption


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'invoice_limit', 'price', 'price_per_invoice_display', 'is_active', 'is_featured', 'sort_order', 'total_purchases']
    list_filter = ['is_active', 'is_featured', 'created_at']
    search_fields = ['name', 'description']
    list_editable = ['is_active', 'is_featured', 'sort_order']
    ordering = ['sort_order', 'price']
    
    fieldsets = (
        ('Información del Plan', {
            'fields': ('name', 'description', 'invoice_limit', 'price')
        }),
        ('Configuración', {
            'fields': ('is_active', 'is_featured', 'sort_order')
        }),
    )
    
    def price_per_invoice_display(self, obj):
        """Mostrar precio por factura formateado"""
        return f"${obj.price_per_invoice:.3f}"
    price_per_invoice_display.short_description = 'Precio/Factura'
    
    def total_purchases(self, obj):
        """Mostrar total de compras del plan"""
        count = obj.purchases.filter(payment_status='approved').count()
        return f"{count} compras"
    total_purchases.short_description = 'Total Compras'


@admin.register(CompanyBillingProfile)
class CompanyBillingProfileAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'available_invoices', 'total_purchased', 'total_consumed', 'usage_percentage_display', 'total_spent', 'is_low_balance_display']
    list_filter = ['last_purchase_date', 'auto_renewal_enabled']
    search_fields = ['company__business_name', 'company__trade_name', 'company__ruc']
    readonly_fields = ['total_invoices_purchased', 'total_invoices_consumed', 'total_spent', 'usage_percentage_display']
    
    fieldsets = (
        ('Empresa', {
            'fields': ('company',)
        }),
        ('Créditos Disponibles', {
            'fields': ('available_invoices',)
        }),
        ('Estadísticas (Solo Lectura)', {
            'fields': ('total_invoices_purchased', 'total_invoices_consumed', 'total_spent', 'usage_percentage_display', 'last_purchase_date'),
            'classes': ('collapse',)
        }),
        ('Configuración', {
            'fields': ('auto_renewal_enabled', 'low_balance_threshold'),
            'classes': ('collapse',)
        }),
    )
    
    def company_name(self, obj):
        """Mostrar nombre de la empresa"""
        return obj.company.business_name or obj.company.trade_name
    company_name.short_description = 'Empresa'
    
    def total_purchased(self, obj):
        """Mostrar total compradas con color"""
        return format_html(
            '<span style="color: #28a745; font-weight: bold;">{}</span>',
            obj.total_invoices_purchased
        )
    total_purchased.short_description = 'Total Compradas'
    
    def total_consumed(self, obj):
        """Mostrar total consumidas con color"""
        return format_html(
            '<span style="color: #dc3545; font-weight: bold;">{}</span>',
            obj.total_invoices_consumed
        )
    total_consumed.short_description = 'Total Consumidas'
    
    def usage_percentage_display(self, obj):
        """Mostrar porcentaje de uso con barra"""
        percentage = obj.usage_percentage
        if percentage <= 50:
            color = '#28a745'  # Verde
        elif percentage <= 80:
            color = '#ffc107'  # Amarillo
        else:
            color = '#dc3545'  # Rojo
        
        return format_html(
            '<div style="width: 100px; background-color: #f8f9fa; border-radius: 3px; overflow: hidden;">'
            '<div style="width: {}%; height: 20px; background-color: {}; text-align: center; line-height: 20px; color: white; font-size: 11px; font-weight: bold;">'
            '{}%'
            '</div>'
            '</div>',
            min(percentage, 100), color, int(percentage)
        )
    usage_percentage_display.short_description = 'Uso'
    
    def is_low_balance_display(self, obj):
        """Mostrar alerta de saldo bajo"""
        if obj.is_low_balance:
            return format_html(
                '<span style="color: #dc3545; font-weight: bold;">⚠️ Saldo Bajo</span>'
            )
        return format_html('<span style="color: #28a745;">✅ OK</span>')
    is_low_balance_display.short_description = 'Estado'


@admin.register(PlanPurchase)
class PlanPurchaseAdmin(admin.ModelAdmin):
    list_display = ['purchase_id_short', 'company_name', 'plan_name', 'payment_amount', 'payment_status_display', 'payment_date', 'created_at', 'actions_display']
    list_filter = ['payment_status', 'payment_method', 'created_at', 'payment_date']
    search_fields = ['company__business_name', 'company__trade_name', 'payer_name', 'payer_document', 'payment_reference']
    readonly_fields = ['purchase_id', 'plan_name', 'plan_invoice_limit', 'plan_price', 'processed_by', 'processed_at']
    
    fieldsets = (
        ('Información de la Compra', {
            'fields': ('purchase_id', 'company', 'plan')
        }),
        ('Detalles del Plan (al momento de compra)', {
            'fields': ('plan_name', 'plan_invoice_limit', 'plan_price'),
            'classes': ('collapse',)
        }),
        ('Información del Pago', {
            'fields': ('payment_method', 'payer_name', 'payer_document', 'payment_amount', 'payment_date', 'payment_reference', 'bank_name')
        }),
        ('Comprobante', {
            'fields': ('payment_receipt',)
        }),
        ('Notas', {
            'fields': ('customer_notes', 'admin_notes'),
            'classes': ('collapse',)
        }),
        ('Estado y Procesamiento', {
            'fields': ('payment_status', 'processed_by', 'processed_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['approve_selected_purchases', 'reject_selected_purchases']
    
    def purchase_id_short(self, obj):
        """Mostrar ID corto de la compra"""
        return str(obj.purchase_id)[:8]
    purchase_id_short.short_description = 'ID Compra'
    
    def company_name(self, obj):
        """Mostrar nombre de la empresa"""
        return obj.company.business_name or obj.company.trade_name
    company_name.short_description = 'Empresa'
    
    def payment_status_display(self, obj):
        """Mostrar estado con color"""
        colors = {
            'pending': '#ffc107',
            'approved': '#28a745',
            'rejected': '#dc3545',
            'expired': '#6c757d',
        }
        color = colors.get(obj.payment_status, '#6c757d')
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            obj.get_payment_status_display()
        )
    payment_status_display.short_description = 'Estado'
    
    def actions_display(self, obj):
        """Mostrar acciones disponibles"""
        if obj.payment_status == 'pending':
            return format_html(
                '<a href="{}?purchase_id={}" style="color: #28a745; margin-right: 10px;">✅ Aprobar</a>'
                '<a href="{}?purchase_id={}" style="color: #dc3545;">❌ Rechazar</a>',
                reverse('admin:billing_planpurchase_changelist'), obj.id,
                reverse('admin:billing_planpurchase_changelist'), obj.id
            )
        elif obj.payment_status == 'approved':
            return format_html('<span style="color: #28a745;">✅ Aprobado</span>')
        elif obj.payment_status == 'rejected':
            return format_html('<span style="color: #dc3545;">❌ Rechazado</span>')
        return '-'
    actions_display.short_description = 'Acciones'
    
    def approve_selected_purchases(self, request, queryset):
        """Aprobar compras seleccionadas"""
        approved_count = 0
        for purchase in queryset.filter(payment_status='pending'):
            if purchase.approve_purchase(request.user):
                approved_count += 1
        
        self.message_user(request, f'{approved_count} compras aprobadas exitosamente.')
    approve_selected_purchases.short_description = '✅ Aprobar compras seleccionadas'
    
    def reject_selected_purchases(self, request, queryset):
        """Rechazar compras seleccionadas"""
        rejected_count = 0
        for purchase in queryset.filter(payment_status='pending'):
            if purchase.reject_purchase(request.user, "Rechazado desde admin"):
                rejected_count += 1
        
        self.message_user(request, f'{rejected_count} compras rechazadas.')
    reject_selected_purchases.short_description = '❌ Rechazar compras seleccionadas'


@admin.register(InvoiceConsumption)
class InvoiceConsumptionAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'invoice_id', 'invoice_type', 'balance_before', 'balance_after', 'consumed_at']
    list_filter = ['invoice_type', 'consumed_at']
    search_fields = ['company__business_name', 'invoice_id', 'ip_address']
    readonly_fields = ['company', 'invoice_id', 'invoice_type', 'balance_before', 'balance_after', 'consumed_at', 'user_agent', 'ip_address', 'api_endpoint']
    
    def company_name(self, obj):
        """Mostrar nombre de la empresa"""
        return obj.company.business_name or obj.company.trade_name
    company_name.short_description = 'Empresa'
    
    def has_add_permission(self, request):
        """No permitir agregar manualmente"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Solo lectura"""
        return False