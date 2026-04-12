# -*- coding: utf-8 -*-
"""
URLs for invoicing app
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CustomerViewSet, ProductCategoryViewSet, ProductTemplateViewSet,
    InvoiceTemplateViewSet, PaymentMethodViewSet
)

app_name = 'invoicing'

router = DefaultRouter()
router.register(r'customers', CustomerViewSet)
router.register(r'categories', ProductCategoryViewSet)
router.register(r'products', ProductTemplateViewSet)
router.register(r'templates', InvoiceTemplateViewSet)
router.register(r'payment-methods', PaymentMethodViewSet)

urlpatterns = [
    path('api/', include(router.urls)),
    path('', include(router.urls)),  # También disponible sin /api/
]