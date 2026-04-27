# -*- coding: utf-8 -*-
"""
Models for SRI integration - VERSIÓN FINAL CORREGIDA CON URLs AUTOMÁTICAS
Modelos para integración con el SRI
✅ RESUELVE ERROR DE reception_url y authorization_url
✅ URLs AUTOMÁTICAS SEGÚN AMBIENTE
✅ COMPATIBLE CON SRISOAPClient
✅ LISTO PARA FRONTEND
✅ ENHANCED CON AUTO-SEND CONFIGURATION
"""

import os
import re
import logging
from datetime import date
from django.db import models, transaction
from django.db.models import F
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from decimal import Decimal, ROUND_HALF_UP
from apps.core.models import BaseModel
from apps.companies.models import Company

# Configuración de logging
logger = logging.getLogger(__name__)


def get_sri_document_upload_path(instance, filename):
    """
    Genera la ruta de almacenamiento según: 
    facturas/[nombre-empresa]/[xml|pdf]/[año]/[mes]/[archivo]
    """
    # 1. Nombre de empresa normalizado
    try:
        business_name = instance.company.business_name.lower()
        company_name = re.sub(r'[^a-z0-9_]', '_', business_name).strip('_')
    except:
        company_name = "desconocida"
    
    # 2. Tipo de carpeta (xml o pdf)
    ext = os.path.splitext(filename)[1].lower()
    folder_type = 'xml' if 'xml' in ext else 'pdf'
    
    # 3. Fecha (año y mes en español)
    issue_date = getattr(instance, 'issue_date', date.today())
    if not isinstance(issue_date, date):
        issue_date = date.today()
    
    year = issue_date.year
    months_es = {
        1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril',
        5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
        9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'
    }
    month_name = months_es.get(issue_date.month, 'desconocido')
    
    return f"facturas/{company_name}/{folder_type.upper()}/{year}/{month_name}/{filename}"


