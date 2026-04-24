# -*- coding: utf-8 -*-
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import Provider, PurchaseInvoice, PurchaseItem

class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 1

@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ('name', 'identification', 'identification_type', 'company', 'regime', 'is_active')
    list_filter = ('company', 'regime', 'is_active')
    search_fields = ('name', 'identification', 'email')
    fieldsets = (
        (_('Identification'), {
            'fields': ('company', 'identification_type', 'identification', 'name', 'provider_code')
        }),
        (_('Contact Info'), {
            'fields': ('email', 'phone', 'address')
        }),
        (_('Tax Info'), {
            'fields': ('regime', 'description')
        }),
        (_('Status'), {
            'fields': ('is_active',)
        }),
    )

@admin.register(PurchaseInvoice)
class PurchaseInvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'provider', 'issue_date', 'total_amount', 'is_processed', 'company')
    list_filter = ('company', 'is_processed', 'issue_date')
    search_fields = ('invoice_number', 'provider__name')
    inlines = [PurchaseItemInline]
    readonly_fields = ('is_processed',)
