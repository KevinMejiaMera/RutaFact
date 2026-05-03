# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from apps.core.models import BaseModel
from apps.companies.models import Company
from apps.invoicing.models import Customer, ProductTemplate

class Order(BaseModel):
    """
    Pedidos realizados por clientes
    """
    STATUS_CHOICES = [
        ('PENDING', _('Pending')),
        ('COMPLETED', _('Completed')),
        ('CANCELLED', _('Cancelled')),
    ]
    
    company = models.ForeignKey(
        Company, 
        on_delete=models.CASCADE, 
        related_name='orders',
        verbose_name=_('company')
    )
    customer = models.ForeignKey(
        Customer, 
        on_delete=models.CASCADE, 
        related_name='orders',
        verbose_name=_('customer')
    )
    delivery_address = models.TextField(_('delivery address'))
    status = models.CharField(
        _('status'),
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='PENDING'
    )
    total_amount = models.DecimalField(
        _('total amount'),
        max_digits=12, 
        decimal_places=2, 
        default=0
    )
    
    # Referencia al documento electrónico generado al completar
    invoice = models.OneToOneField(
        'sri_integration.ElectronicDocument',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order',
        verbose_name=_('invoice')
    )
    
    route = models.ForeignKey(
        'logistics.Route',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name=_('assigned route')
    )
    
    notes = models.TextField(_('notes'), blank=True)

    class Meta:
        verbose_name = _('Order')
        verbose_name_plural = _('Orders')
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.id} - {self.customer.name} ({self.status})"

    @property
    def subtotal_without_tax(self):
        return sum(item.subtotal for item in self.items.all())

    @property
    def total_tax(self):
        return sum(item.tax_amount for item in self.items.all())

    def complete_order(self):
        """
        Marca el pedido como completado y genera la factura
        """
        if self.status == 'PENDING':
            self.status = 'COMPLETED'
            self.save()
            # Aquí se disparará la lógica para generar la factura
            return True
        return False

class OrderItem(BaseModel):
    """
    Ítems de un pedido
    """
    order = models.ForeignKey(
        Order, 
        on_delete=models.CASCADE, 
        related_name='items'
    )
    product = models.ForeignKey(
        ProductTemplate, 
        on_delete=models.CASCADE,
        verbose_name=_('product')
    )
    quantity = models.DecimalField(
        _('quantity'),
        max_digits=12, 
        decimal_places=2
    )
    unit_price = models.DecimalField(
        _('unit_price'),
        max_digits=12, 
        decimal_places=2
    )
    tax_rate = models.DecimalField(
        _('tax rate'),
        max_digits=5, 
        decimal_places=2,
        default=15.00
    )

    class Meta:
        verbose_name = _('Order Item')
        verbose_name_plural = _('Order Items')

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"
    
    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    @property
    def tax_amount(self):
        return self.subtotal * (self.tax_rate / 100)

    @property
    def total(self):
        return self.subtotal + self.tax_amount
