# -*- coding: utf-8 -*-
"""
Inicialización del proyecto rutafact
rutafact/__init__.py

Inicializa Celery para que se cargue cuando Django inicie
"""

# Esto asegura que Celery app se cargue cuando Django inicie
from .celery import app as celery_app

__all__ = ('celery_app',)

# Mensaje de inicialización
print("rutafact initialized with Celery support")
