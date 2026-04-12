# -*- coding: utf-8 -*-
"""
Admin configuration for invoicing app
"""

from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Customer,
    ProductCategory,
    ProductTemplate,
    InvoiceTemplate,
    TemplateProduct,
    PaymentMethod
)


class TemplateProductInline(admin.TabularInline):
    """
    Inline para productos en plantillas
    """
    model = TemplateProduct
    extra = 0
    fields = ['product', 'default_quantity', 'default_discount', 'order']
    ordering = ['order']


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """
    Admin para clientes
    """
    list_display = [
        'name',
        'identification',
        'identification_type',
        'company',
        'email',
        'phone',
        'credit_limit',
        'is_active'
    ]
    
    list_filter = [
        'identification_type',
        'company',
        'is_active',
        'created_at'
    ]
    
    search_fields = [
        'name',
        'identification',
        'email',
        'phone'
    ]
    
    ordering = ['name']
    
    fieldsets = (
        ('Información Básica', {
            'fields': (
                'company',
                'identification_type',
                'identification',
                'name',
            )
        }),
        ('Información de Contacto', {
            'fields': (
                'email',
                'phone',
                'address',
                'city',
                'province',
                'postal_code',
            )
        }),
        ('Configuración de Facturación', {
            'fields': (
                'default_payment_method',
                'credit_limit',
            )
        }),
        ('Notas', {
            'fields': (
                'notes',
            ),
            'classes': ('collapse',)
        }),
        ('Estado', {
            'fields': (
                'is_active',
            )
        }),
    )


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    """
    Admin para categorías de productos
    """
    list_display = [
        'name',
        'company',
        'parent',
        'is_active',
        'created_at'
    ]
    
    list_filter = [
        'company',
        'parent',
        'is_active'
    ]
    
    search_fields = [
        'name',
        'description'
    ]
    
    ordering = ['company', 'parent__name', 'name']


@admin.register(ProductTemplate)
class ProductTemplateAdmin(admin.ModelAdmin):
    """
    Admin para plantillas de productos
    """
    list_display = [
        'main_code',
        'name',
        'company',
        'category',
        'product_type',
        'unit_price',
        'tax_rate',
        'stock_status',
        'is_active'
    ]
    
    list_filter = [
        'product_type',
        'company',
        'category',
        'track_inventory',
        'is_active'
    ]
    
    search_fields = [
        'main_code',
        'auxiliary_code',
        'name',
        'description'
    ]
    
    ordering = ['company', 'main_code']
    
    fieldsets = (
        ('Información Básica', {
            'fields': (
                'company',
                'category',
                'product_type',
                'main_code',
                'auxiliary_code',
                'name',
                'description',
                'unit_of_measure',
                'unit_price',
            )
        }),
        ('Configuración de Impuestos', {
            'fields': (
                'tax_code',
                'tax_rate',
            )
        }),
        ('Inventario', {
            'fields': (
                'track_inventory',
                'current_stock',
                'minimum_stock',
            ),
            'classes': ('collapse',)
        }),
        ('Información Adicional', {
            'fields': (
                'additional_details',
            ),
            'classes': ('collapse',)
        }),
        ('Estado', {
            'fields': (
                'is_active',
            )
        }),
    )
    
    def stock_status(self, obj):
        """Estado del stock"""
        if not obj.track_inventory:
            return format_html('<span style="color: gray;">No rastreado</span>')
        elif obj.is_low_stock:
            return format_html('<span style="color: red;">⚠ Stock bajo</span>')
        else:
            return format_html('<span style="color: green;">✓ Stock OK</span>')
    
    stock_status.short_description = 'Stock'


@admin.register(InvoiceTemplate)
class InvoiceTemplateAdmin(admin.ModelAdmin):
    """
    Admin para plantillas de facturas
    """
    list_display = [
        'name',
        'company',
        'products_count',
        'is_active',
        'created_at'
    ]
    
    list_filter = [
        'company',
        'is_active',
        'created_at'
    ]
    
    search_fields = [
        'name',
        'description'
    ]
    
    ordering = ['company', 'name']
    
    inlines = [TemplateProductInline]
    
    def products_count(self, obj):
        """Número de productos en la plantilla"""
        return obj.template_products.count()
    
    products_count.short_description = 'Productos'


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    """
    Admin para métodos de pago
    """
    list_display = [
        'name',
        'code',
        'company',
        'requires_bank_info',
        'default_days_to_pay',
        'is_active'
    ]
    
    list_filter = [
        'company',
        'requires_bank_info',
        'is_active'
    ]
    
    search_fields = [
        'name',
        'code',
        'description'
    ]
    
    ordering = ['company', 'name']