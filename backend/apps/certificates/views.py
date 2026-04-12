# -*- coding: utf-8 -*-
"""
Views for certificates app - CON CARGA REAL DE P12
"""

from rest_framework import permissions, viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
import os
from django.conf import settings
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from .models import DigitalCertificate, CertificateUsageLog
from .serializers import DigitalCertificateSerializer, CertificateUsageLogSerializer

class DigitalCertificateViewSet(viewsets.ModelViewSet):
    queryset = DigitalCertificate.objects.all()
    serializer_class = DigitalCertificateSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['company', 'status', 'environment']
    search_fields = ['subject_name', 'issuer_name', 'company__business_name']
    
    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser])
    def upload_certificate(self, request):
        """Subir certificado P12 real"""
        try:
            certificate_file = request.FILES.get('certificate_file')
            password = request.data.get('password')
            company_id = request.data.get('company')
            environment = request.data.get('environment', 'TEST')
            
            if not certificate_file:
                return Response({'error': 'Certificate file is required'}, 
                              status=status.HTTP_400_BAD_REQUEST)
            
            if not password:
                return Response({'error': 'Certificate password is required'}, 
                              status=status.HTTP_400_BAD_REQUEST)
                              
            if not company_id:
                return Response({'error': 'Company ID is required'}, 
                              status=status.HTTP_400_BAD_REQUEST)
            
            # Validar extensión de archivo
            if not certificate_file.name.lower().endswith('.p12'):
                return Response({'error': 'File must be a .p12 certificate'}, 
                              status=status.HTTP_400_BAD_REQUEST)
            
            # Leer archivo
            cert_data = certificate_file.read()
            
            # Validar certificado con la contraseña
            try:
                private_key, cert, additional_certs = pkcs12.load_key_and_certificates(
                    cert_data, 
                    password.encode('utf-8')
                )
            except Exception as e:
                return Response({'error': f'Invalid certificate or password: {str(e)}'}, 
                              status=status.HTTP_400_BAD_REQUEST)
            
            # Extraer información del certificado
            subject = cert.subject
            issuer = cert.issuer
            serial_number = str(cert.serial_number)
            valid_from = cert.not_valid_before
            valid_to = cert.not_valid_after
            
            # Calcular fingerprint
            import hashlib
            fingerprint = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
            
            # Verificar si ya existe un certificado para esta empresa
            from apps.companies.models import Company
            try:
                company = Company.objects.get(id=company_id)
                existing_cert = DigitalCertificate.objects.filter(company=company).first()
                if existing_cert:
                    # Desactivar certificado anterior
                    existing_cert.status = 'INACTIVE'
                    existing_cert.save()
            except Company.DoesNotExist:
                return Response({'error': 'Company not found'}, 
                              status=status.HTTP_400_BAD_REQUEST)
            
            # Guardar archivo en storage seguro
            filename = f"cert_{company_id}_{cert.serial_number}.p12"
            file_path = f"certificates/encrypted/{filename}"
            
            # Crear directorio si no existe
            full_path = os.path.join(settings.MEDIA_ROOT, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            # Guardar archivo
            with open(full_path, 'wb') as f:
                f.write(cert_data)
            
            # Crear registro en base de datos
            certificate = DigitalCertificate.objects.create(
                company_id=company_id,
                certificate_file=file_path,
                subject_name=str(subject),
                issuer_name=str(issuer),
                serial_number=serial_number,
                valid_from=valid_from,
                valid_to=valid_to,
                fingerprint=fingerprint,
                environment=environment,
                status='ACTIVE'
            )
            
            # Hashear y guardar contraseña
            certificate.set_password(password)
            certificate.save()
            
            # Log de carga exitosa
            CertificateUsageLog.objects.create(
                certificate=certificate,
                operation='UPLOAD',
                success=True,
                ip_address=self._get_client_ip(request)
            )
            
            return Response({
                'status': 'Certificate uploaded successfully',
                'certificate_id': certificate.id,
                'subject': str(subject),
                'issuer': str(issuer),
                'serial_number': serial_number,
                'valid_from': valid_from.isoformat(),
                'valid_to': valid_to.isoformat(),
                'fingerprint': fingerprint,
                'environment': environment,
                'file_path': file_path,
                'days_until_expiration': certificate.days_until_expiration,
                'message': 'Certificate is ready for digital signing'
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({
                'error': f'Failed to upload certificate: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'])
    def test_certificate(self, request, pk=None):
        """Probar certificado con contraseña"""
        certificate = self.get_object()
        password = request.data.get('password')
        
        if not password:
            return Response({'error': 'Password is required'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Verificar contraseña
            if not certificate.verify_password(password):
                return Response({'error': 'Invalid password'}, 
                              status=status.HTTP_400_BAD_REQUEST)
            
            # Cargar certificado para probar
            cert_path = os.path.join(settings.MEDIA_ROOT, certificate.certificate_file)
            with open(cert_path, 'rb') as f:
                p12_data = f.read()
            
            private_key, cert, additional_certs = pkcs12.load_key_and_certificates(
                p12_data, 
                password.encode('utf-8')
            )
            
            # Log de prueba exitosa
            CertificateUsageLog.objects.create(
                certificate=certificate,
                operation='TEST',
                success=True,
                ip_address=self._get_client_ip(request)
            )
            
            return Response({
                'status': 'Certificate test successful',
                'subject': certificate.subject_name,
                'issuer': certificate.issuer_name,
                'valid_from': certificate.valid_from.isoformat(),
                'valid_to': certificate.valid_to.isoformat(),
                'days_until_expiration': certificate.days_until_expiration,
                'is_expired': certificate.is_expired,
                'message': 'Certificate is valid and ready for use'
            })
            
        except Exception as e:
            # Log de prueba fallida
            CertificateUsageLog.objects.create(
                certificate=certificate,
                operation='TEST',
                success=False,
                error_message=str(e),
                ip_address=self._get_client_ip(request)
            )
            
            return Response({
                'error': f'Certificate test failed: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Certificados activos"""
        active_certs = self.get_queryset().filter(status='ACTIVE')
        serializer = self.get_serializer(active_certs, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def expiring_soon(self, request):
        """Certificados que expiran pronto (próximos 30 días)"""
        expiring_certs = [cert for cert in self.get_queryset() if cert.days_until_expiration <= 30 and not cert.is_expired]
        serializer = self.get_serializer(expiring_certs, many=True)
        return Response({
            'count': len(expiring_certs),
            'certificates': serializer.data,
            'message': f'{len(expiring_certs)} certificates expiring in the next 30 days'
        })
    
    def _get_client_ip(self, request):
        """Obtener IP del cliente"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

class CertificateUsageLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CertificateUsageLog.objects.all()
    serializer_class = CertificateUsageLogSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['certificate', 'operation', 'success']
    search_fields = ['operation', 'document_number']
    ordering_fields = ['created_at']
    ordering = ['-created_at']
    
    @action(detail=False, methods=['get'])
    def recent_activity(self, request):
        """Actividad reciente de certificados"""
        recent_logs = self.get_queryset()[:50]  # Últimos 50 registros
        serializer = self.get_serializer(recent_logs, many=True)
        return Response({
            'count': recent_logs.count(),
            'logs': serializer.data
        })