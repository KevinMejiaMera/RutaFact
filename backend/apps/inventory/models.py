# -*- coding: utf-8 -*-
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator
from apps.core.models import BaseModel
from apps.companies.models import Company
from apps.invoicing.models import ProductTemplate

class Provider(BaseModel):
    """
    Modelo para Proveedores (Suppliers)
    """
    IDENTIFICATION_TYPES = [
        ('04', _('RUC')),
        ('05', _('Cédula')),
        ('06', _('Pasaporte')),
        ('08', _('Identificación del Exterior')),
    ]
    
    REGIMEN_CHOICES = [
        ('GENERAL', _('Régimen General')),
        ('RIMPE_EMPRENDEDOR', _('Régimen RIMPE - Emprendedor')),
        ('RIMPE_POPULAR', _('Régimen RIMPE - Negocio Popular')),
        ('AGROPECUARIO', _('Régimen Agropecuario')),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='providers',
        verbose_name=_('company')
    )
    
    identification_type = models.CharField(
        _('identification type'),
        max_length=2,
        choices=IDENTIFICATION_TYPES,
        default='04'
    )
    
    identification = models.CharField(
        _('identification'),
        max_length=20,
        help_text=_('Provider RUC or ID')
    )
    
    name = models.CharField(
        _('name'),
        max_length=300,
        help_text=_('Provider business name')
    )
    
    description = models.TextField(
        _('description'),
        blank=True
    )
    
    email = models.EmailField(
        _('email'),
        blank=True
    )
    
    phone = models.CharField(
        _('phone'),
        max_length=20,
        blank=True
    )
    
    address = models.TextField(
        _('address'),
        blank=True
    )
    
    regime = models.CharField(
        _('regime'),
        max_length=30,
        choices=REGIMEN_CHOICES,
        default='GENERAL'
    )
    
    authorization_number = models.CharField(
        _('authorization number'),
        max_length=50,
        blank=True,
        help_text=_('SRI Authorization number for physical invoices')
    )
    
    start_sequence = models.PositiveIntegerField(
        _('start sequence'),
        null=True,
        blank=True,
        help_text=_('Starting invoice number authorized')
    )
    
    end_sequence = models.PositiveIntegerField(
        _('end sequence'),
        null=True,
        blank=True,
        help_text=_('Ending invoice number authorized')
    )
    
    expiration_date = models.DateField(
        _('expiration date'),
        null=True,
        blank=True,
        help_text=_('Expiration date of the SRI authorization')
    )
    
    provider_code = models.CharField(
        _('provider code'),
        max_length=50,
        blank=True,
        help_text=_('Internal code or key for the provider')
    )

    class Meta:
        verbose_name = _('Provider')
        verbose_name_plural = _('Providers')
        unique_together = ['company', 'identification']
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.identification})"

class PurchaseInvoice(BaseModel):
    """
    Factura de Compra (Ingreso de inventario)
    """
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='purchase_invoices'
    )
    
    provider = models.ForeignKey(
        Provider,
        on_delete=models.CASCADE,
        related_name='purchases'
    )
    
    invoice_number = models.CharField(
        _('invoice number'),
        max_length=50,
        help_text=_('Format: 001-001-000000001')
    )
    
    issue_date = models.DateField(_('issue date'))
    
    total_amount = models.DecimalField(
        _('total amount'),
        max_digits=12,
        decimal_places=2,
        default=0
    )
    
    notes = models.TextField(blank=True)
    
    is_processed = models.BooleanField(
        _('is processed'),
        default=False,
        help_text=_('True if inventory has been updated')
    )

    class Meta:
        verbose_name = _('Purchase Invoice')
        verbose_name_plural = _('Purchase Invoices')
        ordering = ['-issue_date']

    def __str__(self):
        return f"{self.invoice_number} - {self.provider.name}"

class PurchaseItem(BaseModel):
    """
    Ítems de la Factura de Compra
    """
    purchase_invoice = models.ForeignKey(
        PurchaseInvoice,
        on_delete=models.CASCADE,
        related_name='items'
    )
    
    product = models.ForeignKey(
        ProductTemplate,
        on_delete=models.CASCADE,
        related_name='purchase_items'
    )
    
    quantity = models.DecimalField(
        _('quantity'),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)]
    )
    
    cost_price = models.DecimalField(
        _('cost price'),
        max_digits=12,
        decimal_places=6,
        validators=[MinValueValidator(0)]
    )
    
    subtotal = models.DecimalField(
        _('subtotal'),
        max_digits=12,
        decimal_places=2
    )

    class Meta:
        verbose_name = _('Purchase Item')
        verbose_name_plural = _('Purchase Items')

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

class ProductStock(BaseModel):
    """
    Control de inventario actual por producto y empresa
    """
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='inventory_stocks'
    )
    
    product = models.ForeignKey(
        ProductTemplate,
        on_delete=models.CASCADE,
        related_name='stocks'
    )
    
    quantity = models.DecimalField(
        _('quantity'),
        max_digits=12,
        decimal_places=2,
        default=0
    )
    
    last_purchase_price = models.DecimalField(
        _('last purchase price'),
        max_digits=12,
        decimal_places=6,
        default=0
    )

    class Meta:
        verbose_name = _('Product Stock')
        verbose_name_plural = _('Product Stocks')
        unique_together = ['company', 'product']

    def __str__(self):
        return f"{self.product.name}: {self.quantity}"

class StockMovement(BaseModel):
    """
    Registro histórico de cada entrada o salida de bodega
    """
    MOVEMENT_TYPES = [
        ('IN', _('Entry (Purchase)')),
        ('OUT', _('Exit (Sale)')),
        ('ADJ', _('Adjustment')),
    ]
    
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='stock_movements'
    )
    
    product = models.ForeignKey(
        ProductTemplate,
        on_delete=models.CASCADE,
        related_name='movements'
    )
    
    movement_type = models.CharField(
        max_length=3,
        choices=MOVEMENT_TYPES
    )
    
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )
    
    previous_stock = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )
    
    new_stock = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )
    
    reference = models.CharField(
        max_length=100,
        blank=True,
        help_text=_('Reference ID (Invoice #, Sale #)')
    )
    
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _('Stock Movement')
        verbose_name_plural = _('Stock Movements')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.movement_type} | {self.product.name} | {self.quantity}"
