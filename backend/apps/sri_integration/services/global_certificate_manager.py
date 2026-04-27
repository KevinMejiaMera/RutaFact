# -*- coding: utf-8 -*-
"""
Global Certificate Manager - Sistema de gestión centralizada de certificados
apps/sri_integration/services/global_certificate_manager.py

Carga certificados P12 usando únicamente la librería `cryptography`.
Sin subprocess, sin openssl binary, sin Java.
Compatible con Security Data, BCE, Uanataca y otros proveedores del SRI Ecuador.
"""

import os
import logging
import threading
import hashlib
import base64
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.backends import default_backend
from cryptography import x509
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from apps.certificates.models import DigitalCertificate
from apps.companies.models import Company

logger = logging.getLogger(__name__)


class CertificateData:
    """
    Estructura para datos de certificado en memoria
    """
    def __init__(self, company_id, private_key, certificate, additional_certificates, certificate_obj, p12_data=None, password=None):
        self.company_id = company_id
        self.private_key = private_key
        self.certificate = certificate
        self.additional_certificates = additional_certificates
        self.certificate_obj = certificate_obj
        self.p12_data = p12_data  # Guardamos los datos P12 por si necesitamos recargar
        self._password = password  # Guardamos password para poder recargar con OpenSSL
        self.loaded_at = datetime.now()
        self.last_used = datetime.now()
        self.usage_count = 0
    
    @property
    def password(self):
        """Getter para password"""
        return self._password
    
    def update_usage(self):
        """Actualiza estadísticas de uso"""
        self.last_used = datetime.now()
        self.usage_count += 1
    
    def is_expired(self):
        """Verifica si el certificado ha expirado"""
        return self.certificate.not_valid_after_utc.replace(tzinfo=None) < datetime.utcnow()
    
    def days_until_expiration(self):
        """Días hasta expiración"""
        delta = self.certificate.not_valid_after - datetime.utcnow()
        return max(0, delta.days)


