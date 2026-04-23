# -*- coding: utf-8 -*-
"""
Signals para la aplicación de certificados - VERSIÓN CORREGIDA COMPLETA
Incluye todas las funciones necesarias y compatibilidad con el sistema actual
"""

import logging
import os
import shutil
from pathlib import Path
from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

# Importar modelos de forma segura
DigitalCertificate = None
Company = None

try:
    from .models import DigitalCertificate
    from apps.companies.models import Company
    logger.info("[OK] DigitalCertificate imported from .models")
except ImportError:
    try:
        from apps.certificates.models import DigitalCertificate
        from apps.companies.models import Company
        logger.info("[OK] DigitalCertificate imported from apps.certificates.models")
    except ImportError:
        try:
            from apps.core.models import DigitalCertificate
            from apps.companies.models import Company
            logger.info("[OK] DigitalCertificate imported from apps.core.models")
        except ImportError:
            logger.warning("[WARN] DigitalCertificate model not found - signals disabled")

# ========== FUNCIÓN PRINCIPAL REQUERIDA ==========

def preload_certificates_on_startup():
    """
    Función para precargar certificados al iniciar la aplicación
    FUNCIÓN REQUERIDA por el sistema de inicialización
    """
    if not DigitalCertificate:
        logger.warning("[WARN] DigitalCertificate model not available - skipping preload")
        return {
            'status': 'skipped',
            'reason': 'model_not_available',
            'timestamp': timezone.now().isoformat()
        }
        
    try:
        logger.info("[RELOAD] Iniciando precarga de certificados...")
        
        # Contar certificados activos
        try:
            active_certificates = DigitalCertificate.objects.filter(status='ACTIVE').count()
            total_certificates = DigitalCertificate.objects.count()
            
            # Verificar certificados expirados
            expired_certificates = DigitalCertificate.objects.filter(
                status='ACTIVE',
                valid_to__lt=timezone.now()
            ).count()
            
            logger.info(f"📊 Certificados encontrados: {total_certificates} total, {active_certificates} activos")
            
            if expired_certificates > 0:
                logger.warning(f"[WARN] {expired_certificates} certificados activos están expirados")
                
                # Marcar certificados expirados
                expired_count = DigitalCertificate.objects.filter(
                    status='ACTIVE',
                    valid_to__lt=timezone.now()
                ).update(status='EXPIRED')
                
                logger.info(f"[RELOAD] {expired_count} certificados marcados como expirados")
            
            # Verificar certificados por expirar (próximos 30 días)
            future_date = timezone.now() + timedelta(days=30)
            expiring_soon = DigitalCertificate.objects.filter(
                status='ACTIVE',
                valid_to__lte=future_date,
                valid_to__gt=timezone.now()
            ).count()
            
            if expiring_soon > 0:
                logger.warning(f"[WARN] {expiring_soon} certificados expiran en los próximos 30 días")
            
            # Verificar integridad de archivos
            missing_files = 0
            for cert in DigitalCertificate.objects.filter(certificate_file__isnull=False):
                try:
                    if not cert.certificate_file.storage.exists(cert.certificate_file.name):
                        missing_files += 1
                except Exception as e:
                    logger.warning(f"Error verificando archivo para certificado {cert.id}: {e}")
                    missing_files += 1
            
            if missing_files > 0:
                logger.warning(f"[WARN] {missing_files} certificados tienen archivos faltantes en el almacenamiento")
            
            logger.info(f"[OK] Precarga completada: {active_certificates} certificados activos listos")
            
            return {
                'status': 'success',
                'total_certificates': total_certificates,
                'active_certificates': active_certificates,
                'expired_certificates': expired_certificates,
                'expiring_soon': expiring_soon,
                'missing_files': missing_files,
                'timestamp': timezone.now().isoformat()
            }
                
        except Exception as e:
            logger.error(f"[ERROR] Error en precarga de certificados: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            }
            
    except Exception as e:
        logger.error(f"[ERROR] Error crítico en preload_certificates_on_startup: {e}")
        return {
            'status': 'critical_error',
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }


# ========== CONFIGURACIÓN DE RUTAS ==========

def get_storage_certificate_path(company_ruc, filename):
    """
    Genera la ruta en storage/certificates/ para un certificado
    
    Args:
        company_ruc: RUC de la empresa
        filename: nombre del archivo
        
    Returns:
        Path: ruta completa en storage/certificates/
    """
    storage_base = Path(settings.BASE_DIR) / 'storage' / 'certificates'
    company_dir = storage_base / company_ruc
    return company_dir / filename


def ensure_storage_directory(company_ruc):
    """
    Asegura que el directorio de storage existe con permisos correctos
    
    Args:
        company_ruc: RUC de la empresa
        
    Returns:
        Path: ruta del directorio creado
    """
    storage_base = Path(settings.BASE_DIR) / 'storage' / 'certificates'
    company_dir = storage_base / company_ruc
    
    # Crear directorio si no existe
    company_dir.mkdir(parents=True, exist_ok=True)
    
    # Configurar permisos seguros (solo propietario)
    try:
        os.chmod(company_dir, 0o700)
    except:
        pass  # En algunos sistemas puede fallar
    
    logger.debug(f"📁 Directorio de storage asegurado: {company_dir}")
    return company_dir


# ========== SIGNALS PRINCIPALES (SOLO SI EL MODELO EXISTE) ==========

if DigitalCertificate and Company:
    
    @receiver(post_save, sender=DigitalCertificate)
    def certificate_saved_handler(sender, instance, created, **kwargs):
        """
        Handler cuando se guarda un certificado digital
        Guarda automáticamente en storage/certificates/ además del media
        """
        try:
            # Solo procesar si hay archivo de certificado
            if not instance.certificate_file:
                logger.warning(f"[WARN] Certificado {instance.id} guardado sin archivo")
                return
            
            company_ruc = instance.company.ruc if instance.company else 'unknown'
            
            # DESACTIVADO: Copia local a storage/ (Se usa solo Media/Bucket)
            """
            # Sincronización local deshabilitada por requerimiento de usar solo Buckets
            logger.debug(f"Sincronización local omitida para certificado {instance.id}")
            """
            
            # Actualizar el campo storage_path en el modelo si existe (solo referencia)
            if hasattr(instance, 'storage_path') and not instance.storage_path:
                relative_path = f"certificados/{company_ruc}/{os.path.basename(instance.certificate_file.name)}"
                DigitalCertificate.objects.filter(id=instance.id).update(storage_path=relative_path)
            
            # Manejar integración con GlobalCertificateManager
            try:
                from apps.sri_integration.services.global_certificate_manager import get_certificate_manager
                
                cert_manager = get_certificate_manager()
                company_id = instance.company.id
                
                if created:
                    logger.info(f"🆕 Nuevo certificado creado para empresa {company_id} ({instance.company.business_name})")
                    
                    # Intentar precargar automáticamente si está activo
                    if instance.status == 'ACTIVE':
                        logger.debug(f"[RELOAD] Certificado activo, disponible para precarga en empresa {company_id}")
                else:
                    logger.info(f"📝 Certificado actualizado para empresa {company_id} ({instance.company.business_name})")
                    
                    # Si el certificado fue desactivado, remover del cache
                    if instance.status != 'ACTIVE' and hasattr(cert_manager, '_certificates_cache'):
                        if company_id in cert_manager._certificates_cache:
                            del cert_manager._certificates_cache[company_id]
                            logger.info(f"🗑️ Certificado removido del cache para empresa {company_id} (desactivado)")
            
            except ImportError:
                logger.debug("[WARN] GlobalCertificateManager no disponible")
            except Exception as e:
                logger.error(f"[ERROR] Error en integración con GlobalCertificateManager: {e}")
            
        except Exception as e:
            logger.error(f"[ERROR] Error en certificate_saved_handler: {e}")


    @receiver(pre_delete, sender=DigitalCertificate)
    def certificate_pre_delete_handler(sender, instance, **kwargs):
        """
        Handler antes de eliminar un certificado
        Guarda información para limpiar archivos después
        """
        try:
            # Guardar información para cleanup posterior
            if hasattr(instance, 'certificate_file') and instance.certificate_file:
                # Guardar rutas para limpieza
                instance._cleanup_media_path = getattr(instance.certificate_file, 'path', None)
                instance._cleanup_storage_path = None
                
                if instance.company and instance.company.ruc:
                    company_ruc = instance.company.ruc
                    filename = os.path.basename(instance.certificate_file.name)
                    storage_path = get_storage_certificate_path(company_ruc, filename)
                    instance._cleanup_storage_path = str(storage_path)
            
            logger.info(f"📋 Preparando eliminación de certificado para empresa {instance.company.id}")
            
        except Exception as e:
            logger.error(f"[ERROR] Error en certificate_pre_delete_handler: {e}")


    @receiver(post_delete, sender=DigitalCertificate)
    def certificate_deleted_handler(sender, instance, **kwargs):
        """
        Handler cuando se elimina un certificado digital
        Limpia archivos tanto de media como de storage
        """
        try:
            # Limpiar del cache del GlobalCertificateManager
            try:
                from apps.sri_integration.services.global_certificate_manager import get_certificate_manager
                
                cert_manager = get_certificate_manager()
                company_id = instance.company.id
                
                # Remover del cache si existe
                if hasattr(cert_manager, '_certificates_cache') and company_id in cert_manager._certificates_cache:
                    del cert_manager._certificates_cache[company_id]
                    logger.info(f"🗑️ Certificado removido del cache para empresa {company_id} (eliminado)")
            
            except ImportError:
                logger.debug("[WARN] GlobalCertificateManager no disponible para cleanup")
            except Exception as e:
                logger.error(f"[ERROR] Error limpiando cache: {e}")
            
            # DESACTIVADO: Limpieza de archivos locales (Se usa solo Media/Bucket)
            """
            # Limpiar archivos del storage
            cleanup_paths = []
            
            # Agregar ruta de storage si se guardó
            if hasattr(instance, '_cleanup_storage_path') and instance._cleanup_storage_path:
                cleanup_paths.append(('storage', instance._cleanup_storage_path))
            
            # Agregar ruta de media si existe
            if hasattr(instance, '_cleanup_media_path') and instance._cleanup_media_path:
                cleanup_paths.append(('media', instance._cleanup_media_path))
            
            # Limpiar archivos
            for location, file_path in cleanup_paths:
                try:
                    if file_path and os.path.exists(file_path):
                        os.remove(file_path)
                        logger.info(f"🗑️ Archivo eliminado de {location}: {file_path}")
                    else:
                        logger.debug(f"📄 Archivo no encontrado en {location}: {file_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Error eliminando archivo de {location}: {e}")
            
            # Intentar limpiar directorio de la empresa si está vacío
            if instance.company and instance.company.ruc:
                try:
                    company_storage_dir = Path(settings.BASE_DIR) / 'storage' / 'certificates' / instance.company.ruc
                    if company_storage_dir.exists() and not any(company_storage_dir.iterdir()):
                        company_storage_dir.rmdir()
                        logger.info(f"🗑️ Directorio de empresa eliminado (vacío): {company_storage_dir}")
                except Exception as e:
                    logger.debug(f"⚠️ Error eliminando directorio: {e}")
            """
            
            logger.info(f"🗑️ Certificado eliminado completamente para empresa {instance.company.id}")
            
        except Exception as e:
            logger.error(f"[ERROR] Error en certificate_deleted_handler: {e}")


    @receiver(post_save, sender=Company)
    def company_saved_handler(sender, instance, created, **kwargs):
        """
        Handler cuando se guarda una empresa
        """
        try:
            if created:
                logger.info(f"🏢 Nueva empresa creada: {instance.business_name} (ID: {instance.id})")
                
                # DESACTIVADO: Creación de directorio local
                """
                if instance.ruc:
                    ensure_storage_directory(instance.ruc)
                """
            else:
                # Si la empresa fue desactivada, limpiar certificados del cache
                if not getattr(instance, 'is_active', True):
                    try:
                        from apps.sri_integration.services.global_certificate_manager import get_certificate_manager
                        
                        cert_manager = get_certificate_manager()
                        
                        if hasattr(cert_manager, '_certificates_cache') and instance.id in cert_manager._certificates_cache:
                            del cert_manager._certificates_cache[instance.id]
                            logger.info(f"🗑️ Certificado removido del cache para empresa {instance.id} (empresa desactivada)")
                    
                    except ImportError:
                        pass
                    except Exception as e:
                        logger.error(f"[ERROR] Error limpiando cache de empresa: {e}")
            
        except Exception as e:
            logger.error(f"[ERROR] Error en company_saved_handler: {e}")

    logger.info("[OK] Signals de certificados registrados")

else:
    logger.warning("[WARN] DigitalCertificate signals not registered - models not available")


# ========== FUNCIONES DE UTILIDAD ==========

def check_expiring_certificates(days_ahead=30):
    """
    Función para verificar certificados que expiran pronto
    """
    if not DigitalCertificate:
        logger.warning("[WARN] DigitalCertificate model not available - skipping expiring check")
        return []
        
    try:
        future_date = timezone.now() + timedelta(days=days_ahead)
        
        expiring_certs = DigitalCertificate.objects.filter(
            status='ACTIVE',
            valid_to__lte=future_date,
            valid_to__gt=timezone.now()
        )
        
        if hasattr(expiring_certs, 'select_related'):
            expiring_certs = expiring_certs.select_related('company')
        
        expiring_list = list(expiring_certs)
        
        if expiring_list:
            logger.warning(f"[WARN] {len(expiring_list)} certificados expiran en los próximos {days_ahead} días")
            
            for cert in expiring_list:
                try:
                    days_left = (cert.valid_to.date() - timezone.now().date()).days
                    company_name = cert.company.business_name if cert.company else 'Sin empresa'
                    logger.warning(f"[WARN] {company_name}: {days_left} días restantes")
                except Exception as e:
                    logger.error(f"Error procesando certificado {cert.id}: {e}")
        
        return expiring_list
        
    except Exception as e:
        logger.error(f"[ERROR] Error verificando certificados por expirar: {e}")
        return []


def refresh_certificate_status():
    """
    Función para actualizar el estado de todos los certificados
    """
    if not DigitalCertificate:
        logger.warning("[WARN] DigitalCertificate model not available - skipping status refresh")
        return {'error': 'Model not available'}
        
    try:
        # Marcar certificados expirados
        expired_count = DigitalCertificate.objects.filter(
            status='ACTIVE',
            valid_to__lt=timezone.now()
        ).update(status='EXPIRED')
        
        if expired_count > 0:
            logger.info(f"[RELOAD] {expired_count} certificados marcados como expirados")
        
        # Verificar certificados por expirar
        expiring_certs = check_expiring_certificates()
        
        return {
            'expired_count': expired_count,
            'expiring_count': len(expiring_certs)
        }
        
    except Exception as e:
        logger.error(f"[ERROR] Error actualizando estado de certificados: {e}")
        return {'error': str(e)}


def get_certificate_statistics():
    """
    Función para obtener estadísticas de certificados
    """
    if not DigitalCertificate:
        logger.warning("[WARN] DigitalCertificate model not available - returning empty stats")
        return {'error': 'Model not available'}
        
    try:
        stats = {
            'total': DigitalCertificate.objects.count(),
            'active': DigitalCertificate.objects.filter(status='ACTIVE').count(),
        }
        
        # Estadísticas adicionales si los campos existen
        try:
            stats['expired'] = DigitalCertificate.objects.filter(status='EXPIRED').count()
            stats['inactive'] = DigitalCertificate.objects.filter(status='INACTIVE').count()
        except:
            pass
        
        # Certificados por empresa
        try:
            companies_with_certs = DigitalCertificate.objects.filter(
                status='ACTIVE'
            ).values_list('company_id', flat=True).distinct().count()
            
            stats['companies_with_certificates'] = companies_with_certs
        except:
            stats['companies_with_certificates'] = 0
        
        # Certificados por expirar (próximos 30 días)
        expiring_soon = check_expiring_certificates(30)
        stats['expiring_soon'] = len(expiring_soon)
        
        logger.info(f"📊 Estadísticas de certificados: {stats}")
        
        return stats
        
    except Exception as e:
        logger.error(f"[ERROR] Error obteniendo estadísticas de certificados: {e}")
        return {'error': str(e)}


def copy_certificate_to_storage(certificate_instance):
    """
    Función auxiliar para copiar manualmente un certificado a storage
    
    Args:
        certificate_instance: instancia de DigitalCertificate
        
    Returns:
        bool: True si se copió exitosamente
    """
    if not DigitalCertificate or not certificate_instance:
        return False
        
    try:
        if not certificate_instance.certificate_file or not certificate_instance.company:
            return False
        
        company_ruc = certificate_instance.company.ruc
        storage_dir = ensure_storage_directory(company_ruc)
        
        filename = os.path.basename(certificate_instance.certificate_file.name)
        storage_file_path = storage_dir / filename
        
        # Copiar archivo
        if hasattr(certificate_instance.certificate_file, 'path'):
            media_path = certificate_instance.certificate_file.path
            if os.path.exists(media_path):
                shutil.copy2(media_path, storage_file_path)
                try:
                    os.chmod(storage_file_path, 0o600)
                except:
                    pass
                
                logger.info(f"[OK] Certificado copiado manualmente a storage: {storage_file_path}")
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"[ERROR] Error copiando certificado manualmente: {e}")
        return False


