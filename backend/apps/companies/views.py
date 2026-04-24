# -*- coding: utf-8 -*-
"""
Views for companies app
"""
import logging
from rest_framework import permissions, viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Company
from .serializers import CompanySerializer, CompanyListSerializer

logger = logging.getLogger(__name__)

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
        """Actualizacion completa de configuracion de empresa (Matriz)"""
        company = self.get_object()

        print(f"[POST CONFIG] request.data keys: {list(request.data.keys())}")
        logger.warning(f"[POST CONFIG] request.data keys: {list(request.data.keys())}")

        # Mapa directo: campo del form -> campo del modelo
        # Solo actualizamos los campos que el form puede enviar
        ALLOWED_FIELDS = [
            'trade_name', 'business_name', 'ruc', 'email', 'phone', 'address',
            'ciudad', 'provincia', 'codigo_postal', 'website',
            'tipo_contribuyente', 'obligado_contabilidad', 'contribuyente_especial', 'regimen',
            'ambiente_sri', 'tipo_emision',
            'secuencial_factura', 'secuencial_nota_credito',
            'secuencial_nota_debito', 'secuencial_retencion',
            'codigo_establecimiento', 'codigo_punto_emision',
        ]

        update_fields = {}
        for field in ALLOWED_FIELDS:
            val = request.data.get(field, None)
            if val is not None and str(val).strip() != '':
                update_fields[field] = str(val).strip()

        # Logo (archivo)
        if 'logo' in request.FILES:
            logo_file = request.FILES['logo']
            company.logo = logo_file
            company.logo.save(logo_file.name, logo_file, save=False)
            update_fields['logo'] = company.logo.name

        codigo_establecimiento = update_fields.get('codigo_establecimiento', '')
        codigo_punto_emision = update_fields.get('codigo_punto_emision', '')

        print(f"[POST CONFIG] establecimiento='{codigo_establecimiento}', punto='{codigo_punto_emision}'")
        logger.warning(f"[POST CONFIG] establecimiento='{codigo_establecimiento}', punto='{codigo_punto_emision}'")
        print(f"[POST CONFIG] update_fields={update_fields}")
        logger.warning(f"[POST CONFIG] update_fields={update_fields}")

        if not update_fields:
            return Response({'status': 'ok', 'message': 'Nada que actualizar'})

        # UPDATE directo - nunca llama a model.save()
        Company.objects.filter(pk=company.pk).update(**update_fields)

        # Sincronizar SRIConfiguration
        from apps.sri_integration.models import SRIConfiguration
        sri_update = {}
        if codigo_establecimiento:
            sri_update['establishment_code'] = codigo_establecimiento
        if codigo_punto_emision:
            sri_update['emission_point'] = codigo_punto_emision
        amb = update_fields.get('ambiente_sri')
        if amb:
            sri_update['environment'] = 'TEST' if amb == '1' else 'PRODUCTION'
        if sri_update:
            SRIConfiguration.objects.filter(company=company).update(**sri_update)

        company.refresh_from_db()
        print(f"[POST CONFIG] GUARDADO OK: establecimiento='{company.codigo_establecimiento}' punto='{company.codigo_punto_emision}'")
        logger.warning(f"[POST CONFIG] GUARDADO OK: establecimiento='{company.codigo_establecimiento}', punto='{company.codigo_punto_emision}'")

        return Response({
            'status': 'success',
            'message': 'Configuracion maestra actualizada correctamente',
            'data': CompanySerializer(company).data
        })




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