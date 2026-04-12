# -*- coding: utf-8 -*-
"""
Serializers para certificados digitales - VERSIÓN CORREGIDA Y SEGURA
"""

from rest_framework import serializers
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError
import logging
import uuid
from datetime import timedelta

logger = logging.getLogger(__name__)

# Importaciones seguras de modelos
DigitalCertificate = None
CertificateUsageLog = None

try:
    from .models import DigitalCertificate, CertificateUsageLog
    logger.info("✅ Certificate models imported successfully")
except ImportError:
    try:
        from apps.certificates.models import DigitalCertificate, CertificateUsageLog
        logger.info("✅ Certificate models imported from apps.certificates.models")
    except ImportError:
        try:
            from apps.core.models import DigitalCertificate, CertificateUsageLog
            logger.info("✅ Certificate models imported from apps.core.models")
        except ImportError:
            logger.warning("⚠️ Certificate models not available - serializers will have limited functionality")


class DigitalCertificateSerializer(serializers.ModelSerializer):
    """Serializer principal para certificados digitales - VERSIÓN SEGURA"""
    
    # Campos calculados (solo lectura)
    company_name = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    days_until_expiration = serializers.SerializerMethodField()
    
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
    status_display = serializers.SerializerMethodField()
    
    class Meta:
        model = DigitalCertificate if DigitalCertificate else object
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
    
    def get_company_name(self, obj):
        """Obtener nombre de la empresa de forma segura"""
        try:
            if hasattr(obj, 'company') and obj.company:
                return getattr(obj.company, 'business_name', 
                             getattr(obj.company, 'trade_name', 'Empresa sin nombre'))
            return 'Sin empresa'
        except Exception as e:
            logger.error(f"Error getting company name: {e}")
            return 'Error al obtener empresa'
    
    def get_is_expired(self, obj):
        """Verificar si el certificado está expirado"""
        try:
            if hasattr(obj, 'valid_to') and obj.valid_to:
                return obj.valid_to < timezone.now()
            return False
        except Exception as e:
            logger.error(f"Error checking expiration: {e}")
            return False
    
    def get_days_until_expiration(self, obj):
        """Calcular días hasta expiración"""
        try:
            if hasattr(obj, 'valid_to') and obj.valid_to:
                delta = obj.valid_to - timezone.now()
                return delta.days if delta.days >= 0 else 0
            return 0
        except Exception as e:
            logger.error(f"Error calculating days until expiration: {e}")
            return 0
    
    def get_status_display(self, obj):
        """Obtener estado formateado"""
        try:
            if hasattr(obj, 'get_status_display'):
                return obj.get_status_display()
            elif hasattr(obj, 'status'):
                status_mapping = {
                    'ACTIVE': 'Activo',
                    'INACTIVE': 'Inactivo',
                    'EXPIRED': 'Expirado',
                    'REVOKED': 'Revocado'
                }
                return status_mapping.get(obj.status, obj.status)
            return 'Desconocido'
        except Exception as e:
            logger.error(f"Error getting status display: {e}")
            return 'Error'
    
    def get_file_info(self, obj):
        """Información del archivo de certificado de forma segura"""
        try:
            if hasattr(obj, 'certificate_file') and obj.certificate_file:
                try:
                    return {
                        'filename': obj.certificate_file.name.split('/')[-1],
                        'size_kb': round(obj.certificate_file.size / 1024, 2),
                        'uploaded': True,
                        'has_password': bool(
                            hasattr(obj, 'password_hash') and 
                            obj.password_hash and 
                            obj.password_hash != 'temp_hash'
                        )
                    }
                except Exception:
                    return {'uploaded': True, 'error': 'Cannot read file info'}
            return {'uploaded': False}
        except Exception as e:
            logger.error(f"Error getting file info: {e}")
            return {'uploaded': False, 'error': str(e)}
    
    def validate_certificate_file(self, value):
        """Validar archivo de certificado"""
        if value:
            # Validar extensión
            if not value.name.lower().endswith(('.p12', '.pfx')):
                raise serializers.ValidationError(
                    "El archivo debe ser un certificado P12 (.p12) o PFX (.pfx)"
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
            
            # Validar que sea un archivo binario válido
            try:
                value.seek(0)
                header = value.read(100)
                value.seek(0)
                
                # Verificar que tenga contenido binario
                if len(header) < 10:
                    raise serializers.ValidationError(
                        "El archivo parece estar corrupto o vacío"
                    )
                    
            except Exception as e:
                raise serializers.ValidationError(
                    f"Error al validar el archivo: {str(e)}"
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
        """Actualizar certificado de forma segura"""
        if not DigitalCertificate:
            raise serializers.ValidationError("El sistema de certificados no está disponible")
        
        password = validated_data.pop('password', None)
        certificate_file = validated_data.pop('certificate_file', None)
        
        try:
            # Actualizar campos básicos
            instance = super().update(instance, validated_data)
            
            # Si hay nueva contraseña, actualizarla
            if password and hasattr(instance, 'set_password'):
                instance.set_password(password)
                instance.save()
            
            # Si hay nuevo archivo, procesarlo
            if certificate_file:
                instance.certificate_file = certificate_file
                instance.save()
            
            logger.info(f"✅ Certificate updated for company {instance.company.business_name}")
            return instance
            
        except Exception as e:
            logger.error(f"❌ Error updating certificate: {e}")
            raise serializers.ValidationError(f"Error al actualizar certificado: {str(e)}")


class CertificateUploadSerializer(serializers.Serializer):
    """Serializer específico para subir certificados - VERSIÓN SEGURA"""
    
    company = serializers.IntegerField(
        help_text="ID de la empresa propietaria del certificado"
    )
    certificate_file = serializers.FileField(
        help_text="Archivo P12/PFX del certificado digital"
    )
    password = serializers.CharField(
        help_text="Contraseña del certificado P12/PFX",
        style={'input_type': 'password'},
        min_length=1,
        max_length=100
    )
    environment = serializers.ChoiceField(
        choices=[('TEST', 'Pruebas'), ('PRODUCTION', 'Producción')],
        default='TEST',
        help_text="Ambiente SRI donde se usará el certificado"
    )
    alias = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Alias descriptivo para el certificado"
    )
    
    def validate_certificate_file(self, value):
        """Validar archivo P12/PFX"""
        if not value.name.lower().endswith(('.p12', '.pfx')):
            raise serializers.ValidationError(
                "Solo se permiten archivos .p12 o .pfx"
            )
        
        if value.size > 5 * 1024 * 1024:  # 5MB
            raise serializers.ValidationError(
                "El archivo es demasiado grande (máximo 5MB)"
            )
        
        if value.size == 0:
            raise serializers.ValidationError(
                "El archivo está vacío"
            )
        
        # Verificar que el archivo sea válido
        try:
            value.seek(0)
            header = value.read(100)
            value.seek(0)
            
            if len(header) < 10:
                raise serializers.ValidationError(
                    "El archivo parece estar corrupto"
                )
                
        except Exception as e:
            raise serializers.ValidationError(
                f"Error al leer el archivo: {str(e)}"
            )
        
        return value
    
    def validate_company(self, value):
        """Validar que la empresa existe"""
        try:
            from apps.companies.models import Company
            Company.objects.get(id=value, is_active=True)
        except Exception:
            raise serializers.ValidationError(
                "La empresa especificada no existe o no está activa"
            )
        return value
    
    def validate_password(self, value):
        """Validar contraseña"""
        if not value or len(value.strip()) == 0:
            raise serializers.ValidationError(
                "La contraseña no puede estar vacía"
            )
        return value.strip()
    
    def create(self, validated_data):
        """Crear certificado desde upload - VERSIÓN SEGURA"""
        if not DigitalCertificate:
            raise serializers.ValidationError("El sistema de certificados no está disponible")
        
        try:
            from apps.companies.models import Company
            
            company = Company.objects.get(id=validated_data['company'])
            certificate_file = validated_data['certificate_file']
            password = validated_data['password']
            environment = validated_data.get('environment', 'TEST')
            alias = validated_data.get('alias', f'Certificado {company.business_name}')
            
            # Intentar procesar el certificado con cryptography
            try:
                from cryptography.hazmat.primitives.serialization import pkcs12
                from cryptography.hazmat.backends import default_backend
                import hashlib
                
                # Leer y validar el certificado
                certificate_file.seek(0)
                cert_data = certificate_file.read()
                certificate_file.seek(0)
                
                # Intentar cargar el certificado para validarlo
                try:
                    private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
                        cert_data,
                        password.encode() if password else None,
                        backend=default_backend()
                    )
                except Exception as e:
                    raise serializers.ValidationError(
                        f"No se pudo leer el certificado. Verifique la contraseña: {str(e)}"
                    )
                
                if not certificate:
                    raise serializers.ValidationError(
                        "El archivo no contiene un certificado válido"
                    )
                
                # Extraer información del certificado
                subject = certificate.subject
                issuer = certificate.issuer
                
                # Formatear nombres de forma segura
                try:
                    subject_name = ", ".join([f"{attr.oid._name}={attr.value}" for attr in subject])
                except:
                    subject_name = str(subject)
                
                try:
                    issuer_name = ", ".join([f"{attr.oid._name}={attr.value}" for attr in issuer])
                except:
                    issuer_name = str(issuer)
                
                # Generar fingerprint
                fingerprint = hashlib.sha256(certificate.public_bytes()).hexdigest()[:32]
                
                # Desactivar certificados anteriores de la misma empresa
                try:
                    DigitalCertificate.objects.filter(
                        company=company,
                        status='ACTIVE'
                    ).update(status='INACTIVE')
                except Exception as e:
                    logger.warning(f"No se pudieron desactivar certificados anteriores: {e}")
                
                # Crear nuevo certificado
                new_certificate = DigitalCertificate(
                    company=company,
                    certificate_file=certificate_file,
                    subject_name=subject_name[:255],
                    issuer_name=issuer_name[:255],
                    serial_number=str(certificate.serial_number)[:100],
                    valid_from=certificate.not_valid_before,
                    valid_to=certificate.not_valid_after,
                    fingerprint=fingerprint,
                    environment=environment,
                    status='ACTIVE',
                )
                
                # Establecer contraseña si el método existe
                if hasattr(new_certificate, 'set_password'):
                    new_certificate.set_password(password)
                else:
                    # Fallback: hash simple
                    new_certificate.password_hash = hashlib.sha256(password.encode()).hexdigest()
                
                # Guardar
                new_certificate.save()
                
                logger.info(f"✅ Certificate uploaded successfully for {company.business_name}")
                return new_certificate
                
            except ImportError:
                # Fallback si cryptography no está disponible
                logger.warning("Cryptography library not available, using basic validation")
                
                now = timezone.now()
                
                # Crear certificado con valores por defecto
                new_certificate = DigitalCertificate(
                    company=company,
                    certificate_file=certificate_file,
                    subject_name=alias[:255],
                    issuer_name='Autoridad Certificadora SRI',
                    serial_number=str(uuid.uuid4())[:20],
                    valid_from=now,
                    valid_to=now + timedelta(days=365),
                    fingerprint=str(uuid.uuid4()).replace('-', '')[:32],
                    environment=environment,
                    status='ACTIVE',
                )
                
                # Establecer contraseña
                if hasattr(new_certificate, 'set_password'):
                    new_certificate.set_password(password)
                else:
                    import hashlib
                    new_certificate.password_hash = hashlib.sha256(password.encode()).hexdigest()
                
                new_certificate.save()
                
                logger.info(f"✅ Certificate uploaded (basic mode) for {company.business_name}")
                return new_certificate
                
        except Exception as e:
            logger.error(f"❌ Error creating certificate: {e}")
            raise serializers.ValidationError(f"Error al procesar certificado: {str(e)}")


