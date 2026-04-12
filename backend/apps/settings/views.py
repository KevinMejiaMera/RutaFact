# -*- coding: utf-8 -*-
"""
Views for settings app
"""

from rest_framework import viewsets
from rest_framework.response import Response
from .serializers import SettingSerializer

class SettingViewSet(viewsets.ViewSet):
    """ViewSet básico para configuraciones"""
    
    def list(self, request):
        # Configuraciones de ejemplo
        settings = [
            {
                'key': 'sri_environment',
                'value': 'TEST',
                'description': 'Ambiente del SRI (TEST/PRODUCTION)',
                'category': 'sri'
            },
            {
                'key': 'email_enabled',
                'value': 'true',
                'description': 'Envío automático de emails',
                'category': 'email'
            },
            {
                'key': 'pdf_generation',
                'value': 'true',
                'description': 'Generación automática de PDF',
                'category': 'documents'
            }
        ]
        serializer = SettingSerializer(settings, many=True)
        return Response(serializer.data)