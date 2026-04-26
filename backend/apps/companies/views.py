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
                # Convertir a int si es secuencial
                if 'secuencial' in field or field in ['establecimiento', 'punto_emision']:
                    try:
                        update_fields[field] = str(val).strip()
                    except:
                        pass
                else:
                    update_fields[field] = str(val).strip()

        # Logo (archivo)
        if 'logo' in request.FILES:
            logo_file = request.FILES['logo']
            company.logo = logo_file
            company.logo.save(logo_file.name, logo_file, save=False)
            update_fields['logo'] = company.logo.name

        if not update_fields:
            return Response({'status': 'ok', 'message': 'Nada que actualizar'})

        # UPDATE directo en Company
        Company.objects.filter(pk=company.pk).update(**update_fields)
        company.refresh_from_db()

        # ✅ SINCRONIZACIÓN EXHAUSTIVA CON SRIConfiguration
        from apps.sri_integration.models import SRIConfiguration
        sri_defaults = {
            'environment': 'TEST' if company.ambiente_sri == '1' else 'PRODUCTION',
            'establishment_code': company.codigo_establecimiento,
            'emission_point': company.codigo_punto_emision,
            'invoice_sequence': company.secuencial_factura,
            'credit_note_sequence': company.secuencial_nota_credito,
            'debit_note_sequence': company.secuencial_nota_debito,
            'retention_sequence': company.secuencial_retencion,
            'accounting_required': (company.obligado_contabilidad == 'SI'),
            'special_taxpayer': bool(company.contribuyente_especial),
            'special_taxpayer_number': company.contribuyente_especial or '',
            'regimen': company.regimen
        }
        
        SRIConfiguration.objects.update_or_create(
            company=company,
            defaults=sri_defaults
        )

        logger.info(f"✅ [POST CONFIG] Guardado y Sincronizado OK para {company.ruc}")

        return Response({
            'status': 'success',
            'message': 'Configuración maestra actualizada y sincronizada correctamente',
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
            
        # 1. Intentar refrescar la extracción (por si hay nuevos OIDs soportados)
        password = active_cert.get_password()
        if password:
            active_cert.extract_real_certificate_info(password)
            # extract_real_certificate_info ya actualiza ruc y business_name en la db
            # pero necesitamos recargar el objeto company para tener los datos frescos
            company.refresh_from_db()

        # 2. Sincronizar campos adicionales si no se actualizaron
        if active_cert.extracted_ruc:
            company.ruc = active_cert.extracted_ruc
        
        if active_cert.extracted_name:
            company.business_name = active_cert.extracted_name
            if not company.trade_name:
                company.trade_name = active_cert.extracted_name
        
        # 3. Sincronizar ambiente también
        if active_cert.environment:
            company.ambiente_sri = '1' if active_cert.environment == 'TEST' else '2'
            
        company.save()
        
        return Response({
            'status': 'success',
            'message': f'Datos sincronizados exitosamente con la firma de: {company.business_name}',
            'ruc': company.ruc,
            'business_name': company.business_name,
            'environment': company.get_ambiente_sri_display()
        })