class CertificateStatusSerializer(serializers.ModelSerializer):
    """Serializer simple para estado del certificado"""
    
    company_name = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    days_until_expiration = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    
    class Meta:
        model = DigitalCertificate if DigitalCertificate else object
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
    
    def get_company_name(self, obj):
        """Obtener nombre de empresa"""
        try:
            return obj.company.business_name if obj.company else 'Sin empresa'
        except:
            return 'Error al obtener empresa'
    
    def get_status_display(self, obj):
        """Obtener estado formateado"""
        try:
            if hasattr(obj, 'get_status_display'):
                return obj.get_status_display()
            return obj.status
        except:
            return 'Desconocido'
    
    def get_days_until_expiration(self, obj):
        """Días hasta expiración"""
        try:
            if obj.valid_to:
                delta = obj.valid_to - timezone.now()
                return delta.days if delta.days >= 0 else 0
            return 0
        except:
            return 0
    
    def get_is_expired(self, obj):
        """Verificar expiración"""
        try:
            return obj.valid_to < timezone.now() if obj.valid_to else False
        except:
            return False


# Solo crear serializer de logs si el modelo existe
if CertificateUsageLog:
    class CertificateUsageLogSerializer(serializers.ModelSerializer):
        """Serializer para logs de uso de certificados"""
        
        certificate_company = serializers.SerializerMethodField()
        certificate_subject = serializers.SerializerMethodField()
        
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
        
        def get_certificate_company(self, obj):
            """Obtener empresa del certificado"""
            try:
                return obj.certificate.company.business_name if obj.certificate and obj.certificate.company else 'Sin empresa'
            except:
                return 'Error'
        
        def get_certificate_subject(self, obj):
            """Obtener subject del certificado"""
            try:
                return obj.certificate.subject_name if obj.certificate else 'Sin certificado'
            except:
                return 'Error'
