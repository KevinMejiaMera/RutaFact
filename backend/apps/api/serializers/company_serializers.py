# -*- coding: utf-8 -*-
"""
Serializers for companies
"""

from rest_framework import serializers
from apps.companies.models import Company


class CompanySerializer(serializers.ModelSerializer):
    """
    Serializer para empresas
    """
    display_name = serializers.CharField(read_only=True)
    
    class Meta:
        model = Company
        fields = [
            'id',
            'ruc',
            'business_name',
            'trade_name',
            'display_name',
            'email',
            'phone',
            'address',
            'is_active',
            'created_at',
            'updated_at'
        ]
    
    def validate_ruc(self, value):
        """
        Valida formato de RUC ecuatoriano
        """
        if not value.isdigit():
            raise serializers.ValidationError("RUC must contain only digits")
        
        if len(value) != 13:
            raise serializers.ValidationError("RUC must be exactly 13 digits")
        
        # Validación básica de RUC
        if not self._validate_ruc_checksum(value):
            raise serializers.ValidationError("Invalid RUC checksum")
        
        return value
    
    def _validate_ruc_checksum(self, ruc):
        """
        Valida el dígito verificador del RUC
        """
        try:
            # Algoritmo de validación RUC Ecuador
            coefficients = [2, 1, 2, 1, 2, 1, 2, 1, 2]
            total = 0
            
            for i in range(9):
                digit = int(ruc[i])
                result = digit * coefficients[i]
                if result >= 10:
                    result = result - 9
                total += result
            
            remainder = total % 10
            check_digit = 0 if remainder == 0 else 10 - remainder
            
            return check_digit == int(ruc[9])
            
        except (ValueError, IndexError):
            return False