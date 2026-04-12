# -*- coding: utf-8 -*-
"""
Views for companies app
"""

from rest_framework import permissions, viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Company
from .serializers import CompanySerializer, CompanyListSerializer

class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.all()
    serializer_class = CompanySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['ruc', 'business_name', 'trade_name', 'email']
    ordering_fields = ['business_name', 'created_at']
    ordering = ['business_name']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return CompanyListSerializer
        return CompanySerializer
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Solo empresas activas"""
        active_companies = self.get_queryset().filter(is_active=True)
        serializer = self.get_serializer(active_companies, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Activar/desactivar empresa"""
        company = self.get_object()
        company.is_active = not company.is_active
        company.save()
        return Response({
            'status': 'active' if company.is_active else 'inactive',
            'message': f'Company {company.business_name} is now {"active" if company.is_active else "inactive"}'
        })