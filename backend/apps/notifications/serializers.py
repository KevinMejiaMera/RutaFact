# -*- coding: utf-8 -*-
"""
Serializers for notifications app
"""

from rest_framework import serializers
from .models import *  # Importar todos los modelos de notifications

# Como no tengo el modelo de notifications, creo un serializer básico
class NotificationSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    message = serializers.CharField()
    created_at = serializers.DateTimeField(read_only=True)
    is_read = serializers.BooleanField(default=False)