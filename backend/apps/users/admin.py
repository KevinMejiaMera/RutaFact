# -*- coding: utf-8 -*-
"""
Admin configuration for users app
Panel de administración para usuarios de RutaFact_SRI
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.contrib import messages
from django.utils import timezone
from .models import User, UserProfile, UserCompanyAssignment, AdminNotification


class UserProfileInline(admin.StackedInline):
    """Inline para el perfil del usuario"""
    model = UserProfile
    can_delete = False
    verbose_name_plural = _('Profile Information')
    fields = (
        'bio', 'birth_date', 'timezone', 'language', 
        'notifications_enabled'
    )


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Administración personalizada para el modelo User"""
    
    inlines = (UserProfileInline,)
    
    # Campos que se muestran en la lista
    list_display = (
        'email', 'get_full_name_display', 'company', 
        'is_company_admin', 'is_staff', 'is_active', 
        'date_joined', 'profile_picture_display', 'get_assignment_status'
    )
    
    # Campos por los que se puede filtrar
    list_filter = (
        'is_staff', 'is_superuser', 'is_active', 
        'is_company_admin', 'company', 'date_joined'
    )
    
    # Campos por los que se puede buscar
    search_fields = ('email', 'first_name', 'last_name', 'phone')
    
    # Orden por defecto
    ordering = ('-date_joined',)
    
    # Configuración de campos en el formulario de edición
    fieldsets = (
        (_('Authentication'), {
            'fields': ('email', 'password')
        }),
        (_('Personal info'), {
            'fields': ('first_name', 'last_name', 'phone', 'profile_picture')
        }),
        (_('Company info'), {
            'fields': ('company', 'is_company_admin'),
            'classes': ('collapse',)
        }),
        (_('Permissions'), {
            'fields': (
                'is_active', 'is_staff', 'is_superuser', 
                'groups', 'user_permissions'
            ),
            'classes': ('collapse',)
        }),
        (_('Important dates'), {
            'fields': ('last_login', 'date_joined'),
            'classes': ('collapse',)
        }),
    )
    
    # Configuración para agregar nuevo usuario
    add_fieldsets = (
        (_('Authentication'), {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2'),
        }),
        (_('Personal info'), {
            'classes': ('wide',),
            'fields': ('first_name', 'last_name', 'phone'),
        }),
        (_('Company info'), {
            'classes': ('wide', 'collapse'),
            'fields': ('company', 'is_company_admin'),
        }),
        (_('Permissions'), {
            'classes': ('wide', 'collapse'),
            'fields': ('is_staff', 'is_active'),
        }),
    )
    
    # Configuración de filtros horizontales
    filter_horizontal = ('groups', 'user_permissions')
    
    def get_full_name_display(self, obj):
        """Muestra el nombre completo del usuario"""
        return obj.get_display_name()
    get_full_name_display.short_description = _('Full Name')
    get_full_name_display.admin_order_field = 'first_name'
    
    def profile_picture_display(self, obj):
        """Muestra una miniatura de la foto de perfil"""
        if obj.profile_picture:
            return format_html(
                '<img src="{}" width="30" height="30" style="border-radius: 50%;" />',
                obj.profile_picture.url
            )
        return _('No image')
    profile_picture_display.short_description = _('Picture')
    
    def get_assignment_status(self, obj):
        """Muestra el estado de asignación del usuario"""
        if obj.is_staff or obj.is_superuser:
            return format_html('<span style="color: #28a745;">👑 Admin</span>')
        
        try:
            assignment = obj.company_assignment
            colors = {
                'waiting': '#ffc107',
                'assigned': '#28a745',
                'rejected': '#dc3545',
                'suspended': '#fd7e14',
            }
            color = colors.get(assignment.status, '#6c757d')
            return format_html(
                '<span style="color: {};">● {}</span>',
                color, assignment.get_status_display()
            )
        except UserCompanyAssignment.DoesNotExist:
            return format_html('<span style="color: #6c757d;">Sin asignar</span>')
    get_assignment_status.short_description = _('Assignment Status')
    
    def get_queryset(self, request):
        """Optimiza las consultas"""
        qs = super().get_queryset(request)
        try:
            qs = qs.select_related('company', 'company_assignment')
        except:
            try:
                qs = qs.select_related('company')
            except:
                pass  # Si company no existe aún, continúa sin error
        return qs


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Administración para el perfil del usuario"""
    
    list_display = (
        'user', 'language', 'timezone', 
        'notifications_enabled', 'updated_at'
    )
    
    list_filter = (
        'language', 'timezone', 'notifications_enabled', 
        'created_at', 'updated_at'
    )
    
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'bio')
    
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        (_('User'), {
            'fields': ('user',)
        }),
        (_('Profile Information'), {
            'fields': ('bio', 'birth_date', 'language', 'timezone')
        }),
        (_('Preferences'), {
            'fields': ('notifications_enabled',)
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        """Optimiza las consultas"""
        qs = super().get_queryset(request)
        try:
            qs = qs.select_related('user', 'user__company')
        except:
            qs = qs.select_related('user')  # Si company no existe, solo user
        return qs


# ==========================================
# NUEVOS ADMINS PARA SALA DE ESPERA
# ==========================================

@admin.register(UserCompanyAssignment)
class UserCompanyAssignmentAdmin(admin.ModelAdmin):
    """Admin para gestionar asignaciones de usuarios a empresas"""
    
    list_display = [
        'get_user_info', 'get_status_badge', 'get_companies_count', 
        'assigned_by', 'assigned_at', 'get_actions_column'
    ]
    
    list_filter = [
        'status', 'assigned_at', 'created_at'
    ]
    
    search_fields = [
        'user__email', 'user__first_name', 'user__last_name',
        'notes'
    ]
    
    readonly_fields = [
        'user', 'created_at', 'updated_at', 'assigned_at'
    ]
    
    fieldsets = (
        (_('Usuario'), {
            'fields': ('user', 'status')
        }),
        (_('Asignación de Empresas'), {
            'fields': ('assigned_companies', 'assigned_by', 'assigned_at')
        }),
        (_('Notas'), {
            'fields': ('notes',)
        }),
        (_('Metadatos'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    filter_horizontal = ['assigned_companies']
    
    actions = [
        'approve_users', 'reject_users', 'suspend_users',
        'send_to_waiting'
    ]
    
    def get_user_info(self, obj):
        """Información del usuario"""
        user = obj.user
        email = user.email
        name = user.get_full_name() or "Sin nombre"
        date_joined = user.date_joined.strftime("%d/%m/%Y")
        
        return format_html(
            '<div style="line-height: 1.4;">'
            '<strong>{}</strong><br>'
            '<small style="color: #666;">{}</small><br>'
            '<small style="color: #999;">Registro: {}</small>'
            '</div>',
            name, email, date_joined
        )
    get_user_info.short_description = _('Usuario')
    get_user_info.admin_order_field = 'user__email'
    
    def get_status_badge(self, obj):
        """Badge del estado con colores"""
        colors = {
            'waiting': '#ffc107',      # amarillo
            'assigned': '#28a745',     # verde
            'rejected': '#dc3545',     # rojo
            'suspended': '#fd7e14',    # naranja
        }
        
        color = colors.get(obj.status, '#6c757d')
        status_display = obj.get_status_display()
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 10px; '
            'border-radius: 15px; font-size: 11px; font-weight: bold;">{}</span>',
            color, status_display
        )
    get_status_badge.short_description = _('Estado')
    get_status_badge.admin_order_field = 'status'
    
    def get_companies_count(self, obj):
        """Número de empresas asignadas"""
        count = obj.assigned_companies.count()
        if count == 0:
            return format_html('<span style="color: #999;">Sin asignar</span>')
        elif count == 1:
            try:
                company = obj.assigned_companies.first()
                company_name = getattr(company, 'trade_name', str(company))
                return format_html(
                    '<span style="color: #28a745;"><strong>{}</strong></span>',
                    company_name
                )
            except:
                return format_html('<span style="color: #28a745;">1 empresa</span>')
        else:
            return format_html(
                '<span style="color: #007bff;"><strong>{} empresas</strong></span>',
                count
            )
    get_companies_count.short_description = _('Empresas')
    
    def get_actions_column(self, obj):
        """Acciones rápidas"""
        actions = []
        
        if obj.status == 'waiting':
            # Botón de aprobar
            actions.append(
                f'<a href="{reverse("admin:users_usercompanyassignment_change", args=[obj.pk])}" '
                f'class="button" style="background: #28a745; color: white; text-decoration: none; '
                f'padding: 4px 8px; border-radius: 4px;" title="Asignar">✓ Asignar</a>'
            )
        
        # Botón de editar
        edit_url = reverse('admin:users_usercompanyassignment_change', args=[obj.pk])
        actions.append(
            f'<a href="{edit_url}" class="button" title="Editar">📝</a>'
        )
        
        return mark_safe(' '.join(actions))
    get_actions_column.short_description = _('Acciones')
    
    def approve_users(self, request, queryset):
        """Aprobar usuarios seleccionados"""
        updated = 0
        for assignment in queryset.filter(status='waiting'):
            # Si no tiene empresas asignadas, necesita configuración manual
            if assignment.assigned_companies.count() == 0:
                messages.warning(
                    request, 
                    f'Usuario {assignment.user.email} necesita empresas asignadas.'
                )
                continue
                
            assignment.status = 'assigned'
            assignment.assigned_by = request.user
            assignment.assigned_at = timezone.now()
            assignment.save()
            updated += 1
        
        if updated > 0:
            messages.success(request, f'{updated} usuarios aprobados.')
    approve_users.short_description = _('Aprobar usuarios seleccionados')
    
    def reject_users(self, request, queryset):
        """Rechazar usuarios seleccionados"""
        updated = queryset.filter(status='waiting').update(status='rejected')
        messages.success(request, f'{updated} usuarios rechazados.')
    reject_users.short_description = _('Rechazar usuarios seleccionados')
    
    def suspend_users(self, request, queryset):
        """Suspender usuarios seleccionados"""
        updated = queryset.update(status='suspended')
        messages.warning(request, f'{updated} usuarios suspendidos.')
    suspend_users.short_description = _('Suspender usuarios seleccionados')
    
    def send_to_waiting(self, request, queryset):
        """Enviar usuarios a sala de espera"""
        updated = queryset.update(status='waiting')
        messages.info(request, f'{updated} usuarios enviados a sala de espera.')
    send_to_waiting.short_description = _('Enviar a sala de espera')
    
    def get_queryset(self, request):
        """Optimizar consultas"""
        return super().get_queryset(request).select_related(
            'user', 'assigned_by'
        ).prefetch_related('assigned_companies')


@admin.register(AdminNotification)
class AdminNotificationAdmin(admin.ModelAdmin):
    """Admin para gestionar notificaciones"""
    
    list_display = [
        'get_notification_info', 'get_priority_badge', 'related_user',
        'get_read_status', 'created_at', 'get_actions_column'
    ]
    
    list_filter = [
        'notification_type', 'priority', 'is_read', 
        'created_at'
    ]
    
    search_fields = [
        'title', 'message', 'related_user__email'
    ]
    
    readonly_fields = [
        'created_at', 'read_at', 'read_by'
    ]
    
    fieldsets = (
        (_('Notificación'), {
            'fields': ('notification_type', 'title', 'message', 'priority')
        }),
        (_('Usuario Relacionado'), {
            'fields': ('related_user',)
        }),
        (_('Estado de Lectura'), {
            'fields': ('is_read', 'read_by', 'read_at')
        }),
        (_('Metadatos'), {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )
    
    actions = ['mark_as_read', 'mark_as_unread', 'delete_selected']
    
    def get_notification_info(self, obj):
        """Información de la notificación"""
        icon_map = {
            'user_waiting': '⏳',
            'user_registered': '👤',
            'company_request': '🏢',
            'system_alert': '⚠️',
        }
        
        icon = icon_map.get(obj.notification_type, '📢')
        
        return format_html(
            '<div style="line-height: 1.4;">'
            '<span style="font-size: 16px;">{}</span> <strong>{}</strong><br>'
            '<small style="color: #666;">{}</small>'
            '</div>',
            icon, obj.title, obj.message[:100] + ('...' if len(obj.message) > 100 else '')
        )
    get_notification_info.short_description = _('Notificación')
    
    def get_priority_badge(self, obj):
        """Badge de prioridad"""
        colors = {
            'low': '#6c757d',
            'normal': '#007bff',
            'high': '#fd7e14',
            'urgent': '#dc3545',
        }
        
        color = colors.get(obj.priority, '#6c757d')
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 12px; font-size: 10px; font-weight: bold;">{}</span>',
            color, obj.get_priority_display().upper()
        )
    get_priority_badge.short_description = _('Prioridad')
    
    def get_read_status(self, obj):
        """Estado de lectura"""
        if obj.is_read:
            return format_html(
                '<span style="color: #28a745;">✓ Leída</span><br>'
                '<small style="color: #999;">por {}</small>',
                obj.read_by.email if obj.read_by else 'Sistema'
            )
        else:
            return format_html('<span style="color: #dc3545; font-weight: bold;">● Sin leer</span>')
    get_read_status.short_description = _('Estado')
    
    def get_actions_column(self, obj):
        """Acciones rápidas"""
        actions = []
        
        if not obj.is_read:
            change_url = reverse('admin:users_adminnotification_change', args=[obj.pk])
            actions.append(
                f'<a href="{change_url}" class="button" '
                f'style="background: #28a745; color: white; text-decoration: none; '
                f'padding: 4px 8px; border-radius: 4px;" title="Marcar como leída">✓</a>'
            )
        
        if obj.related_user:
            user_url = reverse('admin:users_usercompanyassignment_changelist') + f'?user__id__exact={obj.related_user.pk}'
            actions.append(
                f'<a href="{user_url}" class="button" title="Ver usuario">👤</a>'
            )
        
        return mark_safe(' '.join(actions))
    get_actions_column.short_description = _('Acciones')
    
    def mark_as_read(self, request, queryset):
        """Marcar notificaciones como leídas"""
        updated = 0
        for notification in queryset.filter(is_read=False):
            notification.mark_as_read(request.user)
            updated += 1
        
        messages.success(request, f'{updated} notificaciones marcadas como leídas.')
    mark_as_read.short_description = _('Marcar como leídas')
    
    def mark_as_unread(self, request, queryset):
        """Marcar notificaciones como no leídas"""
        updated = queryset.update(is_read=False, read_by=None, read_at=None)
        messages.info(request, f'{updated} notificaciones marcadas como no leídas.')
    mark_as_unread.short_description = _('Marcar como no leídas')