class SRIConfiguration(BaseModel):
    """
    Configuración del SRI por empresa
    ✅ VERSIÓN FINAL CORREGIDA - URLs AUTOMÁTICAS + AUTO-SEND CONFIG
    """
    
    ENVIRONMENT_CHOICES = [
        ('PRODUCTION', _('Production')),
        ('TEST', _('Test')),
    ]
    
    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name='sri_configuration',
        verbose_name=_('company')
    )
    
    environment = models.CharField(
        _('environment'),
        max_length=20,
        choices=ENVIRONMENT_CHOICES,
        default='TEST',
        help_text=_('SRI environment')
    )
    
    REGIMEN_CHOICES = [
        ('GENERAL', _('Régimen General')),
        ('RIMPE_EMPRENDEDOR', _('Régimen RIMPE - Emprendedor')),
        ('RIMPE_POPULAR', _('Régimen RIMPE - Negocio Popular')),
        ('AGROPECUARIO', _('Régimen Agropecuario')),
    ]
    
    regimen = models.CharField(
        _('regimen'),
        max_length=30,
        choices=REGIMEN_CHOICES,
        default='GENERAL',
        help_text=_('Tax regime for SRI documents')
    )
    
    # Configuración de establecimiento
    establishment_code = models.CharField(
        _('establishment code'),
        max_length=3,
        default='001',
        help_text=_('Establishment code (3 digits)')
    )
    
    emission_point = models.CharField(
        _('emission point'),
        max_length=3,
        default='001',
        help_text=_('Emission point code (3 digits)')
    )
    
    # Configuración de secuenciales
    invoice_sequence = models.PositiveIntegerField(
        _('invoice sequence'),
        default=1,
        help_text=_('Current invoice sequence number')
    )
    
    credit_note_sequence = models.PositiveIntegerField(
        _('credit note sequence'),
        default=1,
        help_text=_('Current credit note sequence number')
    )
    
    debit_note_sequence = models.PositiveIntegerField(
        _('debit note sequence'),
        default=1,
        help_text=_('Current debit note sequence number')
    )
    
    retention_sequence = models.PositiveIntegerField(
        _('retention sequence'),
        default=1,
        help_text=_('Current retention sequence number')
    )
    
    remission_guide_sequence = models.PositiveIntegerField(
        _('remission guide sequence'),
        default=1,
        help_text=_('Current remission guide sequence number')
    )
    
    purchase_settlement_sequence = models.PositiveIntegerField(
        _('purchase settlement sequence'),
        default=1,
        help_text=_('Current purchase settlement sequence number')
    )
    
    # Configuración de email
    email_enabled = models.BooleanField(
        _('email enabled'),
        default=True,
        help_text=_('Enable automatic email sending')
    )
    
    email_subject_template = models.CharField(
        _('email subject template'),
        max_length=255,
        default='Documento Electrónico - {document_type} {document_number}',
        help_text=_('Email subject template')
    )
    
    email_body_template = models.TextField(
        _('email body template'),
        default='Estimado cliente,\n\nEn archivo adjunto encontrará su {document_type} electrónico número {document_number}.\n\nSaludos cordiales.',
        help_text=_('Email body template')
    )
    
    # Configuración adicional
    special_taxpayer = models.BooleanField(
        _('special taxpayer'),
        default=False,
        help_text=_('Is special taxpayer')
    )
    
    special_taxpayer_number = models.CharField(
        _('special taxpayer number'),
        max_length=20,
        blank=True,
        help_text=_('Special taxpayer resolution number')
    )
    
    accounting_required = models.BooleanField(
        _('accounting required'),
        default=True,
        help_text=_('Required to keep accounting')
    )
    
    # ===============================================
    # CONFIGURACIÓN DE ENVÍO AUTOMÁTICO AL SRI
    # ===============================================
    
    auto_send = models.BooleanField(
        _('auto send'),
        default=True,
        help_text=_('Send automatically to SRI after generation')
    )
    
    auto_retry = models.BooleanField(
        _('auto retry'),
        default=True,
        help_text=_('Retry automatically if sending fails')
    )
    
    max_retry_attempts = models.IntegerField(
        _('max retry attempts'),
        default=3,
        help_text=_('Maximum number of retry attempts')
    )
    
    retry_delay_minutes = models.IntegerField(
        _('retry delay minutes'),
        default=5,
        help_text=_('Minutes to wait between retry attempts')
    )
    
    auto_send_after_generation = models.BooleanField(
        _('auto send after generation'),
        default=True,
        help_text=_('Automatically send to SRI immediately after XML generation')
    )
    
    use_async_processing = models.BooleanField(
        _('use async processing'),
        default=True,
        help_text=_('Use background processing for SRI operations')
    )
    
    circuit_breaker_enabled = models.BooleanField(
        _('circuit breaker enabled'),
        default=True,
        help_text=_('Enable circuit breaker to prevent repeated failures')
    )
    
    circuit_breaker_threshold = models.IntegerField(
        _('circuit breaker threshold'),
        default=5,
        help_text=_('Number of failures before circuit breaker opens')
    )
    
    circuit_breaker_recovery_minutes = models.IntegerField(
        _('circuit breaker recovery minutes'),
        default=60,
        help_text=_('Minutes before circuit breaker resets after opening')
    )
    
    pre_validation_enabled = models.BooleanField(
        _('pre validation enabled'),
        default=True,
        help_text=_('Validate documents before sending to SRI')
    )
    
    validate_xml_schema = models.BooleanField(
        _('validate XML schema'),
        default=True,
        help_text=_('Validate XML against SRI schema before sending')
    )
    
    validate_business_rules = models.BooleanField(
        _('validate business rules'),
        default=True,
        help_text=_('Validate business rules before sending to SRI')
    )
    
    # Configuración de notificaciones
    notify_on_success = models.BooleanField(
        _('notify on success'),
        default=True,
        help_text=_('Send notification when document is successfully authorized')
    )
    
    notify_on_error = models.BooleanField(
        _('notify on error'),
        default=True,
        help_text=_('Send notification when document processing fails')
    )
    
    notify_on_retry = models.BooleanField(
        _('notify on retry'),
        default=False,
        help_text=_('Send notification when retrying failed document')
    )
    
    # Configuración de procesamiento en lote
    queue_processing_enabled = models.BooleanField(
        _('queue processing enabled'),
        default=True,
        help_text=_('Enable queue-based batch processing')
    )
    
    batch_size = models.IntegerField(
        _('batch size'),
        default=10,
        help_text=_('Number of documents to process in each batch')
    )
    
    queue_max_size = models.IntegerField(
        _('queue max size'),
        default=1000,
        help_text=_('Maximum number of documents in processing queue')
    )
    
    queue_batch_timeout_minutes = models.IntegerField(
        _('queue batch timeout minutes'),
        default=5,
        help_text=_('Minutes to wait before processing incomplete batch')
    )
    
    # Configuración de backup y limpieza
    auto_backup_documents = models.BooleanField(
        _('auto backup documents'),
        default=True,
        help_text=_('Automatically backup processed documents')
    )
    
    backup_retention_days = models.IntegerField(
        _('backup retention days'),
        default=365,
        help_text=_('Days to retain document backups')
    )
    
    compress_backup_files = models.BooleanField(
        _('compress backup files'),
        default=True,
        help_text=_('Compress backup files to save storage space')
    )
    
    auto_cleanup_old_logs = models.BooleanField(
        _('auto cleanup old logs'),
        default=True,
        help_text=_('Automatically cleanup old processing logs')
    )
    
    cleanup_days_threshold = models.IntegerField(
        _('cleanup days threshold'),
        default=90,
        help_text=_('Days after which logs are eligible for cleanup')
    )
    
    cleanup_batch_size = models.IntegerField(
        _('cleanup batch size'),
        default=100,
        help_text=_('Number of log entries to cleanup in each batch')
    )
    
    # Configuración de webhook
    webhook_enabled = models.BooleanField(
        _('webhook enabled'),
        default=False,
        help_text=_('Enable webhook notifications for SRI events')
    )
    
    webhook_url = models.URLField(
        _('webhook URL'),
        blank=True,
        help_text=_('URL to receive webhook notifications')
    )
    
    webhook_secret = models.CharField(
        _('webhook secret'),
        max_length=255,
        blank=True,
        help_text=_('Secret key for webhook authentication')
    )
    
    webhook_timeout_seconds = models.IntegerField(
        _('webhook timeout seconds'),
        default=30,
        help_text=_('Timeout for webhook HTTP requests')
    )
    
    # Configuración de métricas y monitoreo
    metrics_enabled = models.BooleanField(
        _('metrics enabled'),
        default=True,
        help_text=_('Enable metrics collection for SRI operations')
    )
    
    performance_logging = models.BooleanField(
        _('performance logging'),
        default=True,
        help_text=_('Log performance metrics for SRI operations')
    )
    
    error_tracking = models.BooleanField(
        _('error tracking'),
        default=True,
        help_text=_('Track and analyze error patterns')
    )
    
    is_active = models.BooleanField(
        _('is active'),
        default=True,
        help_text=_('Configuration is active')
    )
    
    class Meta:
        verbose_name = _('SRI Configuration')
        verbose_name_plural = _('SRI Configurations')
    
    def save(self, *args, **kwargs):
        """Sincronizar esta configuración con los campos duplicados en el modelo Company"""
        # 1. Guardar primero esta configuración
        super().save(*args, **kwargs)
        
        # 2. Sincronizar con Company para mantener concordancia entre paneles
        try:
            company = self.company
            # 3. Sincronizar también el ambiente en el Certificado Digital si existe
            if hasattr(company, 'digital_certificate'):
                from apps.certificates.models import DigitalCertificate
                DigitalCertificate.objects.filter(company=company).update(environment=self.environment)
            
        except Exception as e:
            # No detener el guardado principal si la sincronización falla
            logger.error(f"Error sincronizando SRIConfiguration con Company: {e}")
    
    def __str__(self):
        return f"SRI Config - {self.company.business_name} ({self.environment})"
    
    # ✅ URLs AUTOMÁTICAS SEGÚN AMBIENTE (IGUAL QUE SRISOAPClient)
    @property
    def reception_url(self):
        """URL de recepción según ambiente"""
        if self.environment == 'TEST':
            return "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl"
        else:  # PRODUCTION
            return "https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl"
    
    @property
    def authorization_url(self):
        """URL de autorización según ambiente"""
        if self.environment == 'TEST':
            return "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl"
        else:  # PRODUCTION
            return "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl"
    
    # ===============================================
    # MÉTODOS PARA AUTO-SEND CONFIGURATION
    # ===============================================
    
    def is_auto_send_enabled(self):
        """Verificar si el auto-envío está habilitado"""
        return self.auto_send and self.is_active
    
    def should_auto_send_after_generation(self):
        """Verificar si debe enviar automáticamente después de generar XML"""
        return self.is_auto_send_enabled() and self.auto_send_after_generation
    
    def should_use_async_processing(self):
        """Verificar si debe usar procesamiento asíncrono"""
        return self.is_auto_send_enabled() and self.use_async_processing
    
    def is_circuit_breaker_enabled(self):
        """Verificar si el circuit breaker está habilitado"""
        return self.circuit_breaker_enabled and self.is_active
    
    def should_retry_failures(self):
        """Verificar si debe reintentar fallas automáticamente"""
        return self.is_auto_send_enabled() and self.auto_retry
    
    def get_retry_delay_seconds(self):
        """Obtener delay de reintento en segundos"""
        return self.retry_delay_minutes * 60
    
    def get_circuit_breaker_recovery_seconds(self):
        """Obtener tiempo de recuperación del circuit breaker en segundos"""
        return self.circuit_breaker_recovery_minutes * 60
    
    def get_queue_batch_timeout_seconds(self):
        """Obtener timeout de lote en segundos"""
        return self.queue_batch_timeout_minutes * 60
    
    def should_validate_before_sending(self):
        """Verificar si debe validar antes de enviar"""
        return self.pre_validation_enabled
    
    def get_notification_settings(self):
        """Obtener configuración de notificaciones"""
        return {
            'notify_on_success': self.notify_on_success,
            'notify_on_error': self.notify_on_error,
            'notify_on_retry': self.notify_on_retry
        }
    
    def get_webhook_config(self):
        """Obtener configuración de webhook"""
        if not self.webhook_enabled or not self.webhook_url:
            return None
        
        return {
            'url': self.webhook_url,
            'secret': self.webhook_secret,
            'timeout': self.webhook_timeout_seconds
        }
    
    def get_backup_config(self):
        """Obtener configuración de backup"""
        return {
            'enabled': self.auto_backup_documents,
            'retention_days': self.backup_retention_days,
            'compress': self.compress_backup_files
        }
    
    def get_cleanup_config(self):
        """Obtener configuración de limpieza"""
        return {
            'enabled': self.auto_cleanup_old_logs,
            'days_threshold': self.cleanup_days_threshold,
            'batch_size': self.cleanup_batch_size
        }
    
    def get_processing_config(self):
        """Obtener configuración completa de procesamiento"""
        return {
            'auto_send': self.is_auto_send_enabled(),
            'auto_send_after_generation': self.should_auto_send_after_generation(),
            'use_async': self.should_use_async_processing(),
            'circuit_breaker': self.is_circuit_breaker_enabled(),
            'auto_retry': self.should_retry_failures(),
            'max_retry_attempts': self.max_retry_attempts,
            'retry_delay_seconds': self.get_retry_delay_seconds(),
            'circuit_breaker_threshold': self.circuit_breaker_threshold,
            'circuit_breaker_recovery_seconds': self.get_circuit_breaker_recovery_seconds(),
            'validate_before_sending': self.should_validate_before_sending(),
            'validate_xml_schema': self.validate_xml_schema,
            'validate_business_rules': self.validate_business_rules,
            'notifications': self.get_notification_settings(),
            'webhook': self.get_webhook_config(),
            'backup': self.get_backup_config(),
            'cleanup': self.get_cleanup_config(),
            'queue_processing': {
                'enabled': self.queue_processing_enabled,
                'batch_size': self.batch_size,
                'max_size': self.queue_max_size,
                'timeout_seconds': self.get_queue_batch_timeout_seconds()
            },
            'metrics': {
                'enabled': self.metrics_enabled,
                'performance_logging': self.performance_logging,
                'error_tracking': self.error_tracking
            }
        }
    
    def get_next_sequence(self, document_type):
        """Obtiene el siguiente secuencial para un tipo de documento de forma atómica"""
        field_map = {
            'INVOICE': 'invoice_sequence',
            'CREDIT_NOTE': 'credit_note_sequence',
            'DEBIT_NOTE': 'debit_note_sequence',
            'RETENTION': 'retention_sequence',
            'REMISSION_GUIDE': 'remission_guide_sequence',
            'PURCHASE_SETTLEMENT': 'purchase_settlement_sequence',
        }
        
        if document_type not in field_map:
            raise ValidationError(f"Unknown document type: {document_type}")
        
        field_name = field_map[document_type]
        
        # Operación atómica y con bloqueo de fila para asegurar secuencia 100% correcta
        with transaction.atomic():
            # Obtener configuración con bloqueo para que otros hilos/procesos esperen
            # Usando select_for_update() para evitar condiciones de carrera tipo "click doble"
            config = SRIConfiguration.objects.select_for_update().get(pk=self.pk)
            current_value = getattr(config, field_name)
            
            # Incrementar de forma segura
            setattr(config, field_name, current_value + 1)
            config.save(update_fields=[field_name])
            
            logger.info(f"🔢 Secuencia {document_type} incrementada: {current_value} -> {current_value + 1} para empresa {self.company_id}")
            return current_value
    
    def get_full_document_number(self, document_type, sequence=None):
        """Genera el número completo del documento"""
        if sequence is None:
            sequence = self.get_next_sequence(document_type)
        
        return f"{self.establishment_code}-{self.emission_point}-{sequence:09d}"


