# -*- coding: utf-8 -*-
"""
URLs for settings app
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SettingViewSet

app_name = 'settings'

router = DefaultRouter()
router.register(r'', SettingViewSet, basename='setting')

urlpatterns = [
    path('api/', include(router.urls)),
    path('', include(router.urls)),
]