# -*- coding: utf-8 -*-
"""
Gestor de certificados digitales para firma electrónica - VERSIÓN CORREGIDA
SIN dependencias problemáticas de SignXML y SIN strip_whitespace
"""

import os
import logging
import base64
import hashlib
import uuid
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography import x509
from lxml import etree
from django.core.files.base import ContentFile
from django.utils import timezone
from apps.certificates.models import DigitalCertificate, CertificateUsageLog

logger = logging.getLogger(__name__)


class CertificateManager:
    """
    Gestor de certificados digitales P12 - VERSIÓN CORREGIDA
    Implementación propia de firma XML sin dependencias externas problemáticas
    """
    
    def __init__(self, company):
        self.company = company
        self.certificate = None
        
    def load_certificate(self, password):
        """
        Carga el certificado digital de la empresa
        """
        try:
            certificate_obj = DigitalCertificate.objects.get(
                company=self.company,
                status='ACTIVE'
            )
            
            # Verificar contraseña
            if not certificate_obj.verify_password(password):
                raise ValueError("Invalid certificate password")
            
            # Cargar archivo P12
            with open(certificate_obj.certificate_file.path, 'rb') as f:
                p12_data = f.read()
            
            # Extraer certificado y clave privada
            private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                p12_data, 
                password.encode('utf-8')
            )
            
            self.certificate = {
                'private_key': private_key,
                'certificate': certificate,
                'additional_certificates': additional_certificates,
                'certificate_obj': certificate_obj
            }
            
            logger.info(f"Certificate loaded successfully for {self.company.business_name}")
            return True
            
        except DigitalCertificate.DoesNotExist:
            raise ValueError("No active digital certificate found for company")
        except Exception as e:
            logger.error(f"Error loading certificate: {str(e)}")
            raise ValueError(f"Error loading certificate: {str(e)}")
    
    def sign_xml(self, xml_content, document=None):
        """
        Firma un documento XML usando implementación propia XAdES-BES
        """
        if not self.certificate:
            raise ValueError("Certificate not loaded")
        
        try:
            logger.info("Starting XML signing process with custom implementation")
            
            # Usar nuestra implementación propia
            signed_xml = self._sign_xml_custom(xml_content)
            
            # Log de uso exitoso
            if document:
                self._log_certificate_usage(
                    'SIGN_XML_CUSTOM',
                    document.document_type,
                    document.document_number,
                    True
                )
            
            logger.info("XML signing completed successfully")
            return signed_xml
                
        except Exception as e:
            logger.error(f"Error signing XML: {str(e)}")
            
            # Log de error
            if document:
                self._log_certificate_usage(
                    'SIGN_XML_CUSTOM',
                    document.document_type,
                    document.document_number,
                    False,
                    str(e)
                )
            
            raise ValueError(f"Error signing XML: {str(e)}")
    
    def _sign_xml_custom(self, xml_content):
        """Implementación propia de firma XML XAdES-BES - CORREGIDA"""
        try:
            # Parsear el XML - SIN strip_whitespace para evitar problemas
            parser = etree.XMLParser(remove_blank_text=False)
            root = etree.fromstring(xml_content.encode('utf-8'), parser)
            
            # Canonicalizar el documento para calcular el hash
            canonical_xml = etree.tostring(root, method='c14n')
            
            # Calcular digest SHA-256 del documento
            digest = hashlib.sha256(canonical_xml).digest()
            digest_value = base64.b64encode(digest).decode()
            
            # Generar IDs únicos
            signature_id = f"Signature_{uuid.uuid4().hex[:8]}"
            
            # Crear SignedInfo
            signed_info = self._create_signed_info(digest_value)
            
            # Canonicalizar SignedInfo
            canonical_signed_info = etree.tostring(signed_info, method='c14n')
            
            # Firmar SignedInfo con la clave privada
            signature_bytes = self.certificate['private_key'].sign(
                canonical_signed_info,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            signature_value = base64.b64encode(signature_bytes).decode()
            
            # Obtener certificado en base64
            cert_der = self.certificate['certificate'].public_bytes(serialization.Encoding.DER)
            cert_b64 = base64.b64encode(cert_der).decode()
            
            # Crear el nodo de firma completo
            signature_element = self._create_signature_element(
                signature_id, 
                signed_info, 
                signature_value, 
                cert_b64
            )
            
            # Insertar la firma en el XML
            root.append(signature_element)
            
            # Devolver XML firmado
            signed_xml = etree.tostring(
                root, 
                encoding='unicode', 
                pretty_print=True
            )
            
            # Agregar declaración XML si no la tiene
            if not signed_xml.startswith('<?xml'):
                signed_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + signed_xml
            
            return signed_xml
            
        except Exception as e:
            raise Exception(f"Custom XML signing failed: {str(e)}")
    
    def _create_signed_info(self, digest_value):
        """Crear elemento SignedInfo"""
        ds_ns = "http://www.w3.org/2000/09/xmldsig#"
        
        signed_info = etree.Element(f"{{{ds_ns}}}SignedInfo")
        
        # CanonicalizationMethod
        canon_method = etree.SubElement(signed_info, f"{{{ds_ns}}}CanonicalizationMethod")
        canon_method.set("Algorithm", "http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
        
        # SignatureMethod
        sig_method = etree.SubElement(signed_info, f"{{{ds_ns}}}SignatureMethod")
        sig_method.set("Algorithm", "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256")
        
        # Reference
        reference = etree.SubElement(signed_info, f"{{{ds_ns}}}Reference")
        reference.set("URI", "")
        
        # Transforms
        transforms = etree.SubElement(reference, f"{{{ds_ns}}}Transforms")
        transform = etree.SubElement(transforms, f"{{{ds_ns}}}Transform")
        transform.set("Algorithm", "http://www.w3.org/2000/09/xmldsig#enveloped-signature")
        
        # DigestMethod
        digest_method = etree.SubElement(reference, f"{{{ds_ns}}}DigestMethod")
        digest_method.set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
        
        # DigestValue
        digest_value_elem = etree.SubElement(reference, f"{{{ds_ns}}}DigestValue")
        digest_value_elem.text = digest_value
        
        return signed_info
    
    def _create_signature_element(self, signature_id, signed_info, signature_value, cert_b64):
        """Crear elemento Signature completo"""
        ds_ns = "http://www.w3.org/2000/09/xmldsig#"
        etsi_ns = "http://uri.etsi.org/01903/v1.3.2#"
        
        # Elemento raíz Signature
        signature = etree.Element(f"{{{ds_ns}}}Signature", nsmap={
            'ds': ds_ns,
            'etsi': etsi_ns
        })
        signature.set("Id", signature_id)
        
        # Agregar SignedInfo
        signature.append(signed_info)
        
        # SignatureValue
        sig_value_elem = etree.SubElement(signature, f"{{{ds_ns}}}SignatureValue")
        sig_value_elem.text = signature_value
        
        # KeyInfo
        key_info = etree.SubElement(signature, f"{{{ds_ns}}}KeyInfo")
        x509_data = etree.SubElement(key_info, f"{{{ds_ns}}}X509Data")
        x509_cert = etree.SubElement(x509_data, f"{{{ds_ns}}}X509Certificate")
        x509_cert.text = cert_b64
        
        # Object con QualifyingProperties (XAdES-BES)
        obj = etree.SubElement(signature, f"{{{ds_ns}}}Object")
        qualifying_props = etree.SubElement(obj, f"{{{etsi_ns}}}QualifyingProperties")
        qualifying_props.set("Target", f"#{signature_id}")
        
        signed_props = etree.SubElement(qualifying_props, f"{{{etsi_ns}}}SignedProperties")
        signed_sig_props = etree.SubElement(signed_props, f"{{{etsi_ns}}}SignedSignatureProperties")
        
        # SigningTime
        signing_time = etree.SubElement(signed_sig_props, f"{{{etsi_ns}}}SigningTime")
        signing_time.text = datetime.now().isoformat() + 'Z'
        
        # SigningCertificate
        signing_cert = etree.SubElement(signed_sig_props, f"{{{etsi_ns}}}SigningCertificate")
        cert_elem = etree.SubElement(signing_cert, f"{{{etsi_ns}}}Cert")
        
        cert_digest = etree.SubElement(cert_elem, f"{{{etsi_ns}}}CertDigest")
        cert_digest_method = etree.SubElement(cert_digest, f"{{{ds_ns}}}DigestMethod")
        cert_digest_method.set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
        
        cert_digest_value = etree.SubElement(cert_digest, f"{{{ds_ns}}}DigestValue")
        cert_hash = hashlib.sha256(base64.b64decode(cert_b64)).digest()
        cert_digest_value.text = base64.b64encode(cert_hash).decode()
        
        issuer_serial = etree.SubElement(cert_elem, f"{{{etsi_ns}}}IssuerSerial")
        x509_issuer_name = etree.SubElement(issuer_serial, f"{{{ds_ns}}}X509IssuerName")
        x509_issuer_name.text = self.certificate['certificate'].issuer.rfc4514_string()
        
        x509_serial_number = etree.SubElement(issuer_serial, f"{{{ds_ns}}}X509SerialNumber")
        x509_serial_number.text = str(self.certificate['certificate'].serial_number)
        
        return signature
    
    def validate_certificate(self):
        """
        Valida el estado del certificado
        """
        if not self.certificate:
            return False, "Certificate not loaded"
        
        cert_obj = self.certificate['certificate_obj']
        
        # Verificar expiración
        if cert_obj.is_expired:
            return False, "Certificate has expired"
        
        # Verificar si está cerca de expirar (30 días)
        if cert_obj.days_until_expiration <= 30:
            return True, f"Certificate expires in {cert_obj.days_until_expiration} days"
        
        return True, "Certificate is valid"
    
    def extract_certificate_info(self, p12_file_path, password):
        """
        Extrae información de un certificado P12
        """
        try:
            with open(p12_file_path, 'rb') as f:
                p12_data = f.read()
            
            # Cargar certificado
            private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                p12_data,
                password.encode('utf-8')
            )
            
            # Extraer información
            subject = certificate.subject
            issuer = certificate.issuer
            
            # Buscar campos específicos
            def get_name_attribute(name, oid):
                try:
                    return name.get_attributes_for_oid(oid)[0].value
                except (IndexError, AttributeError):
                    return ""
            
            subject_name = get_name_attribute(subject, x509.NameOID.COMMON_NAME)
            issuer_name = get_name_attribute(issuer, x509.NameOID.COMMON_NAME)
            
            # Fechas de validez
            valid_from = certificate.not_valid_before
            valid_to = certificate.not_valid_after
            
            # Número de serie
            serial_number = str(certificate.serial_number)
            
            # Huella digital
            fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
            
            return {
                'subject_name': subject_name,
                'issuer_name': issuer_name,
                'serial_number': serial_number,
                'valid_from': valid_from,
                'valid_to': valid_to,
                'fingerprint': fingerprint
            }
            
        except Exception as e:
            logger.error(f"Error extracting certificate info: {str(e)}")
            raise ValueError(f"Error extracting certificate info: {str(e)}")
    
    def create_certificate_record(self, p12_file, password, environment='TEST'):
        """
        Crea un registro de certificado en la base de datos
        """
        try:
            # Guardar archivo temporalmente para extraer info
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.p12') as temp_file:
                for chunk in p12_file.chunks():
                    temp_file.write(chunk)
                temp_path = temp_file.name
            
            try:
                # Extraer información
                cert_info = self.extract_certificate_info(temp_path, password)
                
                # Crear registro
                certificate = DigitalCertificate(
                    company=self.company,
                    subject_name=cert_info['subject_name'],
                    issuer_name=cert_info['issuer_name'],
                    serial_number=cert_info['serial_number'],
                    valid_from=cert_info['valid_from'],
                    valid_to=cert_info['valid_to'],
                    fingerprint=cert_info['fingerprint'],
                    environment=environment
                )
                
                # Hashear contraseña
                certificate.set_password(password)
                
                # Guardar archivo
                filename = f"{self.company.ruc}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.p12"
                certificate.certificate_file.save(
                    filename,
                    ContentFile(p12_file.read()),
                    save=False
                )
                
                certificate.save()
                
                return certificate
                
            finally:
                # Limpiar archivo temporal
                os.unlink(temp_path)
                
        except Exception as e:
            logger.error(f"Error creating certificate record: {str(e)}")
            raise ValueError(f"Error creating certificate record: {str(e)}")
    
    def _log_certificate_usage(self, operation, document_type='', document_number='', success=True, error_message=''):
        """
        Registra el uso del certificado
        """
        try:
            CertificateUsageLog.objects.create(
                certificate=self.certificate['certificate_obj'],
                operation=operation,
                document_type=document_type,
                document_number=document_number,
                success=success,
                error_message=error_message
            )
        except Exception as e:
            logger.error(f"Error logging certificate usage: {str(e)}")
    
    def get_signing_method(self):
        """
        Retorna el método de firma que se está usando
        """
        return "Custom XAdES-BES Implementation (SHA-256) - Fixed Version"