# -*- coding: utf-8 -*-
"""
Serializers for invoicing app
"""

from rest_framework import serializers
from .models import (
    Customer, ProductCategory, ProductTemplate, 
    InvoiceTemplate, TemplateProduct, PaymentMethod
)

class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

class ProductCategorySerializer(serializers.ModelSerializer):
    subcategories = serializers.StringRelatedField(many=True, read_only=True)
    
    class Meta:
        model = ProductCategory
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

class ProductTemplateSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    is_low_stock = serializers.ReadOnlyField()
    
    class Meta:
        model = ProductTemplate
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

class TemplateProductSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    
    class Meta:
        model = TemplateProduct
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

class InvoiceTemplateSerializer(serializers.ModelSerializer):
    template_products = TemplateProductSerializer(many=True, read_only=True)
    
    class Meta:
        model = InvoiceTemplate
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')