# -*- coding: utf-8 -*-
"""
Views for notifications app
"""

from rest_framework import viewsets, status
from rest_framework.response import Response
from .serializers import NotificationSerializer

class NotificationViewSet(viewsets.ViewSet):
    """ViewSet básico para notificaciones"""
    
    def list(self, request):
        # Datos de ejemplo hasta implementar el modelo completo
        notifications = [
            {
                'id': 1,
                'message': 'Nueva factura creada',
                'created_at': '2025-07-11T16:00:00Z',
                'is_read': False
            },
            {
                'id': 2,
                'message': 'Certificado próximo a vencer',
                'created_at': '2025-07-11T15:30:00Z',
                'is_read': True
            }
        ]
        serializer = NotificationSerializer(notifications, many=True)
        return Response(serializer.data)