# -*- coding: utf-8 -*-
"""
Admin para certificados digitales - CORREGIDO para llenar automáticamente
"""

from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages
from django import forms
from django.utils import timezone
import uuid
from .models import DigitalCertificate, CertificateUsageLog


class DigitalCertificateAdminForm(forms.ModelForm):
    """Formulario que EXCLUYE campos automáticos"""
    
    password = forms.CharField(
        label='Contraseña del Certificado',
        widget=forms.PasswordInput(attrs={
            'class': 'vTextField',
            'placeholder': 'Ingresa la contraseña del P12'
        }),
        required=True,  # SIEMPRE requerida para nuevos
        help_text='Contraseña del archivo P12 (requerida)'
    )
    
    confirm_password = forms.CharField(
        label='Confirmar Contraseña',
        widget=forms.PasswordInput(attrs={
            'class': 'vTextField',
            'placeholder': 'Confirma la contraseña'
        }),
        required=True,  # SIEMPRE requerida para nuevos
        help_text='Vuelve a escribir la contraseña para confirmar'
    )
    
    extract_real_info = forms.BooleanField(
        label='Extraer información real del certificado',
        required=False,
        initial=True,
        help_text='✅ Marcado: Lee información real del P12. ❌ Desmarcado: Usa valores por defecto.'
    )
    
    class Meta:
        model = DigitalCertificate
        # EXCLUIR todos los campos que se llenan automáticamente
        exclude = [
            'password_hash',      # Se calcula del password
            'subject_name',       # Se extrae del P12
            'issuer_name',        # Se extrae del P12
            'serial_number',      # Se extrae del P12
            'valid_from',         # Se extrae del P12
            'valid_to',           # Se extrae del P12
            'fingerprint',        # Se extrae del P12
        ]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Si es edición, hacer contraseña opcional
        if self.instance and self.instance.pk:
            self.fields['password'].required = False
            self.fields['confirm_password'].required = False
            self.fields['password'].help_text = 'Dejar vacío para mantener contraseña actual'
            self.fields['confirm_password'].help_text = 'Solo si cambias la contraseña'
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        certificate_file = cleaned_data.get('certificate_file')
        
        # Para nuevos certificados, contraseña es obligatoria
        if not self.instance.pk:  # Nuevo certificado
            if not certificate_file:
                raise forms.ValidationError('Debes subir un archivo de certificado P12')
            
            if not password:
                raise forms.ValidationError('La contraseña es requerida para nuevos certificados')
        
        # Si hay contraseña, debe confirmarse
        if password:
            if not confirm_password:
                raise forms.ValidationError({
                    'confirm_password': 'Debes confirmar la contraseña'
                })
            if password != confirm_password:
                raise forms.ValidationError({
                    'confirm_password': 'Las contraseñas no coinciden'
                })
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Configurar campos MÍNIMOS requeridos por el modelo
        now = timezone.now()
        
        if not instance.subject_name:
            instance.subject_name = f'Procesando certificado - {instance.company.business_name}'
        
        if not instance.issuer_name:
            instance.issuer_name = 'Procesando información del emisor...'
        
        if not instance.serial_number:
            instance.serial_number = f'temp_{uuid.uuid4().hex[:16]}'
        
        if not instance.valid_from:
            instance.valid_from = now
        
        if not instance.valid_to:
            instance.valid_to = now + timezone.timedelta(days=365)
        
        if not instance.fingerprint:
            instance.fingerprint = f'temp_{uuid.uuid4().hex[:32]}'
        
        # Configurar contraseña si se proporciona
        password = self.cleaned_data.get('password')
        if password:
            instance.set_password(password)
        
        if commit:
            # GUARDAR PRIMERO con valores temporales
            instance.save()
            
            # LUEGO intentar extraer información real
            extract_real_info = self.cleaned_data.get('extract_real_info', True)
            if extract_real_info and password and instance.certificate_file:
                try:
                    success = instance.extract_real_certificate_info(password)
                    if success:
                        instance._extracted_real_info = True
                        # Recargar el objeto para mostrar los nuevos datos
                        instance.refresh_from_db()
                    else:
                        instance._extraction_failed = True
                except Exception as e:
                    instance._extraction_failed = True
                    print(f'Error extracting certificate info: {e}')
        
        return instance


