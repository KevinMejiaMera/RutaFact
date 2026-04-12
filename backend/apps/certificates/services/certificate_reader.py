# apps/certificates/services/certificate_reader.py

from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.backends import default_backend
from cryptography import x509
import hashlib
from datetime import datetime


class CertificateReader:
    """
    Servicio para leer y validar certificados digitales P12
    """
    
    @staticmethod
    def read_p12(cert_data, password):
        """
        Lee un certificado P12 y extrae su información
        
        Args:
            cert_data: bytes del archivo P12
            password: contraseña del certificado
            
        Returns:
            dict con la información del certificado o None si hay error
        """
        try:
            # Convertir password a bytes si es string
            if isinstance(password, str):
                password = password.encode('utf-8')
            
            # Cargar el certificado
            try:
                # MÉTODO 1: Cryptography (Estándar)
                private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
                    cert_data,
                    password,
                    backend=default_backend()
                )
            except Exception as e:
                print(f"Cryptography falló al leer P12 en el servicio, intentando pyOpenSSL: {str(e)}")
                try:
                    # MÉTODO 2: Fallback con pyOpenSSL (más robusto con formatos legacy)
                    from OpenSSL import crypto
                    p12 = crypto.load_pkcs12(cert_data, password)
                    
                    pk_obj = p12.get_privatekey()
                    private_key = pk_obj.to_cryptography_key() if pk_obj else None
                    
                    cert_obj = p12.get_certificate()
                    certificate = cert_obj.to_cryptography() if cert_obj else None
                    
                    # Additional certs fallback
                    additional_certs = []
                    ca_certs = p12.get_ca_certificates()
                    if ca_certs:
                        for ca in ca_certs:
                            additional_certs.append(ca.to_cryptography())
                except Exception as e2:
                    print(f"Error crítico en el servicio: Ambos métodos fallaron. Error 1: {str(e)}, Error 2: {str(e2)}")
                    return None
            
            if not certificate:
                return None
            
            # Extraer información básica
            subject = certificate.subject
            issuer = certificate.issuer
            
            # Formatear los nombres
            subject_parts = []
            issuer_parts = []
            
            for attribute in subject:
                subject_parts.append(f"{attribute.oid._name}={attribute.value}")
            
            for attribute in issuer:
                issuer_parts.append(f"{attribute.oid._name}={attribute.value}")
            
            # Calcular fingerprint
            fingerprint = hashlib.sha256(certificate.public_bytes(
                encoding=x509.Encoding.DER
            )).hexdigest()
            
            # Retornar información estructurada
            return {
                'subject': ", ".join(subject_parts),
                'issuer': ", ".join(issuer_parts),
                'serial_number': str(certificate.serial_number),
                'not_before': certificate.not_valid_before,
                'not_after': certificate.not_valid_after,
                'fingerprint': fingerprint,
                'version': certificate.version.name,
                'signature_algorithm': certificate.signature_algorithm_oid._name,
                'is_valid': CertificateReader.validate_certificate(certificate),
                'days_until_expiry': (certificate.not_valid_after - datetime.now()).days
            }
            
        except Exception as e:
            print(f"Error reading certificate: {str(e)}")
            return None
    
    @staticmethod
    def validate_certificate(certificate):
        """
        Valida que el certificado esté vigente
        
        Args:
            certificate: objeto certificado x509
            
        Returns:
            bool indicando si el certificado es válido
        """
        try:
            now = datetime.now()
            return certificate.not_valid_before <= now <= certificate.not_valid_after
        except:
            return False
    
    @staticmethod
    def get_certificate_info_for_sri(cert_data, password):
        """
        Obtiene la información del certificado específica para el SRI
        
        Args:
            cert_data: bytes del archivo P12
            password: contraseña del certificado
            
        Returns:
            dict con información relevante para el SRI
        """
        cert_info = CertificateReader.read_p12(cert_data, password)
        
        if not cert_info:
            return None
        
        # Extraer información específica del SRI del subject
        subject_parts = cert_info['subject'].split(', ')
        sri_info = {
            'ruc': None,
            'razon_social': None,
            'tipo_certificado': None
        }
        
        for part in subject_parts:
            if '=' in part:
                key, value = part.split('=', 1)
                
                # Buscar el RUC en diferentes campos posibles
                if key.upper() in ['SERIALNUMBER', 'SN', 'UID']:
                    sri_info['ruc'] = value
                elif key.upper() in ['CN', 'COMMONNAME']:
                    sri_info['razon_social'] = value
                elif key.upper() in ['OU', 'ORGANIZATIONALUNITNAME']:
                    sri_info['tipo_certificado'] = value
        
        # Combinar con la información general
        return {
            **cert_info,
            'sri_info': sri_info
        }
    
    @staticmethod
    def validate_for_sri(cert_data, password, company_ruc=None):
        """
        Valida que el certificado sea apropiado para uso con el SRI
        
        Args:
            cert_data: bytes del archivo P12
            password: contraseña del certificado
            company_ruc: RUC de la empresa (opcional, para validar coincidencia)
            
        Returns:
            tuple (is_valid, error_message)
        """
        try:
            cert_info = CertificateReader.get_certificate_info_for_sri(cert_data, password)
            
            if not cert_info:
                return False, "No se pudo leer el certificado"
            
            # Validar vigencia
            if not cert_info['is_valid']:
                return False, "El certificado no está vigente"
            
            # Validar que no esté próximo a expirar (30 días)
            if cert_info['days_until_expiry'] < 30:
                return False, f"El certificado expira en {cert_info['days_until_expiry']} días. Se recomienda renovarlo."
            
            # Si se proporciona RUC, validar que coincida
            if company_ruc and cert_info['sri_info']['ruc']:
                cert_ruc = cert_info['sri_info']['ruc'].replace('-', '').strip()
                company_ruc_clean = company_ruc.replace('-', '').strip()
                
                if cert_ruc != company_ruc_clean:
                    return False, f"El RUC del certificado ({cert_ruc}) no coincide con el RUC de la empresa ({company_ruc_clean})"
            
            # Validar que sea un certificado de firma electrónica
            issuer_lower = cert_info['issuer'].lower()
            valid_issuers = ['banco central', 'security data', 'anfac', 'consejo de la judicatura']
            
            is_valid_issuer = any(issuer in issuer_lower for issuer in valid_issuers)
            if not is_valid_issuer:
                return False, "El certificado no parece ser emitido por una entidad autorizada por el BCE"
            
            return True, "Certificado válido para uso con el SRI"
            
        except Exception as e:
            return False, f"Error al validar certificado: {str(e)}"