# -*- coding: utf-8 -*-
"""
Firmador XAdES-BES 100% Python para SRI Ecuador.
VERSIÓN ROBUSTA 2026 - COMPATIBLE CON PRODUCCIÓN SHA-256
CUMPLE: ETSI TS 101 903 v1.3.2 + XMLDSIG
"""

import base64
import hashlib
import logging
import uuid
from datetime import datetime, timezone, timedelta
from lxml import etree
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger(__name__)

# Namespaces estándar
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"

# Algoritmos de Producción (Configuración de Máxima Compatibilidad Legacy)
ALGO_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
ALGO_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
ALGO_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
ALGO_SHA1 = "http://www.w3.org/2000/09/xmldsig#sha1"
ALGO_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"

ECUADOR_TZ = timezone(timedelta(hours=-5))

class XAdesBESSigner:
    def __init__(self, private_key, certificate):
        self.private_key = private_key
        self.certificate = certificate
        
        # Preparar el certificado en formato base64 DER
        self.cert_base64 = base64.b64encode(
            self.certificate.public_bytes(encoding=serialization.Encoding.DER)
        ).decode('ascii')

    def sign(self, xml_content: str) -> str:
        """
        Firma un documento XML siguiendo el estándar XAdES-BES (Legacy Pro Configuration)
        Esta configuración está optimizada para los nodos JBoss 6 del SRI Producción.
        """
        # 1. Limpiar y Parsear
        if xml_content.startswith("\ufeff"):
            xml_content = xml_content[1:]
        
        parser = etree.XMLParser(remove_blank_text=True, strip_cdata=False)
        root = etree.fromstring(xml_content.encode("utf-8"), parser)

        # 2. Asegurar ID del comprobante
        if not root.get("id"):
            root.set("id", "comprobante")
        comprobante_id = root.get("id")

        # 3. Generar IDs Únicos para esta firma
        unique_suffix = uuid.uuid4().hex[:8]
        sig_id = f"Signature-{unique_suffix}"
        value_id = f"SignatureValue-{unique_suffix}"
        props_id = f"SignedProperties-{unique_suffix}"
        key_info_id = f"KeyInfo-{unique_suffix}"
        object_id = f"Object-{unique_suffix}"

        # 4. Estructura Signature con Prefijos DS explicativos (Requerido por SRI JBoss)
        nsmap = {"ds": NS_DS, "etsi": NS_XADES}
        signature_elem = etree.Element(f"{{{NS_DS}}}Signature", nsmap=nsmap)
        signature_elem.set("Id", sig_id)

        # 5. SignedInfo
        signed_info = etree.SubElement(signature_elem, f"{{{NS_DS}}}SignedInfo")
        
        # CanonicalizationMethod
        cm = etree.SubElement(signed_info, f"{{{NS_DS}}}CanonicalizationMethod")
        cm.set("Algorithm", ALGO_C14N)
        
        # SignatureMethod
        sm = etree.SubElement(signed_info, f"{{{NS_DS}}}SignatureMethod")
        sm.set("Algorithm", ALGO_RSA_SHA256)

        # --- Referencia 1: Comprobante ---
        ref_doc = etree.SubElement(signed_info, f"{{{NS_DS}}}Reference")
        ref_doc.set("Id", f"Reference-Doc-{unique_suffix}")
        ref_doc.set("URI", f"#{comprobante_id}")
        
        transforms = etree.SubElement(ref_doc, f"{{{NS_DS}}}Transforms")
        etree.SubElement(transforms, f"{{{NS_DS}}}Transform").set("Algorithm", ALGO_ENVELOPED)
        etree.SubElement(transforms, f"{{{NS_DS}}}Transform").set("Algorithm", ALGO_C14N)
        
        dm_doc = etree.SubElement(ref_doc, f"{{{NS_DS}}}DigestMethod")
        dm_doc.set("Algorithm", ALGO_SHA256)
        
        # Calcular DigestValue
        doc_canonical = etree.tostring(root, method="c14n", exclusive=False, with_comments=False)
        dv_doc = etree.SubElement(ref_doc, f"{{{NS_DS}}}DigestValue")
        dv_doc.text = base64.b64encode(hashlib.sha256(doc_canonical).digest()).decode()

        # --- Referencia 2: SignedProperties ---
        ref_props = etree.SubElement(signed_info, f"{{{NS_DS}}}Reference")
        ref_props.set("Type", "http://uri.etsi.org/01903#SignedProperties")
        ref_props.set("URI", f"#{props_id}")
        
        dm_props = etree.SubElement(ref_props, f"{{{NS_DS}}}DigestMethod")
        dm_props.set("Algorithm", ALGO_SHA256)

        # 6. Object (XAdES Data)
        xades_obj = etree.Element(f"{{{NS_DS}}}Object", nsmap=nsmap)
        xades_obj.set("Id", object_id)
        
        qual_props = etree.SubElement(xades_obj, f"{{{NS_XADES}}}QualifyingProperties")
        qual_props.set("Target", f"#{sig_id}")
        
        signed_props = etree.SubElement(qual_props, f"{{{NS_XADES}}}SignedProperties")
        signed_props.set("Id", props_id)
        
        s_sig_props = etree.SubElement(signed_props, f"{{{NS_XADES}}}SignedSignatureProperties")
        
        # SigningTime
        st = etree.SubElement(s_sig_props, f"{{{NS_XADES}}}SigningTime")
        st.text = datetime.now(ECUADOR_TZ).replace(microsecond=0).isoformat()
        
        # SigningCertificate (Suele requerir SHA-1 para el hash del certificado por compatibilidad)
        s_cert = etree.SubElement(s_sig_props, f"{{{NS_XADES}}}SigningCertificate")
        cert_node = etree.SubElement(s_cert, f"{{{NS_XADES}}}Cert")
        
        cert_digest = etree.SubElement(cert_node, f"{{{NS_XADES}}}CertDigest")
        cd_dm = etree.SubElement(cert_digest, f"{{{NS_DS}}}DigestMethod")
        cd_dm.set("Algorithm", ALGO_SHA1)  # Fallback a SHA-1 para compatibility
        cd_dv = etree.SubElement(cert_digest, f"{{{NS_DS}}}DigestValue")
        
        cert_der = self.certificate.public_bytes(serialization.Encoding.DER)
        cd_dv.text = base64.b64encode(hashlib.sha1(cert_der).digest()).decode()
        
        issuer_serial = etree.SubElement(cert_node, f"{{{NS_XADES}}}IssuerSerial")
        is_name = etree.SubElement(issuer_serial, f"{{{NS_DS}}}X509IssuerName")
        is_name.text = self._format_issuer(self.certificate.issuer)
        is_serial = etree.SubElement(issuer_serial, f"{{{NS_DS}}}X509SerialNumber")
        is_serial.text = str(self.certificate.serial_number)
        
        policy = etree.SubElement(s_sig_props, f"{{{NS_XADES}}}SignaturePolicyIdentifier")
        etree.SubElement(policy, f"{{{NS_XADES}}}SignaturePolicyImplied")

        # 7. Calcular Digest de SignedProperties
        # Usamos C14N 1.0 (no exclusiva) pero asegurando que el elemento sea auto-contenido
        props_canonical = etree.tostring(signed_props, method="c14n", exclusive=False, with_comments=False)
        dv_props = etree.SubElement(ref_props, f"{{{NS_DS}}}DigestValue")
        dv_props.text = base64.b64encode(hashlib.sha256(props_canonical).digest()).decode()

        # 8. Calcular SignatureValue
        # Firmar el bloque SignedInfo canonicalizado
        si_canonical = etree.tostring(signed_info, method="c14n", exclusive=False, with_comments=False)
        signature_value_raw = self.private_key.sign(
            si_canonical, 
            padding.PKCS1v15(), 
            hashes.SHA256()
        )
        
        sig_val = etree.SubElement(signature_elem, f"{{{NS_DS}}}SignatureValue")
        sig_val.set("Id", value_id)
        sig_val.text = base64.b64encode(signature_value_raw).decode()

        # 9. KeyInfo
        key_info = etree.SubElement(signature_elem, f"{{{NS_DS}}}KeyInfo")
        key_info.set("Id", key_info_id)
        x509_data = etree.SubElement(key_info, f"{{{NS_DS}}}X509Data")
        x509_cert = etree.SubElement(x509_data, f"{{{NS_DS}}}X509Certificate")
        x509_cert.text = self.cert_base64

        # 10. Ensamblar e Insertar al final del root (preferido por SRI)
        signature_elem.append(xades_obj)
        root.append(signature_elem)
        
        # 11. Retornar XML final sin pretty print para no romper firma
        return etree.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")

    def _format_issuer(self, issuer):
        """Formatea el emisor siguiendo el estándar estricto que espera JBoss 6"""
        mapping = {
            'commonName': 'CN',
            'organizationName': 'O',
            'organizationalUnitName': 'OU',
            'countryName': 'C',
            'localityName': 'L',
            'stateOrProvinceName': 'ST',
            'emailAddress': 'EMAIL',
            'serialNumber': 'SERIALNUMBER'
        }
        parts = []
        # Importante: SRI prefiere el orden EXACTO que viene en el cert, empezando por C=...
        # La mayoría de certs ecuatorianos vienen ordenados de lo más general a lo más específico
        for attr in reversed(list(issuer)):
            # Handle 'Unknown OID' gracefully by using its dotted string (e.g. 2.5.4.97)
            oid_name = attr.oid.dotted_string if attr.oid._name == 'Unknown OID' else attr.oid._name
            short_name = mapping.get(oid_name, oid_name)
            
            # The SRI parser may reject 2.5.4.97 if it expects OID.2.5.4.97 or just 2.5.4.97
            # Actually, using the dotted string is the most standard fallback
            parts.append(f"{short_name}={attr.value}")
        
        # Coma SIN espacio es más robusto para validadores JBoss antiguos
        return ",".join(parts)

def sign_xml(xml_content: str, private_key, certificate) -> str:
    signer = XAdesBESSigner(private_key, certificate)
    return signer.sign(xml_content)
