# -*- coding: utf-8 -*-
"""
Serializers mejorados para SRI integration - API COMPLETA
"""

from rest_framework import serializers
from decimal import Decimal
from .models import (
    SRIConfiguration, ElectronicDocument, DocumentItem,
    DocumentTax, SRIResponse
)

class SRIConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SRIConfiguration
        fields = '__all__'

class DocumentItemCreateSerializer(serializers.Serializer):
    """
    Serializer para crear items de documento
    """
    main_code = serializers.CharField(max_length=25)
    auxiliary_code = serializers.CharField(max_length=25, required=False, allow_blank=True)
    description = serializers.CharField(max_length=500)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=6)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=6)
    discount = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        return value
    
    def validate_unit_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Unit price must be greater than 0")
        return value

class CreateInvoiceSerializer(serializers.Serializer):
    """
    Serializer para crear factura completa con items
    """
    # Información de la empresa
    company = serializers.IntegerField()
    
    # Información del documento
    document_type = serializers.CharField(default='INVOICE')
    issue_date = serializers.DateField(required=False)
    
    # Información del cliente
    customer_identification_type = serializers.ChoiceField(
        choices=[
            ('04', 'RUC'),
            ('05', 'Cedula'), 
            ('06', 'Passport'),
            ('07', 'Consumer'),
            ('08', 'Foreign ID'),
        ]
    )
    customer_identification = serializers.CharField(max_length=20)
    customer_name = serializers.CharField(max_length=300)
    customer_address = serializers.CharField(max_length=500, required=False, allow_blank=True)
    customer_email = serializers.EmailField(required=False, allow_blank=True)
    customer_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    
    # Items de la factura
    items = DocumentItemCreateSerializer(many=True)
    
    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        return value
    
    def validate_company(self, value):
        from apps.companies.models import Company
        try:
            Company.objects.get(id=value)
        except Company.DoesNotExist:
            raise serializers.ValidationError("Company does not exist")
        return value

class DocumentItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentItem
        fields = '__all__'

class DocumentTaxSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentTax
        fields = '__all__'

class ElectronicDocumentListSerializer(serializers.ModelSerializer):
    """
    Serializer simplificado para listados
    """
    class Meta:
        model = ElectronicDocument
        fields = [
            'id', 'document_number', 'document_type', 'status',
            'issue_date', 'customer_name', 'total_amount', 'created_at'
        ]

class ElectronicDocumentSerializer(serializers.ModelSerializer):
    """
    Serializer completo para documentos electrónicos
    """
    items = DocumentItemSerializer(many=True, read_only=True)
    taxes = DocumentTaxSerializer(many=True, read_only=True)
    
    class Meta:
        model = ElectronicDocument
        fields = '__all__'

class SRIResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SRIResponse
        fields = '__all__'
