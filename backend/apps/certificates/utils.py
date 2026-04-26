# -*- coding: utf-8 -*-
import logging
import hashlib
import re
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from OpenSSL import crypto

logger = logging.getLogger(__name__)

def load_p12_safely(cert_data, password):
    """
    Intenta cargar un archivo P12 usando múltiples estrategias de compatibilidad.
    Cubre proveedores como UANATACA, Security Data, BCE, ANF, etc.
    """
    password_bytes = password.encode('utf-8')
    
    # ESTRATEGIA 1: Cryptography Estándar
    try:
        return pkcs12.load_key_and_certificates(cert_data, password_bytes)
    except Exception as e:
        logger.debug(f"Método 1 (Cryptography) falló: {e}")

    # ESTRATEGIA 2: pyOpenSSL (Alta compatibilidad con TripleDES/Legacy)
    try:
        p12 = crypto.load_pkcs12(cert_data, password_bytes)
        cert_obj = p12.get_certificate()
        private_key_obj = p12.get_privatekey()
        
        # Convertir a objetos de cryptography para mantener consistencia
        cert = cert_obj.to_cryptography() if cert_obj else None
        private_key = private_key_obj.to_cryptography_key() if private_key_obj else None
        
        # Extraer certificados adicionales (CA chain)
        additional_certs = []
        ca_certs = p12.get_ca_certificates()
        if ca_certs:
            for ca in ca_certs:
                additional_certs.append(ca.to_cryptography())
                
        return private_key, cert, additional_certs
    except Exception as e:
        logger.debug(f"Método 2 (pyOpenSSL) falló: {e}")

    # Si llegamos aquí, ninguno funcionó
    raise ValueError("No se pudo desencriptar la firma. Verifique la contraseña o el formato del archivo.")

def extract_ecuador_ruc(cert):
    """
    Extrae el RUC y Razón Social buscando en todos los campos conocidos 
    usados por proveedores en Ecuador.
    """
    ruc = ""
    name = ""
    
    # OIDs Específicos para Ecuador (Atributos de Sujeto)
    OID_RUC_UANATACA = "1.3.6.1.4.1.37947.3.1"
    OID_RUC_SECURITY_DATA = "1.3.6.1.4.1.37442.2.1.1"
    OID_CEDULA = "1.3.6.1.4.1.37947.3.10"
    
    # --- 1. BUSCAR EN ATRIBUTOS DEL SUJETO ---
    for attr in cert.subject:
        oid = attr.oid.dotted_string
        val = str(attr.value).strip()
        
        # OIDs conocidos en Sujeto
        if oid in [OID_RUC_UANATACA, OID_RUC_SECURITY_DATA]:
            ruc = val
        
        # Buscar por serialNumber (Muy común: BCE, Security Data, etc.)
        elif attr.oid == NameOID.SERIAL_NUMBER:
            clean_val = ''.join(filter(str.isdigit, val))
            if len(clean_val) == 13:
                ruc = clean_val
            elif len(clean_val) == 10 and not ruc:
                ruc = clean_val + "001"
        
        # Buscar Nombre / Razón Social
        elif attr.oid == NameOID.COMMON_NAME:
            name = val
            if not ruc:
                match = re.search(r'(\d{13})', val)
                if match:
                    ruc = match.group(1)
                else:
                    match_ced = re.search(r'(\d{10})', val)
                    if match_ced:
                        ruc = match_ced.group(1) + "001"

    # --- 2. BUSCAR EN EXTENSIONES (NUEVO: FIRMASEGURA y otros) ---
    # Algunos proveedores ponen el RUC en extensiones personalizadas
    try:
        for ext in cert.extensions:
            oid = ext.oid.dotted_string
            
            # FIRMASEGURA S.A.S. (Específico)
            # 1.3.6.1.4.1.61305.3.11 = RUC
            # 1.3.6.1.4.1.61305.3.10 = Razón Social
            if oid == "1.3.6.1.4.1.61305.3.11":
                val = ext.value.value
                if isinstance(val, bytes):
                    # El valor suele venir con un prefijo de tipo ASN.1 (ej. \x16)
                    # Intentamos limpiar caracteres no imprimibles
                    val_str = ''.join(c for c in val.decode('latin-1', errors='ignore') if c.isdigit())
                    if len(val_str) == 13:
                        ruc = val_str
                elif isinstance(val, str):
                    clean_val = ''.join(filter(str.isdigit, val))
                    if len(clean_val) == 13:
                        ruc = clean_val

            if oid == "1.3.6.1.4.1.61305.3.10" and not name:
                val = ext.value.value
                if isinstance(val, bytes):
                    # Decodificar y quitar posibles prefijos binarios de ASN.1
                    name = val.decode('latin-1', errors='ignore')
                    # Eliminar caracteres de control iniciales
                    name = re.sub(r'^[\x00-\x1F]+', '', name).strip()
                elif isinstance(val, str):
                    name = val.strip()

    except Exception as e:
        logger.warning(f"Error explorando extensiones de certificado: {e}")

    # Limpieza final
    if ruc:
        ruc = ''.join(filter(str.isdigit, ruc))
        if len(ruc) == 10:
            ruc += "001"
    
    # Si aún no hay nombre, usar el Common Name como fallback
    if not name:
        for attr in cert.subject:
            if attr.oid == NameOID.COMMON_NAME:
                name = str(attr.value).strip()
                break
            
    return ruc, name