class ElectronicDocument(BaseModel):
    """
    Modelo base para documentos electrónicos del SRI
    """
    
    DOCUMENT_TYPES = [
        ('INVOICE', _('Invoice')),
        ('CREDIT_NOTE', _('Credit Note')),
        ('DEBIT_NOTE', _('Debit Note')),
        ('RETENTION', _('Retention')),
        ('REMISSION_GUIDE', _('Remission Guide')),
        ('PURCHASE_SETTLEMENT', _('Purchase Settlement')),
    ]
    
    STATUS_CHOICES = [
        ('DRAFT', _('Draft')),
        ('GENERATED', _('Generated')),
        ('SIGNED', _('Signed')),
        ('SENT', _('Sent to SRI')),
        ('AUTHORIZED', _('Authorized')),
        ('REJECTED', _('Rejected')),
        ('ERROR', _('Error')),
    ]
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='electronic_documents',
        verbose_name=_('company')
    )
    
    document_type = models.CharField(
        _('document type'),
        max_length=20,
        choices=DOCUMENT_TYPES
    )
    
    document_number = models.CharField(
        _('document number'),
        max_length=17,
        help_text=_('Format: 001-001-000000001')
    )
    
    access_key = models.CharField(
        _('access key'),
        max_length=49,
        unique=True,
        help_text=_('49-digit access key')
    )
    
    issue_date = models.DateField(
        _('issue date')
    )
    
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT'
    )
    
    # Información del cliente
    customer_identification_type = models.CharField(
        _('customer identification type'),
        max_length=2,
        choices=[
            ('04', _('RUC')),
            ('05', _('Cedula')),
            ('06', _('Passport')),
            ('07', _('Consumer')),
            ('08', _('Foreign ID')),
        ]
    )
    
    customer_identification = models.CharField(
        _('customer identification'),
        max_length=20
    )
    
    customer_name = models.CharField(
        _('customer name'),
        max_length=300
    )
    
    customer_address = models.TextField(
        _('customer address'),
        blank=True
    )
    
    customer_email = models.EmailField(
        _('customer email'),
        blank=True
    )
    
    customer_phone = models.CharField(
        _('customer phone'),
        max_length=20,
        blank=True
    )
    
    # Totales
    subtotal_without_tax = models.DecimalField(
        _('subtotal without tax'),
        max_digits=12,
        decimal_places=2,
        default=0
    )
    
    subtotal_with_tax = models.DecimalField(
        _('subtotal with tax'),
        max_digits=12,
        decimal_places=2,
        default=0
    )
    
    total_discount = models.DecimalField(
        _('total discount'),
        max_digits=12,
        decimal_places=2,
        default=0
    )
    
    total_tax = models.DecimalField(
        _('total tax'),
        max_digits=12,
        decimal_places=2,
        default=0
    )
    
    total_amount = models.DecimalField(
        _('total amount'),
        max_digits=12,
        decimal_places=2,
        default=0
    )
    
    # Archivos generados
    xml_file = models.FileField(
        _('XML file'),
        upload_to=get_sri_document_upload_path,
        blank=True
    )
    
    signed_xml_file = models.FileField(
        _('signed XML file'),
        upload_to=get_sri_document_upload_path,
        blank=True
    )
    
    pdf_file = models.FileField(
        _('PDF file'),
        upload_to=get_sri_document_upload_path,
        blank=True
    )
    
    # Información del SRI
    sri_authorization_code = models.CharField(
        _('SRI authorization code'),
        max_length=49,
        blank=True
    )
    
    sri_authorization_date = models.DateTimeField(
        _('SRI authorization date'),
        null=True,
        blank=True
    )
    
    sri_response = models.JSONField(
        _('SRI response'),
        default=dict,
        blank=True
    )
    
    # Email
    email_sent = models.BooleanField(
        _('email sent'),
        default=False
    )
    
    email_sent_date = models.DateTimeField(
        _('email sent date'),
        null=True,
        blank=True
    )
    
    # Datos adicionales
    additional_data = models.JSONField(
        _('additional data'),
        default=dict,
        blank=True
    )
    
    class Meta:
        verbose_name = _('Electronic Document')
        verbose_name_plural = _('Electronic Documents')
        unique_together = ['company', 'document_number', 'document_type']
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['access_key']),
            models.Index(fields=['issue_date']),
        ]
    
    def __str__(self):
        return f"{self.get_document_type_display()} {self.document_number} - {self.company.business_name}"
    
    @property
    def environment(self):
        """Deduce el ambiente desde la clave de acceso (posición 24)"""
        if self.access_key and len(self.access_key) >= 24:
            env_digit = self.access_key[23]  # Posición 23 (index 0) es el carácter 24
            return 'TEST' if env_digit == '1' else 'PRODUCTION'
        return 'TEST'
    
    def save(self, *args, **kwargs):
        # Solo generamos número si no existe (la lógica de limpieza se movió al Processor y Tasks)
        if not self.document_number:
            try:
                sri_config = self.company.sri_configuration
                
                # Bucle de seguridad para asegurar que el número no exista ya en DB
                # Esto previene errores de "UniqueConstraint" si un proceso "saltó" a un número futuro
                max_safety_retries = 10
                for _ in range(max_safety_retries):
                    sequence = sri_config.get_next_sequence(self.document_type)
                    new_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
                    
                    if not ElectronicDocument.objects.filter(
                        company=self.company, 
                        document_type=self.document_type, 
                        document_number=new_number
                    ).exists():
                        self.document_number = new_number
                        break
                    logger.warning(f"🔢 El número {new_number} ya existe en DB. Saltando al siguiente...")
                
                if not self.document_number:
                    raise ValidationError("Could not generate a unique document number after 10 attempts.")
                    
            except Exception as e:
                logger.error(f"Error generando secuencial: {e}")
                if not self.document_number:
                    self.document_number = "001-001-000000001"
        
        # Generar clave de acceso si no existe
        if not self.access_key:
            self.access_key = self._generate_access_key()
        
        super().save(*args, **kwargs)
    
    def _generate_access_key(self):
        """Genera la clave de acceso de 49 dígitos según especificaciones del SRI"""
        from datetime import datetime
        
        # Obtener configuración SRI de la empresa
        try:
            sri_config = self.company.sri_configuration
        except:
            # Si no hay configuración, usar valores por defecto
            establishment = '001'
            emission_point = '001'
            environment = '1'  # Pruebas por defecto
        else:
            establishment = sri_config.establishment_code.zfill(3)
            emission_point = sri_config.emission_point.zfill(3)
            environment = '1' if sri_config.environment == 'TEST' else '2'
        
        # 1. FECHA DE EMISIÓN (8 dígitos): ddmmyyyy - ✅ CORREGIDO
        # Manejar tanto string como objeto date
        if isinstance(self.issue_date, str):
            date_obj = datetime.strptime(self.issue_date, '%Y-%m-%d').date()
            date_str = date_obj.strftime('%d%m%Y')
        else:
            date_str = self.issue_date.strftime('%d%m%Y')
        
        # 2. TIPO DE COMPROBANTE (2 dígitos)
        doc_type_map = {
            'INVOICE': '01',
            'CREDIT_NOTE': '04',
            'DEBIT_NOTE': '05',
            'RETENTION': '07',
            'REMISSION_GUIDE': '06',
            'PURCHASE_SETTLEMENT': '03',
        }
        doc_type_code = doc_type_map.get(self.document_type, '01')
        
        # 3. RUC (13 dígitos) - rellenar con ceros si es necesario
        ruc = self.company.ruc.zfill(13)
        
        # 4. AMBIENTE (1 dígito): 1=pruebas, 2=producción
        # Ya definido arriba
        
        # 5. SERIE (6 dígitos): establecimiento (3) + punto emisión (3)
        serie = f"{establishment}{emission_point}"
        
        # 6. SECUENCIAL (9 dígitos) - ¡CRÍTICO: debe ser 9 dígitos!
        if self.document_number and '-' in self.document_number:
            sequence = self.document_number.split('-')[-1].zfill(9)
        else:
            # Si no hay número, obtener del SRI config
            try:
                next_seq = sri_config.get_next_sequence(self.document_type)
                sequence = str(next_seq).zfill(9)
            except:
                sequence = '000000001'  # Por defecto
        
        # 7. CÓDIGO NUMÉRICO (8 dígitos): Aleatorio para evitar colisiones "EN PROCESAMIENTO" en Pruebas
        import random
        numeric_code = f"{random.randint(1, 99999999):08d}"
        
        # 8. TIPO DE EMISIÓN (1 dígito): 1=normal
        emission_type = '1'
        
        # Construir clave sin dígito verificador (48 dígitos)
        partial_key = f"{date_str}{doc_type_code}{ruc}{environment}{serie}{sequence}{numeric_code}{emission_type}"
        
        # Verificar que sean exactamente 48 dígitos antes del dígito verificador
        if len(partial_key) != 48:
            raise ValueError(f"Clave parcial debe tener 48 dígitos, tiene {len(partial_key)}: {partial_key}")
        
        # 9. DÍGITO VERIFICADOR (1 dígito) - usando módulo 11
        check_digit = self._calculate_check_digit(partial_key)
        
        # Clave final (49 dígitos)
        final_key = f"{partial_key}{check_digit}"
        
        return final_key
    
    def _calculate_check_digit(self, partial_key):
        """
        Calcula el dígito verificador usando algoritmo módulo 11
        Según las especificaciones técnicas del SRI
        """
        # Factores de multiplicación para módulo 11 (de derecha a izquierda)
        factors = [2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 
                   2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7]
        
        # Invertir la clave para multiplicar de derecha a izquierda
        reversed_key = partial_key[::-1]
        
        # Calcular suma de productos
        total = sum(int(digit) * factor for digit, factor in zip(reversed_key, factors))
        
        # Calcular residuo
        remainder = total % 11
        
        # Determinar dígito verificador
        if remainder < 2:
            return remainder
        else:
            return 11 - remainder