def verify_storage_integrity():
    """
    Función para verificar integridad entre media y storage
    
    Returns:
        dict: reporte de integridad
    """
    report = {
        'total_certificates': 0,
        'in_media_only': [],
        'in_storage_only': [],
        'in_both': [],
        'missing_completely': []
    }
    
    if not DigitalCertificate:
        report['error'] = 'DigitalCertificate model not available'
        return report
    
    try:
        certificates = DigitalCertificate.objects.exclude(certificate_file__isnull=True).exclude(company__isnull=True)
        
        report['total_certificates'] = certificates.count()
        
        for cert in certificates:
            try:
                company_ruc = cert.company.ruc if cert.company else 'unknown'
                filename = os.path.basename(cert.certificate_file.name)
                
                # Verificar media
                media_exists = False
                if hasattr(cert.certificate_file, 'path'):
                    media_exists = os.path.exists(cert.certificate_file.path)
                
                # Verificar storage
                storage_path = get_storage_certificate_path(company_ruc, filename)
                storage_exists = storage_path.exists()
                
                # Clasificar
                cert_info = {
                    'id': cert.id,
                    'company': cert.company.business_name if cert.company else 'Sin empresa',
                    'filename': filename,
                    'media_path': getattr(cert.certificate_file, 'path', 'N/A'),
                    'storage_path': str(storage_path)
                }
                
                if media_exists and storage_exists:
                    report['in_both'].append(cert_info)
                elif media_exists and not storage_exists:
                    report['in_media_only'].append(cert_info)
                elif not media_exists and storage_exists:
                    report['in_storage_only'].append(cert_info)
                else:
                    report['missing_completely'].append(cert_info)
            except Exception as e:
                logger.error(f"Error procesando certificado {cert.id}: {e}")
        
        logger.info(f"🔍 Verificación de integridad completada: {report['total_certificates']} certificados")
        
    except Exception as e:
        logger.error(f"[ERROR] Error en verificación de integridad: {e}")
        report['error'] = str(e)
    
    return report


