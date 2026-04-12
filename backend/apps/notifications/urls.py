# -*- coding: utf-8 -*-
"""
URLs for notifications app
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import NotificationViewSet

app_name = 'notifications'

router = DefaultRouter()
router.register(r'', NotificationViewSet, basename='notification')

urlpatterns = [
    path('api/', include(router.urls)),
    path('', include(router.urls)),
]