# -*- coding: utf-8 -*-
"""
Serializers for companies app
"""

from rest_framework import serializers
from .models import Company

class CompanySerializer(serializers.ModelSerializer):
    display_name = serializers.ReadOnlyField()
    
    class Meta:
        model = Company
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

class CompanyListSerializer(serializers.ModelSerializer):
    """Serializer simplificado para listas"""
    display_name = serializers.ReadOnlyField()
    
    class Meta:
        model = Company
        fields = ['id', 'ruc', 'business_name', 'trade_name', 'display_name', 'email', 'is_active']