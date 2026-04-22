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
    def update_master_config(self, request, pk=None):
        """Actualización completa de configuración de empresa (Matriz)"""
        company = self.get_object()
        
        # ✅ SINCRONIZACIÓN PRIORITARIA CON LA FIRMA
        from apps.certificates.models import DigitalCertificate
        active_cert = DigitalCertificate.objects.filter(company=company, status='ACTIVE').first()
        if active_cert and active_cert.extracted_ruc:
            if company.ruc != active_cert.extracted_ruc:
                company.ruc = active_cert.extracted_ruc
                if active_cert.extracted_name and not request.data.get('business_name'):
                    company.business_name = active_cert.extracted_name
                company.save()
        
        # Usar el serializador para validar y actualizar campos de texto
        serializer = self.get_serializer(company, data=request.data, partial=True)
        
        if serializer.is_valid():
            # Manejo especial para el logo si se envió
            if 'logo' in request.FILES:
                company.logo = request.FILES['logo']
            
            serializer.save()
            
            return Response({
                'status': 'success',
                'message': 'Configuración maestra actualizada correctamente',
                'data': serializer.data
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def sync_from_certificate(self, request, pk=None):
        """Forzar sincronización de datos de la empresa desde la firma activa"""
        company = self.get_object()
        from apps.certificates.models import DigitalCertificate
        active_cert = DigitalCertificate.objects.filter(company=company, status='ACTIVE').first()
        
        if not active_cert:
            return Response({'error': 'No hay una firma activa para sincronizar'}, status=400)
            
        company.ruc = active_cert.extracted_ruc
        if active_cert.extracted_name:
            company.business_name = active_cert.extracted_name
            if not company.trade_name:
                company.trade_name = active_cert.extracted_name
        
        company.save()
        
        return Response({
            'status': 'success',
            'message': f'Sincronizado con RUC: {company.ruc}',
            'ruc': company.ruc,
            'business_name': company.business_name
        })