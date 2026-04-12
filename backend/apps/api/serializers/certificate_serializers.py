# -*- coding: utf-8 -*-
"""
Serializers para certificados digitales - CORREGIDO DEFINITIVO
"""

from rest_framework import serializers
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone
from apps.certificates.models import DigitalCertificate, CertificateUsageLog


class DigitalCertificateSerializer(serializers.ModelSerializer):
    """Serializer principal para certificados digitales"""
    
    # Campos calculados (solo lectura)
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    is_expired = serializers.ReadOnlyField()
    days_until_expiration = serializers.ReadOnlyField()
    
    # Campo para contraseña (solo escritura)
    password = serializers.CharField(
        write_only=True, 
        required=False,
        help_text="Contraseña del certificado P12",
        style={'input_type': 'password'}
    )
    
    # Información del archivo (solo lectura)
    file_info = serializers.SerializerMethodField()
    
    # Estado formateado (solo lectura)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = DigitalCertificate
        fields = [
            'id',
            'company',
            'company_name',
            'certificate_file',
            'subject_name',
            'issuer_name',
            'serial_number',
            'valid_from',
            'valid_to',
            'status',
            'status_display',
            'fingerprint',
            'environment',
            'password',
            'file_info',
            'is_expired',
            'days_until_expiration',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'subject_name',
            'issuer_name',
            'serial_number',
            'valid_from',
            'valid_to',
            'fingerprint',
            'created_at',
            'updated_at'
        ]
        extra_kwargs = {
            'certificate_file': {
                'required': False,
                'help_text': 'Archivo P12 del certificado digital'
            },
            'status': {
                'help_text': 'Estado actual del certificado'
            },
            'environment': {
                'help_text': 'Ambiente SRI (TEST o PRODUCTION)'
            }
        }
    
    def get_file_info(self, obj):
        """Información del archivo de certificado"""
        if obj.certificate_file:
            try:
                return {
                    'filename': obj.certificate_file.name.split('/')[-1],
                    'size_kb': round(obj.certificate_file.size / 1024, 2),
                    'uploaded': True,
                    'has_password': bool(obj.password_hash and obj.password_hash != 'temp_hash')
                }
            except Exception:
                return {'uploaded': False, 'error': 'Cannot read file info'}
        return {'uploaded': False}
    
    def validate_certificate_file(self, value):
        """Validar archivo de certificado"""
        if value:
            # Validar extensión
            if not value.name.lower().endswith('.p12'):
                raise serializers.ValidationError(
                    "El archivo debe ser un certificado P12 (.p12)"
                )
            
            # Validar tamaño (máximo 5MB)
            if value.size > 5 * 1024 * 1024:
                raise serializers.ValidationError(
                    "El archivo no puede ser mayor a 5MB"
                )
            
            # Validar que no esté vacío
            if value.size == 0:
                raise serializers.ValidationError(
                    "El archivo está vacío"
                )
        
        return value
    
    def validate(self, attrs):
        """Validación general"""
        # Si se proporciona un nuevo archivo, debe incluir contraseña
        if attrs.get('certificate_file') and not attrs.get('password'):
            raise serializers.ValidationError({
                'password': 'La contraseña es requerida cuando se sube un certificado'
            })
        
        return attrs
    
    def update(self, instance, validated_data):
        """Actualizar certificado"""
        password = validated_data.pop('password', None)
        certificate_file = validated_data.pop('certificate_file', None)
        
        # Actualizar campos básicos
        instance = super().update(instance, validated_data)
        
        # Si hay nueva contraseña, actualizarla
        if password:
            instance.set_password(password)
            instance.save()
        
        # Si hay nuevo archivo, procesarlo
        if certificate_file:
            instance.certificate_file = certificate_file
            instance.save()
        
        return instance


class CertificateUploadSerializer(serializers.Serializer):
    """Serializer específico para subir certificados - CORREGIDO"""
    
    company = serializers.IntegerField(
        help_text="ID de la empresa propietaria del certificado"
    )
    certificate_file = serializers.FileField(
        help_text="Archivo P12 del certificado digital"
    )
    password = serializers.CharField(
        help_text="Contraseña del certificado P12",
        style={'input_type': 'password'},
        min_length=1,
        max_length=100
    )
    environment = serializers.ChoiceField(
        choices=[('TEST', 'Pruebas'), ('PRODUCTION', 'Producción')],
        default='TEST',
        help_text="Ambiente SRI donde se usará el certificado"
    )
    
    def validate_certificate_file(self, value):
        """Validar archivo P12"""
        if not value.name.lower().endswith('.p12'):
            raise serializers.ValidationError(
                "Solo se permiten archivos .p12"
            )
        
        if value.size > 5 * 1024 * 1024:  # 5MB
            raise serializers.ValidationError(
                "El archivo es demasiado grande (máximo 5MB)"
            )
        
        if value.size == 0:
            raise serializers.ValidationError(
                "El archivo está vacío"
            )
        
        return value
    
    def validate_company(self, value):
        """Validar que la empresa existe"""
        from apps.companies.models import Company
        try:
            Company.objects.get(id=value)
        except Company.DoesNotExist:
            raise serializers.ValidationError(
                "La empresa especificada no existe"
            )
        return value
    
    def create(self, validated_data):
        """Crear certificado desde upload - CORREGIDO"""
        from apps.companies.models import Company
        
        company = Company.objects.get(id=validated_data['company'])
        certificate_file = validated_data['certificate_file']
        password = validated_data['password']
        environment = validated_data.get('environment', 'TEST')
        
        # USAR EL MÉTODO FACTORY DEL MODELO
        certificate = DigitalCertificate.create_with_password(
            company=company,
            certificate_file=certificate_file,
            password=password,
            environment=environment
        )
        
        return certificate


class CertificateStatusSerializer(serializers.ModelSerializer):
    """Serializer simple para estado del certificado"""
    
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    days_until_expiration = serializers.ReadOnlyField()
    is_expired = serializers.ReadOnlyField()
    
    class Meta:
        model = DigitalCertificate
        fields = [
            'id',
            'company',
            'company_name',
            'subject_name',
            'environment',
            'status',
            'status_display',
            'valid_from',
            'valid_to',
            'days_until_expiration',
            'is_expired'
        ]


class CertificateUsageLogSerializer(serializers.ModelSerializer):
    """Serializer para logs de uso de certificados"""
    
    certificate_company = serializers.CharField(
        source='certificate.company.business_name', 
        read_only=True
    )
    certificate_subject = serializers.CharField(
        source='certificate.subject_name', 
        read_only=True
    )
    
    class Meta:
        model = CertificateUsageLog
        fields = [
            'id',
            'certificate',
            'certificate_company',
            'certificate_subject',
            'operation',
            'document_type',
            'document_number',
            'success',
            'error_message',
            'ip_address',
            'created_at'
        ]
        read_only_fields = [
            'id', 
            'created_at'
        ]


class CertificateTestSerializer(serializers.Serializer):
    """Serializer para probar certificado"""
    
    password = serializers.CharField(
        help_text="Contraseña del certificado para probar",
        style={'input_type': 'password'}
    )
    
    def validate_password(self, value):
        """Validar contraseña"""
        if not value:
            raise serializers.ValidationError("La contraseña es requerida")
        return value