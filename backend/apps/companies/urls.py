# -*- coding: utf-8 -*-
"""
URLs for companies app
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CompanyViewSet

app_name = 'companies'

router = DefaultRouter()
router.register(r'', CompanyViewSet, basename='company')

urlpatterns = [
    path('api/', include(router.urls)),
    path('', include(router.urls)),
]