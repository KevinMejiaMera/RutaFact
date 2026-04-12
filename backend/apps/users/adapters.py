# -*- coding: utf-8 -*-
"""
Adaptadores personalizados para allauth en RutaFact_SRI
"""
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.conf import settings
from django.forms import ValidationError

from .models import UserProfile

User = get_user_model()


class CustomAccountAdapter(DefaultAccountAdapter):
    """
    Adaptador personalizado para cuentas regulares
    """
    
    def get_login_redirect_url(self, request):
        """
        Personalizar redirección después del login
        """
        # Verificar estado de aprobación del usuario
        user = request.user
        
        if user.is_pending_approval():
            return '/accounts/waiting-room/'
        elif user.is_rejected():
            return '/accounts/account-rejected/'
        
        # Usuario aprobado - redirigir al dashboard
        return '/'
    
    def save_user(self, request, user, form, commit=True):
        """
        Personalizar guardado de usuario
        """
        user = super().save_user(request, user, form, commit=False)
        
        # Asegurar que el email sea único
        if User.objects.filter(email=user.email).exclude(pk=user.pk).exists():
            raise ValidationError(_('Ya existe un usuario con este email.'))
        
        if commit:
            user.save()
            
            # Crear perfil automáticamente
            UserProfile.objects.get_or_create(user=user)
        
        return user
    
    def is_open_for_signup(self, request):
        """
        Determinar si el registro está abierto
        """
        # Permitir registro solo si está habilitado en settings
        return getattr(settings, 'ACCOUNT_ALLOW_REGISTRATION', True)


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Adaptador personalizado para cuentas sociales (OAuth)
    """
    
    def pre_social_login(self, request, sociallogin):
        """
        Ejecutar antes del login social
        """
        # Verificar si ya existe un usuario con el mismo email
        if sociallogin.account.extra_data.get('email'):
            email = sociallogin.account.extra_data['email']
            
            try:
                existing_user = User.objects.get(email=email)
                
                # Si el usuario existe pero no tiene cuenta social, conectarla
                if not sociallogin.is_existing:
                    sociallogin.connect(request, existing_user)
                    messages.info(
                        request,
                        _('Tu cuenta de Google ha sido vinculada exitosamente.')
                    )
                
            except User.DoesNotExist:
                pass  # El usuario no existe, se creará automáticamente
    
    def save_user(self, request, sociallogin, form=None):
        """
        Personalizar creación de usuario desde datos sociales
        """
        user = super().save_user(request, sociallogin, form)
        
        # Completar información del usuario desde Google
        extra_data = sociallogin.account.extra_data
        
        # Obtener información básica
        if not user.first_name and extra_data.get('given_name'):
            user.first_name = extra_data.get('given_name', '')
        
        if not user.last_name and extra_data.get('family_name'):
            user.last_name = extra_data.get('family_name', '')
        
        # Generar username si no tiene
        if not user.username:
            user.username = self._generate_username(
                user.first_name or 'Usuario',
                user.last_name or 'Google',
                user.email
            )
        
        # Establecer valores por defecto para campos requeridos
        if not user.document_number:
            # Generar un documento temporal basado en el ID de Google
            google_id = extra_data.get('id', '')
            if google_id:
                user.document_number = f"GOOGLE{google_id[-6:]}"  # Últimos 6 dígitos
        
        # Los usuarios de OAuth van directamente a pendiente de aprobación
        # (a menos que sean automáticamente aprobados)
        if not user.is_superuser and not user.is_system_admin:
            user.approval_status = 'pending'
        
        user.save()
        
        # Crear o actualizar perfil
        profile, created = UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'theme': 'light',
                'email_notifications': True,
                'system_notifications': True,
            }
        )
        
        # Guardar foto de perfil si está disponible
        if extra_data.get('picture') and not user.avatar:
            try:
                self._save_avatar_from_url(user, extra_data['picture'])
            except Exception:
                pass  # No fallar si no se puede guardar la imagen
        
        return user
    
    def _generate_username(self, first_name, last_name, email):
        """
        Generar username único basado en nombre y email
        """
        # Crear username base
        base_username = f"{first_name.lower()}_{last_name.lower()}"
        base_username = base_username.replace(' ', '_')
        
        # Si no es válido, usar parte del email
        if not base_username or len(base_username) < 3:
            base_username = email.split('@')[0]
        
        # Asegurar unicidad
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1
        
        return username
    
    def _save_avatar_from_url(self, user, picture_url):
        """
        Guardar avatar desde URL de Google
        """
        import requests
        from django.core.files.base import ContentFile
        
        try:
            response = requests.get(picture_url, timeout=10)
            if response.status_code == 200:
                # Generar nombre único para el archivo
                file_name = f"google_{user.id}.jpg"
                
                # Guardar archivo
                file_content = ContentFile(response.content)
                user.avatar.save(file_name, file_content, save=True)
                
        except Exception as e:
            # Log del error pero no fallar el proceso
            print(f"Error saving avatar from Google: {e}")
    
def get_login_redirect_url(self, request):
    """
    Personalizar redirección después del login
    """
    user = request.user
    
    # NUEVA VERIFICACIÓN PARA ADMIN/STAFF
    if user.is_staff or user.is_superuser:
        return '/admin-panel/'
    
    # Verificar estado de aprobación del usuario
    if user.is_pending_approval():
        return '/accounts/waiting-room/'
    elif user.is_rejected():
        return '/accounts/account-rejected/'
    
    # Usuario aprobado - redirigir al dashboard
    return '/'
    
    def is_auto_signup_allowed(self, request, sociallogin):
        """
        Determinar si se permite el registro automático
        """
        # Permitir registro automático solo si está habilitado
        return getattr(settings, 'SOCIALACCOUNT_AUTO_SIGNUP', True)
    
    def populate_user(self, request, sociallogin, data):
        """
        Poblar datos del usuario desde la cuenta social
        """
        user = super().populate_user(request, sociallogin, data)
        
        # Datos adicionales específicos de Google
        extra_data = sociallogin.account.extra_data
        
        # Verificar si el email está verificado en Google
        if extra_data.get('email_verified', False):
            user.email = extra_data.get('email', user.email)
        
        # Información adicional
        if extra_data.get('locale'):
            # Mapear locale de Google a idiomas soportados
            locale_map = {
                'es': 'es',
                'es-ES': 'es',
                'es-EC': 'es',
                'en': 'en',
                'en-US': 'en',
                'en-GB': 'en',
            }
            user.language = locale_map.get(extra_data['locale'], 'es')
        
        return user
    
    def authentication_error(self, request, provider_id, error=None, exception=None, extra_context=None):
        """
        Manejar errores de autenticación OAuth
        """
        # Agregar mensaje de error personalizado
        messages.error(
            request,
            _('Ha ocurrido un error al iniciar sesión con Google. Inténtalo de nuevo.')
        )
        
        # Redirigir al login
        return redirect('/accounts/login/')
    
    def get_app(self, request, provider, config=None):
        """
        Obtener la aplicación social configurada
        """
        try:
            return super().get_app(request, provider, config)
        except:
            # Si no hay app configurada, mostrar error amigable
            messages.error(
                request,
                _('La autenticación con Google no está configurada correctamente. Contacta al administrador.')
            )
            return None