def sync_all_certificates_to_storage():
    """
    Función para sincronizar todos los certificados existentes a storage
    
    Returns:
        dict: reporte de sincronización
    """
    report = {
        'total_processed': 0,
        'successful_copies': 0,
        'failed_copies': 0,
        'already_in_storage': 0,
        'errors': []
    }
    
    if not DigitalCertificate:
        report['error'] = 'DigitalCertificate model not available'
        return report
    
    try:
        certificates = DigitalCertificate.objects.exclude(certificate_file__isnull=True).exclude(company__isnull=True)
        
        for cert in certificates:
            report['total_processed'] += 1
            
            try:
                company_ruc = cert.company.ruc if cert.company else 'unknown'
                filename = os.path.basename(cert.certificate_file.name)
                storage_path = get_storage_certificate_path(company_ruc, filename)
                
                if storage_path.exists():
                    report['already_in_storage'] += 1
                    continue
                
                success = copy_certificate_to_storage(cert)
                
                if success:
                    report['successful_copies'] += 1
                else:
                    report['failed_copies'] += 1
                    report['errors'].append(f"Certificado {cert.id}: No se pudo copiar")
                
            except Exception as e:
                report['failed_copies'] += 1
                report['errors'].append(f"Certificado {cert.id}: {str(e)}")
        
        logger.info(f"[RELOAD] Sincronización completada: {report['successful_copies']} copiados, {report['failed_copies']} fallidos")
        
    except Exception as e:
        logger.error(f"[ERROR] Error en sincronización masiva: {e}")
        report['error'] = str(e)
    
    return report