@admin.register(DigitalCertificate)
class DigitalCertificateAdmin(admin.ModelAdmin):
    """Admin que maneja extracción automática"""
    
    form = DigitalCertificateAdminForm
    
    list_display = [
        'company',
        'subject_name_display',
        'environment',
        'status_colored',
        'password_status',
        'file_status',
        'info_source',
        'created_at'
    ]
    
    list_filter = [
        'status',
        'environment',
        'created_at'
    ]
    
    search_fields = [
        'company__business_name',
        'company__ruc',
        'subject_name',
        'issuer_name'
    ]
    
    # TODOS los campos automáticos como READONLY
    readonly_fields = [
        'subject_name_readonly',
        'issuer_name_readonly',
        'serial_number_readonly',
        'valid_from_readonly',
        'valid_to_readonly',
        'fingerprint_readonly',
        'file_info',
        'password_info',
        'certificate_details',
        'created_at',
        'updated_at'
    ]
    
    ordering = ['-created_at']
    
    fieldsets = (
        ('📋 Información Básica', {
            'fields': (
                'company',
                'environment',
                'status',
            ),
            'description': 'Información básica del certificado'
        }),
        ('📄 Subir Certificado P12', {
            'fields': (
                'certificate_file',
                'password',
                'confirm_password',
                'extract_real_info',
                'file_info',
            ),
            'description': '🔥 IMPORTANTE: Solo necesitas subir el archivo P12 y su contraseña. El resto se llena automáticamente.'
        }),
        ('🔐 Estado de la Contraseña', {
            'fields': (
                'password_info',
            ),
            'description': 'Estado actual de la contraseña del certificado'
        }),
        ('📜 Información Extraída del Certificado (Solo Lectura)', {
            'fields': (
                'subject_name_readonly',
                'issuer_name_readonly',
                'serial_number_readonly',
                'valid_from_readonly',
                'valid_to_readonly',
                'fingerprint_readonly',
                'certificate_details',
            ),
            'classes': ('collapse',),
            'description': '📊 Esta información se extrae automáticamente del certificado P12 usando cryptography'
        }),
        ('📅 Metadatos', {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',)
        }),
    )
    
    def subject_name_readonly(self, obj):
        """Subject name como readonly"""
        return obj.subject_name or 'No disponible'
    subject_name_readonly.short_description = 'Subject Name'
    
    def issuer_name_readonly(self, obj):
        """Issuer name como readonly"""
        return obj.issuer_name or 'No disponible'
    issuer_name_readonly.short_description = 'Issuer Name'
    
    def serial_number_readonly(self, obj):
        """Serial number como readonly"""
        return obj.serial_number or 'No disponible'
    serial_number_readonly.short_description = 'Serial Number'
    
    def valid_from_readonly(self, obj):
        """Valid from como readonly"""
        if obj.valid_from:
            try:
                return obj.valid_from.strftime('%d/%m/%Y %H:%M:%S')
            except:
                return str(obj.valid_from)
        return 'No disponible'
    valid_from_readonly.short_description = 'Válido Desde'
    
    def valid_to_readonly(self, obj):
        """Valid to como readonly"""
        if obj.valid_to:
            try:
                return obj.valid_to.strftime('%d/%m/%Y %H:%M:%S')
            except:
                return str(obj.valid_to)
        return 'No disponible'
    valid_to_readonly.short_description = 'Válido Hasta'
    
    def fingerprint_readonly(self, obj):
        """Fingerprint como readonly"""
        return obj.fingerprint or 'No disponible'
    fingerprint_readonly.short_description = 'Fingerprint'
    
    def subject_name_display(self, obj):
        """Nombre del subject con indicador de fuente"""
        name = obj.subject_name or 'Sin nombre'
        if 'CN=' in name and not name.startswith('Procesando'):
            # Información real extraída
            return format_html('<span style="color: #0066cc; font-weight: bold;" title="Información extraída del certificado">{}</span>', name[:50] + ('...' if len(name) > 50 else ''))
        else:
            # Información temporal o por defecto
            return format_html('<span style="color: #666;" title="Información temporal/por defecto">{}</span>', name[:40] + ('...' if len(name) > 40 else ''))
    
    subject_name_display.short_description = 'Subject Name'
    
    def status_colored(self, obj):
        """Estado con color"""
        colors = {
            'ACTIVE': 'green',
            'EXPIRED': 'red',
            'REVOKED': 'red',
            'INACTIVE': 'orange'
        }
        
        color = colors.get(obj.status, 'black')
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    
    status_colored.short_description = 'Estado'
    
    def password_status(self, obj):
        """Estado de la contraseña"""
        if obj.password_hash and obj.password_hash != 'temp_hash':
            return format_html('<span style="color: green; font-weight: bold;">🔐</span>')
        else:
            return format_html('<span style="color: red; font-weight: bold;">❌</span>')
    
    password_status.short_description = 'Pass'
    
    def file_status(self, obj):
        """Estado del archivo"""
        if obj.certificate_file:
            try:
                obj.certificate_file.size
                return format_html('<span style="color: green; font-weight: bold;">📄</span>')
            except Exception:
                return format_html('<span style="color: orange; font-weight: bold;">⚠️</span>')
        else:
            return format_html('<span style="color: red; font-weight: bold;">❌</span>')
    
    file_status.short_description = 'Archivo'
    
    def info_source(self, obj):
        """Fuente de la información"""
        if 'CN=' in (obj.subject_name or '') and not (obj.subject_name or '').startswith('Procesando'):
            return format_html('<span style="color: green; font-weight: bold;" title="Información extraída del certificado real">📜 Real</span>')
        else:
            return format_html('<span style="color: gray;" title="Información temporal">📝 Temp</span>')
    
    info_source.short_description = 'Fuente'
    
    def file_info(self, obj):
        """Información del archivo"""
        if obj.certificate_file:
            try:
                size_kb = obj.certificate_file.size / 1024
                filename = obj.certificate_file.name.split('/')[-1]
                
                created_str = 'Fecha desconocida'
                if obj.created_at:
                    try:
                        created_str = obj.created_at.strftime('%d/%m/%Y %H:%M')
                    except Exception:
                        created_str = str(obj.created_at)
                
                info_html = '''
                <div style="background: #f0f8ff; padding: 12px; border-radius: 6px; border-left: 4px solid #0066cc;">
                    <strong>📄 Archivo P12 Cargado</strong><br>
                    <strong>Nombre:</strong> {}<br>
                    <strong>Tamaño:</strong> {:.1f} KB<br>
                    <strong>Subido:</strong> {}<br>
                    <span style="color: green; font-weight: bold;">✅ Listo para procesar</span>
                </div>
                '''.format(filename, size_kb, created_str)
                
                return format_html(info_html)
                
            except Exception as e:
                error_html = '''
                <div style="background: #ffe6e6; padding: 12px; border-radius: 6px; border-left: 4px solid #dc3545;">
                    <strong>❌ Error leyendo archivo</strong><br>
                    {}
                </div>
                '''.format(str(e))
                
                return format_html(error_html)
        else:
            no_file_html = '''
            <div style="background: #f5f5f5; padding: 12px; border-radius: 6px; border-left: 4px solid #6c757d;">
                <strong>📄 Sin archivo de certificado</strong><br>
                Selecciona un archivo P12 arriba para comenzar
            </div>
            '''
            
            return format_html(no_file_html)
    
    file_info.short_description = 'Estado del Archivo'
    
    def password_info(self, obj):
        """Información de la contraseña"""
        if obj.password_hash and obj.password_hash != 'temp_hash':
            hash_preview = obj.password_hash[:16] + '...'
            
            configured_html = '''
            <div style="background: #e8f5e8; padding: 12px; border-radius: 6px; border-left: 4px solid #28a745;">
                <strong>🔐 Contraseña configurada correctamente</strong><br>
                <strong>Método:</strong> PBKDF2 con 100,000 iteraciones<br>
                <strong>Salt:</strong> RUC de la empresa<br>
                <strong>Hash:</strong> {}<br>
                <span style="color: green; font-weight: bold;">✅ Almacenada de forma segura</span>
            </div>
            '''.format(hash_preview)
            
            return format_html(configured_html)
        else:
            not_configured_html = '''
            <div style="background: #f8d7da; padding: 12px; border-radius: 6px; border-left: 4px solid #dc3545;">
                <strong>❌ Contraseña no configurada</strong><br>
                Configure la contraseña del certificado P12 en los campos de arriba.<br>
                <span style="color: #721c24;">⚠️ La contraseña es necesaria para extraer información y usar el certificado.</span>
            </div>
            '''
            
            return format_html(not_configured_html)
    
    password_info.short_description = 'Estado de la Contraseña'
    
    def certificate_details(self, obj):
        """Detalles del certificado"""
        if 'CN=' in (obj.subject_name or '') and not (obj.subject_name or '').startswith('Procesando'):
            # Información extraída real
            details_html = '''
            <div style="background: #e8f4fd; padding: 12px; border-radius: 6px; border-left: 4px solid #0066cc;">
                <strong>📜 Información extraída exitosamente del certificado P12</strong><br>
                <strong>Subject:</strong> {}<br>
                <strong>Issuer:</strong> {}<br>
                <strong>Serial:</strong> {}<br>
                <strong>Válido desde:</strong> {}<br>
                <strong>Válido hasta:</strong> {}<br>
                <strong>Fingerprint:</strong> {}<br>
                <span style="color: #0066cc; font-weight: bold;">✅ Datos verificados usando cryptography</span>
            </div>
            '''.format(
                obj.subject_name or 'N/A',
                obj.issuer_name or 'N/A',
                obj.serial_number or 'N/A',
                obj.valid_from.strftime('%d/%m/%Y %H:%M') if obj.valid_from else 'N/A',
                obj.valid_to.strftime('%d/%m/%Y %H:%M') if obj.valid_to else 'N/A',
                obj.fingerprint or 'N/A'
            )
        elif (obj.subject_name or '').startswith('Procesando'):
            # Está procesando
            details_html = '''
            <div style="background: #fff3cd; padding: 12px; border-radius: 6px; border-left: 4px solid #856404;">
                <strong>⏳ Procesando certificado...</strong><br>
                La información se extraerá automáticamente al guardar con la contraseña correcta.<br>
                <span style="color: #856404;">🔍 Asegúrate de marcar "Extraer información real" y proporcionar la contraseña.</span>
            </div>
            '''
        else:
            # Información por defecto
            details_html = '''
            <div style="background: #f8f9fa; padding: 12px; border-radius: 6px; border-left: 4px solid #6c757d;">
                <strong>📝 Usando información por defecto</strong><br>
                Para obtener información real del certificado:<br>
                1. ✅ Marca "Extraer información real del certificado"<br>
                2. 🔑 Proporciona la contraseña correcta del P12<br>
                3. 💾 Guarda el certificado<br>
                <span style="color: #6c757d;">🔬 Los datos se extraerán automáticamente usando cryptography</span>
            </div>
            '''
        
        return format_html(details_html)
    
    certificate_details.short_description = 'Detalles del Certificado'
    
    def save_model(self, request, obj, form, change):
        """Guardar modelo con mensajes informativos"""
        try:
            super().save_model(request, obj, form, change)
            
            # Mensajes según lo que pasó
            password_provided = form.cleaned_data.get('password')
            extract_real_info = form.cleaned_data.get('extract_real_info', True)
            
            if password_provided and extract_real_info:
                if hasattr(obj, '_extracted_real_info'):
                    self.message_user(
                        request,
                        '🎉 ¡Éxito! Certificado guardado e información real extraída del P12.',
                        level=messages.SUCCESS
                    )
                elif hasattr(obj, '_extraction_failed'):
                    self.message_user(
                        request,
                        '⚠️ Certificado guardado pero no se pudo extraer información real. Verifica que la contraseña sea correcta.',
                        level=messages.WARNING
                    )
                else:
                    self.message_user(
                        request,
                        '✅ Certificado guardado con contraseña configurada.',
                        level=messages.SUCCESS
                    )
            elif password_provided:
                self.message_user(
                    request,
                    '✅ Certificado guardado con contraseña. Información por defecto usada.',
                    level=messages.SUCCESS
                )
            else:
                if change:
                    self.message_user(
                        request,
                        '✅ Certificado actualizado exitosamente.',
                        level=messages.SUCCESS
                    )
                else:
                    self.message_user(
                        request,
                        '⚠️ Certificado guardado pero sin contraseña configurada.',
                        level=messages.WARNING
                    )
        except Exception as e:
            self.message_user(
                request,
                '❌ Error guardando certificado: {}'.format(str(e)),
                level=messages.ERROR
            )


