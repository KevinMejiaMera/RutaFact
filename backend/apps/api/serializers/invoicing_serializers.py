"""
Serializers for invoicing models
"""

from rest_framework import serializers
from apps.invoicing.models import (
    Customer, ProductCategory, ProductTemplate, 
    InvoiceTemplate, PaymentMethod, TemplateProduct
)

class CustomerSerializer(serializers.ModelSerializer):
    """Serializer para clientes"""
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    identification_type_display = serializers.CharField(source='get_identification_type_display', read_only=True)
    
    class Meta:
        model = Customer
        fields = [
            'id', 'company', 'company_name', 
            'identification_type', 'identification_type_display',
            'identification', 'name', 'email', 'phone', 
            'address', 'city', 'province', 'postal_code',
            'default_payment_method', 'credit_limit', 'notes',
            'is_active', 'created_at', 'updated_at'
        ]

class ProductCategorySerializer(serializers.ModelSerializer):
    """Serializer para categorías de productos"""
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    parent_name = serializers.CharField(source='parent.name', read_only=True)
    
    class Meta:
        model = ProductCategory
        fields = [
            'id', 'company', 'company_name', 'name', 'description',
            'parent', 'parent_name', 'is_active', 'created_at', 'updated_at'
        ]

class ProductTemplateSerializer(serializers.ModelSerializer):
    """Serializer para plantillas de productos"""
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    product_type_display = serializers.CharField(source='get_product_type_display', read_only=True)
    tax_code_display = serializers.CharField(source='get_tax_code_display', read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = ProductTemplate
        fields = [
            'id', 'company', 'company_name', 'category', 'category_name',
            'product_type', 'product_type_display', 'main_code', 'auxiliary_code',
            'name', 'description', 'unit_of_measure', 'unit_price',
            'tax_rate', 'tax_code', 'tax_code_display',
            'track_inventory', 'current_stock', 'minimum_stock', 'is_low_stock',
            'additional_details', 'is_active', 'created_at', 'updated_at'
        ]

class PaymentMethodSerializer(serializers.ModelSerializer):
    """Serializer para métodos de pago"""
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    
    class Meta:
        model = PaymentMethod
        fields = [
            'id', 'company', 'company_name', 'name', 'code', 'description',
            'requires_bank_info', 'default_days_to_pay',
            'is_active', 'created_at', 'updated_at'
        ]

class TemplateProductSerializer(serializers.ModelSerializer):
    """Serializer para productos de plantillas"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.main_code', read_only=True)
    
    class Meta:
        model = TemplateProduct
        fields = [
            'id', 'template', 'product', 'product_name', 'product_code',
            'default_quantity', 'default_discount', 'order',
            'created_at', 'updated_at'
        ]

class InvoiceTemplateSerializer(serializers.ModelSerializer):
    """Serializer para plantillas de facturas"""
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    template_products = TemplateProductSerializer(many=True, read_only=True)
    
    class Meta:
        model = InvoiceTemplate
        fields = [
            'id', 'company', 'company_name', 'name', 'description',
            'default_payment_method', 'default_payment_terms',
            'additional_fields', 'template_products',
            'is_active', 'created_at', 'updated_at'
        ]

# apps/invoicing/views.py - ACTUALIZADO
# -*- coding: utf-8 -*-
"""
Views for invoicing app  
"""

from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from apps.invoicing.models import (
    Customer, ProductCategory, ProductTemplate, 
    InvoiceTemplate, PaymentMethod
)
from apps.api.serializers.invoicing_serializers import (
    CustomerSerializer, ProductCategorySerializer, ProductTemplateSerializer,
    InvoiceTemplateSerializer, PaymentMethodSerializer
)

class CustomerViewSet(viewsets.ModelViewSet):
    """ViewSet para clientes"""
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['identification_type', 'company', 'is_active']
    search_fields = ['name', 'identification', 'email']
    ordering = ['name']
    
    def get_queryset(self):
        """Filtrar por empresa del usuario"""
        user = self.request.user
        if user.is_superuser:
            return Customer.objects.all()
        # TODO: Filtrar por empresas del usuario cuando tengas la relación
        return Customer.objects.filter(is_active=True)

class ProductCategoryViewSet(viewsets.ModelViewSet):
    """ViewSet para categorías de productos"""
    serializer_class = ProductCategorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['company', 'parent', 'is_active']
    search_fields = ['name', 'description']
    ordering = ['name']
    
    def get_queryset(self):
        """Filtrar por empresa del usuario"""
        user = self.request.user
        if user.is_superuser:
            return ProductCategory.objects.all()
        return ProductCategory.objects.filter(is_active=True)

class ProductTemplateViewSet(viewsets.ModelViewSet):
    """ViewSet para plantillas de productos"""
    serializer_class = ProductTemplateSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['company', 'category', 'product_type', 'track_inventory', 'is_active']
    search_fields = ['name', 'main_code', 'auxiliary_code', 'description']
    ordering = ['name']
    
    def get_queryset(self):
        """Filtrar por empresa del usuario"""
        user = self.request.user
        if user.is_superuser:
            return ProductTemplate.objects.all()
        return ProductTemplate.objects.filter(is_active=True)

class InvoiceTemplateViewSet(viewsets.ModelViewSet):
    """ViewSet para plantillas de facturas"""
    serializer_class = InvoiceTemplateSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['company', 'is_active']
    search_fields = ['name', 'description']
    ordering = ['name']
    
    def get_queryset(self):
        """Filtrar por empresa del usuario"""
        user = self.request.user
        if user.is_superuser:
            return InvoiceTemplate.objects.all()
        return InvoiceTemplate.objects.filter(is_active=True)

class PaymentMethodViewSet(viewsets.ModelViewSet):
    """ViewSet para métodos de pago"""
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['company', 'requires_bank_info', 'is_active']
    search_fields = ['name', 'code', 'description']
    ordering = ['name']
    
    def get_queryset(self):
        """Filtrar por empresa del usuario"""
        user = self.request.user
        if user.is_superuser:
            return PaymentMethod.objects.all()
        return PaymentMethod.objects.filter(is_active=True)