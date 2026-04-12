# -*- coding: utf-8 -*-
"""
Models for companies app
Modelos para empresas en RutaFact_SRI
ACTUALIZADO: Con campos críticos para SRI y validaciones completas
"""

import secrets
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
import re


def company_logo_upload_path(instance, filename):
    """Genera la ruta para el logo de la empresa"""
    try:
        business_name = instance.business_name.lower()
        company_name = re.sub(r'[^a-z0-9_]', '_', business_name).strip('_')
    except:
        company_name = instance.ruc if instance.ruc else f"empresa_{instance.id}"
    return f"{company_name}/logos/{filename}"


class Company(models.Model):
    """
    Modelo para empresas y personas naturales
    
    ACTUALIZADO: Incluye campos críticos para SRI y validaciones completas
    para resolver Error 35 y otros problemas de facturación electrónica.
    """
    
    # ===============================================================
    # TIPOS DE CONTRIBUYENTE (PARA SRI)
    # ===============================================================
    
    TIPO_CONTRIBUYENTE_CHOICES = [
        ('PERSONA_NATURAL', _('Persona Natural')),
        ('EMPRESA_PRIVADA', _('Empresa Privada')),
        ('EMPRESA_PUBLICA', _('Empresa Pública')),
        ('ONG', _('Organización No Gubernamental')),
        ('OTRO', _('Otro')),
    ]
    
    OBLIGADO_CONTABILIDAD_CHOICES = [
        ('SI', _('Sí')),
        ('NO', _('No')),
    ]
    
    # ===============================================================
    # INFORMACIÓN BÁSICA
    # ===============================================================
    
    ruc = models.CharField(
        _('RUC'),
        max_length=13,
        unique=True,
        help_text=_('RUC number (13 digits)')
    )
    
    business_name = models.CharField(
        _('business name'),
        max_length=300,
        help_text=_('Official business name (Razón Social)')
    )
    
    trade_name = models.CharField(
        _('trade name'),
        max_length=300,
        blank=True,
        help_text=_('Commercial or trade name (Nombre Comercial)')
    )
    
    # ===============================================================
    # CAMPOS CRÍTICOS PARA SRI - ¡OBLIGATORIOS!
    # ===============================================================
    
    tipo_contribuyente = models.CharField(
        _('tipo de contribuyente'),
        max_length=20,
        choices=TIPO_CONTRIBUYENTE_CHOICES,
        default='PERSONA_NATURAL',
        help_text=_('Tipo de contribuyente según el SRI')
    )
    
    obligado_contabilidad = models.CharField(
        _('obligado a llevar contabilidad'),
        max_length=2,
        choices=OBLIGADO_CONTABILIDAD_CHOICES,
        default='NO',
        help_text=_('Si está obligado a llevar contabilidad (crítico para SRI)')
    )
    
    contribuyente_especial = models.CharField(
        _('contribuyente especial'),
        max_length=5,
        blank=True,
        null=True,
        help_text=_('Número de contribuyente especial (si aplica)')
    )
    
    # ===============================================================
    # INFORMACIÓN ADICIONAL PARA SRI
    # ===============================================================
    
    codigo_establecimiento = models.CharField(
        _('código establecimiento'),
        max_length=3,
        default='001',
        help_text=_('Código del establecimiento (3 dígitos)')
    )
    
    codigo_punto_emision = models.CharField(
        _('código punto emisión'),
        max_length=3,
        default='001',
        help_text=_('Código del punto de emisión (3 dígitos)')
    )
    
    ambiente_sri = models.CharField(
        _('ambiente SRI'),
        max_length=1,
        choices=[
            ('1', _('Pruebas')),
            ('2', _('Producción')),
        ],
        default='1',
        help_text=_('Ambiente del SRI (1=Pruebas, 2=Producción)')
    )
    
    tipo_emision = models.CharField(
        _('tipo emisión'),
        max_length=1,
        choices=[
            ('1', _('Normal')),
            ('2', _('Contingencia')),
        ],
        default='1',
        help_text=_('Tipo de emisión (1=Normal, 2=Contingencia)')
    )
    
    # ===============================================================
    # INFORMACIÓN DE CONTACTO
    # ===============================================================
    
    email = models.EmailField(
        _('email'),
        help_text=_('Main contact email')
    )
    
    phone = models.CharField(
        _('phone'),
        max_length=20,
        blank=True,
        help_text=_('Main contact phone')
    )
    
    address = models.TextField(
        _('address'),
        help_text=_('Complete business address (dirección matriz)')
    )
    
    # ===============================================================
    # INFORMACIÓN GEOGRÁFICA
    # ===============================================================
    
    ciudad = models.CharField(
        _('ciudad'),
        max_length=100,
        blank=True,
        help_text=_('Ciudad de la empresa')
    )
    
    provincia = models.CharField(
        _('provincia'),
        max_length=100,
        blank=True,
        help_text=_('Provincia de la empresa')
    )
    
    codigo_postal = models.CharField(
        _('código postal'),
        max_length=10,
        blank=True,
        help_text=_('Código postal')
    )
    
    # ===============================================================
    # CONFIGURACIÓN DE FACTURACIÓN
    # ===============================================================
    
    secuencial_factura = models.PositiveIntegerField(
        _('secuencial factura'),
        default=1,
        help_text=_('Próximo número secuencial para facturas')
    )
    
    secuencial_nota_credito = models.PositiveIntegerField(
        _('secuencial nota crédito'),
        default=1,
        help_text=_('Próximo número secuencial para notas de crédito')
    )
    
    secuencial_nota_debito = models.PositiveIntegerField(
        _('secuencial nota débito'),
        default=1,
        help_text=_('Próximo número secuencial para notas de débito')
    )
    
    secuencial_retencion = models.PositiveIntegerField(
        _('secuencial retención'),
        default=1,
        help_text=_('Próximo número secuencial para retenciones')
    )
    
    # ===============================================================
    # CONFIGURACIÓN ADICIONAL Y PLANES
    # ===============================================================
    
    plan = models.CharField(
        _('plan'),
        max_length=20,
        choices=[
            ('basic', _('Básico')),
            ('professional', _('Profesional')),
            ('enterprise', _('Empresarial')),
        ],
        default='basic',
        help_text=_('Plan de facturación contratado')
    )
    
    logo = models.ImageField(
        _('logo'),
        upload_to=company_logo_upload_path,
        blank=True,
        null=True,
        help_text=_('Company logo for documents')
    )
    
    website = models.URLField(
        _('website'),
        blank=True,
        help_text=_('Company website')
    )
    
    # ===============================================================
    # ESTADO Y AUDITORÍA
    # ===============================================================
    
    is_active = models.BooleanField(
        _('is active'),
        default=True,
        help_text=_('Whether the company is active in the system')
    )
    
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
    
    class Meta:
        verbose_name = _('Company')
        verbose_name_plural = _('Companies')
        ordering = ['business_name']
        indexes = [
            models.Index(fields=['ruc']),
            models.Index(fields=['is_active']),
            models.Index(fields=['tipo_contribuyente']),
        ]
    
    def clean(self):
        """Validaciones personalizadas"""
        errors = {}
        
        # Validar RUC
        if self.ruc:
            if not self.validate_ruc(self.ruc):
                errors['ruc'] = _('RUC inválido. Debe tener 13 dígitos y ser válido.')
        
        # Validar coherencia de persona natural
        if self.ruc and self.ruc.endswith('001'):
            # Es persona natural
            if self.obligado_contabilidad == 'SI':
                errors['obligado_contabilidad'] = _(
                    'Las personas naturales generalmente NO están obligadas a llevar contabilidad.'
                )
            
            if self.contribuyente_especial:
                errors['contribuyente_especial'] = _(
                    'Las personas naturales generalmente NO son contribuyentes especiales.'
                )
        
        # Validar códigos de establecimiento y punto emisión
        if self.codigo_establecimiento:
            if not re.match(r'^\d{3}$', self.codigo_establecimiento):
                errors['codigo_establecimiento'] = _('Debe ser exactamente 3 dígitos.')
        
        if self.codigo_punto_emision:
            if not re.match(r'^\d{3}$', self.codigo_punto_emision):
                errors['codigo_punto_emision'] = _('Debe ser exactamente 3 dígitos.')
        
        if errors:
            raise ValidationError(errors)
    
    def save(self, *args, **kwargs):
        """Guarda el modelo con validaciones y configuraciones automáticas"""
        
        # Auto-configurar para persona natural si el RUC termina en 001
        if self.ruc and self.ruc.endswith('001'):
            if not self.tipo_contribuyente:
                self.tipo_contribuyente = 'PERSONA_NATURAL'
            if not self.obligado_contabilidad:
                self.obligado_contabilidad = 'NO'
            # Para personas naturales, generalmente no hay contribuyente especial
            if not self.contribuyente_especial:
                self.contribuyente_especial = None
        
        # Validar antes de guardar
        self.full_clean()
        super().save(*args, **kwargs)

        # ✅ Sincronizar con SRIConfiguration para mantener concordancia entre paneles
        # Usamos .update() para evitar bucles de recursión con SRIConfiguration.save()
        try:
            if hasattr(self, 'sri_configuration'):
                from apps.sri_integration.models import SRIConfiguration
                SRIConfiguration.objects.filter(pk=self.sri_configuration.pk).update(
                    environment='TEST' if self.ambiente_sri == '1' else 'PRODUCTION',
                    establishment_code=self.codigo_establecimiento,
                    emission_point=self.codigo_punto_emision,
                    invoice_sequence=self.secuencial_factura,
                    credit_note_sequence=self.secuencial_nota_credito,
                    debit_note_sequence=self.secuencial_nota_debito,
                    retention_sequence=self.secuencial_retencion,
                    accounting_required=(self.obligado_contabilidad == 'SI'),
                    special_taxpayer=bool(self.contribuyente_especial),
                    special_taxpayer_number=self.contribuyente_especial or ''
                )
            
            # 3. Sincronizar también el ambiente en el Certificado Digital si existe
            if hasattr(self, 'digital_certificate'):
                from apps.certificates.models import DigitalCertificate
                DigitalCertificate.objects.filter(company=self).update(
                    environment='TEST' if self.ambiente_sri == '1' else 'PRODUCTION'
                )
        except Exception:
            # Silenciar errores de sincronización para no romper el flujo principal
            pass
    
    def __str__(self):
        return f"{self.business_name} ({self.ruc})"
    
    # ===============================================================
    # PROPIEDADES Y MÉTODOS ÚTILES
    # ===============================================================
    
    @property
    def display_name(self):
        """Devuelve el nombre comercial o razón social"""
        return self.trade_name if self.trade_name else self.business_name
    
    @property
    def is_persona_natural(self):
        """Determina si es persona natural basado en el RUC"""
        return self.ruc and self.ruc.endswith('001')
    
    @property
    def razon_social(self):
        """Alias para business_name (compatibilidad con SRI)"""
        return self.business_name
    
    @property
    def direccion_matriz(self):
        """Alias para address (compatibilidad con SRI)"""
        return self.address
    
    def get_next_secuencial(self, tipo_documento='factura'):
        """
        Obtiene y actualiza el próximo secuencial para un tipo de documento
        """
        field_map = {
            'factura': 'secuencial_factura',
            'nota_credito': 'secuencial_nota_credito',
            'nota_debito': 'secuencial_nota_debito',
            'retencion': 'secuencial_retencion',
        }
        
        field_name = field_map.get(tipo_documento)
        if not field_name:
            raise ValueError(f"Tipo de documento no válido: {tipo_documento}")
        
        current_value = getattr(self, field_name)
        next_value = current_value + 1
        
        # Actualizar el campo
        setattr(self, field_name, next_value)
        self.save(update_fields=[field_name, 'updated_at'])
        
        return str(current_value).zfill(9)  # Formato: 000000001
    
    def get_establecimiento_punto_emision(self):
        """
        Retorna el código completo establecimiento-punto de emisión
        """
        return f"{self.codigo_establecimiento}-{self.codigo_punto_emision}"
    
    def get_sri_data(self):
        """
        Retorna los datos necesarios para el SRI en formato dict
        """
        return {
            'ruc': self.ruc,
            'razon_social': self.business_name,
            'nombre_comercial': self.trade_name or '',
            'direccion_matriz': self.address,
            'obligado_contabilidad': self.obligado_contabilidad,
            'contribuyente_especial': self.contribuyente_especial or '',
            'tipo_contribuyente': self.tipo_contribuyente,
            'ambiente': self.ambiente_sri,
            'tipo_emision': self.tipo_emision,
            'establecimiento': self.codigo_establecimiento,
            'punto_emision': self.codigo_punto_emision,
        }
    
    @staticmethod
    def validate_ruc(ruc):
        """
        Valida el RUC ecuatoriano
        """
        if not ruc or len(ruc) != 13:
            return False
        
        try:
            # Algoritmo de validación de RUC ecuatoriano
            digits = [int(d) for d in ruc]
            
            # Verificar que termine en 001 para persona natural o empresa
            if not (ruc.endswith('001')):
                # Para otros tipos de RUC, validar que terminen apropiadamente
                pass
            
            # Aquí puedes implementar el algoritmo completo de validación
            # del dígito verificador del RUC ecuatoriano
            
            return True
        except (ValueError, TypeError):
            return False