class GlobalCertificateManager:
    """
    Gestor global de certificados para múltiples empresas
    Implementa patrón Singleton thread-safe
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # Cache de certificados en memoria
        self._certificates_cache: Dict[int, CertificateData] = {}
        
        # Configuración
        self._cache_timeout = getattr(settings, 'CERTIFICATE_CACHE_TIMEOUT', 3600)  # 1 hora
        self._max_cache_size = getattr(settings, 'MAX_CERTIFICATES_CACHE', 1000)
        self._cleanup_interval = getattr(settings, 'CERTIFICATE_CLEANUP_INTERVAL', 300)  # 5 minutos
        
        # Estadísticas
        self._stats = {
            'certificates_loaded': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'errors': 0,
            'last_cleanup': None
        }
        
        # Lock para operaciones thread-safe
        self._operation_lock = threading.RLock()
        
        self._initialized = True
        logger.info("GlobalCertificateManager initialized")
    
    def get_certificate(self, company_id: int) -> Optional[CertificateData]:
        """
        Obtiene certificado de empresa desde cache o lo carga
        
        Args:
            company_id: ID de la empresa
            
        Returns:
            CertificateData o None si no se puede cargar
        """
        with self._operation_lock:
            # Verificar cache
            if company_id in self._certificates_cache:
                cert_data = self._certificates_cache[company_id]
                
                # Verificar si no ha expirado
                if not cert_data.is_expired():
                    # Verificar si el certificado en la base de datos fue actualizado desde que se cargó
                    try:
                        latest_cert = DigitalCertificate.objects.only('updated_at').get(
                            company_id=company_id, status='ACTIVE'
                        )
                        # Make loaded_at timezone aware for comparison
                        loaded_at_aware = timezone.make_aware(cert_data.loaded_at) if timezone.is_naive(cert_data.loaded_at) else cert_data.loaded_at
                        if latest_cert.updated_at > loaded_at_aware:
                            logger.info(f"Certificate for company {company_id} was updated in DB. Reloading cache.")
                            del self._certificates_cache[company_id]
                        else:
                            cert_data.update_usage()
                            self._stats['cache_hits'] += 1
                            logger.debug(f"Certificate cache HIT for company {company_id}")
                            return cert_data
                    except Exception as e:
                        logger.warning(f"Error checking certificate updated_at: {e}")
                        # Fallback to returning cached data if DB check fails
                        cert_data.update_usage()
                        self._stats['cache_hits'] += 1
                        return cert_data
                else:
                    logger.warning(f"Certificate expired for company {company_id}")
                    del self._certificates_cache[company_id]
            
            # Cache miss - cargar certificado
            self._stats['cache_misses'] += 1
            logger.debug(f"Certificate cache MISS for company {company_id}")
            
            return self._load_certificate(company_id)
    
    # _extract_signing_key eliminado: ya no se usa subprocess/openssl.
    # La librería `cryptography` carga el P12 directamente y maneja
    # múltiples claves (Signing + Encryption) de Security Data / BCE.
    
    def _load_certificate(self, company_id: int) -> Optional[CertificateData]:
        """
        Carga certificado desde base de datos y lo cachea
        FIX: Usa OpenSSL para extraer la clave de FIRMA correcta
        """
        try:
            # Obtener empresa
            try:
                company = Company.objects.get(id=company_id, is_active=True)
            except Company.DoesNotExist:
                logger.error(f"Company {company_id} not found or inactive")
                return None
            
            # Obtener certificado digital
            try:
                certificate_obj = DigitalCertificate.objects.get(
                    company=company,
                    status='ACTIVE'
                )
            except DigitalCertificate.DoesNotExist:
                logger.error(f"No active certificate for company {company_id}")
                return None
            
            # Obtener password descifrado
            password = self._get_decrypted_password(certificate_obj)
            if not password:
                logger.error(f"Could not decrypt password for company {company_id}")
                return None

            # Leer archivo P12 del almacenamiento (compatible con S3 y Local)
            try:
                with certificate_obj.certificate_file.open('rb') as f:
                    p12_data = f.read()
            except Exception as e:
                logger.error(f"Could not read certificate file for company {company_id}: {str(e)}")
                return None
            
            # Cargar P12 con cryptography (sin subprocess ni openssl externo)
            # load_key_and_certificates selecciona automáticamente la clave
            # con atributo "Signing Key" cuando hay múltiples (ej: Security Data)
            try:
                # MÉTODO 1: Cryptography (Estándar)
                private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                    p12_data,
                    password.encode('utf-8')
                )
            except Exception as e:
                logger.warning(f"Cryptography falló al abrir P12 para empresa {company_id}, intentando fallback con pyOpenSSL: {str(e)}")
                try:
                    # MÉTODO 2: Fallback con pyOpenSSL (más robusto con formatos legacy)
                    from OpenSSL import crypto
                    p12 = crypto.load_pkcs12(p12_data, password.encode('utf-8'))
                    
                    pk_obj = p12.get_privatekey()
                    private_key = pk_obj.to_cryptography_key() if pk_obj else None
                    
                    cert_obj = p12.get_certificate()
                    certificate = cert_obj.to_cryptography() if cert_obj else None
                    
                    # Additional certs fallback
                    additional_certificates = []
                    ca_certs = p12.get_ca_certificates()
                    if ca_certs:
                        for ca in ca_certs:
                            additional_certificates.append(ca.to_cryptography())
                            
                    logger.info("✅ P12 cargado exitosamente para empresa %s usando fallback de pyOpenSSL", company_id)
                except Exception as e2:
                    logger.error(f"Error crítico cargando P12 para empresa {company_id}: Ambos métodos fallaron. Error 1: {str(e)}, Error 2: {str(e2)}")
                    return None

            if not certificate:
                logger.error("Could not extract certificate for company %s", company_id)
                return None

            if not private_key:
                logger.error("Could not extract private key for company %s", company_id)
                return None

            logger.info("✅ Certificado cargado con cryptography para empresa %s", company_id)
            
            # Crear objeto de datos de certificado
            cert_data = CertificateData(
                company_id=company_id,
                private_key=private_key,
                certificate=certificate,
                additional_certificates=additional_certificates,
                certificate_obj=certificate_obj,
                p12_data=p12_data,
                password=password
            )
            
            # Cachear
            self._certificates_cache[company_id] = cert_data
            self._stats['certificates_loaded'] += 1
            
            logger.info(f"Certificate loaded and cached for company {company_id} ({company.business_name})")
            
            # Limpiar cache si es necesario
            self._cleanup_cache_if_needed()
            
            return cert_data
            
        except Exception as e:
            logger.error(f"Error loading certificate for company {company_id}: {str(e)}")
            self._stats['errors'] += 1
            return None
    
    def _get_decrypted_password(self, certificate_obj: DigitalCertificate) -> Optional[str]:
        """
        Obtiene password descifrado del certificado usando el método get_password() del modelo
        """
        try:
            # ✅ MÉTODO PRINCIPAL: Usar password encriptado del modelo
            password = certificate_obj.get_password()
            
            if password:
                logger.debug(f"✅ Password retrieved from encrypted storage for company {certificate_obj.company.id}")
                return password
            
            # Si no hay password encriptado, mostrar error claro con instrucciones
            logger.error(
                f"❌ No encrypted password found for company {certificate_obj.company.id}. "
                f"Please set password using Django shell:\n"
                f"  from apps.certificates.models import DigitalCertificate\n"
                f"  cert = DigitalCertificate.objects.get(id={certificate_obj.id})\n"
                f"  cert.set_password('your_password')\n"
                f"  cert.save()"
            )
            return None
            
        except Exception as e:
            logger.error(f"❌ Error retrieving password for company {certificate_obj.company.id}: {str(e)}")
            return None
    
    def preload_certificates(self, company_ids: list = None):
        """
        Precarga certificados al iniciar la aplicación
        """
        try:
            if company_ids is None:
                # Cargar todas las empresas activas con certificados
                companies = Company.objects.filter(
                    is_active=True,
                    digital_certificate__isnull=False,
                    digital_certificate__status='ACTIVE'
                ).values_list('id', flat=True)
            else:
                companies = company_ids
            
            loaded_count = 0
            failed_count = 0
            
            logger.info(f"Preloading certificates for {len(companies)} companies...")
            
            for company_id in companies:
                cert_data = self._load_certificate(company_id)
                if cert_data:
                    loaded_count += 1
                    logger.info(f"✅ Preloaded certificate for company {company_id}")
                else:
                    failed_count += 1
                    logger.warning(f"❌ Failed to preload certificate for company {company_id}")
            
            logger.info(f"Certificate preloading complete: {loaded_count} loaded, {failed_count} failed")
            
            return {
                'total_companies': len(companies),
                'loaded': loaded_count,
                'failed': failed_count,
                'success_rate': (loaded_count / len(companies)) * 100 if companies else 0
            }
            
        except Exception as e:
            logger.error(f"Error preloading certificates: {str(e)}")
            return {'error': str(e)}
    
    def reload_certificate(self, company_id: int) -> bool:
        """
        Recarga un certificado específico (para actualizaciones)
        """
        with self._operation_lock:
            # Remover del cache
            if company_id in self._certificates_cache:
                del self._certificates_cache[company_id]
                logger.info(f"Certificate cache cleared for company {company_id}")
            
            # Recargar
            cert_data = self._load_certificate(company_id)
            return cert_data is not None
    
    def _cleanup_cache_if_needed(self):
        """
        Limpia cache si supera el tamaño máximo
        """
        if len(self._certificates_cache) > self._max_cache_size:
            # Remover certificados más antiguos
            sorted_certs = sorted(
                self._certificates_cache.items(),
                key=lambda x: x[1].last_used
            )
            
            # Remover 10% más antiguo
            remove_count = max(1, int(self._max_cache_size * 0.1))
            
            for i in range(remove_count):
                if i < len(sorted_certs):
                    company_id = sorted_certs[i][0]
                    del self._certificates_cache[company_id]
                    logger.debug(f"Removed certificate cache for company {company_id} (cleanup)")
            
            logger.info(f"Certificate cache cleanup: removed {remove_count} entries")
    
    def cleanup_expired_certificates(self):
        """
        Limpia certificados expirados del cache
        """
        with self._operation_lock:
            expired_companies = []
            
            for company_id, cert_data in self._certificates_cache.items():
                if cert_data.is_expired():
                    expired_companies.append(company_id)
            
            for company_id in expired_companies:
                del self._certificates_cache[company_id]
                logger.warning(f"Removed expired certificate for company {company_id}")
            
            self._stats['last_cleanup'] = datetime.now()
            
            if expired_companies:
                logger.info(f"Cleanup: removed {len(expired_companies)} expired certificates")
    
    def get_stats(self) -> dict:
        """
        Obtiene estadísticas del gestor
        """
        with self._operation_lock:
            cache_size = len(self._certificates_cache)
            
            # Información de certificados cacheados
            cached_info = {}
            for company_id, cert_data in self._certificates_cache.items():
                cached_info[company_id] = {
                    'loaded_at': cert_data.loaded_at.isoformat(),
                    'last_used': cert_data.last_used.isoformat(),
                    'usage_count': cert_data.usage_count,
                    'expires_in_days': cert_data.days_until_expiration(),
                    'subject_name': str(cert_data.certificate.subject),
                    'company_name': cert_data.certificate_obj.company.business_name
                }
            
            return {
                'cache_size': cache_size,
                'max_cache_size': self._max_cache_size,
                'cache_utilization': (cache_size / self._max_cache_size) * 100,
                'statistics': self._stats.copy(),
                'cached_certificates': cached_info,
                'instance_id': id(self),
                'initialized': self._initialized
            }
    
    def clear_cache(self):
        """
        Limpia completamente el cache (para mantenimiento)
        """
        with self._operation_lock:
            cleared_count = len(self._certificates_cache)
            self._certificates_cache.clear()
            logger.info(f"Certificate cache cleared: {cleared_count} certificates removed")
            return cleared_count
    
    def validate_certificate(self, company_id: int) -> Tuple[bool, str]:
        """
        Valida un certificado específico
        """
        cert_data = self.get_certificate(company_id)
        
        if not cert_data:
            return False, "Certificate not found or could not be loaded"
        
        if cert_data.is_expired():
            return False, f"Certificate expired on {cert_data.certificate.not_valid_after}"
        
        days_until_exp = cert_data.days_until_expiration()
        if days_until_exp <= 30:
            return True, f"Certificate valid but expires in {days_until_exp} days"
        
        return True, "Certificate is valid"
    
    def get_company_certificate_info(self, company_id: int) -> Optional[dict]:
        """
        Obtiene información detallada del certificado de una empresa
        """
        cert_data = self.get_certificate(company_id)
        
        if not cert_data:
            return None
        
        return {
            'company_id': company_id,
            'company_name': cert_data.certificate_obj.company.business_name,
            'subject': str(cert_data.certificate.subject),
            'issuer': str(cert_data.certificate.issuer),
            'serial_number': str(cert_data.certificate.serial_number),
            'not_valid_before': cert_data.certificate.not_valid_before.isoformat(),
            'not_valid_after': cert_data.certificate.not_valid_after.isoformat(),
            'days_until_expiration': cert_data.days_until_expiration(),
            'is_expired': cert_data.is_expired(),
            'fingerprint': cert_data.certificate_obj.fingerprint,
            'environment': cert_data.certificate_obj.environment,
            'usage_count': cert_data.usage_count,
            'last_used': cert_data.last_used.isoformat(),
            'loaded_at': cert_data.loaded_at.isoformat()
        }


# Instancia global del gestor
certificate_manager = GlobalCertificateManager()


def get_certificate_manager() -> GlobalCertificateManager:
    """
    Función helper para obtener la instancia del gestor
    """
    return certificate_manager