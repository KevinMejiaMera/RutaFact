# -*- coding: utf-8 -*-
"""
URL configuration for users app
URLs para la gestión de usuarios en RutaFact_SRI
"""

from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
    # API para verificar estado de asignación
    path('api/check-assignment/', views.check_assignment_status, name='check_assignment'),
]