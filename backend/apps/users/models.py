# -*- coding: utf-8 -*-
"""
Models for users app
Sistema de Usuarios personalizado para RutaFact_SRI
"""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
import re

def user_profile_pic_upload_path(instance, filename):
    """Genera la ruta para la foto de perfil del usuario"""
    email_slug = re.sub(r'[^a-z0-9_]', '_', instance.email.lower()).strip('_')
    return f"usuarios/{email_slug}/foto/{filename}"


class UserManager(BaseUserManager):
    """
    Manager personalizado para el modelo User
    """
    
    def create_user(self, email, password=None, **extra_fields):
        """
        Crea y guarda un usuario regular con el email y password dados
        """
        if not email:
            raise ValueError(_('The Email field must be set'))
        
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """
        Crea y guarda un superusuario con el email y password dados
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))
        
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Usuario personalizado para el sistema RutaFact_SRI
    """
    
    # Remover el campo username (no lo usaremos)
    username = None
    
    # Campos adicionales
    email = models.EmailField(
        _('email address'),
        unique=True,
        help_text=_('Required. Enter a valid email address.')
    )
    
    phone = models.CharField(
        _('phone number'),
        max_length=20,
        blank=True,
        help_text=_('Optional. Phone number for contact.')
    )
    
    company = models.ForeignKey(
        'companies.Company',  # Usar string reference para evitar problemas de importación
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        verbose_name=_('company'),
        help_text=_('Company associated with this user.')
    )
    
    is_company_admin = models.BooleanField(
        _('is company admin'),
        default=False,
        help_text=_('Designates whether this user can manage company settings.')
    )
    
    profile_picture = models.ImageField(
        _('profile picture'),
        upload_to=user_profile_pic_upload_path,
        blank=True,
        null=True,
        help_text=_('Optional profile picture.')
    )
    USER_STATUS_CHOICES = [
        ('waiting', 'En Sala de Espera'),
        ('active', 'Activo'),
        ('suspended', 'Suspendido'),
        ('rejected', 'Rechazado'),
    ]
    
    USER_ROLE_CHOICES = [
        ('admin', 'Administrador'),
        ('seller', 'Vendedor'),
        ('dispatcher', 'Despachador'),
        ('driver', 'Transportador'),
        ('client', 'Cliente'),
    ]
    
    user_status = models.CharField(
        max_length=20,
        choices=USER_STATUS_CHOICES,
        default='waiting',
        verbose_name='Estado del Usuario'
    )
    
    role = models.CharField(
        max_length=20,
        choices=USER_ROLE_CHOICES,
        default='client',
        verbose_name='Rol del Usuario'
    )
    
    approved_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_users',
        verbose_name='Aprobado por'
    )
    
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de aprobación'
    )
    
    suspension_reason = models.TextField(
        blank=True,
        null=True,
        verbose_name='Razón de suspensión'
    )
    
    rejection_reason = models.TextField(
        blank=True,
        null=True,
        verbose_name='Razón de rechazo'
    )
    

    # Manager personalizado
    objects = UserManager()
    
    # Configuración de autenticación
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']
    
    class Meta:
        verbose_name = _('User')
        verbose_name_plural = _('Users')
        ordering = ['email']
    
    def __str__(self):
        return f"{self.get_full_name()} ({self.email})" if self.get_full_name() else self.email
    
    def get_display_name(self):
        """Devuelve el nombre completo o email si no hay nombre"""
        full_name = self.get_full_name()
        return full_name if full_name else self.email
    
    @property
    def is_company_user(self):
        """Verifica si el usuario pertenece a una empresa"""
        return self.company is not None


