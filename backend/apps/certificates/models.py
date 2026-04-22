# -*- coding: utf-8 -*-
"""
Models for certificates app - CORREGIDO DEFINITIVO CON STORAGE DUAL + ENCRYPTED PASSWORD
Modelos para certificados digitales del SRI
"""

import os
import hashlib
import uuid
import logging
import base64
from pathlib import Path
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography import x509
from cryptography.fernet import Fernet
from apps.core.models import BaseModel
from apps.companies.models import Company

logger = logging.getLogger(__name__)


import re

def certificate_upload_path(instance, filename):
    """Genera la ruta para subir certificados según la nueva estructura"""
    try:
        business_name = instance.company.business_name.lower()
        company_name = re.sub(r'[^a-z0-9_]', '_', business_name).strip('_')
    except:
        company_name = instance.company.ruc
    
    return f'certificados/{company_name}/{filename}'


class DigitalCertificate(BaseModel):
    """
    Certificado digital para firma electrónica del SRI
    """
    
    STATUS_CHOICES = [
        ('ACTIVE', _('Active')),
        ('EXPIRED', _('Expired')),
        ('REVOKED', _('Revoked')),
        ('INACTIVE', _('Inactive')),
    ]
    
    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name='digital_certificate',
        verbose_name=_('company'),
        help_text=_('Company that owns this certificate')
    )
    
    certificate_file = models.FileField(
        _('certificate file'),
        upload_to=certificate_upload_path,
        help_text=_('P12 certificate file')
    )
    
    # ========== STORAGE DUAL (DEPRECATED) ==========
    storage_path = models.CharField(
        _('storage path'),
        max_length=500,
        blank=True,
        null=True,
        help_text=_('DEPRECATED: Path to certificate file in storage/certificates/ directory. Use certificate_file instead.')
    )
    
    # ========== SEGURIDAD DE PASSWORD ==========
    # Clave hasheada - LEGACY (mantener para compatibilidad)
    password_hash = models.CharField(
        _('password hash'),
        max_length=128,
        help_text=_('Hashed password for the certificate (LEGACY)')
    )
    
    # ✅ NUEVO: Password encriptado con Fernet
    encrypted_password = models.TextField(
        _('encrypted password'),
        blank=True,
        null=True,
        help_text=_('Certificate password encrypted with Fernet (AES-128)')
    )
    
    # Información del certificado
    subject_name = models.CharField(
        _('subject name'),
        max_length=255,
        help_text=_('Certificate subject name')
    )
    
    issuer_name = models.CharField(
        _('issuer name'),
        max_length=255,
        help_text=_('Certificate issuer name')
    )
    
    serial_number = models.CharField(
        _('serial number'),
        max_length=100,
        help_text=_('Certificate serial number')
    )
    
    extracted_ruc = models.CharField(
        _('extracted RUC'),
        max_length=13,
        blank=True,
        null=True,
        help_text=_('RUC extracted from certificate')
    )
    
    extracted_name = models.CharField(
        _('extracted name'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Name or Business Name extracted from certificate')
    )
    
    valid_from = models.DateTimeField(
        _('valid from'),
        help_text=_('Certificate validity start date')
    )
    
    valid_to = models.DateTimeField(
        _('valid to'),
        help_text=_('Certificate expiration date')
    )
    
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=STATUS_CHOICES,
        default='ACTIVE',
        help_text=_('Certificate status')
    )
    
    fingerprint = models.CharField(
        _('fingerprint'),
        max_length=64,
        unique=True,
        help_text=_('Certificate fingerprint (SHA256)')
    )
    
    # Configuración SRI
    environment = models.CharField(
        _('environment'),
        max_length=20,
        choices=[
            ('PRODUCTION', _('Production')),
            ('TEST', _('Test')),
        ],
        default='TEST',
        help_text=_('SRI environment for this certificate')
    )
    
    class Meta:
        verbose_name = _('Digital Certificate')
        verbose_name_plural = _('Digital Certificates')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.company.business_name} - {self.subject_name}"
    
    # ========== ENCRIPTACIÓN DE PASSWORD ==========
    
    def _get_encryption_key(self):
        """
        Genera clave de encriptación desde SECRET_KEY de Django
        Usa PBKDF2 para derivar una clave compatible con Fernet
        """
        # Derivar clave de 32 bytes desde SECRET_KEY
        key = hashlib.pbkdf2_hmac(
            'sha256',
            settings.SECRET_KEY.encode('utf-8'),
            b'certificate_encryption_salt',  # Salt fijo para consistencia
            100000,  # Iteraciones
            dklen=32
        )
        return base64.urlsafe_b64encode(key)
    
    def set_password(self, password: str):
        """
        Encripta y almacena el password del certificado usando Fernet (AES-128)
        
        Args:
            password: contraseña en texto plano del certificado P12
        """
        if not password:
            logger.warning(f"Intentando establecer password vacío para certificado {self.id}")
            return
        
        try:
            # Encriptar con Fernet
            fernet = Fernet(self._get_encryption_key())
            encrypted = fernet.encrypt(password.encode('utf-8'))
            self.encrypted_password = base64.b64encode(encrypted).decode('utf-8')
            
            # LEGACY: También actualizar password_hash para compatibilidad
            self.password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
            
            logger.info(f"✅ Password encriptado exitosamente para certificado {self.id}")
            
        except Exception as e:
            logger.error(f"❌ Error encriptando password para certificado {self.id}: {e}")
            raise
    
    def get_password(self) -> str:
        """
        Desencripta y retorna el password del certificado
        
        Returns:
            str: password en texto plano o None si no existe
        """
        if not self.encrypted_password:
            logger.warning(
                f"No hay password encriptado para certificado {self.id} (empresa {self.company_id}). "
                f"Use cert.set_password('su_password') para establecerlo."
            )
            return None
        
        try:
            # Desencriptar con Fernet
            fernet = Fernet(self._get_encryption_key())
            encrypted_bytes = base64.b64decode(self.encrypted_password.encode('utf-8'))
            decrypted = fernet.decrypt(encrypted_bytes)
            password = decrypted.decode('utf-8')
            
            logger.debug(f"✅ Password desencriptado exitosamente para certificado {self.id}")
            return password
            
        except Exception as e:
            logger.error(f"❌ Error desencriptando password para certificado {self.id}: {e}")
            return None
    
    def verify_password(self, password: str) -> bool:
        """
        Verifica si un password es correcto para este certificado
        
        Args:
            password: password a verificar
            
        Returns:
            bool: True si el password es correcto
        """
        stored_password = self.get_password()
        if not stored_password:
            return False
        
        return stored_password == password
    
    def has_valid_password(self) -> bool:
        """
        Verifica si el certificado tiene un password válido almacenado
        
        Returns:
            bool: True si tiene password encriptado
        """
        return bool(self.encrypted_password)
    
    # ========== MÉTODOS DJANGO ==========
    
    def save(self, *args, **kwargs):
        # Asegurar campos requeridos ANTES de guardar
        self._ensure_required_fields()
        
        # Guardar primero
        super().save(*args, **kwargs)
        
        # ✅ Sincronizar ambiente con Company y SRIConfiguration para evitar discrepancias
        try:
            from apps.companies.models import Company
            from apps.sri_integration.models import SRIConfiguration
            
            # 1. Actualizar Company.ambiente_sri ('1' o '2')
            new_val = '1' if self.environment == 'TEST' else '2'
            Company.objects.filter(pk=self.company.pk).update(ambiente_sri=new_val)
            
            # 2. Actualizar SRIConfiguration.environment ('TEST' o 'PRODUCTION')
            SRIConfiguration.objects.filter(company=self.company).update(environment=self.environment)
            
            logger.info(f"✅ Sincronización de ambiente desde Certificado para empresa {self.company.ruc}: {self.environment}")
        except Exception as e:
            logger.warning(f"No se pudo sincronizar ambiente desde DigitalCertificate: {e}")
        
        # Luego intentar extraer información del certificado si es posible
        if self.certificate_file:
            try:
                self._extract_certificate_info()
                # Guardar de nuevo si se extrajo información
                super().save(update_fields=['fingerprint'])
            except Exception as e:
                logger.debug(f'Warning: Could not extract certificate info: {e}')
    
    def _ensure_required_fields(self):
        """Asegurar que todos los campos requeridos tienen valores"""
        now = timezone.now()
        
        # Asegurar fechas
        if not self.valid_from:
            self.valid_from = now
        
        if not self.valid_to:
            self.valid_to = now + timezone.timedelta(days=365)
        
        # Asegurar nombres
        if not self.subject_name:
            self.subject_name = f'Certificado {self.company.business_name if self.company else "Desconocido"}'
        
        if not self.issuer_name:
            self.issuer_name = 'Autoridad Certificadora'
        
        if not self.serial_number:
            self.serial_number = str(uuid.uuid4())[:20]
        
        # Asegurar fingerprint único
        if not self.fingerprint:
            self.fingerprint = str(uuid.uuid4()).replace('-', '')[:32]
        
        # Asegurar password_hash
        if not self.password_hash:
            self.password_hash = 'temp_hash'
    
    # ========== EXTRACCIÓN DE INFORMACIÓN ==========
    
    def extract_real_certificate_info(self, password: str) -> bool:
        """
        Extrae información REAL del certificado P12
        
        Args:
            password: contraseña del certificado
            
        Returns:
            bool: True si se extrajo correctamente, False si falló
        """
        try:
            if not self.certificate_file or not password:
                return False
            
            # Leer el archivo P12
            try:
                # Usamos open() del FieldFile que es compatible con S3 y Local
                with self.certificate_file.open('rb') as f:
                    cert_data = f.read()
            except Exception as e:
                logger.error(f"Error leyendo archivo de certificado: {e}")
                return False
            
            if not cert_data:
                return False
            
            # Cargar certificado con contraseña
            try:
                # MÉTODO 1: Cryptography (Estándar)
                private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
                    cert_data,
                    password.encode('utf-8')
                )
            except Exception as e:
                logger.warning(f"Cryptography falló al abrir P12 en el modelo, intentando fallback con pyOpenSSL: {str(e)}")
                try:
                    # MÉTODO 2: Fallback con pyOpenSSL (más robusto con formatos legacy)
                    from OpenSSL import crypto
                    p12 = crypto.load_pkcs12(cert_data, password.encode('utf-8'))
                    
                    pk_obj = p12.get_privatekey()
                    private_key = pk_obj.to_cryptography_key() if pk_obj else None
                    
                    cert_obj = p12.get_certificate()
                    certificate = cert_obj.to_cryptography() if cert_obj else None
                    
                    # Additional certs fallback
                    additional_certs = []
                    ca_certs = p12.get_ca_certificates()
                    if ca_certs:
                        for ca in ca_certs:
                            additional_certs.append(ca.to_cryptography())
                            
                    logger.info("✅ P12 cargado exitosamente en el modelo usando fallback de pyOpenSSL")
                except Exception as e2:
                    logger.error(f"Error crítico en el modelo: Ambos métodos fallaron. Error 1: {str(e)}, Error 2: {str(e2)}")
                    return False
            
            if not certificate:
                return False
            
            # Extraer información REAL
            subject = certificate.subject
            issuer = certificate.issuer
            
            # 🕵️ BUSCAR RUC Y NOMBRE (Ecuador Específico)
            from .utils import extract_ecuador_ruc
            ruc_found, name_found = extract_ecuador_ruc(certificate)
            
            # Formatear nombres de forma legible
            subject_parts = []
            for attribute in subject:
                subject_parts.append(f"{attribute.oid._name}={attribute.value}")
            
            # Actualizar campos con información REAL
            self.subject_name = name_found or ", ".join(subject_parts)
            self.extracted_ruc = ruc_found
            self.extracted_name = name_found
            from django.utils.timezone import make_aware
            
            # Asegurar que las fechas del certificado sean aware
            v_from = certificate.not_valid_before
            v_to = certificate.not_valid_after
            
            if v_from.tzinfo is None:
                v_from = make_aware(v_from)
            if v_to.tzinfo is None:
                v_to = make_aware(v_to)
                
            self.valid_from = v_from
            self.valid_to = v_to
            self.serial_number = str(certificate.serial_number)
            
            # ✅ ACTUALIZACIÓN AUTOMÁTICA DE LA EMPRESA
            # Si encontramos datos reales en la firma, actualizamos la empresa para que coincidan
            if ruc_found and self.company:
                logger.info(f"🔎 Sincronizando Empresa con datos de firma: {ruc_found} - {name_found}")
                
                # Solo actualizar si es diferente o la empresa tiene el RUC genérico/placeholder
                is_placeholder = self.company.ruc in ['0000000000001', '1234567890001']
                
                if is_placeholder or self.company.ruc != ruc_found:
                    self.company.ruc = ruc_found
                    if name_found:
                        self.company.business_name = name_found
                        if not self.company.trade_name:
                            self.company.trade_name = name_found
                    
                    # Guardar empresa (esto disparará a su vez la sincronización con SRIConfig)
                    self.company.save()
                    logger.info(f"✅ Datos de Empresa actualizados desde la firma digital")
            
            # Calcular fingerprint REAL
            self.fingerprint = hashlib.sha256(
                certificate.public_bytes(serialization.Encoding.DER)
            ).hexdigest()[:32]
            
            # Determinar estado basado en fechas
            now = timezone.now()
            if v_to < now:
                self.status = 'EXPIRED'
            else:
                self.status = 'ACTIVE'
            
            # Guardar password encriptado
            self.set_password(password)
            
            # Guardar cambios
            self.save()
            
            logger.info(f"✅ Información real extraída para {self.company.business_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error extrayendo información real: {e}")
            return False
    
    def _extract_certificate_info(self):
        """Extrae información del certificado P12 (método legado simplificado)"""
        try:
            # Verificar que el archivo existe
            if not self.certificate_file:
                return
                
            file_path = None
            cert_data = None
            
            # Intentar obtener el contenido del archivo
            try:
                with self.certificate_file.open('rb') as f:
                    cert_data = f.read()
            except Exception as e:
                logger.debug(f"Error leyendo certificado en _extract_certificate_info (intento 1): {e}")
                # Fallback: intentar lectura directa si el objeto lo soporta
                try:
                    if hasattr(self.certificate_file, 'read'):
                        self.certificate_file.seek(0)
                        cert_data = self.certificate_file.read()
                except Exception as e2:
                    logger.error(f"Error en fallback de lectura: {e2}")
            
            if cert_data:
                # Generar fingerprint del archivo
                self.fingerprint = hashlib.sha256(cert_data).hexdigest()[:32]
            else:
                # Generar fingerprint único como fallback
                self.fingerprint = str(uuid.uuid4()).replace('-', '')[:32]
            
        except Exception as e:
            # En caso de error, generar fingerprint único
            self.fingerprint = str(uuid.uuid4()).replace('-', '')[:32]
            logger.debug(f'Warning extracting certificate info: {e}')
    
    # ========== STORAGE DUAL ==========
    
    @property
    def storage_file_exists(self):
        """Verifica si el archivo existe en storage"""
        if not self.storage_path:
            return False
        
        full_path = Path(settings.BASE_DIR) / 'storage' / self.storage_path
        return full_path.exists()
    
    @property
    def storage_file_path(self):
        """Ruta completa al archivo en storage"""
        if not self.storage_path:
            return None
        
        return Path(settings.BASE_DIR) / 'storage' / self.storage_path
    
    @property
    def storage_file_size(self):
        """Tamaño del archivo en storage"""
        try:
            if not self.storage_file_exists:
                return 0
            return self.storage_file_path.stat().st_size
        except Exception:
            return 0
    
    def get_certificate_content_from_storage(self):
        """
        Lee el contenido del certificado desde storage
        
        Returns:
            bytes: contenido del archivo P12 o None si no existe
        """
        try:
            if not self.storage_file_exists:
                logger.warning(f"Archivo de certificado no existe en storage: {self.storage_path}")
                return None
            
            with open(self.storage_file_path, 'rb') as f:
                content = f.read()
                logger.info(f"Certificado leído desde storage: {len(content)} bytes")
                return content
                
        except Exception as e:
            logger.error(f"Error leyendo certificado desde storage: {e}")
            return None
    
    def get_certificate_content_from_media(self):
        """
        Lee el contenido del certificado desde media
        
        Returns:
            bytes: contenido del archivo P12 o None si no existe
        """
        try:
            if not self.certificate_file:
                return None
            
            try:
                with self.certificate_file.open('rb') as f:
                    content = f.read()
                    logger.info(f"Certificado leído desde almacenamiento (S3/Media): {len(content)} bytes")
                    return content
            except Exception as e:
                # Fallback: intentar lectura directa si el objeto lo soporta
                if hasattr(self.certificate_file, 'read'):
                    try:
                        self.certificate_file.seek(0)
                        content = self.certificate_file.read()
                        self.certificate_file.seek(0)
                        logger.info(f"Certificado leído desde file object: {len(content)} bytes")
                        return content
                    except:
                        pass
                raise e
            
            return None
            
        except Exception as e:
            logger.error(f"Error leyendo certificado desde media: {e}")
            return None
    
    def get_certificate_content(self, prefer_storage=False):
        """
        Lee el contenido del certificado desde media (Bucket/S3)
        
        Args:
            prefer_storage: Ignorado (mantenido por compatibilidad de firma)
            
        Returns:
            bytes: contenido del archivo P12
        """
        # Siempre intentar media (Bucket) primero
        content = self.get_certificate_content_from_media()
        if content:
            return content
        
        # Fallback a storage (para certificados antiguos no migrados)
        logger.warning(f"Certificado no encontrado en media para {self.id}, intentando storage local...")
        return self.get_certificate_content_from_storage()
    
    def verify_storage_integrity(self):
        """
        Verifica que el archivo en media y storage sean idénticos
        
        Returns:
            dict: estado de la verificación
        """
        result = {
            'media_exists': False,
            'storage_exists': False,
            'sizes_match': False,
            'contents_match': False,
            'error': None
        }
        
        try:
            # Verificar media
            media_content = self.get_certificate_content_from_media()
            result['media_exists'] = media_content is not None
            
            # Verificar storage
            storage_content = self.get_certificate_content_from_storage()
            result['storage_exists'] = storage_content is not None
            
            # Comparar tamaños y contenido
            if media_content and storage_content:
                result['sizes_match'] = len(media_content) == len(storage_content)
                result['contents_match'] = media_content == storage_content
            
            logger.info(f"Verificación de integridad: {result}")
            
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Error verificando integridad: {e}")
        
        return result
    
    def force_sync_to_storage(self):
        """
        Fuerza la sincronización del archivo desde media a storage
        
        Returns:
            bool: True si se sincronizó exitosamente
        """
        try:
            # Obtener contenido desde media
            content = self.get_certificate_content_from_media()
            if not content:
                logger.error("No se pudo obtener contenido desde media para sincronizar")
                return False
            
            # Asegurar directorio de storage
            if not self.company or not self.company.ruc:
                logger.error("No se puede sincronizar: empresa o RUC no válido")
                return False
            
            storage_base = Path(settings.BASE_DIR) / 'storage' / 'certificates'
            company_dir = storage_base / self.company.ruc
            company_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(company_dir, 0o700)
            
            # Obtener nombre del archivo
            filename = os.path.basename(self.certificate_file.name)
            storage_file_path = company_dir / filename
            
            # Escribir archivo
            with open(storage_file_path, 'wb') as f:
                f.write(content)
            
            # Configurar permisos seguros
            os.chmod(storage_file_path, 0o600)
            
            # Actualizar storage_path
            relative_path = f"certificates/{self.company.ruc}/{filename}"
            self.storage_path = relative_path
            self.save(update_fields=['storage_path'])
            
            logger.info(f"Certificado sincronizado exitosamente a storage: {storage_file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error sincronizando certificado a storage: {e}")
            return False
    
    # ========== PROPIEDADES ==========
    
    @property
    def is_expired(self):
        """Verifica si el certificado ha expirado"""
        if not self.valid_to:
            return False
        return timezone.now() > self.valid_to
    
    @property
    def days_until_expiration(self):
        """Días hasta la expiración"""
        if not self.valid_to or self.is_expired:
            return 0
        return (self.valid_to - timezone.now()).days
    
    @property
    def storage_status(self):
        """Estado del almacenamiento dual"""
        media_exists = bool(self.certificate_file)
        storage_exists = self.storage_file_exists
        
        if media_exists and storage_exists:
            integrity = self.verify_storage_integrity()
            if integrity['contents_match']:
                return 'synced'  # Sincronizado
            else:
                return 'differs'  # Archivos diferentes
        elif media_exists and not storage_exists:
            return 'media_only'  # Solo en media
        elif not media_exists and storage_exists:
            return 'storage_only'  # Solo en storage
        else:
            return 'missing'  # No existe en ningún lado
    
    def get_storage_status_display(self):
        """Descripción legible del estado de storage"""
        status_map = {
            'synced': '✅ Sincronizado',
            'differs': '⚠️ Archivos diferentes',
            'media_only': '📄 Solo en media',
            'storage_only': '💾 Solo en storage',
            'missing': '❌ Archivos faltantes'
        }
        return status_map.get(self.storage_status, '❓ Estado desconocido')
    
    # ========== FACTORY METHOD ==========
    
    @classmethod
    def create_with_password(cls, company, certificate_file, password, environment='TEST', **kwargs):
        """
        MÉTODO FACTORY: Crear certificado con contraseña de forma segura
        
        Args:
            company: instancia de Company
            certificate_file: archivo P12
            password: contraseña del certificado
            environment: ambiente SRI
            **kwargs: otros campos opcionales
            
        Returns:
            DigitalCertificate: instancia creada
        """
        now = timezone.now()
        
        # Crear certificado con valores mínimos
        certificate = cls(
            company=company,
            certificate_file=certificate_file,
            environment=environment,
            status=kwargs.get('status', 'ACTIVE'),
            # Valores temporales - se actualizarán si se extrae info real
            subject_name=kwargs.get('subject_name', f'Procesando certificado - {company.business_name}'),
            issuer_name=kwargs.get('issuer_name', 'Procesando información del emisor...'),
            serial_number=kwargs.get('serial_number', f'temp_{uuid.uuid4().hex[:16]}'),
            valid_from=kwargs.get('valid_from', now),
            valid_to=kwargs.get('valid_to', now + timezone.timedelta(days=365)),
            fingerprint=kwargs.get('fingerprint', f'temp_{uuid.uuid4().hex[:32]}'),
            password_hash='temp'  # Se actualizará inmediatamente
        )
        
        # Configurar contraseña ENCRIPTADA
        certificate.set_password(password)
        
        # Guardar
        certificate.save()
        
        # Intentar extraer información real
        try:
            certificate.extract_real_certificate_info(password)
        except Exception as e:
            logger.warning(f'Could not extract real certificate info: {e}')
        
        return certificate


class CertificateUsageLog(BaseModel):
    """
    Registro de uso de certificados digitales
    """
    
    certificate = models.ForeignKey(
        DigitalCertificate,
        on_delete=models.CASCADE,
        related_name='usage_logs',
        verbose_name=_('certificate')
    )
    
    operation = models.CharField(
        _('operation'),
        max_length=50,
        help_text=_('Type of operation performed')
    )
    
    document_type = models.CharField(
        _('document type'),
        max_length=20,
        blank=True,
        help_text=_('Type of document signed')
    )
    
    document_number = models.CharField(
        _('document number'),
        max_length=50,
        blank=True,
        help_text=_('Document number or identifier')
    )
    
    success = models.BooleanField(
        _('success'),
        default=True,
        help_text=_('Whether the operation was successful')
    )
    
    error_message = models.TextField(
        _('error message'),
        blank=True,
        help_text=_('Error message if operation failed')
    )
    
    ip_address = models.GenericIPAddressField(
        _('IP address'),
        null=True,
        blank=True
    )
    
    class Meta:
        verbose_name = _('Certificate Usage Log')
        verbose_name_plural = _('Certificate Usage Logs')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.certificate} - {self.operation} - {self.created_at}"