@admin.register(CertificateUsageLog)
class CertificateUsageLogAdmin(admin.ModelAdmin):
    """Admin para logs de uso de certificados"""
    
    list_display = [
        'fecha_formatted',
        'certificate_info',
        'operation',
        'document_number',
        'result_icon',
        'ip_address'
    ]
    
    list_filter = [
        'operation',
        'success',
        'created_at'
    ]
    
    search_fields = [
        'certificate__company__business_name',
        'certificate__subject_name',
        'document_number',
        'operation'
    ]
    
    readonly_fields = [
        'certificate',
        'operation',
        'document_type',
        'document_number',
        'success',
        'error_message',
        'ip_address',
        'created_at'
    ]
    
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    
    def fecha_formatted(self, obj):
        """Fecha formateada de forma segura"""
        if obj.created_at:
            try:
                return obj.created_at.strftime('%d/%m/%Y %H:%M')
            except Exception:
                return str(obj.created_at)
        return 'Sin fecha'
    
    fecha_formatted.short_description = 'Fecha'
    
    def certificate_info(self, obj):
        """Información del certificado"""
        company_name = obj.certificate.company.business_name
        subject_name = obj.certificate.subject_name
        
        # Truncar subject si es muy largo
        if len(subject_name) > 50:
            subject_display = subject_name[:47] + '...'
        else:
            subject_display = subject_name
        
        return format_html(
            '<strong>{}</strong><br><small style="color: gray;">{}</small>',
            company_name,
            subject_display
        )
    
    certificate_info.short_description = 'Certificado'
    
    def result_icon(self, obj):
        """Icono del resultado"""
        if obj.success:
            return format_html(
                '<span style="color: green; font-weight: bold; font-size: 14px;">✅</span>'
            )
        else:
            error_preview = ''
            if obj.error_message:
                if len(obj.error_message) > 50:
                    error_preview = obj.error_message[:47] + '...'
                else:
                    error_preview = obj.error_message
            
            return format_html(
                '<span style="color: red; font-weight: bold; font-size: 14px;" title="{}">❌</span>',
                error_preview
            )
    
    result_icon.short_description = 'Resultado'
    
    def has_add_permission(self, request):
        """No permitir agregar logs manualmente"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """No permitir editar logs"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Solo superusuarios pueden eliminar logs"""
        return request.user.is_superuser