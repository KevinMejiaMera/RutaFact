import logging
from rest_framework import permissions, viewsets, status, filters

logger = logging.getLogger(__name__)
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
import os
import hashlib
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
                              
            # Nota: company_id ahora es opcional para permitir auto-creación de Matriz
            pass
            
            # Validar extensión de archivo
            allowed_extensions = ['.p12', '.pfx']
            if not any(certificate_file.name.lower().endswith(ext) for ext in allowed_extensions):
                return Response({'error': f'File must be one of: {", ".join(allowed_extensions)}'}, 
                              status=status.HTTP_400_BAD_REQUEST)
            
            # Leer archivo
            cert_data = certificate_file.read()
            
            # --- DESENCRIPTACIÓN UNIVERSAL (TODOS LOS PROVEEDORES) ---
            from .utils import load_p12_safely, extract_ecuador_ruc
            try:
                private_key, cert, additional_certs = load_p12_safely(cert_data, password)
                logger.info("✅ Firma desencriptada exitosamente con el motor universal")
            except Exception as e:
                return Response({'error': f'Contraseña incorrecta o formato no soportado: {str(e)}'}, 
                              status=status.HTTP_400_BAD_REQUEST)
            
            # --- EXTRACCIÓN DE DATOS MULTI-PROVEEDOR ---
            extracted_ruc, extracted_name = extract_ecuador_ruc(cert)
            from django.utils.timezone import make_aware
            import datetime
            
            # Extraer metadatos del certificado
            subject = cert.subject
            issuer = cert.issuer
            serial_number = str(cert.serial_number)
            
            # Asegurar que las fechas sean aware (Django las prefiere así)
            valid_from = cert.not_valid_before
            if valid_from.tzinfo is None:
                valid_from = make_aware(valid_from)
                
            valid_to = cert.not_valid_after
            if valid_to.tzinfo is None:
                valid_to = make_aware(valid_to)
                
            fingerprint = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
            
            # Detectar ambiente SRI sugerido
            environment = 'TEST'
            if "uanataca" in str(issuer).lower() or "security data" in str(issuer).lower():
                environment = 'PRODUCTION' 
            
            # ------------------------------------------------------
            if extracted_ruc and len(extracted_ruc) < 13:
                logger.warning(f"⚠️ RUC extraído sospechoso: {extracted_ruc}")
            # --------------------------------------------------
            
            # Verificar si ya existe una empresa o crear la Matriz
            from apps.companies.models import Company
            from apps.users.models import User, UserCompanyAssignment
            
            company = None
            if company_id and company_id != "undefined" and company_id != "null":
                try:
                    company = Company.objects.get(id=company_id)
                except Company.DoesNotExist:
                    pass
            
            # Si no hay empresa especificada o no existe, buscar la Matriz o crearla
            if not company:
                company = Company.objects.filter(is_active=True).first()
                if not company:
                    # ✨ AUTO-CREACIÓN: Si no hay nada, creamos la Matriz con los datos del certificado
                    logger.info(f"🚀 Creando Empresa Matriz automática para RUC: {extracted_ruc}")
                    company = Company.objects.create(
                        ruc=extracted_ruc or "0000000000001",
                        business_name=extracted_name or "Empresa Matriz Principal",
                        trade_name=extracted_name or "Empresa Matriz",
                        email="administrador@rutafact.com",
                        address="Dirección Principal",
                        ciudad="Quito",
                        is_active=True
                    )
                    # Asignar al usuario actual (superuser)
                    user = request.user
                    if user.is_authenticated:
                        # Usando el nombre de campo correcto según el error: assigned_companies
                        UserCompanyAssignment.objects.get_or_create(
                            user=user, 
                            assigned_companies=company, 
                            status='APPROVED'
                        )
            
            # Re-asignar company_id para el resto del proceso
            company_id = company.id
            
            # Desactivar certificados anteriores de esta empresa
            DigitalCertificate.objects.filter(company=company).update(status='INACTIVE')
            
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
                extracted_ruc=extracted_ruc,
                extracted_name=extracted_name,
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
                'extracted_ruc': extracted_ruc,
                'extracted_name': extracted_name,
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
    
    @action(detail=False, methods=['delete'])
    def delete_active(self, request):
        """Elimina el certificado activo de la empresa matriz"""
        try:
            # Importar dinámicamente para evitar circulares
            from apps.core.views import get_user_companies_secure
            companies = get_user_companies_secure(request.user)
            
            if not companies.exists():
                return Response({'error': 'No tienes empresas asignadas'}, status=404)
            
            company = companies.first()
            cert = DigitalCertificate.objects.filter(company=company).first()
            
            if cert:
                cert_id = cert.id
                cert.delete()
                logger.info(f"🗑️ Certificado {cert_id} eliminado exitosamente para empresa {company.ruc}")
                return Response({'status': 'Certificate deleted successfully'})
            else:
                return Response({'error': 'No se encontró una firma activa para eliminar'}, status=404)
        except Exception as e:
            logger.error(f"Error eliminando certificado: {e}")
            return Response({'error': str(e)}, status=500)
            
    @action(detail=False, methods=['post'])
    def update_environment(self, request):
        """Actualiza el ambiente (TEST/PRODUCTION) del certificado activo"""
        try:
            environment = request.data.get('environment')
            if environment not in ['TEST', 'PRODUCTION']:
                return Response({'error': 'Ambiente no válido'}, status=400)

            from apps.core.views import get_user_companies_secure
            companies = get_user_companies_secure(request.user)
            
            if not companies.exists():
                return Response({'error': 'No tienes empresas asignadas'}, status=404)
            
            company = companies.first()
            cert = DigitalCertificate.objects.filter(company=company).first()
            
            if cert:
                cert.environment = environment
                cert.save() # El save() del modelo ya sincroniza con Company y SRIConfig
                logger.info(f"🌐 Ambiente actualizado a {environment} para empresa {company.ruc}")
                return Response({'status': 'Environment updated successfully'})
            else:
                return Response({'error': 'No se encontró un certificado activo'}, status=404)
        except Exception as e:
            logger.error(f"Error actualizando ambiente: {e}")
            return Response({'error': str(e)}, status=500)

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