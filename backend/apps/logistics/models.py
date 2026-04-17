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
        ('DRAFT', _('Draft')),
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
        related_name='routes'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT'
    )
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
