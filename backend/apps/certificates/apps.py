# -*- coding: utf-8 -*-
"""
Configuración de la aplicación de certificados digitales
VERSIÓN ACTUALIZADA con GlobalCertificateManager
"""

from django.apps import AppConfig
import logging
import threading
import time

logger = logging.getLogger(__name__)


class CertificatesConfig(AppConfig):
    """
    Configuración de la app de certificados digitales
    ACTUALIZADA con integración de GlobalCertificateManager
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.certificates'
    verbose_name = 'Certificados Digitales'
    verbose_name_plural = 'Certificados Digitales'
    
    def ready(self):
        """
        Código que se ejecuta cuando la app está lista
        Integra GlobalCertificateManager para auto-gestión
        """
        try:
            logger.info("🚀 Inicializando aplicación de certificados digitales...")
            
            # 1. Importar signals para registrarlos automáticamente
            self._register_signals()
            
            # 2. Configurar logging específico para certificados
            self._setup_certificate_logging()
            
            # 3. Configurar precarga automática de certificados
            self._setup_auto_preload()
            
            # 4. Configurar limpieza automática de cache
            self._setup_auto_cleanup()
            
            logger.info("✅ Aplicación de certificados digitales inicializada correctamente")
            
        except Exception as e:
            logger.error(f"❌ Error inicializando aplicación de certificados: {e}")
    
    def _register_signals(self):
        """
        Registra los signals de certificados
        """
        try:
            import apps.certificates.signals
            logger.info("✅ Signals de certificados registrados")
        except ImportError as e:
            logger.warning(f"⚠️  No se pudieron cargar signals: {e}")
        except Exception as e:
            logger.error(f"❌ Error registrando signals: {e}")
    
    def _setup_certificate_logging(self):
        """
        Configura logging específico para certificados
        """
        try:
            # Configurar logger específico para certificados
            cert_logger = logging.getLogger('apps.certificates')
            
            if not cert_logger.handlers:
                # Handler para consola
                console_handler = logging.StreamHandler()
                console_formatter = logging.Formatter(
                    '[CERTIFICATES] %(asctime)s %(levelname)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                console_handler.setFormatter(console_formatter)
                cert_logger.addHandler(console_handler)
                cert_logger.setLevel(logging.INFO)
            
            logger.info("✅ Logging de certificados configurado")
            
        except Exception as e:
            logger.error(f"❌ Error configurando logging: {e}")
    
    def _setup_auto_preload(self):
        """
        Configura la precarga automática de certificados
        """
        try:
            from django.conf import settings
            
            # Verificar si la precarga automática está habilitada
            auto_preload = getattr(settings, 'CERTIFICATE_AUTO_PRELOAD', True)
            
            if not auto_preload:
                logger.info("📋 Precarga automática deshabilitada en settings")
                return
            
            # Configurar delay antes de precargar
            delay = getattr(settings, 'CERTIFICATE_AUTO_PRELOAD_DELAY', 2)
            
            # Ejecutar precarga en thread separado para no bloquear Django
            def delayed_preload():
                try:
                    # Esperar a que Django termine de cargar completamente
                    time.sleep(delay)
                    
                    logger.info(f"🔄 Iniciando precarga automática de certificados (delay: {delay}s)")
                    
                    # Importar y ejecutar precarga de base de datos (status)
                    from apps.certificates.signals import preload_certificates_on_startup
                    preload_certificates_on_startup()
                    
                    # Cargar certificados físicos en memoria el gestor global
                    from apps.sri_integration.services.global_certificate_manager import get_certificate_manager
                    cert_manager = get_certificate_manager()
                    cert_manager.preload_certificates()
                    
                    logger.info("✅ Precarga física de certificados en memoria completada")
                    
                except Exception as e:
                    logger.error(f"❌ Error en precarga automática: {e}")
            
            # Crear y lanzar thread
            preload_thread = threading.Thread(
                target=delayed_preload, 
                name='CertificatePreloader',
                daemon=True
            )
            preload_thread.start()
            
            logger.info("✅ Precarga automática de certificados configurada")
            
        except Exception as e:
            logger.error(f"❌ Error configurando precarga automática: {e}")
    
    def _setup_auto_cleanup(self):
        """
        Configura limpieza automática del cache de certificados
        """
        try:
            from django.conf import settings
            
            # Verificar si la limpieza automática está habilitada
            auto_cleanup = getattr(settings, 'CERTIFICATE_AUTO_CLEANUP', True)
            cleanup_interval = getattr(settings, 'CERTIFICATE_CLEANUP_INTERVAL', 300)  # 5 minutos
            
            if not auto_cleanup:
                logger.info("📋 Limpieza automática deshabilitada en settings")
                return
            
            def periodic_cleanup():
                """
                Función para limpieza periódica en background
                """
                while True:
                    try:
                        time.sleep(cleanup_interval)
                        
                        # Importar gestor y ejecutar limpieza
                        from apps.sri_integration.services.global_certificate_manager import get_certificate_manager
                        cert_manager = get_certificate_manager()
                        
                        # Limpiar certificados expirados
                        cert_manager.cleanup_expired_certificates()
                        
                        logger.debug("🧹 Limpieza automática de certificados ejecutada")
                        
                    except Exception as e:
                        logger.error(f"❌ Error en limpieza automática: {e}")
                        # Continuar ejecutando a pesar del error
                        continue
            
            # Crear thread de limpieza
            cleanup_thread = threading.Thread(
                target=periodic_cleanup,
                name='CertificateCleanup',
                daemon=True
            )
            cleanup_thread.start()
            
            logger.info(f"✅ Limpieza automática configurada (intervalo: {cleanup_interval}s)")
            
        except Exception as e:
            logger.error(f"❌ Error configurando limpieza automática: {e}")
    
    def get_certificate_manager_status(self):
        """
        Obtiene el estado del GlobalCertificateManager
        """
        try:
            from apps.sri_integration.services.global_certificate_manager import get_certificate_manager
            cert_manager = get_certificate_manager()
            return cert_manager.get_stats()
        except Exception as e:
            logger.error(f"❌ Error obteniendo estado del certificate manager: {e}")
            return {'error': str(e)}
    
    def preload_all_certificates(self, force_reload=False):
        """
        Método para precargar manualmente todos los certificados
        """
        try:
            from apps.sri_integration.services.global_certificate_manager import get_certificate_manager
            cert_manager = get_certificate_manager()
            
            if force_reload:
                cert_manager.clear_cache()
                logger.info("🗑️  Cache limpiado antes de precargar")
            
            result = cert_manager.preload_certificates()
            logger.info(f"✅ Precarga manual completada: {result}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error en precarga manual: {e}")
            return {'error': str(e)}
    
    def validate_all_certificates(self):
        """
        Valida todos los certificados configurados
        """
        try:
            from apps.companies.models import Company
            from apps.certificates.models import DigitalCertificate
            from apps.sri_integration.services.global_certificate_manager import get_certificate_manager
            
            cert_manager = get_certificate_manager()
            validation_results = []
            
            # Obtener todas las empresas con certificados
            companies = Company.objects.filter(
                is_active=True,
                digital_certificate__isnull=False
            )
            
            for company in companies:
                try:
                    is_valid, message = cert_manager.validate_certificate(company.id)
                    validation_results.append({
                        'company_id': company.id,
                        'company_name': company.business_name,
                        'is_valid': is_valid,
                        'message': message
                    })
                except Exception as e:
                    validation_results.append({
                        'company_id': company.id,
                        'company_name': company.business_name,
                        'is_valid': False,
                        'message': f'Error validating: {str(e)}'
                    })
            
            logger.info(f"✅ Validación completada para {len(validation_results)} empresas")
            return validation_results
            
        except Exception as e:
            logger.error(f"❌ Error en validación de certificados: {e}")
            return {'error': str(e)}
    
    def get_app_info(self):
        """
        Información de la aplicación de certificados
        """
        try:
            from django.conf import settings
            
            info = {
                'app_name': self.verbose_name,
                'version': '2.0.0',
                'certificate_manager': 'GlobalCertificateManager',
                'auto_preload_enabled': getattr(settings, 'CERTIFICATE_AUTO_PRELOAD', True),
                'auto_cleanup_enabled': getattr(settings, 'CERTIFICATE_AUTO_CLEANUP', True),
                'cache_timeout': getattr(settings, 'CERTIFICATE_CACHE_TIMEOUT', 3600),
                'max_cache_size': getattr(settings, 'MAX_CERTIFICATES_CACHE', 1000),
                'features': [
                    'Automatic certificate preloading',
                    'Multi-company certificate management',
                    'Certificate caching for performance',
                    'Automatic cleanup of expired certificates',
                    'Real-time certificate validation',
                    'Password-free document processing'
                ]
            }
            
            # Agregar estadísticas del gestor si está disponible
            try:
                manager_stats = self.get_certificate_manager_status()
                if 'error' not in manager_stats:
                    info['manager_stats'] = manager_stats
            except:
                pass
            
            return info
            
        except Exception as e:
            return {'error': str(e)}


# ========== FUNCIONES AUXILIARES ==========

def get_certificates_app_config():
    """
    Función helper para obtener la configuración de la app
    """
    from django.apps import apps
    return apps.get_app_config('certificates')


def preload_certificates_manually(force_reload=False):
    """
    Función helper para precargar certificados manualmente
    """
    try:
        app_config = get_certificates_app_config()
        return app_config.preload_all_certificates(force_reload)
    except Exception as e:
        logger.error(f"❌ Error en precarga manual: {e}")
        return {'error': str(e)}


def get_certificate_system_status():
    """
    Función helper para obtener estado completo del sistema de certificados
    """
    try:
        app_config = get_certificates_app_config()
        
        return {
            'app_info': app_config.get_app_info(),
            'certificate_manager_status': app_config.get_certificate_manager_status(),
            'validation_results': app_config.validate_all_certificates()
        }
    except Exception as e:
        logger.error(f"❌ Error obteniendo estado del sistema: {e}")
        return {'error': str(e)}


# ========== CONFIGURACIÓN DE LOGGING ESPECÍFICO ==========

def setup_advanced_logging():
    """
    Configuración avanzada de logging para certificados
    """
    import sys
    
    # Logger específico para esta app
    app_logger = logging.getLogger('apps.certificates')
    
    if not app_logger.handlers:
        # Handler para archivo
        try:
            import os
            log_dir = 'logs'
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            file_handler = logging.FileHandler(f'{log_dir}/certificates.log')
            file_formatter = logging.Formatter(
                '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            app_logger.addHandler(file_handler)
            
        except Exception as e:
            print(f"Warning: Could not setup file logging: {e}")
        
        # Handler para consola
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter(
            '[CERTIFICATES] %(levelname)s: %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        app_logger.addHandler(console_handler)
        
        app_logger.setLevel(logging.INFO)
        app_logger.propagate = False


# Configurar logging al importar
setup_advanced_logging()