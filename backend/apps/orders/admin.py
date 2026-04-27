# -*- coding: utf-8 -*-
from django.contrib import admin
from .models import Order, OrderItem

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['subtotal', 'tax_amount', 'total']

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'company', 'customer', 'status', 'total_amount', 'created_at']
    list_filter = ['status', 'company', 'created_at']
    search_fields = ['customer__name', 'delivery_address']
    inlines = [OrderItemInline]
    readonly_fields = ['total_amount', 'invoice']
    
    def save_model(self, request, obj, form, change):
        if not obj.company and not request.user.is_superuser:
            obj.company = request.user.company
        super().save_model(request, obj, form, change)