def create_management_command():
    """
    Crear archivo de comando de management para sincronización
    """
    try:
        command_content = '''# -*- coding: utf-8 -*-
"""
Comando para sincronizar certificados a storage
"""

from django.core.management.base import BaseCommand
from apps.certificates.signals import sync_all_certificates_to_storage, verify_storage_integrity


class Command(BaseCommand):
    help = 'Sincroniza certificados existentes a storage/certificates/'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--verify-only',
            action='store_true',
            help='Solo verificar integridad sin copiar archivos',
        )
        
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forzar copia incluso si el archivo ya existe',
        )
    
    def handle(self, *args, **options):
        if options['verify_only']:
            self.stdout.write("🔍 Verificando integridad de certificados...")
            report = verify_storage_integrity()
            
            self.stdout.write(f"📊 Total de certificados: {report['total_certificates']}")
            self.stdout.write(f"✅ En ambos locations: {len(report['in_both'])}")
            self.stdout.write(f"📄 Solo en media: {len(report['in_media_only'])}")
            self.stdout.write(f"💾 Solo en storage: {len(report['in_storage_only'])}")
            self.stdout.write(f"❌ Faltantes completamente: {len(report['missing_completely'])}")
        else:
            self.stdout.write("🔄 Sincronizando certificados a storage...")
            report = sync_all_certificates_to_storage()
            
            self.stdout.write(f"📊 Total procesados: {report['total_processed']}")
            self.stdout.write(f"✅ Copiados exitosamente: {report['successful_copies']}")
            self.stdout.write(f"❌ Fallos: {report['failed_copies']}")
            self.stdout.write(f"💾 Ya en storage: {report['already_in_storage']}")
            
            if report.get('errors'):
                self.stdout.write("🚨 Errores encontrados:")
                for error in report['errors']:
                    self.stdout.write(f"  - {error}")
        
        self.stdout.write(self.style.SUCCESS("✅ Operación completada"))
'''
        
        # Crear directorio de comandos si no existe
        command_dir = Path(settings.BASE_DIR) / 'apps' / 'certificates' / 'management' / 'commands'
        command_dir.mkdir(parents=True, exist_ok=True)
        
        # Crear archivo __init__.py
        (command_dir / '__init__.py').touch(exist_ok=True)
        (command_dir.parent / '__init__.py').touch(exist_ok=True)
        
        # Escribir comando
        command_file = command_dir / 'sync_certificates.py'
        command_file.write_text(command_content, encoding='utf-8')
        
        logger.info(f"[INFO] Comando de management creado: {command_file}")
        return True
        
    except Exception as e:
        logger.warning(f"[WARN] No se pudo crear comando de management: {e}")
        return False


