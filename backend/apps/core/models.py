# -*- coding: utf-8 -*-
"""
Core models for RutaFact_SRI
Modelos base y compartidos del sistema
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model


User = get_user_model()


class BaseModel(models.Model):
    """
    Modelo base abstracto con campos comunes
    """
    
    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        help_text=_('Date and time when the record was created.')
    )
    
    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True,
        help_text=_('Date and time when the record was last updated.')
    )
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_created',
        verbose_name=_('created by'),
        help_text=_('User who created this record.')
    )
    
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_updated',
        verbose_name=_('updated by'),
        help_text=_('User who last updated this record.')
    )
    
    is_active = models.BooleanField(
        _('is active'),
        default=True,
        help_text=_('Designates whether this record should be treated as active.')
    )
    
    class Meta:
        abstract = True
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        """Guarda el modelo con validaciones adicionales"""
        self.full_clean()
        super().save(*args, **kwargs)


class AuditLog(BaseModel):
    """
    Registro de auditoría para cambios importantes en el sistema
    """
    
    # OPCIONES DE ACCIONES COMPLETAS PARA SRI Y SISTEMA
    ACTION_CHOICES = [
        # Acciones básicas de CRUD
        ('CREATE', _('Create')),
        ('UPDATE', _('Update')),
        ('DELETE', _('Delete')),
        ('VIEW', _('View')),
        
        # Acciones de autenticación
        ('LOGIN', _('Login')),
        ('LOGOUT', _('Logout')),
        ('LOGIN_FAILED', _('Login Failed')),
        
        # Acciones de archivos
        ('EXPORT', _('Export')),
        ('IMPORT', _('Import')),
        ('UPLOAD', _('Upload')),
        ('DOWNLOAD', _('Download')),
        
        # Acciones de comunicación
        ('SEND', _('Send')),
        ('RECEIVE', _('Receive')),
        
        # Acciones de autorización
        ('AUTHORIZE', _('Authorize')),
        ('REJECT', _('Reject')),
        ('APPROVE', _('Approve')),
        ('DENY', _('Deny')),
        
        # Acciones específicas del SRI
        ('SRI_RESPONSE', _('SRI Response')),
        ('SRI_SENT', _('SRI Sent')),
        ('SRI_RECEIVED', _('SRI Received')),
        ('SRI_AUTHORIZED', _('SRI Authorized')),
        ('SRI_REJECTED', _('SRI Rejected')),
        ('SRI_ERROR', _('SRI Error')),
        ('SRI_TIMEOUT', _('SRI Timeout')),
        ('SRI_VALIDATION', _('SRI Validation')),
        
        # Acciones de documentos electrónicos
        ('DOCUMENT_GENERATED', _('Document Generated')),
        ('DOCUMENT_SIGNED', _('Document Signed')),
        ('DOCUMENT_VALIDATED', _('Document Validated')),
        ('DOCUMENT_CANCELLED', _('Document Cancelled')),
        
        # Acciones de XML
        ('XML_GENERATED', _('XML Generated')),
        ('XML_SIGNED', _('XML Signed')),
        ('XML_VALIDATED', _('XML Validated')),
        ('XML_ERROR', _('XML Error')),
        
        # Acciones de certificados
        ('CERTIFICATE_LOADED', _('Certificate Loaded')),
        ('CERTIFICATE_EXPIRED', _('Certificate Expired')),
        ('CERTIFICATE_ERROR', _('Certificate Error')),
        
        # Acciones de sistema
        ('SYSTEM_START', _('System Start')),
        ('SYSTEM_STOP', _('System Stop')),
        ('BACKUP_CREATED', _('Backup Created')),
        ('BACKUP_RESTORED', _('Backup Restored')),
        
        # Acciones de configuración
        ('CONFIG_CHANGED', _('Configuration Changed')),
        ('SETTINGS_UPDATED', _('Settings Updated')),
        
        # Acciones de errores
        ('ERROR_OCCURRED', _('Error Occurred')),
        ('WARNING_ISSUED', _('Warning Issued')),
        ('EXCEPTION_CAUGHT', _('Exception Caught')),
    ]
    
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name=_('user'),
        help_text=_('User who performed the action.')
    )
    
    action = models.CharField(
        _('action'),
        max_length=50,
        help_text=_('Type of action performed.')
    )
    
    model_name = models.CharField(
        _('model name'),
        max_length=100,
        help_text=_('Name of the model affected.')
    )
    
    object_id = models.CharField(
        _('object ID'),
        max_length=100,
        blank=True,
        help_text=_('ID of the object affected.')
    )
    
    object_representation = models.CharField(
        _('object representation'),
        max_length=255,
        blank=True,
        help_text=_('String representation of the object.')
    )
    
    changes = models.JSONField(
        _('changes'),
        default=dict,
        blank=True,
        help_text=_('JSON representation of changes made.')
    )
    
    ip_address = models.GenericIPAddressField(
        _('IP address'),
        null=True,
        blank=True,
        help_text=_('IP address from which the action was performed.')
    )
    
    user_agent = models.TextField(
        _('user agent'),
        blank=True,
        help_text=_('Browser/client information.')
    )
    
    additional_data = models.JSONField(
        _('additional data'),
        default=dict,
        blank=True,
        help_text=_('Additional context data.')
    )
    
    class Meta:
        verbose_name = _('Audit Log')
        verbose_name_plural = _('Audit Logs')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['model_name', 'object_id']),
            models.Index(fields=['action', 'model_name']),
        ]
    
    def __str__(self):
        user_display = self.user.get_display_name() if self.user else _('System')
        return f"{user_display} - {self.get_action_display()} - {self.model_name}"


class SystemConfiguration(BaseModel):
    """
    Configuraciones del sistema
    """
    
    CONFIG_TYPES = [
        ('SYSTEM', _('System')),
        ('SRI', _('SRI')),
        ('EMAIL', _('Email')),
        ('NOTIFICATION', _('Notification')),
        ('SECURITY', _('Security')),
        ('BACKUP', _('Backup')),
    ]
    
    key = models.CharField(
        _('configuration key'),
        max_length=100,
        unique=True,
        help_text=_('Unique identifier for the configuration.')
    )
    
    value = models.TextField(
        _('configuration value'),
        help_text=_('Configuration value (can be JSON).')
    )
    
    config_type = models.CharField(
        _('configuration type'),
        max_length=20,
        choices=CONFIG_TYPES,
        default='SYSTEM',
        help_text=_('Type of configuration.')
    )
    
    description = models.TextField(
        _('description'),
        blank=True,
        help_text=_('Description of what this configuration does.')
    )
    
    is_sensitive = models.BooleanField(
        _('is sensitive'),
        default=False,
        help_text=_('Whether this configuration contains sensitive data.')
    )
    
    class Meta:
        verbose_name = _('System Configuration')
        verbose_name_plural = _('System Configurations')
        ordering = ['config_type', 'key']
    
    def __str__(self):
        return f"{self.get_config_type_display()}: {self.key}"


class FileUpload(BaseModel):
    """
    Registro de archivos subidos al sistema
    """
    
    FILE_TYPES = [
        ('DOCUMENT', _('Document')),
        ('IMAGE', _('Image')),
        ('CERTIFICATE', _('Certificate')),
        ('BACKUP', _('Backup')),
        ('EXPORT', _('Export')),
        ('IMPORT', _('Import')),
        ('LOG', _('Log')),
    ]
    
    file = models.FileField(
        _('file'),
        upload_to='uploads/%Y/%m/%d/',
        help_text=_('Uploaded file.')
    )
    
    original_name = models.CharField(
        _('original file name'),
        max_length=255,
        help_text=_('Original name of the uploaded file.')
    )
    
    file_type = models.CharField(
        _('file type'),
        max_length=20,
        choices=FILE_TYPES,
        default='DOCUMENT',
        help_text=_('Type of file uploaded.')
    )
    
    file_size = models.PositiveIntegerField(
        _('file size'),
        help_text=_('Size of the file in bytes.')
    )
    
    mime_type = models.CharField(
        _('MIME type'),
        max_length=100,
        blank=True,
        help_text=_('MIME type of the file.')
    )
    
    description = models.TextField(
        _('description'),
        blank=True,
        help_text=_('Description of the file.')
    )
    
    is_public = models.BooleanField(
        _('is public'),
        default=False,
        help_text=_('Whether this file can be accessed publicly.')
    )
    
    checksum = models.CharField(
        _('checksum'),
        max_length=64,
        blank=True,
        help_text=_('File checksum for integrity verification.')
    )
    
    class Meta:
        verbose_name = _('File Upload')
        verbose_name_plural = _('File Uploads')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.original_name} ({self.get_file_type_display()})"
    
    def save(self, *args, **kwargs):
        """Guarda el archivo calculando automáticamente el tamaño y otros metadatos"""
        if self.file and not self.file_size:
            self.file_size = self.file.size
        
        if self.file and not self.mime_type:
            import mimetypes
            mime_type, _ = mimetypes.guess_type(self.file.name)
            if mime_type:
                self.mime_type = mime_type
        
        if self.file and not self.checksum:
            import hashlib
            self.file.seek(0)
            file_hash = hashlib.md5()
            for chunk in iter(lambda: self.file.read(4096), b""):
                file_hash.update(chunk)
            self.checksum = file_hash.hexdigest()
            self.file.seek(0)
        
        super().save(*args, **kwargs)
    
    @property
    def file_size_human(self):
        """Devuelve el tamaño del archivo en formato legible"""
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"