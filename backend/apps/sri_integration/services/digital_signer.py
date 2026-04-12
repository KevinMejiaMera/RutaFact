# -*- coding: utf-8 -*-
"""
Servicio para firma digital de documentos XML del SRI - ADAPTADO AL PROYECTO EXISTENTE
"""

import os
import logging
from datetime import datetime
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree
import base64

logger = logging.getLogger(__name__)


class DigitalSigner:
    """Firma digital de documentos XML para el SRI usando certificados P12"""
    
    def __init__(self, certificate_path, password):
        """
        Inicializa el firmador con certificado P12
        
        Args:
            certificate_path (str): Ruta al archivo P12
            password (str): Contraseña del certificado
        """
        self.certificate_path = certificate_path
        self.password = password
        self.private_key = None
        self.certificate = None
        self._load_certificate()
    
    def _load_certificate(self):
        """Carga el certificado P12"""
        try:
            with open(self.certificate_path, 'rb') as f:
                p12_data = f.read()
            
            try:
                # MÉTODO 1: Cryptography (Estándar)
                self.private_key, self.certificate, additional_certs = pkcs12.load_key_and_certificates(
                    p12_data, 
                    self.password.encode('utf-8')
                )
            except Exception as e:
                logger.warning(f"Cryptography falló al abrir P12 para firma, intentando fallback con pyOpenSSL: {str(e)}")
                try:
                    # MÉTODO 2: Fallback con pyOpenSSL (más robusto con formatos legacy)
                    from OpenSSL import crypto
                    p12 = crypto.load_pkcs12(p12_data, self.password.encode('utf-8'))
                    
                    pk_obj = p12.get_privatekey()
                    self.private_key = pk_obj.to_cryptography_key() if pk_obj else None
                    
                    cert_obj = p12.get_certificate()
                    self.certificate = cert_obj.to_cryptography() if cert_obj else None
                    
                    logger.info("✅ P12 cargado para firma usando fallback de pyOpenSSL")
                except Exception as e2:
                    logger.error(f"Error crítico cargando P12 para firma: Ambos métodos fallaron. Error 1: {str(e)}, Error 2: {str(e2)}")
                    raise Exception(f'Error cargando certificado para firma: {str(e2)}')
            
            if not self.certificate or not self.private_key:
                raise ValueError('No se pudo cargar el certificado o la clave privada')
            
            logger.info(f"Certificado cargado exitosamente: {self.certificate.subject}")
                
        except Exception as e:
            logger.error(f"Error cargando certificado P12: {str(e)}")
            raise Exception(f'Error cargando certificado: {str(e)}')
    
    def sign_xml_document(self, xml_content, document_type='FACTURA'):
        """
        Firma un documento XML según estándares del SRI
        
        Args:
            xml_content (str): Contenido XML a firmar
            document_type (str): Tipo de documento (FACTURA, NOTA_CREDITO, etc.)
            
        Returns:
            str: XML firmado digitalmente
        """
        try:
            logger.info(f"Iniciando firma digital para documento {document_type}")
            
            # Parsear XML con lxml para mejor manejo de namespaces
            parser = etree.XMLParser(remove_blank_text=True)
            root = etree.fromstring(xml_content.encode('utf-8'), parser)
            
            # Crear nodo de firma según estándares del SRI
            signature_node = self._create_sri_signature_node(xml_content, root)
            
            # Agregar firma al XML
            root.append(signature_node)
            
            # Retornar XML firmado con declaración XML
            signed_xml = etree.tostring(
                root, 
                encoding='utf-8', 
                xml_declaration=True,
                pretty_print=True
            ).decode('utf-8')
            
            logger.info("Documento XML firmado exitosamente")
            return signed_xml
            
        except Exception as e:
            logger.error(f"Error firmando XML: {str(e)}")
            raise Exception(f'Error firmando XML: {str(e)}')
    
    def _create_sri_signature_node(self, xml_content, root_element):
        """
        Crea el nodo de firma digital según estándares específicos del SRI
        """
        try:
            # Obtener el ID del documento para la referencia
            document_id = root_element.get('id', 'comprobante')
            
            # Canonicalizar el documento para el digest
            canonical_xml = etree.tostring(
                root_element, 
                method='c14n',
                exclusive=False,
                with_comments=False
            )
            
            # Generar digest SHA1 del documento
            document_hash = hashes.Hash(hashes.SHA1())
            document_hash.update(canonical_xml)
            digest_value = base64.b64encode(document_hash.finalize()).decode('utf-8')
            
            # Crear SignedInfo con transformaciones específicas del SRI
            signed_info_xml = f'''<ds:SignedInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
                <ds:CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>
                <ds:SignatureMethod Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1"/>
                <ds:Reference URI="#{document_id}">
                    <ds:Transforms>
                        <ds:Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"/>
                    </ds:Transforms>
                    <ds:DigestMethod Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"/>
                    <ds:DigestValue>{digest_value}</ds:DigestValue>
                </ds:Reference>
            </ds:SignedInfo>'''
            
            # Canonicalizar SignedInfo para firmar
            signed_info_element = etree.fromstring(signed_info_xml)
            canonical_signed_info = etree.tostring(
                signed_info_element,
                method='c14n',
                exclusive=False,
                with_comments=False
            )
            
            # Firmar el SignedInfo canonicalizado
            signature_value = self.private_key.sign(
                canonical_signed_info,
                padding.PKCS1v15(),
                hashes.SHA1()
            )
            
            signature_value_b64 = base64.b64encode(signature_value).decode('utf-8')
            
            # Obtener certificado en base64
            cert_der = self.certificate.public_bytes(serialization.Encoding.DER)
            cert_b64 = base64.b64encode(cert_der).decode('utf-8')
            
            # Crear nodo de firma completo según estándares SRI
            signature_xml = f'''<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Id="Signature890561">
                {signed_info_xml}
                <ds:SignatureValue Id="SignatureValue890561">
{signature_value_b64}
                </ds:SignatureValue>
                <ds:KeyInfo Id="Certificate1">
                    <ds:X509Data>
                        <ds:X509Certificate>
{cert_b64}
                        </ds:X509Certificate>
                    </ds:X509Data>
                </ds:KeyInfo>
            </ds:Signature>'''
            
            return etree.fromstring(signature_xml)
            
        except Exception as e:
            logger.error(f"Error creando nodo de firma: {str(e)}")
            raise Exception(f'Error creando firma digital: {str(e)}')
    
    def validate_signature(self, signed_xml):
        """
        Valida una firma XML (para testing y verificación)
        
        Args:
            signed_xml (str): XML firmado a validar
            
        Returns:
            tuple: (bool, str) - (es_válida, mensaje)
        """
        try:
            root = etree.fromstring(signed_xml.encode('utf-8'))
            signature_node = root.find('.//{http://www.w3.org/2000/09/xmldsig#}Signature')
            
            if signature_node is None:
                return False, 'No se encontró nodo de firma digital'
            
            # Verificar que tiene los elementos básicos
            signed_info = signature_node.find('.//{http://www.w3.org/2000/09/xmldsig#}SignedInfo')
            signature_value = signature_node.find('.//{http://www.w3.org/2000/09/xmldsig#}SignatureValue')
            x509_cert = signature_node.find('.//{http://www.w3.org/2000/09/xmldsig#}X509Certificate')
            
            if not all([signed_info, signature_value, x509_cert]):
                return False, 'Estructura de firma incompleta'
            
            logger.info("Firma XML validada - estructura correcta")
            return True, 'Firma válida - estructura correcta'
            
        except Exception as e:
            logger.error(f"Error validando firma: {str(e)}")
            return False, f'Error validando firma: {str(e)}'
    
    def get_certificate_info(self):
        """
        Obtiene información del certificado cargado
        
        Returns:
            dict: Información del certificado
        """
        if not self.certificate:
            return None
        
        try:
            return {
                'subject': str(self.certificate.subject),
                'issuer': str(self.certificate.issuer),
                'serial_number': str(self.certificate.serial_number),
                'not_valid_before': self.certificate.not_valid_before,
                'not_valid_after': self.certificate.not_valid_after,
                'fingerprint': self.certificate.fingerprint(hashes.SHA256()).hex()
            }
        except Exception as e:
            logger.error(f"Error obteniendo info del certificado: {str(e)}")
            return None