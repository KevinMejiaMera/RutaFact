# -*- coding: utf-8 -*-
"""
Comando de gestión para precargar certificados en GlobalCertificateManager
apps/sri_integration/management/commands/preload_certificates.py
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from apps.sri_integration.services.global_certificate_manager import get_certificate_manager
from apps.companies.models import Company
from apps.certificates.models import DigitalCertificate
import logging
import os

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Precarga certificados digitales en el GlobalCertificateManager'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--company-id',
            type=int,
            help='ID de empresa específica para precargar'
        )
        
        parser.add_argument(
            '--all',
            action='store_true',
            help='Precargar certificados de todas las empresas activas'
        )
        
        parser.add_argument(
            '--force-reload',
            action='store_true',
            help='Forzar recarga de certificados ya cacheados'
        )
        
        parser.add_argument(
            '--validate-only',
            action='store_true',
            help='Solo validar certificados sin cargarlos'
        )
        
        parser.add_argument(
            '--stats',
            action='store_true',
            help='Mostrar estadísticas del GlobalCertificateManager'
        )
        
        parser.add_argument(
            '--clear-cache',
            action='store_true',
            help='Limpiar cache de certificados antes de precargar'
        )
    
    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('🚀 GlobalCertificateManager - Sistema de Gestión de Certificados')
        )
        self.stdout.write('=' * 80)
        
        cert_manager = get_certificate_manager()
        
        # Mostrar estadísticas
        if options['stats']:
            self._show_stats(cert_manager)
            return
        
        # Limpiar cache si se solicita
        if options['clear_cache']:
            self._clear_cache(cert_manager)
        
        # Validar solo
        if options['validate_only']:
            self._validate_certificates()
            return
        
        # Determinar qué empresas procesar
        companies_to_process = self._get_companies_to_process(options)
        
        if not companies_to_process:
            self.stdout.write(
                self.style.WARNING('❌ No se encontraron empresas para procesar')
            )
            return
        
        # Precargar certificados
        self._preload_certificates(cert_manager, companies_to_process, options)
        
        # Mostrar estadísticas finales
        self._show_final_stats(cert_manager)
    
    def _get_companies_to_process(self, options):
        """Determina qué empresas procesar"""
        companies = []
        
        if options['company_id']:
            try:
                company = Company.objects.get(id=options['company_id'], is_active=True)
                companies = [company]
                self.stdout.write(f"📋 Procesando empresa específica: {company.business_name}")
            except Company.DoesNotExist:
                raise CommandError(f"Empresa con ID {options['company_id']} no encontrada")
        
        elif options['all']:
            companies = Company.objects.filter(
                is_active=True,
                digital_certificate__isnull=False,
                digital_certificate__status='ACTIVE'
            ).distinct()
            self.stdout.write(f"📋 Procesando todas las empresas activas: {companies.count()}")
        
        else:
            self.stdout.write(
                self.style.WARNING('❓ Especifica --company-id ID o --all para procesar todas')
            )
            return []
        
        return companies
    
    def _preload_certificates(self, cert_manager, companies, options):
        """Precarga certificados de las empresas especificadas"""
        self.stdout.write('\n🔄 Iniciando precarga de certificados...')
        
        total_companies = len(companies)
        loaded_count = 0
        failed_count = 0
        already_cached_count = 0
        
        for i, company in enumerate(companies, 1):
            self.stdout.write(f"\n📦 [{i}/{total_companies}] Procesando: {company.business_name}")
            
            try:
                # Verificar si ya está cacheado
                cert_data = cert_manager._certificates_cache.get(company.id)
                
                if cert_data and not options['force_reload']:
                    self.stdout.write(f"   ✅ Ya está cacheado (última uso: {cert_data.last_used})")
                    already_cached_count += 1
                    continue
                
                # Cargar certificado
                if options['force_reload'] and company.id in cert_manager._certificates_cache:
                    del cert_manager._certificates_cache[company.id]
                    self.stdout.write("   🔄 Forzando recarga...")
                
                # Intentar cargar
                result = cert_manager._load_certificate(company.id)
                
                if result:
                    loaded_count += 1
                    cert_info = cert_manager.get_company_certificate_info(company.id)
                    self.stdout.write(
                        self.style.SUCCESS(f"   ✅ Cargado exitosamente")
                    )
                    if cert_info:
                        self.stdout.write(f"      📋 Subject: {cert_info['subject']}")
                        self.stdout.write(f"      📅 Expira en: {cert_info['days_until_expiration']} días")
                        self.stdout.write(f"      🌍 Ambiente: {cert_info['environment']}")
                else:
                    failed_count += 1
                    self.stdout.write(
                        self.style.ERROR(f"   ❌ Error cargando certificado")
                    )
                    
                    # Intentar obtener más detalles del error
                    try:
                        certificate = DigitalCertificate.objects.get(
                            company=company,
                            status='ACTIVE'
                        )
                        self.stdout.write(f"      📄 Archivo: {certificate.certificate_file}")
                        
                        import os
                        if certificate.certificate_file and certificate.certificate_file.storage.exists(certificate.certificate_file.name):
                            self.stdout.write("      📁 Archivo existe en el almacenamiento")
                        else:
                            self.stdout.write("      ❌ Archivo no encontrado en el almacenamiento")
                            
                    except DigitalCertificate.DoesNotExist:
                        self.stdout.write("      ❌ No hay certificado digital configurado")
                    except Exception as e:
                        self.stdout.write(f"      ⚠️  Error verificando: {e}")
                
            except Exception as e:
                failed_count += 1
                self.stdout.write(
                    self.style.ERROR(f"   ❌ Error: {str(e)}")
                )
                logger.error(f"Error preloading certificate for company {company.id}: {e}")
        
        # Resumen
        self.stdout.write('\n' + '=' * 80)
        self.stdout.write(
            self.style.SUCCESS(f"📊 RESUMEN DE PRECARGA:")
        )
        self.stdout.write(f"   📦 Total empresas: {total_companies}")
        self.stdout.write(f"   ✅ Cargados exitosamente: {loaded_count}")
        self.stdout.write(f"   💾 Ya cacheados: {already_cached_count}")
        self.stdout.write(f"   ❌ Fallidos: {failed_count}")
        
        success_rate = ((loaded_count + already_cached_count) / total_companies * 100) if total_companies > 0 else 0
        self.stdout.write(f"   📈 Tasa de éxito: {success_rate:.1f}%")
    
    def _validate_certificates(self):
        """Valida certificados sin cargarlos"""
        self.stdout.write('\n🔍 Validando certificados...')
        
        companies = Company.objects.filter(
            is_active=True,
            digital_certificate__isnull=False
        )
        
        valid_count = 0
        invalid_count = 0
        
        for company in companies:
            try:
                certificate = DigitalCertificate.objects.get(
                    company=company,
                    status='ACTIVE'
                )
                
                # Validaciones básicas
                issues = []
                
                # Verificar archivo
                if not certificate.certificate_file:
                    issues.append("No hay archivo de certificado")
                elif not certificate.certificate_file.storage.exists(certificate.certificate_file.name):
                    issues.append("Archivo de certificado no encontrado")
                
                # Verificar fechas
                if certificate.is_expired:
                    issues.append("Certificado expirado")
                elif certificate.days_until_expiration <= 30:
                    issues.append(f"Expira en {certificate.days_until_expiration} días")
                
                # Verificar password
                if not certificate.password_hash or certificate.password_hash == 'temp_hash':
                    issues.append("Password no configurado")
                
                if issues:
                    invalid_count += 1
                    self.stdout.write(f"❌ {company.business_name}:")
                    for issue in issues:
                        self.stdout.write(f"   - {issue}")
                else:
                    valid_count += 1
                    self.stdout.write(f"✅ {company.business_name}: OK")
                
            except DigitalCertificate.DoesNotExist:
                invalid_count += 1
                self.stdout.write(f"❌ {company.business_name}: Sin certificado digital")
        
        self.stdout.write(f"\n📊 VALIDACIÓN: {valid_count} válidos, {invalid_count} con problemas")
    
    def _clear_cache(self, cert_manager):
        """Limpia el cache de certificados"""
        cleared_count = cert_manager.clear_cache()
        self.stdout.write(
            self.style.WARNING(f"🗑️  Cache limpiado: {cleared_count} certificados removidos")
        )
    
    def _show_stats(self, cert_manager):
        """Muestra estadísticas del GlobalCertificateManager"""
        stats = cert_manager.get_stats()
        
        self.stdout.write('\n📊 ESTADÍSTICAS DEL GlobalCertificateManager:')
        self.stdout.write('=' * 60)
        
        # Información del cache
        self.stdout.write(f"💾 Cache:")
        self.stdout.write(f"   Certificados cacheados: {stats['cache_size']}")
        self.stdout.write(f"   Capacidad máxima: {stats['max_cache_size']}")
        self.stdout.write(f"   Utilización: {stats['cache_utilization']:.1f}%")
        
        # Estadísticas de uso
        statistics = stats['statistics']
        self.stdout.write(f"\n📈 Estadísticas de uso:")
        self.stdout.write(f"   Certificados cargados: {statistics['certificates_loaded']}")
        self.stdout.write(f"   Cache hits: {statistics['cache_hits']}")
        self.stdout.write(f"   Cache misses: {statistics['cache_misses']}")
        self.stdout.write(f"   Errores: {statistics['errors']}")
        
        if statistics['cache_hits'] + statistics['cache_misses'] > 0:
            hit_rate = statistics['cache_hits'] / (statistics['cache_hits'] + statistics['cache_misses']) * 100
            self.stdout.write(f"   Tasa de acierto: {hit_rate:.1f}%")
        
        # Certificados cacheados
        cached_certs = stats.get('cached_certificates', {})
        if cached_certs:
            self.stdout.write(f"\n🔐 Certificados actualmente cacheados:")
            for company_id, cert_info in cached_certs.items():
                self.stdout.write(f"   📋 Empresa {company_id}: {cert_info['company_name']}")
                self.stdout.write(f"      Usado {cert_info['usage_count']} veces")
                self.stdout.write(f"      Expira en {cert_info['expires_in_days']} días")
    
    def _show_final_stats(self, cert_manager):
        """Muestra estadísticas finales después de la precarga"""
        stats = cert_manager.get_stats()
        
        self.stdout.write('\n📊 ESTADO FINAL DEL CACHE:')
        self.stdout.write(f"   💾 Certificados en cache: {stats['cache_size']}")
        self.stdout.write(f"   📈 Total cargados en sesión: {stats['statistics']['certificates_loaded']}")
        
        if stats['cache_size'] > 0:
            self.stdout.write(
                self.style.SUCCESS('\n✅ GlobalCertificateManager listo para procesar documentos SIN PASSWORDS')
            )
        else:
            self.stdout.write(
                self.style.WARNING('\n⚠️  No hay certificados cacheados - verificar configuración')
            )
        
        self.stdout.write('=' * 80)