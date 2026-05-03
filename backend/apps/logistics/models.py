# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from apps.core.models import BaseModel
from apps.companies.models import Company
from apps.invoicing.models import Customer
from django.conf import settings

class Vehicle(BaseModel):
    """
    Vehículos utilizados para las rutas de venta
    """
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='vehicles',
        verbose_name=_('company')
    )
    plate = models.CharField(_('plate'), max_length=20, unique=True)
    brand = models.CharField(_('brand'), max_length=50, blank=True)
    model = models.CharField(_('model'), max_length=50, blank=True)
    color = models.CharField(_('color'), max_length=30, blank=True)
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        verbose_name = _('Vehicle')
        verbose_name_plural = _('Vehicles')

    def __str__(self):
        return f"{self.plate} - {self.brand} {self.model}"

class Route(BaseModel):
    """
    Rutas de venta/distribución
    """
    STATUS_CHOICES = [
        ('PENDING', _('Pending')),
        ('ACTIVE', _('Active')),
        ('COMPLETED', _('Completed')),
        ('CANCELLED', _('Cancelled')),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='routes'
    )
    name = models.CharField(_('route name'), max_length=100)
    date = models.DateField(_('date'))
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='assigned_routes'
    )
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='routes'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    destination_name = models.CharField(_('destination name'), max_length=255, blank=True)
    google_maps_url = models.URLField(_('google maps url'), max_length=500, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _('Route')
        verbose_name_plural = _('Routes')
        ordering = ['-date', 'name']

    def __str__(self):
        return f"{self.name} - {self.date}"

class RouteStop(BaseModel):
    """
    Paradas/Visitas dentro de una ruta
    """
    STATUS_CHOICES = [
        ('PENDING', _('Pending')),
        ('VISITED', _('Visited')),
        ('SKIPPED', _('Skipped')),
    ]

    route = models.ForeignKey(
        Route,
        on_delete=models.CASCADE,
        related_name='stops'
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='route_visits'
    )
    order = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    arrival_time = models.DateTimeField(null=True, blank=True)
    departure_time = models.DateTimeField(null=True, blank=True)
    
    # Referencia al documento generado en esta parada (si aplica)
    # En este proyecto está en apps.sri_integration.models
    invoice = models.ForeignKey(
        'sri_integration.ElectronicDocument',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='route_stops'
    )

    class Meta:
        verbose_name = _('Route Stop')
        verbose_name_plural = _('Route Stops')
        ordering = ['order']
        unique_together = ['route', 'customer']

    def __str__(self):
        return f"{self.route.name} - {self.customer.name}"

class RouteTemplate(BaseModel):
    """
    Plantillas de rutas frecuentes para reutilizar destinos y configuraciones
    """
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='route_templates'
    )
    name = models.CharField(_('template name'), max_length=100)
    destination_name = models.CharField(_('destination name'), max_length=255, blank=True)
    google_maps_url = models.URLField(_('google maps url'), max_length=500, blank=True)

    class Meta:
        verbose_name = _('Route Template')
        verbose_name_plural = _('Route Templates')
        ordering = ['name']

    def __str__(self):
        return self.name

class RouteProduct(BaseModel):
    """
    Productos asignados a una ruta para venta directa (Consignación)
    """
    route = models.ForeignKey(
        Route,
        on_delete=models.CASCADE,
        related_name='products'
    )
    product = models.ForeignKey(
        'invoicing.ProductTemplate',
        on_delete=models.CASCADE,
        related_name='route_assignments'
    )
    quantity_loaded = models.DecimalField(_('quantity loaded'), max_digits=12, decimal_places=2)
    quantity_sold = models.DecimalField(_('quantity sold'), max_digits=12, decimal_places=2, default=0)
    quantity_returned = models.DecimalField(_('quantity returned'), max_digits=12, decimal_places=2, default=0)

    def save(self, *args, **kwargs):
        from apps.inventory.services import InventoryService
        from django.db import transaction
        
        is_new = self.pk is None
        old_qty = 0
        if not is_new:
            old_qty = RouteProduct.objects.get(pk=self.pk).quantity_loaded
        
        diff = self.quantity_loaded - old_qty
        
        with transaction.atomic():
            super().save(*args, **kwargs)
            if diff != 0:
                # Si diff > 0, cargamos más al camión (sale de bodega) -> OUT
                # Si diff < 0, devolvemos a bodega -> IN
                m_type = 'OUT' if diff > 0 else 'IN'
                InventoryService.register_movement(
                    company=self.route.company,
                    product=self.product,
                    movement_type=m_type,
                    quantity=abs(diff),
                    reference=f"RUTA-{self.route.id}",
                    notes=f"Asignación a ruta {self.route.name}",
                    user=None # Podría pasarse si se manejara en la vista
                )

    def delete(self, *args, **kwargs):
        from apps.inventory.services import InventoryService
        from django.db import transaction
        
        with transaction.atomic():
            # Devolver todo lo cargado a bodega al eliminar la asignación
            InventoryService.register_movement(
                company=self.route.company,
                product=self.product,
                movement_type='IN',
                quantity=self.quantity_loaded,
                reference=f"RUTA-DEL-{self.route.id}",
                notes=f"Eliminación de asignación en ruta {self.route.name}",
                user=None
            )
            super().delete(*args, **kwargs)

    class Meta:
        verbose_name = _('Route Product')
        verbose_name_plural = _('Route Products')

    def __str__(self):
        return f"{self.product.name} ({self.quantity_loaded})"

class RouteDelivery(BaseModel):
    """Registro individual de una entrega/venta realizada en la ruta"""
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='deliveries')
    customer_name = models.CharField(_('customer name'), max_length=255)
    latitude = models.DecimalField(_('latitude'), max_digits=12, decimal_places=9, null=True, blank=True)
    longitude = models.DecimalField(_('longitude'), max_digits=12, decimal_places=9, null=True, blank=True)
    notes = models.TextField(_('notes'), blank=True)
    seller = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='route_deliveries',
        verbose_name=_('seller')
    )
    
    invoice = models.OneToOneField(
        'sri_integration.ElectronicDocument',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='route_delivery',
        verbose_name=_('invoice')
    )
    
    class Meta:
        verbose_name = _('Route Delivery')
        verbose_name_plural = _('Route Deliveries')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.customer_name} - {self.created_at.strftime('%H:%M')}"

class RouteDeliveryItem(BaseModel):
    """Detalle de productos en una entrega específica"""
    delivery = models.ForeignKey(RouteDelivery, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('invoicing.ProductTemplate', on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product.name}: {self.quantity}"


