# apps/companies/forms.py
from django import forms
from django.core.exceptions import ValidationError
from .models import Company
from certificates.models import DigitalCertificate
import re


class CompanyEditForm(forms.ModelForm):
    """Formulario para editar información de la empresa"""
    
    class Meta:
        model = Company
        fields = [
            'business_name', 'trade_name', 'email', 'phone', 'address',
            'ciudad', 'provincia', 'codigo_postal', 'website',
            'tipo_contribuyente', 'obligado_contabilidad', 'contribuyente_especial',
            'codigo_establecimiento', 'codigo_punto_emision', 'ambiente_sri',
            'tipo_emision', 'logo'
        ]
        
        widgets = {
            'business_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Razón Social'
            }),
            'trade_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre Comercial (opcional)'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'correo@empresa.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+593 99 999 9999'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Dirección completa'
            }),
            'ciudad': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ciudad'
            }),
            'provincia': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Provincia'
            }),
            'codigo_postal': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Código Postal'
            }),
            'website': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://www.empresa.com'
            }),
            'tipo_contribuyente': forms.Select(attrs={
                'class': 'form-select'
            }),
            'obligado_contabilidad': forms.Select(attrs={
                'class': 'form-select'
            }),
            'contribuyente_especial': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Número (si aplica)',
                'maxlength': '5'
            }),
            'codigo_establecimiento': forms.TextInput(attrs={
                'class': 'form-control',
                'pattern': '[0-9]{3}',
                'maxlength': '3',
                'placeholder': '001'
            }),
            'codigo_punto_emision': forms.TextInput(attrs={
                'class': 'form-control',
                'pattern': '[0-9]{3}',
                'maxlength': '3',
                'placeholder': '001'
            }),
            'ambiente_sri': forms.Select(attrs={
                'class': 'form-select'
            }),
            'tipo_emision': forms.Select(attrs={
                'class': 'form-select'
            }),
            'logo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            })
        }
    
    def clean_codigo_establecimiento(self):
        codigo = self.cleaned_data.get('codigo_establecimiento')
        if codigo and not re.match(r'^\d{3}$', codigo):
            raise ValidationError('El código debe tener exactamente 3 dígitos.')
        return codigo
    
    def clean_codigo_punto_emision(self):
        codigo = self.cleaned_data.get('codigo_punto_emision')
        if codigo and not re.match(r'^\d{3}$', codigo):
            raise ValidationError('El código debe tener exactamente 3 dígitos.')
        return codigo
    
    def clean_contribuyente_especial(self):
        numero = self.cleaned_data.get('contribuyente_especial')
        if numero and len(numero) > 5:
            raise ValidationError('El número no puede tener más de 5 dígitos.')
        return numero


class CertificateUploadForm(forms.Form):
    """Formulario para subir certificado digital"""
    
    certificate_file = forms.FileField(
        label='Archivo de Certificado',
        help_text='Seleccione archivo .p12 o .pfx',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.p12,.pfx'
        })
    )
    
    certificate_password = forms.CharField(
        label='Contraseña del Certificado',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Contraseña del certificado'
        })
    )
    
    alias = forms.CharField(
        label='Alias (opcional)',
        required=False,
        help_text='Nombre descriptivo para el certificado',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: Certificado Principal'
        })
    )
    
    def clean_certificate_file(self):
        file = self.cleaned_data.get('certificate_file')
        if file:
            # Validar extensión
            if not file.name.lower().endswith(('.p12', '.pfx')):
                raise ValidationError('Solo se permiten archivos .p12 o .pfx')
            
            # Validar tamaño (máximo 5MB)
            if file.size > 5 * 1024 * 1024:
                raise ValidationError('El archivo no puede superar los 5MB')
        
        return file