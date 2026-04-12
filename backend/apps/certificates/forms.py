# -*- coding: utf-8 -*-
"""
Formularios para certificados digitales - CORREGIDO
"""

from django import forms
from django.core.exceptions import ValidationError
from .models import DigitalCertificate


class CertificatePasswordForm(forms.Form):
    """Formulario para configurar contraseña del certificado"""
    
    password = forms.CharField(
        label='Contraseña del Certificado',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ingresa la contraseña del certificado P12',
            'autocomplete': 'new-password'
        }),
        help_text='Esta es la contraseña que usaste al crear el certificado P12',
        min_length=1,
        max_length=100
    )
    
    def clean_password(self):
        """Validar contraseña"""
        password = self.cleaned_data.get('password')
        if not password:
            raise ValidationError('La contraseña es requerida')
        return password


class CertificateUploadForm(forms.ModelForm):
    """Formulario para subir certificado con contraseña"""
    
    certificate_file = forms.FileField(
        label='Archivo del Certificado',
        help_text='Selecciona el archivo .p12 del certificado digital',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.p12'
        })
    )
    
    password = forms.CharField(
        label='Contraseña del Certificado',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Contraseña del archivo P12',
            'autocomplete': 'new-password'
        }),
        help_text='Contraseña que protege el archivo del certificado',
        min_length=1,
        max_length=100
    )
    
    confirm_password = forms.CharField(
        label='Confirmar Contraseña',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirma la contraseña',
            'autocomplete': 'new-password'
        }),
        help_text='Vuelve a escribir la contraseña para confirmar',
        min_length=1,
        max_length=100
    )
    
    class Meta:
        model = DigitalCertificate
        fields = ['company', 'environment', 'certificate_file']
        widgets = {
            'company': forms.Select(attrs={
                'class': 'form-control'
            }),
            'environment': forms.Select(attrs={
                'class': 'form-control'
            })
        }
        help_texts = {
            'company': 'Empresa propietaria del certificado',
            'environment': 'Ambiente SRI donde se usará el certificado'
        }
    
    def clean_certificate_file(self):
        """Validar archivo de certificado"""
        file = self.cleaned_data.get('certificate_file')
        
        if file:
            # Validar extensión
            if not file.name.lower().endswith('.p12'):
                raise ValidationError('El archivo debe tener extensión .p12')
            
            # Validar tamaño (máximo 5MB)
            if file.size > 5 * 1024 * 1024:
                raise ValidationError('El archivo no puede ser mayor a 5MB')
            
            # Validar que no esté vacío
            if file.size == 0:
                raise ValidationError('El archivo está vacío')
        
        return file
    
    def clean(self):
        """Validación general del formulario"""
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        certificate_file = cleaned_data.get('certificate_file')
        
        # Validar que las contraseñas coincidan
        if password and confirm_password and password != confirm_password:
            raise ValidationError({
                'confirm_password': 'Las contraseñas no coinciden'
            })
        
        # Validar que hay archivo y contraseña
        if certificate_file and not password:
            raise ValidationError({
                'password': 'La contraseña es requerida cuando se sube un certificado'
            })
        
        return cleaned_data
    
    def save(self, commit=True):
        """Guardar certificado con contraseña"""
        instance = super().save(commit=False)
        
        if commit:
            # Guardar primero la instancia
            instance.save()
            
            # Configurar contraseña si se proporcionó
            password = self.cleaned_data.get('password')
            if password:
                instance.set_password(password)
                instance.save()
        
        return instance


class CertificateTestForm(forms.Form):
    """Formulario para probar certificado"""
    
    password = forms.CharField(
        label='Contraseña para Prueba',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ingresa la contraseña del certificado',
            'autocomplete': 'current-password'
        }),
        help_text='Contraseña para verificar que el certificado funciona correctamente'
    )
    
    def __init__(self, certificate=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.certificate = certificate
    
    def clean_password(self):
        """Validar contraseña contra el certificado"""
        password = self.cleaned_data.get('password')
        
        if self.certificate and password:
            try:
                if not self.certificate.verify_password(password):
                    raise ValidationError('Contraseña incorrecta para este certificado')
            except Exception as e:
                raise ValidationError(f'Error validando contraseña: {str(e)}')
        
        return password


class CertificateUpdateForm(forms.ModelForm):
    """Formulario para actualizar certificado"""
    
    class Meta:
        model = DigitalCertificate
        fields = ['status', 'environment']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-control'}),
            'environment': forms.Select(attrs={'class': 'form-control'})
        }
        help_texts = {
            'status': 'Estado actual del certificado',
            'environment': 'Ambiente SRI donde se usa'
        }