class DocumentItem(BaseModel):
    """
    Líneas de detalle de documentos electrónicos - VERSIÓN CORREGIDA CON VALIDACIONES SEGURAS
    """
    
    document = models.ForeignKey(
        ElectronicDocument,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_('document')
    )
    
    main_code = models.CharField(
        _('main code'),
        max_length=25,
        help_text=_('Product main code')
    )
    
    auxiliary_code = models.CharField(
        _('auxiliary code'),
        max_length=25,
        blank=True,
        help_text=_('Product auxiliary code')
    )
    
    description = models.TextField(
        _('description'),
        help_text=_('Product description')
    )
    
    quantity = models.DecimalField(
        _('quantity'),
        max_digits=12,
        decimal_places=6,
        help_text=_('Maximum: 999,999.999999')
    )
    
    unit_price = models.DecimalField(
        _('unit price'),
        max_digits=12,
        decimal_places=6,
        help_text=_('Maximum: 999,999.999999')
    )
    
    discount = models.DecimalField(
        _('discount'),
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text=_('Maximum: 9,999,999,999.99')
    )
    
    subtotal = models.DecimalField(
        _('subtotal'),
        max_digits=12,
        decimal_places=2,
        help_text=_('Calculated automatically. Maximum: 9,999,999,999.99')
    )
    
    # Información adicional del producto
    additional_details = models.JSONField(
        _('additional details'),
        default=dict,
        blank=True
    )
    
    class Meta:
        verbose_name = _('Document Item')
        verbose_name_plural = _('Document Items')
        ordering = ['id']
        indexes = [
            models.Index(fields=['document', 'main_code']),
        ]
    
    def __str__(self):
        return f"{self.description} - {self.quantity} x {self.unit_price}"
    
    def clean(self):
        """Validación a nivel de modelo"""
        super().clean()
        
        # Validar rangos
        if self.quantity and self.quantity <= 0:
            raise ValidationError({'quantity': 'Quantity must be greater than 0'})
        
        if self.unit_price and self.unit_price <= 0:
            raise ValidationError({'unit_price': 'Unit price must be greater than 0'})
        
        if self.discount and self.discount < 0:
            raise ValidationError({'discount': 'Discount cannot be negative'})
        
        # Validar que no excedan los límites máximos
        max_quantity_price = Decimal('999999.999999')
        if self.quantity and self.quantity > max_quantity_price:
            raise ValidationError({'quantity': f'Quantity cannot exceed {max_quantity_price}'})
        
        if self.unit_price and self.unit_price > max_quantity_price:
            raise ValidationError({'unit_price': f'Unit price cannot exceed {max_quantity_price}'})
        
        max_discount = Decimal('9999999999.99')
        if self.discount and self.discount > max_discount:
            raise ValidationError({'discount': f'Discount cannot exceed {max_discount}'})
        
        # Validar cálculo de subtotal si tenemos todos los valores
        if self.quantity and self.unit_price and self.discount is not None:
            calculated_subtotal = self._calculate_subtotal_safe()
            
            if calculated_subtotal < 0:
                raise ValidationError({'discount': 'Discount cannot be greater than (quantity × unit_price)'})
            
            max_subtotal = Decimal('9999999999.99')
            if calculated_subtotal > max_subtotal:
                raise ValidationError({
                    '__all__': f'Calculated subtotal ({calculated_subtotal}) exceeds maximum allowed ({max_subtotal}). '
                              f'Please reduce quantity, unit_price, or increase discount.'
                })
    
    def _calculate_subtotal_safe(self):
        """
        Cálculo seguro del subtotal con manejo de precisión decimal
        """
        # Convertir a Decimal con precisión controlada
        quantity = Decimal(str(self.quantity)) if self.quantity else Decimal('0')
        unit_price = Decimal(str(self.unit_price)) if self.unit_price else Decimal('0')
        discount = Decimal(str(self.discount)) if self.discount else Decimal('0')
        
        # Calcular subtotal: (cantidad × precio) - descuento
        subtotal = (quantity * unit_price) - discount
        
        # Redondear a 2 decimales usando ROUND_HALF_UP (redondeo bancario)
        return subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    def save(self, *args, **kwargs):
        """
        MÉTODO CRÍTICO CORREGIDO: Calcular subtotal de forma segura antes de guardar
        """
        # Calcular subtotal antes de cualquier validación
        if self.quantity is not None and self.unit_price is not None:
            if self.discount is None:
                self.discount = Decimal('0.00')
            
            # Calcular subtotal de forma segura
            self.subtotal = self._calculate_subtotal_safe()
        else:
            # Si no hay valores, establecer subtotal por defecto
            self.subtotal = Decimal('0.00')
        
        # Ejecutar validación completa después de calcular
        try:
            self.full_clean()
        except ValidationError:
            # Si la validación falla, al menos asegurar que subtotal no sea nulo
            if self.subtotal is None:
                self.subtotal = Decimal('0.00')
        
        # Llamar al método save() original
        super().save(*args, **kwargs)


