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
            'ciudad',
            'provincia',
            'codigo_postal',
            'regimen',
            'logo',
            'secuencial_factura',
            'secuencial_nota_credito',
            'secuencial_retencion',
            'codigo_punto_emision',
            'ambiente_sri',
            'tipo_emision',
            'is_active',
            'created_at',
            'updated_at'
        ]
    
    def validate_ruc(self, value):
        """
        Valida formato de RUC ecuatoriano (13 dígitos)
        """
        if not value.isdigit():
            raise serializers.ValidationError("El RUC debe contener solo números")
        
        if len(value) != 13:
            raise serializers.ValidationError("El RUC debe tener exactamente 13 dígitos")
        
        # Eliminamos la validación de checksum manual ya que los RUCs 
        # vienen validados por la firma electrónica del SRI.
        return value