class UserProfile(models.Model):
    """
    Perfil extendido del usuario
    """
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name=_('user')
    )
    
    bio = models.TextField(
        _('biography'),
        max_length=500,
        blank=True,
        help_text=_('Brief description about the user.')
    )
    
    birth_date = models.DateField(
        _('birth date'),
        null=True,
        blank=True
    )
    
    timezone = models.CharField(
        _('timezone'),
        max_length=50,
        default='America/Guayaquil',
        help_text=_('User timezone for date/time display.')
    )
    
    language = models.CharField(
        _('language'),
        max_length=10,
        default='es',
        choices=[
            ('es', _('Spanish')),
            ('en', _('English')),
        ],
        help_text=_('Preferred language for the interface.')
    )
    
    notifications_enabled = models.BooleanField(
        _('notifications enabled'),
        default=True,
        help_text=_('Whether to receive email notifications.')
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('User Profile')
        verbose_name_plural = _('User Profiles')
    
    def __str__(self):
        return f"Profile for {self.user.get_display_name()}"


# ==========================================
# NUEVOS MODELOS PARA SALA DE ESPERA
# ==========================================

class UserCompanyAssignment(models.Model):
    """Modelo para asignar usuarios a empresas específicas"""
    
    STATUS_CHOICES = [
        ('waiting', _('En Sala de Espera')),
        ('assigned', _('Asignado')),
        ('rejected', _('Rechazado')),
        ('suspended', _('Suspendido')),
    ]
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='company_assignment',
        verbose_name=_('Usuario')
    )
    
    assigned_companies = models.ManyToManyField(
        'companies.Company',
        blank=True,
        related_name='assigned_users',
        verbose_name=_('Empresas Asignadas')
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='assigned',
        verbose_name=_('Estado')
    )
    
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users_assigned',
        verbose_name=_('Asignado por')
    )
    
    assigned_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Fecha de Asignación')
    )
    
    notes = models.TextField(
        blank=True,
        verbose_name=_('Notas del Administrador')
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Fecha de Creación')
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('Última Actualización')
    )
    
    class Meta:
        verbose_name = _('Asignación de Usuario')
        verbose_name_plural = _('Asignaciones de Usuarios')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.email} - {self.get_status_display()}"
    
    def assign_companies(self, companies, assigned_by_user):
        """Asignar empresas al usuario"""
        self.assigned_companies.set(companies)
        self.status = 'assigned'
        self.assigned_by = assigned_by_user
        self.assigned_at = timezone.now()
        self.save()
    
    def is_waiting(self):
        """Verifica si el usuario está en sala de espera"""
        return self.status == 'waiting'
    
    def is_assigned(self):
        """Verifica si el usuario ya fue asignado"""
        return self.status == 'assigned'
    
    def get_assigned_companies(self):
        """Obtiene las empresas asignadas al usuario"""
        return self.assigned_companies.all()


class AdminNotification(models.Model):
    """Notificaciones para administradores"""
    
    NOTIFICATION_TYPES = [
        ('user_waiting', _('Usuario en Sala de Espera')),
        ('user_registered', _('Nuevo Usuario Registrado')),
        ('company_request', _('Solicitud de Empresa')),
        ('system_alert', _('Alerta del Sistema')),
    ]
    
    PRIORITY_CHOICES = [
        ('low', _('Baja')),
        ('normal', _('Normal')),
        ('high', _('Alta')),
        ('urgent', _('Urgente')),
    ]
    
    notification_type = models.CharField(
        max_length=20,
        choices=NOTIFICATION_TYPES,
        verbose_name=_('Tipo de Notificación')
    )
    
    title = models.CharField(
        max_length=200,
        verbose_name=_('Título')
    )
    
    message = models.TextField(
        verbose_name=_('Mensaje')
    )
    
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='normal',
        verbose_name=_('Prioridad')
    )
    
    related_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='admin_notifications',
        verbose_name=_('Usuario Relacionado')
    )
    
    is_read = models.BooleanField(
        default=False,
        verbose_name=_('Leída')
    )
    
    read_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='read_notifications',
        verbose_name=_('Leída por')
    )
    
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Fecha de Lectura')
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Fecha de Creación')
    )
    
    class Meta:
        verbose_name = _('Notificación de Admin')
        verbose_name_plural = _('Notificaciones de Admin')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_read', '-created_at']),
            models.Index(fields=['notification_type']),
            models.Index(fields=['priority']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.get_priority_display()}"
    
    def mark_as_read(self, user):
        """Marcar notificación como leída"""
        self.is_read = True
        self.read_by = user
        self.read_at = timezone.now()
        self.save()
    
    @classmethod
    def create_user_waiting_notification(cls, user):
        """Crear notificación cuando un usuario está en sala de espera"""
        return cls.objects.create(
            notification_type='user_waiting',
            title=f'Usuario en sala de espera',
            message=f'El usuario {user.email} está esperando asignación de empresa.',
            priority='normal',
            related_user=user
        )
    
    @classmethod
    def create_user_registered_notification(cls, user):
        """Crear notificación cuando se registra un nuevo usuario"""
        return cls.objects.create(
            notification_type='user_registered',
            title=f'Nuevo usuario registrado',
            message=f'Se ha registrado un nuevo usuario: {user.email}',
            priority='normal',
            related_user=user
        )