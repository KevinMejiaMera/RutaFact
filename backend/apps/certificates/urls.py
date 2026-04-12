# -*- coding: utf-8 -*-
"""
URLs for certificates app
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DigitalCertificateViewSet, CertificateUsageLogViewSet

app_name = 'certificates'

router = DefaultRouter()
router.register(r'certificates', DigitalCertificateViewSet)
router.register(r'usage-logs', CertificateUsageLogViewSet)

urlpatterns = [
    path('api/', include(router.urls)),
    path('', include(router.urls)),
]