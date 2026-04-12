# -*- coding: utf-8 -*-
"""
Models for invoicing app
Modelos para facturación y plantillas
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from apps.core.models import BaseModel
from apps.companies.models import Company


class Customer(BaseModel):
    """
    Modelo para clientes
    """
    
    IDENTIFICATION_TYPES = [
        ('04', _('RUC')),
        ('05', _('Cedula')),
        ('06', _('Passport')),
        ('07', _('Consumer')),
        ('08', _('Foreign ID')),
    ]
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='customers',
        verbose_name=_('company')
    )
    
    identification_type = models.CharField(
        _('identification type'),
        max_length=2,
        choices=IDENTIFICATION_TYPES,
        default='05'
    )
    
    identification = models.CharField(
        _('identification'),
        max_length=20,
        help_text=_('Customer identification number')
    )
    
    name = models.CharField(
        _('name'),
        max_length=300,
        help_text=_('Customer full name or business name')
    )
    
    email = models.EmailField(
        _('email'),
        blank=True,
        help_text=_('Customer email address')
    )
    
    phone = models.CharField(
        _('phone'),
        max_length=20,
        blank=True,
        help_text=_('Customer phone number')
    )
    
    address = models.TextField(
        _('address'),
        blank=True,
        help_text=_('Customer address')
    )
    
    city = models.CharField(
        _('city'),
        max_length=100,
        blank=True
    )
    
    province = models.CharField(
        _('province'),
        max_length=100,
        blank=True
    )
    
    postal_code = models.CharField(
        _('postal code'),
        max_length=10,
        blank=True
    )
    
    # Configuración de facturación
    default_payment_method = models.CharField(
        _('default payment method'),
        max_length=50,
        blank=True,
        help_text=_('Default payment method for this customer')
    )
    
    credit_limit = models.DecimalField(
        _('credit limit'),
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text=_('Credit limit for this customer')
    )
    
    # Información adicional
    notes = models.TextField(
        _('notes'),
        blank=True,
        help_text=_('Additional notes about the customer')
    )
    
    class Meta:
        verbose_name = _('Customer')
        verbose_name_plural = _('Customers')
        unique_together = ['company', 'identification']
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.identification})"


class ProductCategory(BaseModel):
    """
    Categorías de productos/servicios
    """
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='product_categories',
        verbose_name=_('company')
    )
    
    name = models.CharField(
        _('name'),
        max_length=100
    )
    
    description = models.TextField(
        _('description'),
        blank=True
    )
    
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subcategories',
        verbose_name=_('parent category')
    )
    
    class Meta:
        verbose_name = _('Product Category')
        verbose_name_plural = _('Product Categories')
        unique_together = ['company', 'name']
        ordering = ['name']
    
    def __str__(self):
        if self.parent:
            return f"{self.parent.name} > {self.name}"
        return self.name


class ProductTemplate(BaseModel):
    """
    Plantillas de productos/servicios para facilitar la facturación
    """
    
    PRODUCT_TYPES = [
        ('PRODUCT', _('Product')),
        ('SERVICE', _('Service')),
    ]
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='product_templates',
        verbose_name=_('company')
    )
    
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        verbose_name=_('category')
    )
    
    product_type = models.CharField(
        _('product type'),
        max_length=20,
        choices=PRODUCT_TYPES,
        default='PRODUCT'
    )
    
    main_code = models.CharField(
        _('main code'),
        max_length=25,
        help_text=_('Product main identification code')
    )
    
    auxiliary_code = models.CharField(
        _('auxiliary code'),
        max_length=25,
        blank=True,
        help_text=_('Product auxiliary code')
    )
    
    name = models.CharField(
        _('name'),
        max_length=200,
        help_text=_('Product or service name')
    )
    
    description = models.TextField(
        _('description'),
        help_text=_('Detailed product description')
    )
    
    unit_of_measure = models.CharField(
        _('unit of measure'),
        max_length=20,
        default='u',
        help_text=_('Unit of measure (u, kg, m, etc.)')
    )
    
    unit_price = models.DecimalField(
        _('unit price'),
        max_digits=12,
        decimal_places=6,
        validators=[MinValueValidator(0)],
        help_text=_('Default unit price')
    )
    
    # Configuración de impuestos
    tax_rate = models.DecimalField(
        _('tax rate'),
        max_digits=5,
        decimal_places=2,
        default=12.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=_('Default tax rate percentage')
    )
    
    tax_code = models.CharField(
        _('tax code'),
        max_length=2,
        choices=[
            ('2', _('IVA')),
            ('3', _('ICE')),
            ('5', _('IRBPNR')),
        ],
        default='2',
        help_text=_('Tax type code')
    )
    
    # Inventario (opcional)
    track_inventory = models.BooleanField(
        _('track inventory'),
        default=False,
        help_text=_('Whether to track inventory for this product')
    )
    
    current_stock = models.DecimalField(
        _('current stock'),
        max_digits=12,
        decimal_places=6,
        default=0,
        help_text=_('Current stock quantity')
    )
    
    minimum_stock = models.DecimalField(
        _('minimum stock'),
        max_digits=12,
        decimal_places=6,
        default=0,
        help_text=_('Minimum stock level for alerts')
    )
    
    # Información adicional
    additional_details = models.JSONField(
        _('additional details'),
        default=dict,
        blank=True,
        help_text=_('Additional product details')
    )
    
    class Meta:
        verbose_name = _('Product Template')
        verbose_name_plural = _('Product Templates')
        unique_together = ['company', 'main_code']
        ordering = ['name']
    
    def __str__(self):
        return f"{self.main_code} - {self.name}"
    
    @property
    def is_low_stock(self):
        """Verifica si el stock está bajo"""
        if not self.track_inventory:
            return False
        return self.current_stock <= self.minimum_stock


class InvoiceTemplate(BaseModel):
    """
    Plantillas de facturas para reutilizar configuraciones
    """
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='invoice_templates',
        verbose_name=_('company')
    )
    
    name = models.CharField(
        _('template name'),
        max_length=100,
        help_text=_('Name for this invoice template')
    )
    
    description = models.TextField(
        _('description'),
        blank=True
    )
    
    # Configuración por defecto
    default_payment_method = models.CharField(
        _('default payment method'),
        max_length=50,
        blank=True
    )
    
    default_payment_terms = models.CharField(
        _('default payment terms'),
        max_length=100,
        blank=True,
        help_text=_('Default payment terms text')
    )
    
    # Productos por defecto
    default_products = models.ManyToManyField(
        ProductTemplate,
        through='TemplateProduct',
        related_name='invoice_templates',
        blank=True
    )
    
    # Configuración adicional
    additional_fields = models.JSONField(
        _('additional fields'),
        default=dict,
        blank=True,
        help_text=_('Additional fields to include in invoices')
    )
    
    class Meta:
        verbose_name = _('Invoice Template')
        verbose_name_plural = _('Invoice Templates')
        unique_together = ['company', 'name']
        ordering = ['name']
    
    def __str__(self):
        return self.name


class TemplateProduct(BaseModel):
    """
    Productos incluidos en plantillas de factura
    """
    
    template = models.ForeignKey(
        InvoiceTemplate,
        on_delete=models.CASCADE,
        related_name='template_products'
    )
    
    product = models.ForeignKey(
        ProductTemplate,
        on_delete=models.CASCADE,
        related_name='template_uses'
    )
    
    default_quantity = models.DecimalField(
        _('default quantity'),
        max_digits=12,
        decimal_places=6,
        default=1,
        validators=[MinValueValidator(0)]
    )
    
    default_discount = models.DecimalField(
        _('default discount'),
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    
    order = models.PositiveIntegerField(
        _('order'),
        default=0,
        help_text=_('Order of appearance in the template')
    )
    
    class Meta:
        verbose_name = _('Template Product')
        verbose_name_plural = _('Template Products')
        unique_together = ['template', 'product']
        ordering = ['order', 'product__name']
    
    def __str__(self):
        return f"{self.template.name} - {self.product.name}"


class PaymentMethod(BaseModel):
    """
    Métodos de pago disponibles
    """
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='payment_methods',
        verbose_name=_('company')
    )
    
    name = models.CharField(
        _('name'),
        max_length=50
    )
    
    code = models.CharField(
        _('code'),
        max_length=20,
        help_text=_('Internal code for this payment method')
    )
    
    description = models.TextField(
        _('description'),
        blank=True
    )
    
    # Configuración
    requires_bank_info = models.BooleanField(
        _('requires bank info'),
        default=False,
        help_text=_('Whether this payment method requires bank information')
    )
    
    default_days_to_pay = models.PositiveIntegerField(
        _('default days to pay'),
        default=0,
        help_text=_('Default number of days for payment')
    )
    
    class Meta:
        verbose_name = _('Payment Method')
        verbose_name_plural = _('Payment Methods')
        unique_together = ['company', 'code']
        ordering = ['name']
    
    def __str__(self):
        return self.name
        return self.name
