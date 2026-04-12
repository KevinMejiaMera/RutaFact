# -*- coding: utf-8 -*-
"""
Firmador XML simplificado para evitar problemas de compatibilidad
"""

import os
import tempfile
from lxml import etree
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

class SimpleXMLSigner:
    """
    Firmador XML simplificado que evita problemas de librería
    """
    
    def __init__(self, certificate_path, password):
        self.certificate_path = certificate_path
        self.password = password
        self.private_key = None
        self.certificate = None
        
    def load_certificate(self):
        """Cargar certificado P12"""
        try:
            with open(self.certificate_path, 'rb') as f:
                p12_data = f.read()
            
            # Cargar P12
            private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                p12_data, 
                self.password.encode('utf-8')
            )
            
            self.private_key = private_key
            self.certificate = certificate
            
            return True
            
        except Exception as e:
            print(f"Error cargando certificado: {e}")
            return False
    
    def sign_xml_simple(self, xml_content):
        """
        Firma XML de forma simplificada
        Para desarrollo - no es firma XAdES completa
        """
        try:
            if not self.load_certificate():
                return False, "Error cargando certificado"
            
            # Para desarrollo, solo agregamos información del certificado
            # En producción necesitarías una librería de firma XAdES completa
            
            # Parsear XML
            root = etree.fromstring(xml_content.encode('utf-8'))
            
            # Agregar información de firma (simplificada)
            signature_info = etree.Element("SignatureInfo")
            signature_info.set("algorithm", "XAdES-BES-Simplified")
            signature_info.set("certificate_subject", str(self.certificate.subject))
            signature_info.set("signed_at", str(datetime.now()))
            
            root.append(signature_info)
            
            # Convertir de vuelta a string
            signed_xml = etree.tostring(root, encoding='utf-8', xml_declaration=True).decode('utf-8')
            
            return True, signed_xml
            
        except Exception as e:
            return False, f"Error en firma simplificada: {e}"

def sign_xml_for_development(xml_content, certificate_path, password):
    """
    Función de firma para desarrollo que evita problemas de librería
    """
    signer = SimpleXMLSigner(certificate_path, password)
    return signer.sign_xml_simple(xml_content)