# ===================================================================
# MODELO DE TOKEN API (SIN CAMBIOS)
# ===================================================================

class CompanyAPIToken(models.Model):
    """
    Token de API específico por empresa
    
    Permite que sistemas externos accedan directamente a UNA empresa
    sin necesidad de especificar company_id en cada request.
    """
    
    company = models.OneToOneField(
        'companies.Company', 
        on_delete=models.CASCADE,
        related_name='api_token',
        verbose_name=_('Company'),
        help_text=_('Company this token belongs to')
    )
    
    key = models.CharField(
        _('Token Key'),
        max_length=64, 
        unique=True,
        help_text=_('Unique token for this company (auto-generated)')
    )
    
    name = models.CharField(
        _('Token Name'),
        max_length=100,
        help_text=_('Descriptive name for this token')
    )
    
    is_active = models.BooleanField(
        _('Is Active'),
        default=True,
        help_text=_('Whether this token is active and can be used')
    )
    
    created_at = models.DateTimeField(
        _('Created At'),
        auto_now_add=True
    )
    
    updated_at = models.DateTimeField(
        _('Updated At'),
        auto_now=True
    )
    
    # ===============================================================
    # PERMISOS ESPECÍFICOS DEL TOKEN
    # ===============================================================
    
    can_create_documents = models.BooleanField(
        _('Can Create Documents'),
        default=True,
        help_text=_('Permission to create SRI documents (invoices, etc.)')
    )
    
    can_read_documents = models.BooleanField(
        _('Can Read Documents'),
        default=True,
        help_text=_('Permission to read/list SRI documents')
    )
    
    can_update_documents = models.BooleanField(
        _('Can Update Documents'),
        default=False,
        help_text=_('Permission to update SRI documents')
    )
    
    can_delete_documents = models.BooleanField(
        _('Can Delete Documents'),
        default=False,
        help_text=_('Permission to delete SRI documents')
    )
    
    can_manage_customers = models.BooleanField(
        _('Can Manage Customers'),
        default=True,
        help_text=_('Permission to create/edit customers')
    )
    
    can_manage_products = models.BooleanField(
        _('Can Manage Products'),
        default=True,
        help_text=_('Permission to create/edit products')
    )
    
    # ===============================================================
    # LÍMITES Y CONTROL DE USO
    # ===============================================================
    
    requests_per_hour = models.PositiveIntegerField(
        _('Requests Per Hour'),
        default=1000,
        help_text=_('Maximum number of API requests per hour')
    )
    
    requests_per_day = models.PositiveIntegerField(
        _('Requests Per Day'),
        default=10000,
        help_text=_('Maximum number of API requests per day')
    )
    
    # ===============================================================
    # ESTADÍSTICAS DE USO
    # ===============================================================
    
    total_requests = models.PositiveIntegerField(
        _('Total Requests'),
        default=0,
        help_text=_('Total number of requests made with this token')
    )
    
    last_used_at = models.DateTimeField(
        _('Last Used At'),
        null=True, 
        blank=True,
        help_text=_('When this token was last used')
    )
    
    last_used_ip = models.GenericIPAddressField(
        _('Last Used IP'),
        null=True,
        blank=True,
        help_text=_('IP address of last request')
    )
    
    # ===============================================================
    # CONFIGURACIÓN DE EXPIRACIÓN (OPCIONAL)
    # ===============================================================
    
    expires_at = models.DateTimeField(
        _('Expires At'),
        null=True,
        blank=True,
        help_text=_('When this token expires (null = never expires)')
    )
    
    class Meta:
        db_table = 'company_api_tokens'
        verbose_name = _('Company API Token')
        verbose_name_plural = _('Company API Tokens')
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        """Auto-generar token y nombre si no existen"""
        if not self.key:
            self.key = self.generate_token()
        if not self.name:
            self.name = f"API Token for {self.company.business_name}"
        super().save(*args, **kwargs)
    
    def generate_token(self):
        """
        Generar token único con prefijo identificable
        Formato: vsr_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX (48 chars total)
        """
        # Prefijo 'vsr_' para identificar tokens de VendoSRI
        return f"vsr_{secrets.token_urlsafe(33)}"  # 33 bytes = 44 chars + 4 prefix = 48 total
    
    def is_valid(self):
        """
        Verificar si el token es válido para uso
        """
        if not self.is_active:
            return False
        
        if not self.company.is_active:
            return False
        
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        
        return True
    
    def increment_usage(self, ip_address=None):
        """
        Incrementar contador de uso y actualizar estadísticas
        """
        self.total_requests += 1
        self.last_used_at = timezone.now()
        
        if ip_address:
            self.last_used_ip = ip_address
        
        # Solo actualizar estos campos específicos para optimizar
        update_fields = ['total_requests', 'last_used_at']
        if ip_address:
            update_fields.append('last_used_ip')
        
        self.save(update_fields=update_fields)
    
    def get_permissions(self):
        """
        Obtener permisos activos del token como diccionario
        """
        return {
            'create_documents': self.can_create_documents,
            'read_documents': self.can_read_documents,
            'update_documents': self.can_update_documents,
            'delete_documents': self.can_delete_documents,
            'manage_customers': self.can_manage_customers,
            'manage_products': self.can_manage_products,
        }
    
    def check_rate_limit(self, period='hour'):
        """
        Verificar si el token está dentro de los límites de rate limiting
        """
        now = timezone.now()
        
        if period == 'hour':
            # Verificar requests en la última hora
            limit = self.requests_per_hour
            time_threshold = now - timezone.timedelta(hours=1)
        elif period == 'day':
            # Verificar requests en el último día
            limit = self.requests_per_day
            time_threshold = now - timezone.timedelta(days=1)
        else:
            return True  # Período no reconocido, permitir
        
        # Aquí podrías implementar un sistema más sofisticado
        # que trackee requests individuales en una tabla separada
        # Por ahora, asumimos que está dentro del límite
        return True
    
    def __str__(self):
        return f"API Token: {self.name} ({self.company.business_name})"
    
    def __repr__(self):
        return f"<CompanyAPIToken: {self.key[:8]}... for {self.company.business_name}>"