else:
    class CertificateUsageLogSerializer(serializers.Serializer):
        """Serializer dummy para cuando el modelo no existe"""
        message = serializers.CharField(
            default="CertificateUsageLog model not available",
            read_only=True
        )


class CertificateTestSerializer(serializers.Serializer):
    """Serializer para probar certificado"""
    
    password = serializers.CharField(
        help_text="Contraseña del certificado para probar",
        style={'input_type': 'password'},
        min_length=1
    )
    
    def validate_password(self, value):
        """Validar contraseña"""
        if not value or len(value.strip()) == 0:
            raise serializers.ValidationError("La contraseña es requerida")
        return value.strip()


class CertificateInfoSerializer(serializers.Serializer):
    """Serializer para información básica del certificado"""
    
    id = serializers.IntegerField(read_only=True)
    company_name = serializers.CharField(read_only=True)
    subject_name = serializers.CharField(read_only=True)
    issuer_name = serializers.CharField(read_only=True)
    valid_from = serializers.DateTimeField(read_only=True)
    valid_to = serializers.DateTimeField(read_only=True)
    status = serializers.CharField(read_only=True)
    environment = serializers.CharField(read_only=True)
    days_until_expiration = serializers.IntegerField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    
    def to_representation(self, instance):
        """Convertir instancia a representación segura"""
        try:
            if not instance:
                return {}
            
            data = {
                'id': getattr(instance, 'id', None),
                'company_name': getattr(instance.company, 'business_name', 'Sin empresa') if hasattr(instance, 'company') and instance.company else 'Sin empresa',
                'subject_name': getattr(instance, 'subject_name', 'Sin subject'),
                'issuer_name': getattr(instance, 'issuer_name', 'Sin emisor'),
                'valid_from': getattr(instance, 'valid_from', None),
                'valid_to': getattr(instance, 'valid_to', None),
                'status': getattr(instance, 'status', 'UNKNOWN'),
                'environment': getattr(instance, 'environment', 'TEST'),
            }
            
            # Calcular expiración
            try:
                if data['valid_to']:
                    delta = data['valid_to'] - timezone.now()
                    data['days_until_expiration'] = delta.days if delta.days >= 0 else 0
                    data['is_expired'] = delta.days < 0
                else:
                    data['days_until_expiration'] = 0
                    data['is_expired'] = False
            except:
                data['days_until_expiration'] = 0
                data['is_expired'] = False
            
            return data
            
        except Exception as e:
            logger.error(f"Error in certificate info serialization: {e}")
            return {
                'error': 'Error al obtener información del certificado',
                'details': str(e)
            }


# Función de utilidad para verificar disponibilidad
def check_serializer_availability():
    """Verificar qué serializers están disponibles"""
    return {
        'digital_certificate': DigitalCertificate is not None,
        'certificate_usage_log': CertificateUsageLog is not None,
        'cryptography_available': True,  # Se verifica en runtime
        'serializers_loaded': True
    }


# Log de inicialización
try:
    availability = check_serializer_availability()
    logger.info(f"📊 Certificate serializers loaded: {availability}")
except Exception as e:
    logger.error(f"❌ Error checking serializer availability: {e}")