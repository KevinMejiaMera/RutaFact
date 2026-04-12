# -*- coding: utf-8 -*-
"""
Models for notifications app
Modelos para notificaciones del sistema
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from apps.core.models import BaseModel
from apps.companies.models import Company

User = get_user_model()


class NotificationTemplate(BaseModel):
    """
    Plantillas de notificaciones
    """
    
    NOTIFICATION_TYPES = [
        ('DOCUMENT_AUTHORIZED', _('Document Authorized')),
        ('DOCUMENT_REJECTED', _('Document Rejected')),
        ('CERTIFICATE_EXPIRING', _('Certificate Expiring')),
        ('CERTIFICATE_EXPIRED', _('Certificate Expired')),
        ('BACKUP_COMPLETED', _('Backup Completed')),
        ('BACKUP_FAILED', _('Backup Failed')),
        ('SYSTEM_ERROR', _('System Error')),
        ('LOW_STOCK', _('Low Stock')),
        ('PAYMENT_REMINDER', _('Payment Reminder')),
        ('WELCOME', _('Welcome')),
        ('PASSWORD_CHANGED', _('Password Changed')),
        ('LOGIN_ALERT', _('Login Alert')),
    ]
    
    CHANNELS = [
        ('EMAIL', _('Email')),
        ('BROWSER', _('Browser')),
        ('SMS', _('SMS')),
        ('WEBHOOK', _('Webhook')),
    ]
    
    notification_type = models.CharField(
        _('notification type'),
        max_length=30,
        choices=NOTIFICATION_TYPES,
        unique=True
    )
    
    name = models.CharField(
        _('template name'),
        max_length=100
    )
    
    description = models.TextField(
        _('description'),
        blank=True
    )
    
    # Configuración de canales
    email_enabled = models.BooleanField(
        _('email enabled'),
        default=True
    )
    
    browser_enabled = models.BooleanField(
        _('browser enabled'),
        default=True
    )
    
    sms_enabled = models.BooleanField(
        _('SMS enabled'),
        default=False
    )
    
    webhook_enabled = models.BooleanField(
        _('webhook enabled'),
        default=False
    )
    
    # Plantillas de contenido
    email_subject = models.CharField(
        _('email subject'),
        max_length=255,
        blank=True,
        help_text=_('Email subject template with variables like {variable}')
    )
    
    email_template = models.TextField(
        _('email template'),
        blank=True,
        help_text=_('Email body template with variables')
    )
    
    browser_title = models.CharField(
        _('browser notification title'),
        max_length=100,
        blank=True
    )
    
    browser_message = models.TextField(
        _('browser notification message'),
        blank=True
    )
    
    sms_message = models.CharField(
        _('SMS message'),
        max_length=160,
        blank=True,
        help_text=_('SMS message template (max 160 chars)')
    )
    
    # Configuración de envío
    priority = models.CharField(
        _('priority'),
        max_length=10,
        choices=[
            ('LOW', _('Low')),
            ('NORMAL', _('Normal')),
            ('HIGH', _('High')),
            ('URGENT', _('Urgent')),
        ],
        default='NORMAL'
    )
    
    delay_minutes = models.PositiveIntegerField(
        _('delay in minutes'),
        default=0,
        help_text=_('Minutes to wait before sending notification')
    )
    
    retry_attempts = models.PositiveIntegerField(
        _('retry attempts'),
        default=3,
        help_text=_('Number of retry attempts for failed notifications')
    )
    
    class Meta:
        verbose_name = _('Notification Template')
        verbose_name_plural = _('Notification Templates')
        ordering = ['notification_type']
    
    def __str__(self):
        return f"{self.name} ({self.get_notification_type_display()})"


class Notification(BaseModel):
    """
    Notificaciones enviadas a usuarios
    """
    
    STATUS_CHOICES = [
        ('PENDING', _('Pending')),
        ('SENT', _('Sent')),
        ('DELIVERED', _('Delivered')),
        ('READ', _('Read')),
        ('FAILED', _('Failed')),
    ]
    
    template = models.ForeignKey(
        NotificationTemplate,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name=_('template')
    )
    
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications_received',
        verbose_name=_('recipient')
    )
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications',
        verbose_name=_('company')
    )
    
    # Contenido
    title = models.CharField(
        _('title'),
        max_length=255
    )
    
    message = models.TextField(
        _('message')
    )
    
    # Estado
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    
    # Fechas importantes
    scheduled_for = models.DateTimeField(
        _('scheduled for'),
        null=True,
        blank=True,
        help_text=_('When to send this notification')
    )
    
    sent_at = models.DateTimeField(
        _('sent at'),
        null=True,
        blank=True
    )
    
    read_at = models.DateTimeField(
        _('read at'),
        null=True,
        blank=True
    )
    
    # Metadatos
    context_data = models.JSONField(
        _('context data'),
        default=dict,
        blank=True,
        help_text=_('Additional data related to this notification')
    )
    
    # Canales de envío
    sent_via_email = models.BooleanField(
        _('sent via email'),
        default=False
    )
    
    sent_via_browser = models.BooleanField(
        _('sent via browser'),
        default=False
    )
    
    sent_via_sms = models.BooleanField(
        _('sent via SMS'),
        default=False
    )
    
    sent_via_webhook = models.BooleanField(
        _('sent via webhook'),
        default=False
    )
    
    # URLs y acciones
    action_url = models.URLField(
        _('action URL'),
        blank=True,
        help_text=_('URL to redirect when notification is clicked')
    )
    
    action_text = models.CharField(
        _('action text'),
        max_length=50,
        blank=True,
        help_text=_('Text for the action button')
    )
    
    # Información de entrega
    delivery_attempts = models.PositiveIntegerField(
        _('delivery attempts'),
        default=0
    )
    
    last_attempt_at = models.DateTimeField(
        _('last attempt at'),
        null=True,
        blank=True
    )
    
    error_message = models.TextField(
        _('error message'),
        blank=True,
        help_text=_('Error message if delivery failed')
    )
    
    class Meta:
        verbose_name = _('Notification')
        verbose_name_plural = _('Notifications')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'status']),
            models.Index(fields=['recipient', 'read_at']),
            models.Index(fields=['company', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.recipient.email}"
    
    def mark_as_read(self):
        """Marca la notificación como leída"""
        if not self.read_at:
            from django.utils import timezone
            self.read_at = timezone.now()
            self.status = 'READ'
            self.save()
    
    @property
    def is_read(self):
        """Verifica si la notificación ha sido leída"""
        return self.read_at is not None


class NotificationChannel(BaseModel):
    """
    Configuración de canales de notificación
    """
    
    CHANNEL_TYPES = [
        ('EMAIL', _('Email')),
        ('SMS', _('SMS')),
        ('WEBHOOK', _('Webhook')),
        ('SLACK', _('Slack')),
        ('TELEGRAM', _('Telegram')),
    ]
    
    name = models.CharField(
        _('channel name'),
        max_length=100,
        unique=True
    )
    
    channel_type = models.CharField(
        _('channel type'),
        max_length=20,
        choices=CHANNEL_TYPES
    )
    
    # Configuración del canal
    configuration = models.JSONField(
        _('configuration'),
        default=dict,
        help_text=_('Channel-specific configuration (API keys, URLs, etc.)')
    )
    
    # Estado
    enabled = models.BooleanField(
        _('enabled'),
        default=True
    )
    
    # Límites de envío
    rate_limit_per_minute = models.PositiveIntegerField(
        _('rate limit per minute'),
        default=60,
        help_text=_('Maximum notifications per minute')
    )
    
    rate_limit_per_hour = models.PositiveIntegerField(
        _('rate limit per hour'),
        default=1000,
        help_text=_('Maximum notifications per hour')
    )
    
    # Estadísticas
    total_sent = models.PositiveIntegerField(
        _('total sent'),
        default=0
    )
    
    total_failed = models.PositiveIntegerField(
        _('total failed'),
        default=0
    )
    
    last_used_at = models.DateTimeField(
        _('last used at'),
        null=True,
        blank=True
    )
    
    class Meta:
        verbose_name = _('Notification Channel')
        verbose_name_plural = _('Notification Channels')
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.get_channel_type_display()})"


class NotificationSubscription(BaseModel):
    """
    Suscripciones de usuarios a tipos de notificaciones
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notification_subscriptions',
        verbose_name=_('user')
    )
    
    notification_type = models.CharField(
        _('notification type'),
        max_length=30,
        choices=NotificationTemplate.NOTIFICATION_TYPES
    )
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notification_subscriptions',
        verbose_name=_('company'),
        help_text=_('Company-specific subscription (leave empty for global)')
    )
    
    # Configuración de canales
    email_enabled = models.BooleanField(
        _('email enabled'),
        default=True
    )
    
    browser_enabled = models.BooleanField(
        _('browser enabled'),
        default=True
    )
    
    sms_enabled = models.BooleanField(
        _('SMS enabled'),
        default=False
    )
    
    # Configuración adicional
    frequency = models.CharField(
        _('frequency'),
        max_length=20,
        choices=[
            ('IMMEDIATE', _('Immediate')),
            ('HOURLY', _('Hourly')),
            ('DAILY', _('Daily')),
            ('WEEKLY', _('Weekly')),
        ],
        default='IMMEDIATE'
    )
    
    quiet_hours_start = models.TimeField(
        _('quiet hours start'),
        null=True,
        blank=True,
        help_text=_('Start of quiet hours (no notifications)')
    )
    
    quiet_hours_end = models.TimeField(
        _('quiet hours end'),
        null=True,
        blank=True,
        help_text=_('End of quiet hours')
    )
    
    class Meta:
        verbose_name = _('Notification Subscription')
        verbose_name_plural = _('Notification Subscriptions')
        unique_together = ['user', 'notification_type', 'company']
        ordering = ['user', 'notification_type']
    
    def __str__(self):
        company_str = f" - {self.company.business_name}" if self.company else ""
        return f"{self.user.email} - {self.get_notification_type_display()}{company_str}"


class NotificationLog(BaseModel):
    """
    Log de envío de notificaciones
    """
    
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name='logs',
        verbose_name=_('notification')
    )
    
    channel = models.ForeignKey(
        NotificationChannel,
        on_delete=models.CASCADE,
        related_name='logs',
        verbose_name=_('channel')
    )
    
    # Estado del envío
    success = models.BooleanField(
        _('success'),
        default=False
    )
    
    response_code = models.CharField(
        _('response code'),
        max_length=10,
        blank=True
    )
    
    response_message = models.TextField(
        _('response message'),
        blank=True
    )
    
    # Metadatos
    sent_at = models.DateTimeField(
        _('sent at'),
        auto_now_add=True
    )
    
    delivery_time_ms = models.PositiveIntegerField(
        _('delivery time (ms)'),
        null=True,
        blank=True,
        help_text=_('Time taken to deliver notification in milliseconds')
    )
    
    class Meta:
        verbose_name = _('Notification Log')
        verbose_name_plural = _('Notification Logs')
        ordering = ['-sent_at']
    
    def __str__(self):
        status = "✓" if self.success else "✗"
        return f"{status} {self.notification.title} via {self.channel.name}"