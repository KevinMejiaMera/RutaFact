# -*- coding: utf-8 -*-
"""
Models for settings app
Modelos para configuración del sistema
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from apps.core.models import BaseModel
from apps.companies.models import Company

User = get_user_model()


class SystemSetting(BaseModel):
    """
    Configuraciones globales del sistema
    """
    
    SETTING_TYPES = [
        ('STRING', _('String')),
        ('INTEGER', _('Integer')),
        ('FLOAT', _('Float')),
        ('BOOLEAN', _('Boolean')),
        ('JSON', _('JSON')),
        ('EMAIL', _('Email')),
        ('URL', _('URL')),
        ('PASSWORD', _('Password')),
    ]
    
    CATEGORIES = [
        ('SYSTEM', _('System')),
        ('EMAIL', _('Email')),
        ('SRI', _('SRI')),
        ('SECURITY', _('Security')),
        ('BACKUP', _('Backup')),
        ('NOTIFICATION', _('Notification')),
        ('INTEGRATION', _('Integration')),
    ]
    
    key = models.CharField(
        _('setting key'),
        max_length=100,
        unique=True,
        help_text=_('Unique identifier for this setting')
    )
    
    value = models.TextField(
        _('value'),
        help_text=_('Setting value')
    )
    
    default_value = models.TextField(
        _('default value'),
        blank=True,
        help_text=_('Default value for this setting')
    )
    
    setting_type = models.CharField(
        _('setting type'),
        max_length=20,
        choices=SETTING_TYPES,
        default='STRING'
    )
    
    category = models.CharField(
        _('category'),
        max_length=20,
        choices=CATEGORIES,
        default='SYSTEM'
    )
    
    name = models.CharField(
        _('display name'),
        max_length=100,
        help_text=_('Human-readable name for this setting')
    )
    
    description = models.TextField(
        _('description'),
        blank=True,
        help_text=_('Description of what this setting does')
    )
    
    is_sensitive = models.BooleanField(
        _('is sensitive'),
        default=False,
        help_text=_('Whether this setting contains sensitive information')
    )
    
    requires_restart = models.BooleanField(
        _('requires restart'),
        default=False,
        help_text=_('Whether changing this setting requires system restart')
    )
    
    validation_regex = models.CharField(
        _('validation regex'),
        max_length=255,
        blank=True,
        help_text=_('Regular expression to validate the value')
    )
    
    class Meta:
        verbose_name = _('System Setting')
        verbose_name_plural = _('System Settings')
        ordering = ['category', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.key})"
    
    def get_typed_value(self):
        """Retorna el valor convertido al tipo apropiado"""
        if self.setting_type == 'BOOLEAN':
            return self.value.lower() in ('true', '1', 'yes', 'on')
        elif self.setting_type == 'INTEGER':
            try:
                return int(self.value)
            except ValueError:
                return 0
        elif self.setting_type == 'FLOAT':
            try:
                return float(self.value)
            except ValueError:
                return 0.0
        elif self.setting_type == 'JSON':
            import json
            try:
                return json.loads(self.value)
            except json.JSONDecodeError:
                return {}
        else:
            return self.value


class CompanySetting(BaseModel):
    """
    Configuraciones específicas por empresa
    """
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='settings',
        verbose_name=_('company')
    )
    
    key = models.CharField(
        _('setting key'),
        max_length=100,
        help_text=_('Setting identifier')
    )
    
    value = models.TextField(
        _('value'),
        help_text=_('Setting value')
    )
    
    setting_type = models.CharField(
        _('setting type'),
        max_length=20,
        choices=SystemSetting.SETTING_TYPES,
        default='STRING'
    )
    
    name = models.CharField(
        _('display name'),
        max_length=100
    )
    
    description = models.TextField(
        _('description'),
        blank=True
    )
    
    class Meta:
        verbose_name = _('Company Setting')
        verbose_name_plural = _('Company Settings')
        unique_together = ['company', 'key']
        ordering = ['company', 'name']
    
    def __str__(self):
        return f"{self.company.business_name} - {self.name}"


class UserPreference(BaseModel):
    """
    Preferencias de usuario
    """
    
    THEMES = [
        ('LIGHT', _('Light')),
        ('DARK', _('Dark')),
        ('AUTO', _('Auto')),
    ]
    
    LANGUAGES = [
        ('es', _('Spanish')),
        ('en', _('English')),
    ]
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='preferences',
        verbose_name=_('user')
    )
    
    # Apariencia
    theme = models.CharField(
        _('theme'),
        max_length=10,
        choices=THEMES,
        default='LIGHT'
    )
    
    language = models.CharField(
        _('language'),
        max_length=5,
        choices=LANGUAGES,
        default='es'
    )
    
    # Dashboard
    dashboard_layout = models.JSONField(
        _('dashboard layout'),
        default=dict,
        blank=True,
        help_text=_('User dashboard layout configuration')
    )
    
    # Notificaciones
    email_notifications = models.BooleanField(
        _('email notifications'),
        default=True,
        help_text=_('Receive email notifications')
    )
    
    browser_notifications = models.BooleanField(
        _('browser notifications'),
        default=True,
        help_text=_('Receive browser notifications')
    )
    
    notification_frequency = models.CharField(
        _('notification frequency'),
        max_length=20,
        choices=[
            ('IMMEDIATE', _('Immediate')),
            ('HOURLY', _('Hourly')),
            ('DAILY', _('Daily')),
            ('WEEKLY', _('Weekly')),
        ],
        default='IMMEDIATE'
    )
    
    # Configuración de trabajo
    default_company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='default_for_users',
        verbose_name=_('default company')
    )
    
    timezone = models.CharField(
        _('timezone'),
        max_length=50,
        default='America/Guayaquil',
        help_text=_('User timezone')
    )
    
    # Configuración de tablas
    items_per_page = models.PositiveIntegerField(
        _('items per page'),
        default=20,
        help_text=_('Number of items to show per page in tables')
    )
    
    class Meta:
        verbose_name = _('User Preference')
        verbose_name_plural = _('User Preferences')
    
    def __str__(self):
        return f"Preferences - {self.user.email}"


class BackupConfiguration(BaseModel):
    """
    Configuración de respaldos
    """
    
    BACKUP_TYPES = [
        ('FULL', _('Full Backup')),
        ('INCREMENTAL', _('Incremental')),
        ('DIFFERENTIAL', _('Differential')),
    ]
    
    FREQUENCIES = [
        ('DAILY', _('Daily')),
        ('WEEKLY', _('Weekly')),
        ('MONTHLY', _('Monthly')),
    ]
    
    STORAGE_TYPES = [
        ('LOCAL', _('Local Storage')),
        ('S3', _('Amazon S3')),
        ('FTP', _('FTP Server')),
        ('SFTP', _('SFTP Server')),
    ]
    
    name = models.CharField(
        _('backup name'),
        max_length=100,
        unique=True
    )
    
    backup_type = models.CharField(
        _('backup type'),
        max_length=20,
        choices=BACKUP_TYPES,
        default='FULL'
    )
    
    frequency = models.CharField(
        _('frequency'),
        max_length=20,
        choices=FREQUENCIES,
        default='DAILY'
    )
    
    storage_type = models.CharField(
        _('storage type'),
        max_length=20,
        choices=STORAGE_TYPES,
        default='LOCAL'
    )
    
    storage_config = models.JSONField(
        _('storage configuration'),
        default=dict,
        help_text=_('Storage-specific configuration (credentials, paths, etc.)')
    )
    
    # Configuración de retención
    retention_days = models.PositiveIntegerField(
        _('retention days'),
        default=30,
        help_text=_('Number of days to keep backups')
    )
    
    max_backups = models.PositiveIntegerField(
        _('max backups'),
        default=10,
        help_text=_('Maximum number of backups to keep')
    )
    
    # Configuración de contenido
    include_media = models.BooleanField(
        _('include media files'),
        default=True
    )
    
    include_logs = models.BooleanField(
        _('include log files'),
        default=False
    )
    
    exclude_tables = models.JSONField(
        _('exclude tables'),
        default=list,
        blank=True,
        help_text=_('Database tables to exclude from backup')
    )
    
    # Estado
    enabled = models.BooleanField(
        _('enabled'),
        default=True
    )
    
    last_backup = models.DateTimeField(
        _('last backup'),
        null=True,
        blank=True
    )
    
    last_backup_status = models.CharField(
        _('last backup status'),
        max_length=20,
        choices=[
            ('SUCCESS', _('Success')),
            ('FAILED', _('Failed')),
            ('RUNNING', _('Running')),
        ],
        blank=True
    )
    
    class Meta:
        verbose_name = _('Backup Configuration')
        verbose_name_plural = _('Backup Configurations')
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.get_frequency_display()})"


class MaintenanceMode(BaseModel):
    """
    Configuración de modo de mantenimiento
    """
    
    is_enabled = models.BooleanField(
        _('maintenance mode enabled'),
        default=False
    )
    
    message = models.TextField(
        _('maintenance message'),
        default=_('System is under maintenance. Please try again later.'),
        help_text=_('Message to show users during maintenance')
    )
    
    allowed_ips = models.JSONField(
        _('allowed IP addresses'),
        default=list,
        blank=True,
        help_text=_('IP addresses that can access the system during maintenance')
    )
    
    start_time = models.DateTimeField(
        _('start time'),
        null=True,
        blank=True,
        help_text=_('When maintenance mode was enabled')
    )
    
    estimated_end_time = models.DateTimeField(
        _('estimated end time'),
        null=True,
        blank=True,
        help_text=_('Estimated time when maintenance will be completed')
    )
    
    class Meta:
        verbose_name = _('Maintenance Mode')
        verbose_name_plural = _('Maintenance Mode')
    
    def __str__(self):
        status = _('Enabled') if self.is_enabled else _('Disabled')
        return f"Maintenance Mode - {status}"