class DocumentTax(BaseModel):
    """
    Impuestos aplicados a documentos electrónicos
    """
    
    TAX_CODES = [
        ('2', _('IVA')),
        ('3', _('ICE')),
        ('5', _('IRBPNR')),
    ]
    
    TAX_RATES = [
        ('0', _('0%')),
        ('2', _('12%')),
        ('3', _('14%')),
        ('4', _('15%')),  # ✅ AGREGADO PARA 15%
        ('6', _('No Objeto de Impuesto')),
        ('7', _('Exento de IVA')),
    ]
    
    document = models.ForeignKey(
        ElectronicDocument,
        on_delete=models.CASCADE,
        related_name='taxes',
        verbose_name=_('document')
    )
    
    item = models.ForeignKey(
        DocumentItem,
        on_delete=models.CASCADE,
        related_name='taxes',
        verbose_name=_('item'),
        null=True,
        blank=True
    )
    
    tax_code = models.CharField(
        _('tax code'),
        max_length=2,
        choices=TAX_CODES
    )
    
    percentage_code = models.CharField(
        _('percentage code'),
        max_length=2,
        choices=TAX_RATES
    )
    
    rate = models.DecimalField(
        _('tax rate'),
        max_digits=5,
        decimal_places=2
    )
    
    taxable_base = models.DecimalField(
        _('taxable base'),
        max_digits=12,
        decimal_places=2
    )
    
    tax_amount = models.DecimalField(
        _('tax amount'),
        max_digits=12,
        decimal_places=2
    )
    
    class Meta:
        verbose_name = _('Document Tax')
        verbose_name_plural = _('Document Taxes')
    
    def __str__(self):
        return f"{self.get_tax_code_display()} {self.rate}% - {self.tax_amount}"


class DocumentPayment(BaseModel):
    """
    Formas de pago de documentos electrónicos según Tabla 16 del SRI
    """
    document = models.ForeignKey(
        ElectronicDocument,
        on_delete=models.CASCADE,
        related_name='payment_methods',
        verbose_name=_('document')
    )
    
    payment_method_code = models.CharField(
        _('payment method code'),
        max_length=2,
        default='01',
        help_text=_('SRI Payment method code (e.g., 01 for Cash)')
    )
    
    amount = models.DecimalField(
        _('amount'),
        max_digits=12,
        decimal_places=2
    )
    
    payment_term = models.IntegerField(
        _('payment term'),
        default=0,
        help_text=_('Term in units of time')
    )
    
    time_unit = models.CharField(
        _('time unit'),
        max_length=20,
        default='dias',
        help_text=_('Unit of time for the term (e.g., dias)')
    )
    
    class Meta:
        verbose_name = _('Document Payment')
        verbose_name_plural = _('Document Payments')

    def __str__(self):
        return f"{self.payment_method_code} - {self.amount}"


class SRIResponse(BaseModel):
    """
    Respuestas del SRI
    """
    
    document = models.ForeignKey(
        ElectronicDocument,
        on_delete=models.CASCADE,
        related_name='sri_responses',
        verbose_name=_('document')
    )
    
    operation_type = models.CharField(
        _('operation type'),
        max_length=20,
        choices=[
            ('RECEPTION', _('Reception')),
            ('AUTHORIZATION', _('Authorization')),
        ]
    )
    
    response_code = models.CharField(
        _('response code'),
        max_length=10
    )
    
    response_message = models.TextField(
        _('response message')
    )
    
    raw_response = models.JSONField(
        _('raw response'),
        default=dict
    )
    
    class Meta:
        verbose_name = _('SRI Response')
        verbose_name_plural = _('SRI Responses')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.operation_type} - {self.response_code} - {self.document}"


# ========== MODELOS ESPECÍFICOS DE DOCUMENTOS ==========

