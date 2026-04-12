import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from apps.sri_integration.models import ElectronicDocument
from apps.certificates.models import DigitalCertificate
from apps.sri_integration.services.sri_processor import SRIProcessor

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Procesa facturas pendientes: XML -> Firma -> SRI -> PDF'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--document-id',
            type=int,
            help='ID específico de documento a procesar'
        )
        parser.add_argument(
            '--document-number',
            type=str,
            help='Número específico de documento a procesar (ej: 001-001-000000001)'
        )
        parser.add_argument(
            '--password',
            type=str,
            required=True,
            help='Contraseña del certificado digital'
        )
        parser.add_argument(
            '--environment',
            type=str,
            choices=['TEST', 'PRODUCTION'],
            default='TEST',
            help='Ambiente del SRI (por defecto: TEST)'
        )
        parser.add_argument(
            '--company-id',
            type=int,
            help='ID de empresa específica a procesar'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simular procesamiento sin enviar al SRI'
        )
        parser.add_argument(
            '--max-documents',
            type=int,
            default=10,
            help='Máximo número de documentos a procesar (por defecto: 10)'
        )
    
    def handle(self, *args, **options):
        password = options['password']
        environment = options['environment']
        document_id = options.get('document_id')
        document_number = options.get('document_number')
        company_id = options.get('company_id')
        dry_run = options.get('dry_run', False)
        max_documents = options.get('max_documents', 10)
        
        # Header del comando
        self.stdout.write('=' * 80)
        self.stdout.write(self.style.SUCCESS('🚀 PROCESADOR DE FACTURAS ELECTRÓNICAS SRI'))
        self.stdout.write('=' * 80)
        self.stdout.write(f'Ambiente: {environment}')
        self.stdout.write(f'Fecha/Hora: {timezone.now().strftime("%Y-%m-%d %H:%M:%S")}')
        if dry_run:
            self.stdout.write(self.style.WARNING('⚠️  MODO SIMULACIÓN - No se enviará al SRI'))
        self.stdout.write('-' * 80)
        
        try:
            # Obtener certificado activo
            certificate = self._get_active_certificate(environment, company_id)
            if not certificate:
                return
            
            # Verificar contraseña del certificado
            if not self._verify_certificate_password(certificate, password):
                return
            
            # Obtener documentos a procesar
            documents = self._get_documents_to_process(
                document_id, document_number, company_id, certificate.company, max_documents
            )
            
            if not documents.exists():
                self.stdout.write(
                    self.style.WARNING('⚠️ No hay documentos pendientes para procesar')
                )
                return
            
            self.stdout.write(f'📄 Documentos encontrados: {documents.count()}')
            self.stdout.write('-' * 80)
            
            # Procesar cada documento
            processor = SRIProcessor(certificate, environment)
            
            processed_count = 0
            success_count = 0
            error_count = 0
            
            for document in documents:
                processed_count += 1
                
                self.stdout.write(f'\n📋 [{processed_count}/{documents.count()}] Procesando: {document.document_number}')
                self.stdout.write(f'   Cliente: {document.customer_name}')
                self.stdout.write(f'   Total: ${document.total_amount}')
                self.stdout.write(f'   Estado actual: {document.status}')
                
                if dry_run:
                    self.stdout.write('   🔄 SIMULACIÓN - Saltando envío real al SRI')
                    continue
                
                try:
                    with transaction.atomic():
                        result = processor.process_document(document, password)
                        
                        if result['success']:
                            success_count += 1
                            self.stdout.write(
                                self.style.SUCCESS(f'   ✅ Procesado exitosamente')
                            )
                            self.stdout.write(f'   📧 Clave acceso: {result["access_key"]}')
                            
                            if result['authorization_number']:
                                self.stdout.write(f'   🔢 Autorización: {result["authorization_number"]}')
                            
                            if result['pdf_path']:
                                self.stdout.write(f'   📄 PDF generado: {result["pdf_path"]}')
                                
                        else:
                            error_count += 1
                            self.stdout.write(
                                self.style.ERROR(f'   ❌ Error en procesamiento')
                            )
                            
                            for step in result['steps']:
                                self.stdout.write(f'     📝 Paso completado: {step}')
                            
                            for error in result['errors']:
                                self.stdout.write(f'     🔸 Error: {error}')
                
                except KeyboardInterrupt:
                    self.stdout.write(
                        self.style.WARNING('\n⚠️ Procesamiento interrumpido por usuario')
                    )
                    break
                    
                except Exception as e:
                    error_count += 1
                    self.stdout.write(
                        self.style.ERROR(f'   ❌ Excepción no controlada: {str(e)}')
                    )
                    logger.error(f"Error procesando documento {document.document_number}: {str(e)}")
            
            # Resumen final
            self.stdout.write('\n' + '=' * 80)
            self.stdout.write(self.style.SUCCESS('📊 RESUMEN DE PROCESAMIENTO'))
            self.stdout.write('=' * 80)
            self.stdout.write(f'Total procesados: {processed_count}')
            self.stdout.write(f'Exitosos: {success_count}')
            self.stdout.write(f'Con errores: {error_count}')
            
            if success_count > 0:
                self.stdout.write(
                    self.style.SUCCESS(f'🎉 {success_count} documentos autorizados por el SRI')
                )
            
            if error_count > 0:
                self.stdout.write(
                    self.style.WARNING(f'⚠️ {error_count} documentos con errores - revisar logs')
                )
            
        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING('\n⚠️ Comando interrumpido por usuario')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error general en el comando: {str(e)}')
            )
            logger.error(f"Error general en process_invoices: {str(e)}")
    
    def _get_active_certificate(self, environment, company_id=None):
        """Obtiene el certificado activo para el ambiente especificado"""
        try:
            certificate_filter = {
                'status': 'ACTIVE',
                'environment': environment
            }
            
            if company_id:
                certificate_filter['company_id'] = company_id
            
            certificate = DigitalCertificate.objects.filter(**certificate_filter).first()
            
            if not certificate:
                self.stdout.write(
                    self.style.ERROR(f'❌ No hay certificado activo para ambiente {environment}')
                )
                if company_id:
                    self.stdout.write(f'   Empresa ID especificada: {company_id}')
                return None
            
            # Verificar que el certificado tenga contraseña configurada
            if not certificate.password_hash or certificate.password_hash == 'temp_hash':
                self.stdout.write(
                    self.style.ERROR('❌ Certificado sin contraseña configurada')
                )
                return None
            
            self.stdout.write(
                self.style.SUCCESS(f'✅ Certificado encontrado: {certificate.company.business_name}')
            )
            self.stdout.write(f'   Subject: {certificate.subject_name}')
            self.stdout.write(f'   Válido hasta: {certificate.valid_to}')
            
            return certificate
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error obteniendo certificado: {str(e)}')
            )
            return None
    
    def _verify_certificate_password(self, certificate, password):
        """Verifica que la contraseña del certificado sea correcta"""
        try:
            if not certificate.verify_password(password):
                self.stdout.write(
                    self.style.ERROR('❌ Contraseña incorrecta para el certificado')
                )
                return False
            
            self.stdout.write(
                self.style.SUCCESS('✅ Contraseña del certificado verificada')
            )
            return True
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error verificando contraseña: {str(e)}')
            )
            return False
    
    def _get_documents_to_process(self, document_id, document_number, company_id, certificate_company, max_documents):
        """Obtiene los documentos a procesar según los filtros especificados"""
        
        # Filtro base - documentos en borrador
        queryset = ElectronicDocument.objects.filter(status='DRAFT')
        
        # Filtros específicos
        if document_id:
            queryset = queryset.filter(id=document_id)
            self.stdout.write(f'🔍 Filtrando por ID: {document_id}')
            
        elif document_number:
            queryset = queryset.filter(document_number=document_number)
            self.stdout.write(f'🔍 Filtrando por número: {document_number}')
            
        else:
            # Si no se especifica documento específico, usar la empresa del certificado
            if company_id:
                queryset = queryset.filter(company_id=company_id)
                self.stdout.write(f'🔍 Filtrando por empresa ID: {company_id}')
            else:
                queryset = queryset.filter(company=certificate_company)
                self.stdout.write(f'🔍 Usando empresa del certificado: {certificate_company.business_name}')
            
            # Limitar cantidad
            queryset = queryset[:max_documents]
        
        # Ordenar por fecha de emisión
        queryset = queryset.order_by('issue_date', 'document_number')
        
        return queryset