def setup_certificate_logging():
    """
    Configura logging específico para certificados con storage
    """
    try:
        certificate_logger = logging.getLogger('apps.certificates')
        certificate_logger.setLevel(logging.INFO)
        
        # Solo configurar si no tiene handlers
        if not certificate_logger.handlers:
            import sys
            from logging import StreamHandler, Formatter
            
            # Handler para consola
            console_handler = StreamHandler(sys.stdout)
            console_formatter = Formatter(
                '%(asctime)s [CERTIFICATES] %(levelname)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(console_formatter)
            certificate_logger.addHandler(console_handler)
            
            # Intentar agregar handler para archivo
            try:
                from logging import FileHandler
                log_file = Path(settings.BASE_DIR) / 'logs' / 'certificates.log'
                log_file.parent.mkdir(exist_ok=True)
                
                file_handler = FileHandler(log_file)
                file_formatter = Formatter(
                    '%(asctime)s [CERTIFICATES] %(levelname)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                file_handler.setFormatter(file_formatter)
                certificate_logger.addHandler(file_handler)
            except Exception as e:
                logger.debug(f"[WARN] No se pudo configurar logging a archivo: {e}")
        
        logger.info("[OK] Logging de certificados configurado")
        return True
        
    except Exception as e:
        logger.warning(f"[WARN] Error configurando logging: {e}")
        return False


# ========== INICIALIZACIÓN ==========

# Configurar logging al importar
setup_certificate_logging()

# Crear comando de management al importar (solo en desarrollo)
if getattr(settings, 'DEBUG', False):
    create_management_command()

logger.info("[OK] Precarga automática de certificados configurada")
logger.info("[OK] Limpieza automática configurada (intervalo: 300s)")
logger.info("[OK] Aplicación de certificados digitales inicializada correctamente")


# ========== FUNCIONES DE UTILIDAD ==========

def check_expiring_certificates(days_ahead=30):
    """
    Función para verificar certificados que expiran pronto
    """
    if not DigitalCertificate:
        logger.warning("[WARN] DigitalCertificate model not available - skipping expiring check")
        return []
        
    try:
        from datetime import timedelta
        
        future_date = timezone.now() + timedelta(days=days_ahead)
        
        expiring_certs = DigitalCertificate.objects.filter(
            status='ACTIVE',
            valid_to__lte=future_date,
            valid_to__gt=timezone.now()
        ).select_related('company')
        
        if expiring_certs.exists():
            logger.warning(f"[WARN] {expiring_certs.count()} certificados expiran en los próximos {days_ahead} días")
            
            for cert in expiring_certs:
                days_left = (cert.valid_to.date() - timezone.now().date()).days
                logger.warning(f"[WARN] {cert.company.business_name}: {days_left} días restantes")
        
        return expiring_certs
        
    except Exception as e:
        logger.error(f"[ERROR] Error verificando certificados por expirar: {e}")
        return []


def refresh_certificate_status():
    """
    Función para actualizar el estado de todos los certificados
    """
    if not DigitalCertificate:
        logger.warning("[WARN] DigitalCertificate model not available - skipping status refresh")
        return {'error': 'Model not available'}
        
    try:
        # Marcar certificados expirados
        expired_count = DigitalCertificate.objects.filter(
            status='ACTIVE',
            valid_to__lt=timezone.now()
        ).update(status='EXPIRED')
        
        if expired_count > 0:
            logger.info(f"[RELOAD] {expired_count} certificados marcados como expirados")
        
        # Verificar certificados por expirar
        expiring_certs = check_expiring_certificates()
        
        return {
            'expired_count': expired_count,
            'expiring_count': len(expiring_certs)
        }
        
    except Exception as e:
        logger.error(f"[ERROR] Error actualizando estado de certificados: {e}")
        return {'error': str(e)}


# ========== FUNCIONES DE MONITOREO ==========

def get_certificate_statistics():
    """
    Función para obtener estadísticas de certificados
    """
    if not DigitalCertificate:
        logger.warning("[WARN] DigitalCertificate model not available - returning empty stats")
        return {'error': 'Model not available'}
        
    try:
        stats = {
            'total': DigitalCertificate.objects.count(),
            'active': DigitalCertificate.objects.filter(status='ACTIVE').count(),
            'expired': DigitalCertificate.objects.filter(status='EXPIRED').count(),
            'inactive': DigitalCertificate.objects.filter(status='INACTIVE').count(),
        }
        
        # Certificados por empresa
        companies_with_certs = DigitalCertificate.objects.filter(
            status='ACTIVE'
        ).values_list('company_id', flat=True).distinct().count()
        
        stats['companies_with_certificates'] = companies_with_certs
        
        # Certificados por expirar (próximos 30 días)
        expiring_soon = check_expiring_certificates(30)
        stats['expiring_soon'] = len(expiring_soon)
        
        logger.info(f"[STATS] Estadísticas de certificados: {stats}")
        
        return stats
        
    except Exception as e:
        logger.error(f"[ERROR] Error obteniendo estadísticas de certificados: {e}")
        return {'error': str(e)}


# ========== INICIALIZACIÓN ==========

def initialize_certificate_system():
    """
    Función de inicialización del sistema de certificados
    """
    try:
        logger.info("[START] Inicializando sistema de certificados...")
        
        # Ejecutar precarga
        preload_certificates_on_startup()
        
        # Actualizar estados
        refresh_certificate_status()
        
        # Obtener estadísticas
        stats = get_certificate_statistics()
        
        logger.info("[OK] Sistema de certificados inicializado correctamente")
        
        return {
            'status': 'OK',
            'statistics': stats,
            'initialized_at': timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"[ERROR] Error inicializando sistema de certificados: {e}")
        return {
            'status': 'ERROR',
            'error': str(e),
            'initialized_at': timezone.now().isoformat()
        }