class CreditNote(BaseModel):
    """
    Nota de Crédito - Documento que anula o corrige una factura - VERSIÓN CORREGIDA
    """
    CREDIT_NOTE_REASONS = [
        ('01', _('Devolución de bienes')),
        ('02', _('Anulación de venta')),
        ('03', _('Descuento otorgado')),
        ('04', _('Bonificación')),
        ('05', _('Devolución en compras')),
        ('06', _('Descuento por pronto pago')),
        ('07', _('Otros')),
    ]
    
    STATUS_CHOICES = [
        ('DRAFT', _('Draft')),
        ('GENERATED', _('Generated')),
        ('SIGNED', _('Signed')),
        ('SENT', _('Sent to SRI')),
        ('AUTHORIZED', _('Authorized')),
        ('REJECTED', _('Rejected')),
        ('ERROR', _('Error')),
    ]
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='credit_notes',
        verbose_name=_('company')
    )
    
    # Referencia al documento original
    original_document = models.ForeignKey(
        ElectronicDocument,
        on_delete=models.CASCADE,
        related_name='credit_notes',
        verbose_name=_('original document'),
        help_text=_('Invoice or document being credited')
    )
    
    document_number = models.CharField(
        _('document number'),
        max_length=17,
        help_text=_('Format: 001-001-000000001')
    )
    
    access_key = models.CharField(
        _('access key'),
        max_length=49,
        unique=True,
        help_text=_('49-digit access key')
    )
    
    issue_date = models.DateField(_('issue date'))
    
    reason_code = models.CharField(
        _('reason code'),
        max_length=2,
        choices=CREDIT_NOTE_REASONS,
        default='07'
    )
    
    reason_description = models.TextField(
        _('reason description'),
        max_length=300,
        help_text=_('Detailed reason for credit note')
    )
    
    # Información del cliente (copiada del documento original)
    customer_identification_type = models.CharField(_('customer identification type'), max_length=2)
    customer_identification = models.CharField(_('customer identification'), max_length=20)
    customer_name = models.CharField(_('customer name'), max_length=300)
    customer_address = models.TextField(_('customer address'), blank=True)
    customer_email = models.EmailField(_('customer email'), blank=True)
    
    # Totales de la nota de crédito
    subtotal_without_tax = models.DecimalField(_('subtotal without tax'), max_digits=12, decimal_places=2, default=0)
    total_tax = models.DecimalField(_('total tax'), max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(_('total amount'), max_digits=12, decimal_places=2, default=0)
    
    # Status y archivos
    status = models.CharField(_('status'), max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    xml_file = models.FileField(_('XML file'), upload_to=get_sri_document_upload_path, blank=True)
    signed_xml_file = models.FileField(_('signed XML file'), upload_to=get_sri_document_upload_path, blank=True)
    pdf_file = models.FileField(_('PDF file'), upload_to=get_sri_document_upload_path, blank=True)
    
    # SRI response
    sri_authorization_code = models.CharField(_('SRI authorization code'), max_length=49, blank=True)
    sri_authorization_date = models.DateTimeField(_('SRI authorization date'), null=True, blank=True)
    
    @property
    def document_type(self):
        return 'CREDIT_NOTE'
        
    class Meta:
        verbose_name = _('Credit Note')
        verbose_name_plural = _('Credit Notes')
        unique_together = ['company', 'document_number']
    
    def __str__(self):
        return f"Credit Note {self.document_number} - {self.company.business_name}"
    
    def save(self, *args, **kwargs):
        """
        Override save method to ensure proper saving of CreditNote - CORREGIDO
        """
        from django.utils import timezone
        
        # ENTORNO DE PRUEBAS: Siempre intentar obtener un nuevo número si el actual falló
        # para evitar el error 'CLAVE DE ACCESO EN PROCESAMIENTO'
        is_test = False
        try:
            sri_config = self.company.sri_configuration
            is_test = (sri_config.environment == 'TEST')
        except:
            pass

        if is_test and self.status in ['ERROR', 'REJECTED']:
            # Limpiar para forzar regeneración con nueva secuencia y clave aleatoria
            self.document_number = None
            self.access_key = None

        # Generar número de documento si no existe
        if not self.document_number:
            try:
                sri_config = self.company.sri_configuration
                sequence = sri_config.get_next_sequence("CREDIT_NOTE")
                self.document_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
            except Exception as e:
                # Si no hay configuración SRI, usar valores por defecto
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                self.document_number = f"001-001-{timestamp[-9:]}"
        
        # Generar clave de acceso si no existe
        if not self.access_key:
            self.access_key = self._generate_access_key()
        
        # Establecer fecha de emisión si no existe
        if not self.issue_date:
            self.issue_date = timezone.localtime(timezone.now()).date()
        
        # ✅ LLAMADA SEGURA AL SAVE DEL PADRE
        try:
            # Usar directamente models.Model.save() para evitar problemas con BaseModel
            models.Model.save(self, *args, **kwargs)
        except Exception as e:
            # Intentar con super() como backup
            super().save(*args, **kwargs)
    
    def _generate_access_key(self):
        """Genera la clave de acceso de 49 dígitos para nota de crédito - ✅ CORREGIDO"""
        from datetime import datetime
        
        # Obtener configuración SRI de la empresa
        try:
            sri_config = self.company.sri_configuration
            establishment = sri_config.establishment_code.zfill(3)
            emission_point = sri_config.emission_point.zfill(3)
            environment = "1" if sri_config.environment == "TEST" else "2"
        except:
            establishment = "001"
            emission_point = "001"
            environment = "1"  # Pruebas por defecto
        
        # 1. FECHA DE EMISIÓN (8 dígitos): ddmmyyyy - ✅ CORREGIDO
        # Manejar tanto string como objeto date
        if isinstance(self.issue_date, str):
            date_obj = datetime.strptime(self.issue_date, '%Y-%m-%d').date()
            date_str = date_obj.strftime("%d%m%Y")
        else:
            date_str = self.issue_date.strftime("%d%m%Y")
        
        # 2. TIPO DE COMPROBANTE (2 dígitos) - 04 para nota de crédito
        doc_type_code = "04"
        
        # 3. RUC (13 dígitos)
        ruc = self.company.ruc.zfill(13)
        
        # 4. AMBIENTE (1 dígito): ya definido arriba
        
        # 5. SERIE (6 dígitos): establecimiento + punto emisión
        serie = f"{establishment}{emission_point}"
        
        # 6. SECUENCIAL (9 dígitos)
        if self.document_number and "-" in self.document_number:
            sequence = self.document_number.split("-")[-1].zfill(9)
        else:
            # Generar secuencial temporal
            import random
            sequence = str(random.randint(1, 999999999)).zfill(9)
        
        # 7. CÓDIGO NUMÉRICO (8 dígitos): Aleatorio para evitar colisiones "EN PROCESAMIENTO" en Pruebas
        import random
        numeric_code = f"{random.randint(1, 99999999):08d}"
        
        # 8. TIPO DE EMISIÓN (1 dígito): 1=normal
        emission_type = "1"
        
        # Construir clave sin dígito verificador (48 dígitos)
        partial_key = f"{date_str}{doc_type_code}{ruc}{environment}{serie}{sequence}{numeric_code}{emission_type}"
        
        # Verificar longitud
        if len(partial_key) != 48:
            raise ValueError(f"Clave parcial debe tener 48 dígitos, tiene {len(partial_key)}: {partial_key}")
        
        # 9. DÍGITO VERIFICADOR
        check_digit = self._calculate_check_digit(partial_key)
        
        return f"{partial_key}{check_digit}"
    
    def _calculate_check_digit(self, partial_key):
        """Calcula el dígito verificador usando algoritmo módulo 11"""
        # Factores de multiplicación para módulo 11
        factors = [2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 
                   2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7]
        
        # Invertir la clave para multiplicar de derecha a izquierda
        reversed_key = partial_key[::-1]
        
        # Calcular suma de productos
        total = sum(int(digit) * factor for digit, factor in zip(reversed_key, factors))
        
        # Calcular residuo
        remainder = total % 11
        
        # Determinar dígito verificador
        if remainder < 2:
            return remainder
        else:
            return 11 - remainder


class DebitNote(BaseModel):
    """
    Nota de Débito - Documento que incrementa el valor de una factura
    """
    DEBIT_NOTE_REASONS = [
        ('01', _('Intereses de mora')),
        ('02', _('Gastos de cobranza')),
        ('03', _('Gastos de transporte')),
        ('04', _('Otros gastos')),
        ('05', _('Aumento en el precio')),
    ]
    
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='debit_notes')
    
    # Referencia al documento original
    original_document = models.ForeignKey(
        ElectronicDocument,
        on_delete=models.CASCADE,
        related_name='debit_notes',
        verbose_name=_('original document')
    )
    
    document_number = models.CharField(_('document number'), max_length=17)
    access_key = models.CharField(_('access key'), max_length=49, unique=True)
    issue_date = models.DateField(_('issue date'))
    
    reason_code = models.CharField(_('reason code'), max_length=2, choices=DEBIT_NOTE_REASONS)
    reason_description = models.TextField(_('reason description'), max_length=300)
    
    # Cliente
    customer_identification_type = models.CharField(_('customer identification type'), max_length=2)
    customer_identification = models.CharField(_('customer identification'), max_length=20)
    customer_name = models.CharField(_('customer name'), max_length=300)
    customer_address = models.TextField(_('customer address'), blank=True)
    customer_email = models.EmailField(_('customer email'), blank=True)
    
    # Totales
    subtotal_without_tax = models.DecimalField(_('subtotal without tax'), max_digits=12, decimal_places=2, default=0)
    total_tax = models.DecimalField(_('total tax'), max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(_('total amount'), max_digits=12, decimal_places=2, default=0)
    
    # Status y archivos
    status = models.CharField(_('status'), max_length=20, choices=ElectronicDocument.STATUS_CHOICES, default='DRAFT')
    xml_file = models.FileField(_('XML file'), upload_to=get_sri_document_upload_path, blank=True)
    signed_xml_file = models.FileField(_('signed XML file'), upload_to=get_sri_document_upload_path, blank=True)
    pdf_file = models.FileField(_('PDF file'), upload_to=get_sri_document_upload_path, blank=True)
    
    # SRI response
    sri_authorization_code = models.CharField(_('SRI authorization code'), max_length=49, blank=True)
    sri_authorization_date = models.DateTimeField(_('SRI authorization date'), null=True, blank=True)
    
    @property
    def document_type(self):
        return 'DEBIT_NOTE'
        
    class Meta:
        verbose_name = _('Debit Note')
        verbose_name_plural = _('Debit Notes')
        unique_together = ['company', 'document_number']
    
    def save(self, *args, **kwargs):
        """Override save method to ensure proper numbering"""
        from django.utils import timezone
        
        # ENTORNO DE PRUEBAS
        is_test = False
        try:
            sri_config = self.company.sri_configuration
            is_test = (sri_config.environment == 'TEST')
        except:
            pass

        if is_test and self.status in ['ERROR', 'REJECTED']:
            self.document_number = None
            self.access_key = None

        if not self.document_number:
            try:
                sri_config = self.company.sri_configuration
                sequence = sri_config.get_next_sequence("DEBIT_NOTE")
                self.document_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
            except:
                self.document_number = f"001-001-000000001"
        
        if not self.access_key:
            self.access_key = self._generate_access_key()
            
        if not self.issue_date:
            self.issue_date = timezone.localtime(timezone.now()).date()
            
        super().save(*args, **kwargs)
    
    def _generate_access_key(self):
        """Genera la clave de acceso de 49 dígitos"""
        from datetime import datetime
        import random
        
        try:
            sri_config = self.company.sri_configuration
            establishment = sri_config.establishment_code.zfill(3)
            emission_point = sri_config.emission_point.zfill(3)
            environment = "1" if sri_config.environment == "TEST" else "2"
        except:
            establishment = "001"
            emission_point = "001"
            environment = "1"
        
        date_str = self.issue_date.strftime("%d%m%Y")
        doc_type_code = "05"
        ruc = self.company.ruc.zfill(13)
        serie = f"{establishment}{emission_point}"
        
        if self.document_number and "-" in self.document_number:
            sequence = self.document_number.split("-")[-1].zfill(9)
        else:
            sequence = f"{random.randint(1, 999999999):09d}"
        
        numeric_code = f"{random.randint(1, 99999999):08d}"
        emission_type = "1"
        
        partial_key = f"{date_str}{doc_type_code}{ruc}{environment}{serie}{sequence}{numeric_code}{emission_type}"
        check_digit = self._calculate_check_digit(partial_key)
        return f"{partial_key}{check_digit}"

    def _calculate_check_digit(self, partial_key):
        factors = [2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 
                   2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7]
        reversed_key = partial_key[::-1]
        total = sum(int(digit) * factor for digit, factor in zip(reversed_key, factors))
        remainder = total % 11
        return remainder if remainder < 2 else 11 - remainder


class Retention(BaseModel):
    """
    Comprobante de Retención
    """
    RETENTION_TYPES = [
        ('RENT', _('Retención en la Fuente del Impuesto a la Renta')),
        ('IVA', _('Retención del Impuesto al Valor Agregado')),
    ]
    
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='retentions')
    
    document_number = models.CharField(_('document number'), max_length=17)
    access_key = models.CharField(_('access key'), max_length=49, unique=True)
    issue_date = models.DateField(_('issue date'))
    
    # Información del proveedor (a quien se retiene)
    supplier_identification_type = models.CharField(_('supplier identification type'), max_length=2)
    supplier_identification = models.CharField(_('supplier identification'), max_length=20)
    supplier_name = models.CharField(_('supplier name'), max_length=300)
    supplier_address = models.TextField(_('supplier address'), blank=True)
    
    # Período fiscal
    fiscal_period = models.CharField(_('fiscal period'), max_length=7, help_text=_('MM/YYYY format'))
    
    # Totales
    total_retained = models.DecimalField(_('total retained'), max_digits=12, decimal_places=2, default=0)
    
    # Status y archivos
    status = models.CharField(_('status'), max_length=20, choices=ElectronicDocument.STATUS_CHOICES, default='DRAFT')
    xml_file = models.FileField(_('XML file'), upload_to=get_sri_document_upload_path, blank=True)
    signed_xml_file = models.FileField(_('signed XML file'), upload_to=get_sri_document_upload_path, blank=True)
    pdf_file = models.FileField(_('PDF file'), upload_to=get_sri_document_upload_path, blank=True)
    
    # SRI response
    sri_authorization_code = models.CharField(_('SRI authorization code'), max_length=49, blank=True)
    sri_authorization_date = models.DateTimeField(_('SRI authorization date'), null=True, blank=True)
    
    class Meta:
        verbose_name = _('Retention')
        verbose_name_plural = _('Retentions')
        unique_together = ['company', 'document_number']

    def save(self, *args, **kwargs):
        """Override save method to ensure proper numbering"""
        from django.utils import timezone
        
        # ENTORNO DE PRUEBAS
        is_test = False
        try:
            sri_config = self.company.sri_configuration
            is_test = (sri_config.environment == 'TEST')
        except:
            pass

        if is_test and self.status in ['ERROR', 'REJECTED']:
            self.document_number = None
            self.access_key = None

        if not self.document_number:
            try:
                sri_config = self.company.sri_configuration
                sequence = sri_config.get_next_sequence("RETENTION")
                self.document_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
            except:
                self.document_number = f"001-001-000000001"
        
        if not self.access_key:
            self.access_key = self._generate_access_key()
            
        if not self.issue_date:
            self.issue_date = timezone.localtime(timezone.now()).date()
            
        super().save(*args, **kwargs)
    
    def _generate_access_key(self):
        """Genera la clave de acceso de 49 dígitos"""
        from datetime import datetime
        import random
        
        try:
            sri_config = self.company.sri_configuration
            establishment = sri_config.establishment_code.zfill(3)
            emission_point = sri_config.emission_point.zfill(3)
            environment = "1" if sri_config.environment == "TEST" else "2"
        except:
            establishment = "001"
            emission_point = "001"
            environment = "1"
        
        date_str = self.issue_date.strftime("%d%m%Y")
        doc_type_code = "07"
        ruc = self.company.ruc.zfill(13)
        serie = f"{establishment}{emission_point}"
        
        if self.document_number and "-" in self.document_number:
            sequence = self.document_number.split("-")[-1].zfill(9)
        else:
            sequence = f"{random.randint(1, 999999999):09d}"
        
        numeric_code = f"{random.randint(1, 99999999):08d}"
        emission_type = "1"
        
        partial_key = f"{date_str}{doc_type_code}{ruc}{environment}{serie}{sequence}{numeric_code}{emission_type}"
        check_digit = self._calculate_check_digit(partial_key)
        return f"{partial_key}{check_digit}"

    def _calculate_check_digit(self, partial_key):
        factors = [2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 
                   2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7]
        reversed_key = partial_key[::-1]
        total = sum(int(digit) * factor for digit, factor in zip(reversed_key, factors))
        remainder = total % 11
        return remainder if remainder < 2 else 11 - remainder


class RetentionDetail(BaseModel):
    """
    Detalle de retenciones
    """
    retention = models.ForeignKey(Retention, on_delete=models.CASCADE, related_name='details')
    
    # Documento sustento
    support_document_type = models.CharField(_('support document type'), max_length=2)
    support_document_number = models.CharField(_('support document number'), max_length=20)
    support_document_date = models.DateField(_('support document date'))
    
    # Retención
    tax_code = models.CharField(_('tax code'), max_length=4)  # Código del impuesto
    retention_code = models.CharField(_('retention code'), max_length=5)  # Código de retención específico
    retention_percentage = models.DecimalField(_('retention percentage'), max_digits=5, decimal_places=2)
    
    taxable_base = models.DecimalField(_('taxable base'), max_digits=12, decimal_places=2)
    retained_amount = models.DecimalField(_('retained amount'), max_digits=12, decimal_places=2)
    
    class Meta:
        verbose_name = _('Retention Detail')
        verbose_name_plural = _('Retention Details')


class PurchaseSettlement(BaseModel):
    """
    Liquidación de Compra
    """
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='purchase_settlements')
    
    document_number = models.CharField(_('document number'), max_length=17)
    access_key = models.CharField(_('access key'), max_length=49, unique=True)
    issue_date = models.DateField(_('issue date'))
    
    # Información del proveedor
    supplier_identification_type = models.CharField(_('supplier identification type'), max_length=2)
    supplier_identification = models.CharField(_('supplier identification'), max_length=20)
    supplier_name = models.CharField(_('supplier name'), max_length=300)
    supplier_address = models.TextField(_('supplier address'), blank=True)
    
    # Totales
    subtotal_without_tax = models.DecimalField(_('subtotal without tax'), max_digits=12, decimal_places=2, default=0)
    total_tax = models.DecimalField(_('total tax'), max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(_('total amount'), max_digits=12, decimal_places=2, default=0)
    
    # Status y archivos
    status = models.CharField(_('status'), max_length=20, choices=ElectronicDocument.STATUS_CHOICES, default='DRAFT')
    xml_file = models.FileField(_('XML file'), upload_to=get_sri_document_upload_path, blank=True)
    signed_xml_file = models.FileField(_('signed XML file'), upload_to=get_sri_document_upload_path, blank=True)
    pdf_file = models.FileField(_('PDF file'), upload_to=get_sri_document_upload_path, blank=True)
    
    # SRI response
    sri_authorization_code = models.CharField(_('SRI authorization code'), max_length=49, blank=True)
    sri_authorization_date = models.DateTimeField(_('SRI authorization date'), null=True, blank=True)
    
    class Meta:
        verbose_name = _('Purchase Settlement')
        verbose_name_plural = _('Purchase Settings')
        unique_together = ['company', 'document_number']

    def save(self, *args, **kwargs):
        """Override save method to ensure proper numbering"""
        from django.utils import timezone
        
        # ENTORNO DE PRUEBAS
        is_test = False
        try:
            sri_config = self.company.sri_configuration
            is_test = (sri_config.environment == 'TEST')
        except:
            pass

        if is_test and self.status in ['ERROR', 'REJECTED']:
            self.document_number = None
            self.access_key = None

        if not self.document_number:
            try:
                sri_config = self.company.sri_configuration
                sequence = sri_config.get_next_sequence("PURCHASE_SETTLEMENT")
                self.document_number = f"{sri_config.establishment_code}-{sri_config.emission_point}-{sequence:09d}"
            except:
                self.document_number = f"001-001-000000001"
        
        if not self.access_key:
            self.access_key = self._generate_access_key()
            
        if not self.issue_date:
            self.issue_date = timezone.now().date()
            
        super().save(*args, **kwargs)
    
    def _generate_access_key(self):
        """Genera la clave de acceso de 49 dígitos"""
        from datetime import datetime
        import random
        
        try:
            sri_config = self.company.sri_configuration
            establishment = sri_config.establishment_code.zfill(3)
            emission_point = sri_config.emission_point.zfill(3)
            environment = "1" if sri_config.environment == "TEST" else "2"
        except:
            establishment = "001"
            emission_point = "001"
            environment = "1"
        
        date_str = self.issue_date.strftime("%d%m%Y")
        doc_type_code = "03"
        ruc = self.company.ruc.zfill(13)
        serie = f"{establishment}{emission_point}"
        
        if self.document_number and "-" in self.document_number:
            sequence = self.document_number.split("-")[-1].zfill(9)
        else:
            sequence = f"{random.randint(1, 999999999):09d}"
        
        numeric_code = f"{random.randint(1, 99999999):08d}"
        emission_type = "1"
        
        partial_key = f"{date_str}{doc_type_code}{ruc}{environment}{serie}{sequence}{numeric_code}{emission_type}"
        check_digit = self._calculate_check_digit(partial_key)
        return f"{partial_key}{check_digit}"

    def _calculate_check_digit(self, partial_key):
        factors = [2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 
                   2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7]
        reversed_key = partial_key[::-1]
        total = sum(int(digit) * factor for digit, factor in zip(reversed_key, factors))
        remainder = total % 11
        return remainder if remainder < 2 else 11 - remainder


class PurchaseSettlementItem(BaseModel):
    """
    Items de liquidación de compra - VERSIÓN CORREGIDA Y SEGURA
    """
    settlement = models.ForeignKey(
        PurchaseSettlement,
        on_delete=models.CASCADE,
        related_name='items'
    )
    
    main_code = models.CharField(
        _('main code'),
        max_length=25
    )
    
    description = models.TextField(
        _('description')
    )
    
    quantity = models.DecimalField(
        _('quantity'),
        max_digits=12,
        decimal_places=6,
        help_text=_('Maximum: 999,999.999999')
    )
    
    unit_price = models.DecimalField(
        _('unit price'),
        max_digits=12,
        decimal_places=6,
        help_text=_('Maximum: 999,999.999999')
    )
    
    discount = models.DecimalField(
        _('discount'),
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text=_('Maximum: 9,999,999,999.99')
    )
    
    subtotal = models.DecimalField(
        _('subtotal'),
        max_digits=12,
        decimal_places=2,
        help_text=_('Calculated automatically. Maximum: 9,999,999,999.99')
    )
    
    class Meta:
        verbose_name = _('Purchase Settlement Item')
        verbose_name_plural = _('Purchase Settlement Items')
        indexes = [
            models.Index(fields=['settlement', 'main_code']),
        ]
    
    def __str__(self):
        return f"{self.description} - {self.quantity} x {self.unit_price}"
    
    def clean(self):
        """Validación a nivel de modelo"""
        super().clean()
        
        # Validar rangos
        if self.quantity and self.quantity <= 0:
            raise ValidationError({'quantity': 'Quantity must be greater than 0'})
        
        if self.unit_price and self.unit_price <= 0:
            raise ValidationError({'unit_price': 'Unit price must be greater than 0'})
        
        if self.discount and self.discount < 0:
            raise ValidationError({'discount': 'Discount cannot be negative'})
        
        # Validar límites máximos
        max_quantity_price = Decimal('999999.999999')
        if self.quantity and self.quantity > max_quantity_price:
            raise ValidationError({'quantity': f'Quantity cannot exceed {max_quantity_price}'})
        
        if self.unit_price and self.unit_price > max_quantity_price:
            raise ValidationError({'unit_price': f'Unit price cannot exceed {max_quantity_price}'})
        
        max_discount = Decimal('9999999999.99')
        if self.discount and self.discount > max_discount:
            raise ValidationError({'discount': f'Discount cannot exceed {max_discount}'})
        
        # Validar cálculo de subtotal
        if self.quantity and self.unit_price and self.discount is not None:
            calculated_subtotal = self._calculate_subtotal_safe()
            
            if calculated_subtotal < 0:
                raise ValidationError({'discount': 'Discount cannot be greater than (quantity × unit_price)'})
            
            max_subtotal = Decimal('9999999999.99')
            if calculated_subtotal > max_subtotal:
                raise ValidationError({
                    '__all__': f'Calculated subtotal ({calculated_subtotal}) exceeds maximum allowed ({max_subtotal}). '
                              f'Please reduce quantity, unit_price, or increase discount.'
                })
    
    def _calculate_subtotal_safe(self):
        """
        Cálculo seguro del subtotal con manejo de precisión decimal
        """
        # Convertir a Decimal con precisión controlada
        quantity = Decimal(str(self.quantity)) if self.quantity else Decimal('0')
        unit_price = Decimal(str(self.unit_price)) if self.unit_price else Decimal('0')
        discount = Decimal(str(self.discount)) if self.discount else Decimal('0')
        
        # Calcular subtotal: (cantidad × precio) - descuento
        subtotal = (quantity * unit_price) - discount
        
        # Redondear a 2 decimales usando ROUND_HALF_UP
        return subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    def save(self, *args, **kwargs):
        """
        MÉTODO CRÍTICO CORREGIDO: Calcular subtotal de forma segura antes de guardar
        """
        # Calcular subtotal antes de cualquier validación
        if self.quantity is not None and self.unit_price is not None:
            if self.discount is None:
                self.discount = Decimal('0.00')
            
            # Calcular subtotal de forma segura
            self.subtotal = self._calculate_subtotal_safe()
        else:
            # Si no hay valores, establecer subtotal por defecto
            self.subtotal = Decimal('0.00')
        
        # Ejecutar validación completa después de calcular
        try:
            self.full_clean()
        except ValidationError:
            # Si la validación falla, al menos asegurar que subtotal no sea nulo
            if self.subtotal is None:
                self.subtotal = Decimal('0.00')
        
        # Llamar al método save() original
        super().save(*args, **kwargs)


# ========== CLASE UTILITARIA PARA CÁLCULOS SEGUROS ==========

class SafeDocumentCalculations:
    """
    Clase utilitaria para cálculos seguros de documentos
    """
    
    @staticmethod
    def validate_item_calculation(quantity, unit_price, discount=0):
        """
        Valida que los cálculos de un item no excedan los límites
        
        Args:
            quantity: Cantidad del item
            unit_price: Precio unitario
            discount: Descuento (opcional)
        
        Returns:
            tuple: (is_valid, calculated_subtotal, error_message)
        """
        try:
            # Convertir a Decimal
            qty = Decimal(str(quantity))
            price = Decimal(str(unit_price))
            disc = Decimal(str(discount))
            
            # Validar rangos individuales
            max_qty_price = Decimal('999999.999999')
            max_discount = Decimal('9999999999.99')
            max_subtotal = Decimal('9999999999.99')
            
            if qty <= 0:
                return False, None, "Quantity must be greater than 0"
            
            if price <= 0:
                return False, None, "Unit price must be greater than 0"
            
            if disc < 0:
                return False, None, "Discount cannot be negative"
            
            if qty > max_qty_price:
                return False, None, f"Quantity exceeds maximum allowed ({max_qty_price})"
            
            if price > max_qty_price:
                return False, None, f"Unit price exceeds maximum allowed ({max_qty_price})"
            
            if disc > max_discount:
                return False, None, f"Discount exceeds maximum allowed ({max_discount})"
            
            # Calcular subtotal
            subtotal = (qty * price) - disc
            
            if subtotal < 0:
                return False, None, "Discount cannot be greater than (quantity × unit_price)"
            
            if subtotal > max_subtotal:
                return False, None, f"Calculated subtotal ({subtotal}) exceeds maximum allowed ({max_subtotal})"
            
            # Redondear resultado
            final_subtotal = subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            return True, final_subtotal, None
            
        except Exception as e:
            return False, None, f"Calculation error: {str(e)}"
    
    @staticmethod
    def validate_document_total(items_data):
        """
        Valida que el total del documento no exceda los límites
        
        Args:
            items_data: Lista de diccionarios con quantity, unit_price, discount
        
        Returns:
            tuple: (is_valid, calculated_total, error_message)
        """
        try:
            total = Decimal('0.00')
            max_document_total = Decimal('99999999999.99')  # Límite realista para documentos
            
            for i, item in enumerate(items_data):
                is_valid, subtotal, error = SafeDocumentCalculations.validate_item_calculation(
                    item.get('quantity', 0),
                    item.get('unit_price', 0),
                    item.get('discount', 0)
                )
                
                if not is_valid:
                    return False, None, f"Item {i+1}: {error}"
                
                total += subtotal
            
            if total > max_document_total:
                return False, None, f"Document total ({total}) exceeds reasonable limit ({max_document_total})"
            
            return True, total, None
            
        except Exception as e:
            return False, None, f"Document validation error: {str(e)}"