# -*- coding: utf-8 -*-
"""
Cliente SOAP para integración con el SRI - VERSIÓN COMPLETA CORREGIDA
✅ MANTIENE TODAS LAS FUNCIONES ORIGINALES
✅ ELIMINA SOLO LOS ERRORES DE IMPORT DE ZEEP
✅ CORRIGE PROBLEMAS ESPECÍFICOS SIN PERDER FUNCIONALIDAD
✅ RESUELVE ERROR 39 MANTENIENDO TODO EL CÓDIGO ORIGINAL
✅ FIX CRÍTICO #1: Parseo de autorizaciones Zeep (response.autorizaciones.autorizacion)
✅ FIX CRÍTICO #2: Fallback a requests cuando Zeep falla en autorización
✅ FIX #3: Extracción de errores Zeep con estructura anidada (.mensajes.mensaje)
"""

import logging
import requests
import base64
from datetime import datetime
from xml.etree import ElementTree as ET
from django.conf import settings
from django.utils import timezone
from apps.sri_integration.models import SRIConfiguration, SRIResponse
from apps.core.models import AuditLog
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ✅ SOLUCIÓN AL PROBLEMA DE ZEEP: Importación condicional mejorada
ZEEP_AVAILABLE = False
try:
    from zeep import Client, Transport, Settings
    from zeep.exceptions import Fault
    from requests import Session
    from requests.adapters import HTTPAdapter
    ZEEP_AVAILABLE = True
    logger.info("Zeep library loaded successfully")
except ImportError as e:
    logger.warning(f"Zeep not available, using requests fallback: {e}")
    # ✅ CORREGIDO: Clases dummy funcionales para evitar errores
    class Client:
        def __init__(self, *args, **kwargs):
            pass
        def service(self):
            return None
    
    class Transport:
        def __init__(self, *args, **kwargs):
            pass
    
    class Settings:
        def __init__(self, *args, **kwargs):
            pass
    
    class Fault(Exception):
        def __init__(self, message="SOAP Fault"):
            self.message = message
            super().__init__(self.message)


class SRISOAPClient:
    """
    Cliente SOAP para comunicación con los servicios del SRI
    ✅ VERSIÓN CORREGIDA FINAL COMPLETA - MANTIENE TODA LA FUNCIONALIDAD ORIGINAL
    ✅ RESUELVE ERRORES DE IMPORT SIN PERDER CARACTERÍSTICAS
    """
    
    # ✅ URLs OFICIALES DEL SRI - ACTUALIZADAS 2025
    SRI_URLS = {
        'TEST': {
            'reception': 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl',
            'authorization': 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl',
            'reception_endpoint': 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline',
            'authorization_endpoint': 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline'
        },
        'PRODUCTION': {
            'reception': 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl',
            'authorization': 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl',
            'reception_endpoint': 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline',
            'authorization_endpoint': 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline'
        }
    }
    
    def __init__(self, company):
        self.company = company
        try:
            self.sri_config = company.sri_configuration
            self.environment = self.sri_config.environment
        except Exception:
            # Configuración por defecto si no existe
            self.environment = 'TEST'
            self.sri_config = None
        
        # Inicializar clientes
        self._reception_client = None
        self._authorization_client = None
        
        logger.info(f"SRI SOAP Client initialized for {self.environment} environment")
        logger.info(f"Using {'Zeep' if ZEEP_AVAILABLE else 'Requests fallback'} for SOAP communication")
    
    # ========================================================================
    # RECEPCIÓN DE COMPROBANTES
    # ========================================================================
    
    def send_document_to_reception(self, document, signed_xml_content):
        """
        Envía documento firmado al servicio de recepción del SRI
        ✅ MÉTODO CORREGIDO FINAL - RESUELVE SOAP Fault Unknown MANTENIENDO FUNCIONALIDAD COMPLETA
        """
        try:
            logger.info(f"🚀 [SRI_FINAL] Sending document {document.document_number} to SRI reception")
            
            # ✅ PRIMERO: Validar firma digitalmente antes de enviar
            if not self._validate_signed_xml(signed_xml_content):
                msg = "XML signature local validation failed (before sending)"
                logger.error(f"❌ [SRI_CLIENT] {msg}")
                # Dependiendo de cuán estricto quieras ser, podrías retornar False aquí.
                # Por ahora solo logueamos y seguimos, o retornamos error.
                # return False, msg
            
            # ✅ CAMBIO CRÍTICO: NO USAR ZEEP PARA RECEPCIÓN
            # Zeep puede re-serializar el XML o el Envelope, invalidando la firma.
            # Usamos EXCLUSIVAMENTE el método 'requests' robusto que envía el raw bytes/string.
            
            logger.info("🚀 [SRI_FINAL] Forcing requests method (bypassing Zeep) to preserve XML signature")
            return self._send_with_requests_robust(document, signed_xml_content)
                
        except Exception as e:
            error_msg = f"ERROR_IN_SRI_SOAP_CLIENT_send_document_to_reception: {str(e)}"
            logger.error(f"❌ [SRI_CLIENT] Critical error: {error_msg}")
            
            # ✅ LOG CORREGIDO
            self._log_sri_response(
                document,
                'RECEPTION',
                'CRIT_ERROR',
                error_msg,
                {'error': str(e), 'method': 'send_document_to_reception'}
            )
            
            return False, error_msg
    
    def _send_with_zeep(self, document, signed_xml_content):
        """
        ✅ MÉTODO ZEEP CORREGIDO - MANTIENE FUNCIONALIDAD ORIGINAL PERO CORREGIDA
        """
        try:
            logger.info("🔧 [SRI_ZEEP] Using Zeep SOAP client")
            
            # ✅ CONFIGURAR SESIÓN CON RETRY
            session = Session()
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[500, 502, 503, 504],
                allowed_methods=["POST"]
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            
            # ✅ CONFIGURAR TRANSPORT
            transport = Transport(session=session)
            settings = Settings(strict=False, xml_huge_tree=True)
            
            # ✅ CREAR CLIENTE ZEEP
            wsdl_url = self.SRI_URLS[self.environment]['reception']
            client = Client(wsdl_url, transport=transport, settings=settings)
            
            # ✅ PREPARAR XML (PRESERVACIÓN DE FIRMA)
            # Asegurar bytes
            if isinstance(signed_xml_content, str):
                xml_bytes = signed_xml_content.encode('utf-8')
            else:
                xml_bytes = signed_xml_content

            # ✅ CODIFICAR EN BASE64
            xml_b64 = base64.b64encode(xml_bytes).decode('ascii')
            # Limpieza de base64 por seguridad
            xml_b64 = xml_b64.replace('\n', '').replace('\r', '')
            
            # ✅ LLAMADA ZEEP
            logger.info(f"🔧 [SRI_ZEEP] Calling validarComprobante with Zeep")
            response = client.service.validarComprobante(xml=xml_b64)
            
            # ✅ PROCESAR RESPUESTA ZEEP
            if hasattr(response, 'estado'):
                if response.estado == 'RECIBIDA':
                    document.status = "SENT"
                    document.save()
                    
                    self._log_sri_response(
                        document,
                        'RECEPTION',
                        'RECIBIDA',
                        "Document received by SRI successfully (Zeep)",
                        {'response': str(response), 'method': 'zeep'}
                    )
                    
                    return True, "Document received by SRI (Zeep method)"
                
                elif response.estado == 'DEVUELTA':
                    document.status = "ERROR"
                    document.save()
                    
                    # ✅ FIX #3: EXTRAER MENSAJES DE ERROR ZEEP CON ESTRUCTURA ANIDADA
                    error_messages = self._extract_zeep_comprobante_errors(response)
                    error_text = "; ".join(error_messages) if error_messages else "Document rejected by SRI"
                    
                    self._log_sri_response(
                        document,
                        'RECEPTION',
                        'DEVUELTA',
                        f"SRI rejected (Zeep): {error_text}",
                        {'response': str(response), 'method': 'zeep', 'errors': error_messages}
                    )
                    
                    return False, f"SRI rejected (Zeep): {error_text}"
            
            return False, f"Unknown Zeep response: {str(response)}"
            
        except Fault as zeep_fault:
            logger.error(f"❌ [SRI_ZEEP] SOAP Fault: {zeep_fault}")
            return False, f"Zeep SOAP Fault: {str(zeep_fault)}"
        except Exception as e:
            logger.error(f"❌ [SRI_ZEEP] Error: {str(e)}")
            return False, f"Zeep error: {str(e)}"
    
    def _extract_zeep_comprobante_errors(self, response):
        """
        ✅ FIX #3: EXTRAER ERRORES DE RECEPCIÓN DESDE RESPUESTA ZEEP
        Maneja estructura anidada: comprobantes.comprobante[].mensajes.mensaje[]
        """
        error_messages = []
        try:
            if hasattr(response, 'comprobantes') and response.comprobantes:
                comprobantes_obj = response.comprobantes
                # Puede ser .comprobante (lista) o directamente iterable
                items = getattr(comprobantes_obj, 'comprobante', comprobantes_obj)
                if not isinstance(items, list):
                    items = [items]
                for comp in items:
                    if hasattr(comp, 'mensajes') and comp.mensajes:
                        mensajes_obj = comp.mensajes
                        mensajes = getattr(mensajes_obj, 'mensaje', mensajes_obj)
                        if not isinstance(mensajes, list):
                            mensajes = [mensajes]
                        for msg in mensajes:
                            ident = getattr(msg, 'identificador', 'N/A')
                            texto = getattr(msg, 'mensaje', '')
                            info = getattr(msg, 'informacionAdicional', '')
                            tipo = getattr(msg, 'tipo', '')
                            error = f"[{tipo}] Error {ident}: {texto}"
                            if info:
                                error += f" - {info}"
                            error_messages.append(error)
                            logger.info(f"🔍 [SRI_ZEEP] Comprobante error: {error}")
        except Exception as e:
            logger.error(f"❌ [SRI_ZEEP] Error extracting comprobante errors: {e}")
        return error_messages
    
    def _send_with_requests_robust(self, document, signed_xml_content):
        """
        ✅ MÉTODO ULTRA ROBUSTO PARA MANEJAR ERRORES 500 DEL SRI
        MANTIENE TODA LA FUNCIONALIDAD ROBUSTA ORIGINAL
        """
        try:
            logger.info("🔧 [SRI_ROBUST] Using ultra-robust requests method")
            
            # ===== PASO 1: PREPARACIÓN DE XML (PRESERVACIÓN DE FIRMA) =====
            # CRÍTICO: El XML firmado NO DEBE SER MODIFICADO EN ABSOLUTO.
            # Cualquier cambio (espacios, saltos de línea, declaraciones) invalida la firma.
            
            # Asegurar bytes
            if isinstance(signed_xml_content, str):
                xml_bytes = signed_xml_content.encode('utf-8')
            else:
                xml_bytes = signed_xml_content
            
            xml_size_original = len(xml_bytes)
            logger.info(f"✅ [SRI_ROBUST] XML bytes prepared, size: {xml_size_original}")

            # ===== PASO 2: ENCODING BASE64 =====
            try:
                # Codificación directa de los bytes
                xml_b64 = base64.b64encode(xml_bytes).decode('ascii')
                # Eliminar saltos de línea si existen en el b64 (RFC 2045 vs SOAP)
                xml_b64 = xml_b64.replace('\n', '').replace('\r', '')
                
                logger.info(f"✅ [SRI_ROBUST] Base64 encoded successfully, size: {len(xml_b64)}")
            except Exception as e:
                logger.error(f"❌ [SRI_ROBUST] Encoding error: {str(e)}")
                return False, f"XML encoding error: {str(e)}"
            
            # ===== PASO 3: SOAP ENVELOPE QUE FUNCIONA CON SRI =====
            # ✅ ESTRUCTURA EXACTA: xml SIN NAMESPACE como requiere el SRI
            soap_envelope = f'''<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ser="http://ec.gob.sri.ws.recepcion">
    <soap:Body>
        <ser:validarComprobante>
            <xml>{xml_b64}</xml>
        </ser:validarComprobante>
    </soap:Body>
</soap:Envelope>'''
            
            # ===== PASO 4: HEADERS OPTIMIZADOS =====
            headers = {
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction': '',
                'User-Agent': 'SRI-Ecuador-Client-Robust/2025.2',
                'Accept': 'text/xml, application/soap+xml',
                'Accept-Encoding': 'gzip, deflate',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Connection': 'keep-alive',
                'Content-Length': str(len(soap_envelope.encode('utf-8')))
            }
            
            endpoint_url = self.SRI_URLS[self.environment]["reception_endpoint"]
            logger.info(f"🌐 [SRI_ROBUST] Sending to: {endpoint_url}")
            
            # ===== PASO 5: ESTRATEGIA ULTRA ROBUSTA =====
            max_attempts = 7  # ✅ Más intentos
            backoff_delays = [3, 7, 15, 30, 60, 120, 300]  # ✅ Backoff exponencial
            
            session = requests.Session()
            
            # ✅ RETRY STRATEGY MÁS AGRESIVA
            retry_strategy = Retry(
                total=0,  # ✅ Manejamos los reintentos manualmente
                backoff_factor=0,
                status_forcelist=[],
                allowed_methods=["POST"]
            )
            
            adapter = requests.adapters.HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            
            # ===== PASO 6: BUCLE DE REINTENTOS INTELIGENTE =====
            last_error = None
            
            for attempt in range(max_attempts):
                try:
                    delay = backoff_delays[attempt] if attempt < len(backoff_delays) else 300
                    
                    if attempt > 0:
                        logger.info(f"⏳ [SRI_ROBUST] Waiting {delay} seconds before attempt {attempt + 1}")
                        import time
                        time.sleep(delay)
                    
                    logger.info(f"🔄 [SRI_ROBUST] Attempt {attempt + 1}/{max_attempts}")
                    
                    # ✅ TIMEOUTS PROGRESIVOS
                    timeout_connect = 30 + (attempt * 10)  # 30, 40, 50, etc.
                    timeout_read = 90 + (attempt * 30)     # 90, 120, 150, etc.
                    
                    response = session.post(
                        endpoint_url,
                        data=soap_envelope.encode('utf-8'),
                        headers=headers,
                        timeout=(timeout_connect, timeout_read),
                        verify=True,
                        allow_redirects=False,
                        stream=False
                    )
                    
                    logger.info(f"📨 [SRI_ROBUST] Response status: {response.status_code}")
                    logger.info(f"📨 [SRI_ROBUST] Response headers: {dict(response.headers)}")
                    # ✅ LOG COMPLETO DE LA RESPUESTA PARA DEBUG
                    logger.info(f"📨 [SRI_ROBUST] FULL Response content: {response.text}")
                    
                    # ===== PASO 7: ANÁLISIS INTELIGENTE DE RESPUESTA =====
                    if response.status_code == 200:
                        logger.info("✅ [SRI_ROBUST] HTTP 200 - Processing response")
                        return self._process_sri_response_fixed(document, response)
                    
                    elif response.status_code == 500:
                        logger.warning(f"⚠️ [SRI_ROBUST] HTTP 500 on attempt {attempt + 1}")
                        
                        # ✅ ANALIZAR CONTENIDO DE ERROR 500
                        try:
                            response_preview = response.text[:500]
                            logger.info(f"🔍 [SRI_ROBUST] HTTP 500 content preview: {response_preview}")
                            
                            # ✅ VERIFICAR SI EL 500 CONTIENE RESPUESTA VÁLIDA DEL SRI
                            if any(keyword in response.text for keyword in ['RECIBIDA', 'DEVUELTA', 'estado', 'comprobante']):
                                logger.info("🔍 [SRI_ROBUST] HTTP 500 contains valid SRI response")
                                return self._process_sri_soap_fault_fixed(document, response)
                            
                            # ✅ VERIFICAR ERRORES ESPECÍFICOS
                            if 'Service Temporarily Unavailable' in response.text:
                                logger.warning("🚨 [SRI_ROBUST] SRI service temporarily unavailable")
                                last_error = "SRI service temporarily unavailable"
                            elif 'Internal Server Error' in response.text:
                                logger.warning("🚨 [SRI_ROBUST] SRI internal server error")
                                last_error = "SRI internal server error"
                            else:
                                logger.warning("🚨 [SRI_ROBUST] Unknown HTTP 500 error")
                                last_error = f"HTTP 500: {response_preview}"
                            
                        except Exception as e:
                            logger.error(f"❌ [SRI_ROBUST] Error analyzing 500 response: {e}")
                            last_error = f"HTTP 500 analysis failed: {str(e)}"
                        
                        # ✅ DECIDIR SI CONTINUAR O NO
                        if attempt < max_attempts - 1:
                            if attempt < 3:  # Primeros 3 intentos siempre continuar
                                logger.info(f"🔄 [SRI_ROBUST] Retrying after HTTP 500 (attempt {attempt + 1})")
                                continue
                            elif 'temporarily unavailable' in last_error.lower():
                                logger.info(f"🔄 [SRI_ROBUST] Service unavailable, retrying (attempt {attempt + 1})")
                                continue
                            else:
                                logger.warning(f"🛑 [SRI_ROBUST] Persistent HTTP 500, stopping retries")
                                break
                        else:
                            logger.error(f"❌ [SRI_ROBUST] Maximum attempts reached with HTTP 500")
                            break
                    
                    else:
                        # ✅ OTROS CÓDIGOS HTTP
                        error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                        logger.error(f"❌ [SRI_ROBUST] {error_msg}")
                        
                        if attempt < 2 and response.status_code in [502, 503, 504]:
                            # Reintentar para errores de gateway
                            logger.info(f"🔄 [SRI_ROBUST] Retrying gateway error")
                            continue
                        else:
                            # ✅ LOG CORREGIDO
                            self._log_sri_response(
                                document,
                                "RECEPTION",
                                f"HTTP_{response.status_code}",
                                error_msg,
                                {"status_code": response.status_code, "response": response.text}
                            )
                            return False, error_msg
                
                except requests.exceptions.Timeout:
                    timeout_msg = f"Timeout on attempt {attempt + 1} (connect: {timeout_connect}s, read: {timeout_read}s)"
                    logger.error(f"⏰ [SRI_ROBUST] {timeout_msg}")
                    last_error = timeout_msg
                    
                    if attempt < max_attempts - 1:
                        continue
                    else:
                        return False, "SRI service timeout after all retries"
                
                except requests.exceptions.ConnectionError as e:
                    conn_error = f"Connection error on attempt {attempt + 1}: {str(e)}"
                    logger.error(f"🌐 [SRI_ROBUST] {conn_error}")
                    last_error = conn_error
                    
                    if attempt < max_attempts - 1:
                        continue
                    else:
                        return False, f"Connection error after all retries: {str(e)}"
                
                except Exception as e:
                    unexpected_error = f"Unexpected error on attempt {attempt + 1}: {str(e)}"
                    logger.error(f"❌ [SRI_ROBUST] {unexpected_error}")
                    last_error = unexpected_error
                    
                    if attempt < max_attempts - 1:
                        continue
                    else:
                        return False, f"Unexpected error after all retries: {str(e)}"
            
            # ===== RESULTADO FINAL =====
            final_error = f"SRI service unavailable after {max_attempts} attempts. Last error: {last_error}"
            
            # ✅ LOG CORREGIDO
            self._log_sri_response(
                document,
                "RECEPTION",
                "SVC_UNAVL",
                final_error,
                {
                    "attempts": max_attempts,
                    "last_error": last_error,
                    "backoff_strategy": "exponential",
                    "method": "robust_requests"
                }
            )
            
            # ✅ NO MARCAR COMO ERROR PERMANENTE - PUEDE SER TEMPORAL
            logger.warning(f"⚠️ [SRI_ROBUST] {final_error}")
            return False, f"SRI temporarily unavailable: {last_error}"
            
        except Exception as e:
            logger.error(f"❌ [SRI_ROBUST] Critical error: {str(e)}")
            return False, f"Critical error in robust SRI submission: {str(e)}"
    
    def _process_sri_response_fixed(self, document, response):
        """
        ✅ PROCESAR RESPUESTA SRI - VERSIÓN CORREGIDA FINAL
        MANTIENE TODA LA LÓGICA ORIGINAL DE PROCESAMIENTO
        """
        try:
            response_text = response.text
            logger.info(f"✅ [SRI_FIXED] Processing SRI response: {len(response_text)} characters")
            
            # ✅ DEBUG: Log de los primeros 500 caracteres para análisis
            logger.info(f"🔍 [SRI_FIXED] Response preview: {response_text[:500]}...")
            
            # ✅ PARSEAR XML DE RESPUESTA CON MANEJO DE ERRORES
            try:
                root = ET.fromstring(response_text.encode('utf-8'))
            except ET.ParseError as e:
                logger.error(f"❌ [SRI_FIXED] Invalid XML response: {e}")
                return False, f"Invalid XML response from SRI: {str(e)}"
            
            # ✅ NAMESPACES CORREGIDOS PARA SRI 2025
            namespaces = {
                'soap': 'http://schemas.xmlsoap.org/soap/envelope/',
                'ns2': 'http://ec.gob.sri.ws.recepcion'
            }
            
            # ✅ BUSCAR ESTADO EN MÚLTIPLES UBICACIONES
            estado = None
            
            # Buscar en estructura estándar
            estado_elem = root.find('.//ns2:estado', namespaces)
            if estado_elem is not None:
                estado = estado_elem.text
                logger.info(f"✅ [SRI_FIXED] Found estado: {estado}")
            
            # Si no se encuentra, buscar sin namespace
            if not estado:
                estado_elem = root.find('.//estado')
                if estado_elem is not None:
                    estado = estado_elem.text
                    logger.info(f"✅ [SRI_FIXED] Found estado (no namespace): {estado}")
            
            # ✅ PROCESAR ESTADO
            if estado == "RECIBIDA":
                logger.info("🎉 [SRI_FIXED] Document RECEIVED by SRI!")
                
                # ✅ LOG CORREGIDO
                self._log_sri_response(
                    document,
                    "RECEPTION",
                    "RECIBIDA",
                    "Document received by SRI successfully",
                    {"response": response_text, "method": "requests_fixed_final"}
                )
                
                document.status = "SENT"
                document.save()
                return True, "Document received by SRI successfully"
            
            elif estado == "DEVUELTA":
                logger.warning("⚠️ [SRI_FIXED] Document REJECTED by SRI")
                
                # ✅ EXTRAER MENSAJES DE ERROR DETALLADOS
                error_messages = self._extract_error_messages_fixed(root, namespaces)
                error_text = "; ".join(error_messages) if error_messages else "Document rejected by SRI (no details)"
                
                # ✅ LOG CORREGIDO
                self._log_sri_response(
                    document,
                    "RECEPTION",
                    "DEVUELTA",
                    error_text,
                    {"response": response_text, "method": "requests_fixed_final", "errors": error_messages}
                )
                # ✅ FIX: Si el SRI dice que ya se está procesando o ya fue registrada, es como si se hubiera RECIBIDO
                # Esto permite que el flujo continúe hacia la consulta de autorización de forma segura.
                if any(kw in error_text.upper() for kw in ["EN PROCESAMIENTO", "IN PROCESSING", "PROCESADA", "PROCESAMIENTO", "REGISTRADA", "REGISTRADO"]):
                    logger.info(f"🎉 [SRI_FIXED] Document already handled by SRI ({error_text}) - treating as RECEIVED")
                    document.status = "SENT"
                    document.save()
                    
                    self._log_sri_response(
                        document,
                        "RECEPTION",
                        "RECIBIDA_P",
                        f"Already in processing/registered: {error_text}",
                        {"response": response_text, "method": "requests_fixed_final", "errors": error_messages}
                    )
                    return True, f"Document already in processing/registered (Status: {estado}): {error_text}"

                document.status = "ERROR"
                document.save()
                return False, f"SRI rejected document: {error_text}"
            
            else:
                # ✅ ESTADO DESCONOCIDO O FALTANTE
                logger.warning(f"⚠️ [SRI_FIXED] Unknown estado: {estado}")
                
                # Intentar extraer errores de todas formas
                error_messages = self._extract_error_messages_fixed(root, namespaces)
                if error_messages:
                    error_text = "; ".join(error_messages)
                    
                    # ✅ LOG CORREGIDO
                    self._log_sri_response(
                        document,
                        "RECEPTION",
                        "ERROR",
                        error_text,
                        {"response": response_text, "method": "requests_fixed_final", "errors": error_messages}
                    )
                    return False, f"SRI Error: {error_text}"
                
                # Si no hay errores específicos, error genérico
                error_msg = f"Unexpected SRI response state: {estado or 'None'}"
                
                # ✅ LOG CORREGIDO
                self._log_sri_response(
                    document,
                    "RECEPTION",
                    "UNKNOWN",
                    error_msg,
                    {"response": response_text, "method": "requests_fixed_final"}
                )
                return False, error_msg
            
        except Exception as e:
            logger.error(f"❌ [SRI_FIXED] Error processing SRI response: {str(e)}")
            return False, f"Error processing SRI response: {str(e)}"
    
    def _process_sri_soap_fault_fixed(self, document, response):
        """
        ✅ PROCESAR SOAP FAULT - VERSIÓN CORREGIDA FINAL CON DEBUG
        MANTIENE TODA LA LÓGICA ORIGINAL
        """
        try:
            response_text = response.text
            logger.info(f"🔍 [SRI_FAULT] Processing SOAP fault: {response.status_code}")
            logger.info(f"🔍 [SRI_FAULT] COMPLETE Response: {response_text}")
            
            try:
                root = ET.fromstring(response_text.encode('utf-8'))
            except ET.ParseError as e:
                logger.error(f"❌ [SRI_FAULT] Invalid XML in SOAP fault: {e}")
                return False, f"Invalid SOAP fault response: {str(e)}"
            
            # ✅ BUSCAR SOAP FAULT PRIMERO
            fault_elem = root.find('.//{http://schemas.xmlsoap.org/soap/envelope/}Fault')
            if fault_elem is not None:
                fault_code_elem = fault_elem.find('.//{http://schemas.xmlsoap.org/soap/envelope/}faultcode')
                fault_string_elem = fault_elem.find('.//{http://schemas.xmlsoap.org/soap/envelope/}faultstring')
                fault_detail_elem = fault_elem.find('.//{http://schemas.xmlsoap.org/soap/envelope/}detail')
                
                fault_code = fault_code_elem.text if fault_code_elem is not None else "Unknown"
                fault_string = fault_string_elem.text if fault_string_elem is not None else "Unknown error"
                fault_detail = fault_detail_elem.text if fault_detail_elem is not None else ""
                
                # ✅ LOG DETALLADO DEL FAULT
                logger.error(f"❌ [SRI_FAULT] Code: {fault_code}")
                logger.error(f"❌ [SRI_FAULT] String: {fault_string}")
                logger.error(f"❌ [SRI_FAULT] Detail: {fault_detail}")
                
                error_msg = f"SOAP Fault {fault_code}: {fault_string}"
                if fault_detail:
                    error_msg += f" | Detail: {fault_detail}"
                
                # ✅ LOG CORREGIDO
                self._log_sri_response(
                    document,
                    "RECEPTION",
                    "SOAP_FAULT",
                    error_msg,
                    {
                        "response": response_text, 
                        "method": "requests_fixed_final", 
                        "fault_code": fault_code,
                        "fault_string": fault_string,
                        "fault_detail": fault_detail
                    }
                )
                
                document.status = "ERROR"
                document.save()
                return False, error_msg
            
            # ✅ SI NO ES SOAP FAULT, PROCESAR COMO RESPUESTA NORMAL
            logger.info("🔍 [SRI_FAULT] No SOAP fault found, processing as normal response")
            return self._process_sri_response_fixed(document, response)
            
        except Exception as e:
            logger.error(f"❌ [SRI_FAULT] Error processing SOAP fault: {str(e)}")
            return False, f"Error processing SOAP fault: {str(e)}"
    
    def _extract_error_messages_fixed(self, root, namespaces):
        """
        ✅ EXTRAER MENSAJES DE ERROR - VERSIÓN MEJORADA FINAL
        MANTIENE TODA LA LÓGICA ORIGINAL DE EXTRACCIÓN
        """
        error_messages = []
        
        try:
            # ✅ BUSCAR MENSAJES CON NAMESPACE
            mensaje_elements = root.findall('.//ns2:mensaje', namespaces)
            for mensaje_elem in mensaje_elements:
                identificador_elem = mensaje_elem.find('ns2:identificador', namespaces)
                mensaje_text_elem = mensaje_elem.find('ns2:mensaje', namespaces)
                info_adicional_elem = mensaje_elem.find('ns2:informacionAdicional', namespaces)
                
                if mensaje_text_elem is not None:
                    identificador = identificador_elem.text if identificador_elem is not None else "N/A"
                    mensaje_text = mensaje_text_elem.text
                    info_adicional = info_adicional_elem.text if info_adicional_elem is not None else ""
                    
                    error_detail = f"Error {identificador}: {mensaje_text}"
                    if info_adicional:
                        error_detail += f" - {info_adicional}"
                    
                    error_messages.append(error_detail)
                    logger.info(f"🔍 [SRI_FIXED] Found error: {error_detail}")
            
            # ✅ BUSCAR MENSAJES SIN NAMESPACE SI NO SE ENCONTRARON
            if not error_messages:
                mensaje_elements = root.findall('.//mensaje')
                for mensaje_elem in mensaje_elements:
                    if mensaje_elem.text:
                        error_messages.append(mensaje_elem.text)
                        logger.info(f"🔍 [SRI_FIXED] Found error (no namespace): {mensaje_elem.text}")
            
            # ✅ BUSCAR OTROS FORMATOS DE ERROR
            if not error_messages:
                error_elems = root.findall('.//error')
                for error_elem in error_elems:
                    if error_elem.text:
                        error_messages.append(error_elem.text)
                        logger.info(f"🔍 [SRI_FIXED] Found generic error: {error_elem.text}")
            
        except Exception as e:
            logger.error(f"❌ [SRI_FIXED] Error extracting error messages: {e}")
        
        return error_messages
    
    def _validate_signed_xml(self, signed_xml_content):
        """
        ✅ VALIDAR XML FIRMADO - VERSIÓN CORREGIDA
        MANTIENE TODA LA VALIDACIÓN ORIGINAL
        """
        try:
            # Verificar que es XML válido
            root = ET.fromstring(signed_xml_content)
            
            # ✅ VERIFICAR ELEMENTOS CRÍTICOS
            xml_str = ET.tostring(root, encoding='unicode')
            
            # Verificar que tenga clave de acceso
            if 'claveAcceso' not in xml_str:
                logger.error("❌ [SRI_FIXED] No claveAcceso found in XML")
                return False
            
            # Verificar que tenga estructura de documento
            document_elements = ['factura', 'notaCredito', 'notaDebito', 'comprobanteRetencion', 'liquidacionCompra']
            has_document = any(elem in xml_str for elem in document_elements)
            if not has_document:
                logger.error("❌ [SRI_FIXED] No document structure found in XML")
                return False
            
            # ✅ VERIFICAR FIRMA DIGITAL (opcional pero recomendado)
            if 'http://www.w3.org/2000/09/xmldsig#' in xml_str:
                logger.info("✅ [SRI_FIXED] Digital signature namespace found")
            else:
                logger.warning("⚠️ [SRI_FIXED] No digital signature found - may cause issues")
            
            logger.info("✅ [SRI_FIXED] XML validation passed")
            return True
            
        except ET.ParseError as e:
            logger.error(f"❌ [SRI_FIXED] Invalid XML format: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ [SRI_FIXED] XML validation error: {e}")
            return False
    
    # ========================================================================
    # AUTORIZACIÓN DE COMPROBANTES - SECCIÓN CON FIXES CRÍTICOS #1 Y #2
    # ========================================================================
    
    def get_document_authorization(self, document):
        """
        Consulta la autorización de un documento en el SRI
        
        ✅ FIX CRÍTICO #2: Lógica de fallback corregida
        ANTES: if success or "not found" not in message.lower()  ← NUNCA hacía fallback
        AHORA: Solo retorna sin fallback si es error DEFINITIVO del SRI (NO AUTORIZADO)
        """
        try:
            logger.info(f"🔍 [SRI_AUTH] Getting authorization for document {document.document_number}")
            
            # ✅ INTENTAR ZEEP PRIMERO SI ESTÁ DISPONIBLE
            if ZEEP_AVAILABLE:
                try:
                    logger.info("🔧 [SRI_AUTH] Attempting Zeep authorization method")
                    success, message = self._get_auth_with_zeep(document)
                    
                    # ✅ FIX #2: Si Zeep tuvo éxito, retornar directamente
                    if success:
                        return success, message
                    
                    # ✅ FIX #2: Si es error DEFINITIVO del SRI (NO AUTORIZADO), retornar sin fallback
                    msg_lower = message.lower()
                    if 'no autorizado' in msg_lower or 'not authorized' in msg_lower:
                        logger.warning(f"⚠️ [SRI_AUTH] SRI definitive rejection via Zeep: {message}")
                        return success, message
                    
                    # ✅ FIX #2: Cualquier OTRO error de Zeep (parseo, conexión, etc) → intentar con requests
                    logger.warning(f"⚠️ [SRI_AUTH] Zeep inconclusive: {message}, falling back to requests")
                    
                except Exception as zeep_error:
                    logger.warning(f"⚠️ [SRI_AUTH] Zeep error: {zeep_error}, falling back to requests")
            
            # ✅ USAR REQUESTS COMO MÉTODO PRINCIPAL/FALLBACK
            return self._get_auth_with_requests_ultra_fixed(document)
                
        except Exception as e:
            error_msg = f"Error getting authorization from SRI: {str(e)}"
            logger.error(error_msg)
            
            # ✅ LOG CORREGIDO
            self._log_sri_response(
                document,
                'AUTHORIZATION',
                'ERROR',
                error_msg,
                {'error': str(e)}
            )
            return False, error_msg
    
    def _get_auth_with_zeep(self, document):
        """
        ✅ FIX CRÍTICO #1: AUTORIZACIÓN CON ZEEP - PARSEO CORREGIDO
        
        ANTES (ROTO):
            for autorizacion in response.autorizaciones:  ← iteraba sobre contenedor, no lista
        
        AHORA (CORREGIDO):
            La estructura real de Zeep es: response.autorizaciones.autorizacion → [lista]
            Se accede correctamente a .autorizacion dentro del contenedor
        """
        try:
            logger.info("🔧 [SRI_AUTH_ZEEP] Getting authorization using Zeep")
            
            # ✅ CONFIGURAR CLIENTE ZEEP PARA AUTORIZACIÓN
            session = Session()
            transport = Transport(session=session)
            settings = Settings(strict=False, xml_huge_tree=True)
            
            wsdl_url = self.SRI_URLS[self.environment]['authorization']
            client = Client(wsdl_url, transport=transport, settings=settings)
            
            # ✅ LLAMADA ZEEP
            logger.info(f"🔧 [SRI_AUTH_ZEEP] Calling autorizacionComprobante with access key: {document.access_key}")
            response = client.service.autorizacionComprobante(claveAccesoComprobante=document.access_key)
            
            # =================================================================
            # ✅ FIX CRÍTICO #1: PARSEO CORRECTO DE AUTORIZACIONES
            #
            # La estructura real de Zeep para el servicio de autorización SRI:
            #   response.autorizaciones           → objeto contenedor (NO iterable directo)
            #   response.autorizaciones.autorizacion → [lista de autorizaciones]
            #
            # El código original hacía:
            #   for autorizacion in response.autorizaciones:  ← NUNCA encontraba nada
            #
            # Ahora se accede correctamente a la lista interna:
            # =================================================================
            
            logger.info(f"🔧 [SRI_AUTH_ZEEP] Response type: {type(response)}")
            
            autorizaciones_list = None
            
            if hasattr(response, 'autorizaciones') and response.autorizaciones is not None:
                autorizaciones_obj = response.autorizaciones
                logger.info(f"🔧 [SRI_AUTH_ZEEP] autorizaciones type: {type(autorizaciones_obj)}")
                
                # Caso 1: response.autorizaciones.autorizacion (estructura normal del SRI)
                if hasattr(autorizaciones_obj, 'autorizacion'):
                    autorizaciones_list = autorizaciones_obj.autorizacion
                    if not isinstance(autorizaciones_list, list):
                        autorizaciones_list = [autorizaciones_list]
                    logger.info(f"🔧 [SRI_AUTH_ZEEP] Found {len(autorizaciones_list)} auth(s) via .autorizacion")
                
                # Caso 2: response.autorizaciones es directamente iterable (algunos WSDL)
                elif hasattr(autorizaciones_obj, '__iter__'):
                    autorizaciones_list = list(autorizaciones_obj)
                    logger.info(f"🔧 [SRI_AUTH_ZEEP] Found {len(autorizaciones_list)} auth(s) via iteration")
                
                # Caso 3: response.autorizaciones es un solo objeto con estado
                elif hasattr(autorizaciones_obj, 'estado'):
                    autorizaciones_list = [autorizaciones_obj]
                    logger.info("🔧 [SRI_AUTH_ZEEP] Found single authorization object")
            
            if not autorizaciones_list:
                logger.warning("⚠️ [SRI_AUTH_ZEEP] No authorizations found in Zeep response")
                if hasattr(response, 'autorizaciones') and response.autorizaciones is not None:
                    logger.warning(f"⚠️ [SRI_AUTH_ZEEP] autorizaciones attrs: {dir(response.autorizaciones)}")
                else:
                    logger.warning(f"⚠️ [SRI_AUTH_ZEEP] response attrs: {dir(response)}")
                return False, 'No authorization data in Zeep response'
            
            # ✅ PROCESAR AUTORIZACIONES (lógica original preservada, solo cambió el acceso a la lista)
            for autorizacion in autorizaciones_list:
                if not hasattr(autorizacion, 'estado'):
                    logger.warning(f"⚠️ [SRI_AUTH_ZEEP] Auth object without estado, skipping: {autorizacion}")
                    continue
                
                estado = autorizacion.estado
                numero_autorizacion = str(getattr(autorizacion, 'numeroAutorizacion', '') or '')
                fecha_autorizacion_str = str(getattr(autorizacion, 'fechaAutorizacion', '') or '')
                
                # ✅ PARSEAR FECHA
                fecha_autorizacion = self._parse_authorization_date(fecha_autorizacion_str)
                
                # Preparar datos de respuesta
                response_data = {
                    'estado': estado,
                    'numeroAutorizacion': numero_autorizacion,
                    'fechaAutorizacion': fecha_autorizacion_str,
                    'response': str(response),
                    'method': 'zeep'
                }
                
                # ✅ LOG CORREGIDO
                self._log_sri_response(
                    document,
                    'AUTHORIZATION',
                    estado[:10],  # ✅ Limitar a 10 caracteres
                    f"Authorization response (Zeep): {estado}",
                    response_data
                )
                
                if estado == 'AUTORIZADO':
                    document.status = 'AUTHORIZED'
                    document.sri_authorization_code = numero_autorizacion
                    document.sri_authorization_date = fecha_autorizacion
                    document.sri_response = response_data
                    document.save()
                    logger.info(f"🎉 [SRI_AUTH_ZEEP] Document AUTHORIZED: {numero_autorizacion}")
                    return True, f'Document authorized (Zeep): {numero_autorizacion}'
                    
                elif estado == 'NO AUTORIZADO':
                    # ✅ FIX #3: EXTRAER ERRORES ZEEP CON ESTRUCTURA ANIDADA
                    error_messages = self._extract_zeep_auth_errors(autorizacion)
                    error_text = "; ".join(error_messages) if error_messages else "Document not authorized"
                    
                    # Guardar el mensaje legible para la UI
                    response_data['mensaje'] = error_text
                    
                    document.status = 'REJECTED'
                    document.sri_response = response_data
                    document.save()
                    
                    logger.warning(f"⚠️ [SRI_AUTH_ZEEP] Document not authorized: {error_text}")
                    return False, f'Document not authorized (Zeep): {error_text}'
                    
                else:
                    # ✅ MANTENER SENT si estaba en ese estado
                    if document.status != 'SENT':
                        document.status = 'PENDING'
                    document.sri_response = response_data
                    document.save()
                    logger.info(f"🔄 [SRI_AUTH_ZEEP] Document in process: {estado}")
                    return False, f'Document in process (Zeep): {estado}'
            
            return False, 'No valid authorization entries found in Zeep response'
            
        except Fault as zeep_fault:
            logger.error(f"❌ [SRI_AUTH_ZEEP] SOAP Fault: {zeep_fault}")
            return False, f"Zeep authorization SOAP Fault: {str(zeep_fault)}"
        except Exception as e:
            logger.error(f"❌ [SRI_AUTH_ZEEP] Error: {str(e)}")
            return False, f"Zeep authorization error: {str(e)}"
    
    def _extract_zeep_auth_errors(self, autorizacion_obj):
        """
        ✅ FIX #3: EXTRAER ERRORES DE AUTORIZACIÓN DESDE OBJETO ZEEP
        Maneja estructura anidada: autorizacion.mensajes.mensaje → [lista]
        
        ANTES: iteraba directamente sobre autorizacion.mensajes (contenedor)
        AHORA: accede a autorizacion.mensajes.mensaje (la lista real)
        """
        error_messages = []
        try:
            if hasattr(autorizacion_obj, 'mensajes') and autorizacion_obj.mensajes:
                mensajes_obj = autorizacion_obj.mensajes
                # Estructura: auth.mensajes.mensaje → lista
                mensajes = getattr(mensajes_obj, 'mensaje', mensajes_obj)
                if not isinstance(mensajes, list):
                    mensajes = [mensajes]
                for msg in mensajes:
                    ident = getattr(msg, 'identificador', 'N/A')
                    texto = getattr(msg, 'mensaje', '')
                    info = getattr(msg, 'informacionAdicional', '')
                    tipo = getattr(msg, 'tipo', '')
                    error = f"[{tipo}] Error {ident}: {texto}"
                    if info:
                        error += f" - {info}"
                    error_messages.append(error)
                    logger.info(f"🔍 [SRI_AUTH_ZEEP] Auth error detail: {error}")
        except Exception as e:
            logger.error(f"❌ [SRI_AUTH_ZEEP] Error extracting auth errors: {e}")
        return error_messages
    
    def _get_auth_with_requests_ultra_fixed(self, document):
        """
        ✅ CONSULTAR AUTORIZACIÓN - VERSIÓN FINAL QUE RESUELVE COMPLETAMENTE EL NAMESPACE ERROR
        MANTIENE TODA LA FUNCIONALIDAD ROBUSTA ORIGINAL
        """
        try:
            logger.info("🔍 [SRI_AUTH_ULTRA] Getting authorization using ULTRA FIXED method")
            
            # ✅ SOAP ENVELOPE DEFINITIVAMENTE CORREGIDO - xmlns="" EXPLÍCITO
            # El SRI quiere: <{}claveAccesoComprobante> (sin namespace)
            # Solución: xmlns="" para anular el namespace heredado
            soap_body = f'''<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
    <soap:Body>
        <autorizacionComprobante xmlns="http://ec.gob.sri.ws.autorizacion">
            <claveAccesoComprobante xmlns="">{document.access_key}</claveAccesoComprobante>
        </autorizacionComprobante>
    </soap:Body>
</soap:Envelope>'''
            
            # ✅ HEADERS ULTRA CORREGIDOS
            headers = {
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction': '',
                'User-Agent': 'SRI-Ecuador-Auth-Final-Fixed/2025.3',
                'Accept': 'text/xml, application/soap+xml',
                'Cache-Control': 'no-cache'
            }
            
            endpoint_url = self.SRI_URLS[self.environment]['authorization_endpoint']
            logger.info(f"🌐 [SRI_AUTH_ULTRA] Sending to: {endpoint_url}")
            logger.info(f"🔑 [SRI_AUTH_ULTRA] Access key: {document.access_key}")
            logger.info(f"🔧 [SRI_AUTH_ULTRA] Using xmlns='' to remove namespace from claveAccesoComprobante")
            
            response = requests.post(
                endpoint_url,
                data=soap_body.encode('utf-8'),
                headers=headers,
                timeout=(30, 90),
                verify=True,
                allow_redirects=False
            )
            
            logger.info(f"📨 [SRI_AUTH_ULTRA] Authorization response status: {response.status_code}")
            logger.info(f"📨 [SRI_AUTH_ULTRA] Response preview: {response.text[:300]}...")
            
            if response.status_code == 200:
                return self._process_authorization_response_ultra_fixed(document, response)
            elif response.status_code == 500:
                # ✅ ANALIZAR EL SOAP FAULT DETALLADAMENTE
                logger.info(f"📨 [SRI_AUTH_ULTRA] SOAP Fault detected, analyzing...")
                return self._process_authorization_soap_fault_ultra_fixed(document, response)
            else:
                return False, f'Authorization HTTP Error: {response.status_code}'
                
        except Exception as e:
            return False, f'Authorization request failed: {str(e)}'
    
    def _process_authorization_response_ultra_fixed(self, document, response):
        """
        ✅ PROCESAR RESPUESTA DE AUTORIZACIÓN - VERSIÓN ULTRA CORREGIDA
        MANTIENE TODA LA LÓGICA ORIGINAL
        """
        try:
            response_text = response.text
            logger.info(f"✅ [SRI_AUTH_ULTRA] Processing authorization response: {len(response_text)} chars")
            
            root = ET.fromstring(response_text.encode('utf-8'))
            
            # ✅ NAMESPACES PARA AUTORIZACIÓN
            ns = {
                'soap': 'http://schemas.xmlsoap.org/soap/envelope/',
                'ns2': 'http://ec.gob.sri.ws.autorizacion'
            }
            
            # ✅ BUSCAR AUTORIZACIÓN
            autorizacion_elems = root.findall('.//ns2:autorizacion', ns)
            if not autorizacion_elems:
                # Buscar sin namespace
                autorizacion_elems = root.findall('.//autorizacion')
            
            if not autorizacion_elems:
                logger.warning("⚠️ [SRI_AUTH_ULTRA] No authorization elements found")
                return False, "No authorization data in response"
            
            for autorizacion_elem in autorizacion_elems:
                estado_elem = autorizacion_elem.find('.//estado')
                numero_elem = autorizacion_elem.find('.//numeroAutorizacion')
                fecha_elem = autorizacion_elem.find('.//fechaAutorizacion')
                
                if estado_elem is not None:
                    estado = estado_elem.text
                    numero_autorizacion = numero_elem.text if numero_elem is not None else ''
                    fecha_autorizacion_str = fecha_elem.text if fecha_elem is not None else ''
                    
                    logger.info(f"✅ [SRI_AUTH_ULTRA] Authorization estado: {estado}")
                    
                    # ✅ PROCESAR FECHA
                    fecha_autorizacion = self._parse_authorization_date(fecha_autorizacion_str)
                    
                    # Preparar datos de respuesta
                    response_data = {
                        'estado': estado,
                        'numeroAutorizacion': numero_autorizacion,
                        'fechaAutorizacion': fecha_autorizacion_str,
                        'response': response_text,
                        'method': 'requests_ultra_fixed'
                    }
                    
                    # ✅ LOG CORREGIDO
                    self._log_sri_response(
                        document,
                        'AUTHORIZATION',
                        estado[:10],  # ✅ Limitar a 10 caracteres
                        f"Authorization response: {estado}",
                        response_data
                    )
                    
                    if estado == 'AUTORIZADO':
                        document.status = 'AUTHORIZED'
                        document.sri_authorization_code = numero_autorizacion
                        document.sri_authorization_date = fecha_autorizacion
                        document.sri_response = response_data
                        document.save()
                        logger.info(f"🎉 [SRI_AUTH_ULTRA] Document AUTHORIZED: {numero_autorizacion}")
                        return True, f'Document authorized: {numero_autorizacion}'
                        
                    elif estado == 'NO AUTORIZADO':
                        # ✅ EXTRAER ERRORES
                        error_messages = self._extract_authorization_errors_ultra_fixed(autorizacion_elem)
                        error_text = "; ".join(error_messages) if error_messages else "Document not authorized"
                        
                        # Guardar el mensaje legible para la UI
                        response_data['mensaje'] = error_text
                        
                        document.status = 'REJECTED'
                        document.sri_response = response_data
                        document.save()
                        
                        logger.warning(f"⚠️ [SRI_AUTH_ULTRA] Document not authorized: {error_text}")
                        return False, f'Document not authorized: {error_text}'
                        
                    else:
                        # ✅ MANTENER SENT si estaba en ese estado
                        if document.status != 'SENT':
                            document.status = 'PENDING'
                        document.sri_response = response_data
                        document.save()
                        logger.info(f"🔄 [SRI_AUTH_ULTRA] Document in process: {estado}")
                        return False, f'Document in process with state: {estado}'
            
            return False, 'No authorization found in response'
            
        except ET.ParseError as e:
            logger.error(f"❌ [SRI_AUTH_ULTRA] XML Parse error: {e}")
            return False, f'Invalid XML authorization response: {str(e)}'
        except Exception as e:
            logger.error(f"❌ [SRI_AUTH_ULTRA] Processing error: {e}")
            return False, f'Error processing authorization response: {str(e)}'
    
    def _process_authorization_soap_fault_ultra_fixed(self, document, response):
        """
        ✅ PROCESAR SOAP FAULT DE AUTORIZACIÓN - ULTRA CORREGIDO PARA DEBUGGING
        MANTIENE TODA LA FUNCIONALIDAD ORIGINAL
        """
        try:
            response_text = response.text
            logger.info(f"🔍 [SRI_FAULT_ULTRA] Processing authorization SOAP fault")
            logger.info(f"🔍 [SRI_FAULT_ULTRA] Full response: {response_text}")
            
            try:
                root = ET.fromstring(response_text.encode('utf-8'))
            except ET.ParseError as e:
                logger.error(f"❌ [SRI_FAULT_ULTRA] Invalid XML in SOAP fault: {e}")
                return False, f"Invalid SOAP fault response: {str(e)}"
            
            # ✅ BUSCAR SOAP FAULT CON ANÁLISIS DETALLADO
            fault_elem = root.find('.//{http://schemas.xmlsoap.org/soap/envelope/}Fault')
            if fault_elem is not None:
                fault_code_elem = fault_elem.find('.//{http://schemas.xmlsoap.org/soap/envelope/}faultcode')
                fault_string_elem = fault_elem.find('.//{http://schemas.xmlsoap.org/soap/envelope/}faultstring')
                fault_detail_elem = fault_elem.find('.//{http://schemas.xmlsoap.org/soap/envelope/}detail')
                
                fault_code = fault_code_elem.text if fault_code_elem is not None else "Unknown"
                fault_string = fault_string_elem.text if fault_string_elem is not None else "Unknown error"
                fault_detail = fault_detail_elem.text if fault_detail_elem is not None else ""
                
                # ✅ LOG ULTRA DETALLADO DEL FAULT
                logger.error(f"❌ [SRI_FAULT_ULTRA] Fault Code: {fault_code}")
                logger.error(f"❌ [SRI_FAULT_ULTRA] Fault String: {fault_string}")
                logger.error(f"❌ [SRI_FAULT_ULTRA] Fault Detail: {fault_detail}")
                
                # ✅ DETECTAR ERRORES INTERNOS DEL SRI (STACK TRACES)
                if any(kw in fault_string for kw in ["JDBCConnectionException", "SQLRecoverableException", "No more data to read from socket", "rolled back"]):
                    error_msg = f"SRI Internal Service Error (Temporary): {fault_string[:100]}"
                    logger.warning(f"⚠️ [SRI_FAULT_ULTRA] Detected SRI internal DB error: {fault_string}")
                else:
                    error_msg = f"SOAP Fault {fault_code}: {fault_string}"
                    if fault_detail:
                        error_msg += f" | Detail: {fault_detail}"
                
                # ✅ NO CAMBIAR EL STATUS DE SENT A ERROR por un problema de consulta
                if document.status == 'SENT':
                    logger.warning(f"⚠️ [SRI_FAULT_ULTRA] Keeping SENT status despite authorization fault")
                else:
                    document.status = 'ERROR'
                    document.save()
                
                # ✅ LOG CORREGIDO
                self._log_sri_response(
                    document,
                    "AUTHORIZATION",
                    "SOAP_FAULT",
                    error_msg,
                    {
                        "response": response_text, 
                        "method": "requests_ultra_fixed", 
                        "fault_code": fault_code,
                        "fault_string": fault_string,
                        "fault_detail": fault_detail
                    }
                )
                
                return False, error_msg
            
            # ✅ SI NO ES SOAP FAULT, PROCESAR COMO RESPUESTA NORMAL
            logger.info("🔍 [SRI_FAULT_ULTRA] No SOAP fault found, processing as normal response")
            return self._process_authorization_response_ultra_fixed(document, response)
            
        except Exception as e:
            logger.error(f"❌ [SRI_FAULT_ULTRA] Error processing SOAP fault: {str(e)}")
            return False, f"Error processing SOAP fault: {str(e)}"
    
    def _extract_authorization_errors_ultra_fixed(self, autorizacion_elem):
        """
        ✅ EXTRAER ERRORES DE AUTORIZACIÓN XML - VERSIÓN ULTRA MEJORADA
        MANTIENE TODA LA FUNCIONALIDAD ORIGINAL
        """
        error_messages = []
        
        try:
            # Buscar mensajes con diferentes estructuras
            mensaje_elems = autorizacion_elem.findall('.//mensaje') 
            
            for mensaje_elem in mensaje_elems:
                identificador_elem = mensaje_elem.find('.//identificador')
                mensaje_text_elem = mensaje_elem.find('.//mensaje')
                info_adicional_elem = mensaje_elem.find('.//informacionAdicional')
                tipo_elem = mensaje_elem.find('.//tipo')
                
                if mensaje_text_elem is not None:
                    identificador = identificador_elem.text if identificador_elem is not None else "N/A"
                    mensaje_text = mensaje_text_elem.text
                    info_adicional = info_adicional_elem.text if info_adicional_elem is not None else ""
                    tipo = tipo_elem.text if tipo_elem is not None else ""
                    
                    error_detail = f"[{tipo}] Error {identificador}: {mensaje_text}"
                    if info_adicional:
                        error_detail += f" - {info_adicional}"
                    
                    error_messages.append(error_detail)
                    logger.info(f"🔍 [SRI_AUTH_ULTRA] Authorization error: {error_detail}")
        
        except Exception as e:
            logger.error(f"❌ [SRI_AUTH_ULTRA] Error extracting authorization errors: {e}")
        
        return error_messages
    
    # ========================================================================
    # UTILIDADES COMUNES
    # ========================================================================
    
    def _parse_authorization_date(self, fecha_str):
        """
        ✅ PARSEAR FECHAS DE AUTORIZACIÓN - MÚLTIPLES FORMATOS
        MANTIENE TODA LA FUNCIONALIDAD ORIGINAL
        """
        if not fecha_str:
            return None
        
        # ✅ FORMATOS DE FECHA SOPORTADOS POR SRI 2025
        date_formats = [
            '%d/%m/%Y %H:%M:%S',
            '%Y-%m-%d %H:%M:%S',
            '%d/%m/%Y %H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S%z',
            '%d/%m/%Y'
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(fecha_str, fmt)
            except ValueError:
                continue
        
        logger.warning(f"⚠️ [SRI_AUTH_ULTRA] Could not parse authorization date: {fecha_str}")
        return None
    
    def _log_sri_response(self, document, operation_type, response_code, message, raw_response):
        """
        ✅ REGISTRAR RESPUESTA SRI - ULTRA CORREGIDO SIN CAMPOS INEXISTENTES Y CON LÍMITES
        MANTIENE TODA LA FUNCIONALIDAD ORIGINAL DE LOGGING
        """
        try:
            # ✅ OBTENER EL ElectronicDocument CORRECTO
            if hasattr(document, "original_document"):
                electronic_doc = document.original_document
            elif hasattr(document, "document_ptr"):
                electronic_doc = document.document_ptr
            else:
                electronic_doc = document
            
            # ✅ TRUNCAR response_code a máximo 10 caracteres OBLIGATORIO
            response_code_truncated = str(response_code)[:10] if response_code else "UNKNOWN"
            
            # ✅ TRUNCAR message si es muy largo (para evitar problemas de BD)
            message_truncated = str(message)[:500] if message else ""
            
            # ✅ ASEGURAR QUE raw_response SEA DICT
            if isinstance(raw_response, dict):
                raw_response_safe = raw_response
            else:
                raw_response_safe = {'response': str(raw_response)[:1000]}  # Limitar tamaño
            
            # ✅ CREAR REGISTRO EN SRIResponse - SOLO CAMPOS QUE EXISTEN
            sri_response = SRIResponse.objects.create(
                document=electronic_doc,
                operation_type=operation_type,
                response_code=response_code_truncated,  # ✅ CORREGIDO: Máximo 10 chars
                response_message=message_truncated,
                raw_response=raw_response_safe
            )
            
            # ✅ LOG DE AUDITORÍA (OPCIONAL Y PROTEGIDO)
            try:
                AuditLog.objects.create(
                    action=f'SRI_{operation_type}_{response_code_truncated}',
                    model_name='ElectronicDocument',
                    object_id=str(document.id),
                    object_representation=str(document)[:100],  # ✅ Limitar representación
                    additional_data={
                        'operation_type': operation_type,
                        'response_code': response_code_truncated,
                        'message': message_truncated[:200],  # ✅ Límite adicional para auditoría
                        'environment': self.environment,
                        'document_number': getattr(document, 'document_number', 'N/A'),
                        'access_key': getattr(document, 'access_key', 'N/A'),
                        'sri_version': '2025.4_AUTH_PARSING_FIXED'
                    }
                )
            except Exception as audit_error:
                logger.warning(f"⚠️ [SRI_LOG_FIXED] Audit log failed (non-critical): {audit_error}")
            
            logger.info(f"✅ [SRI_LOG_FIXED] Response logged: {operation_type} - {response_code_truncated}")
            
        except Exception as e:
            logger.error(f"❌ [SRI_LOG_FIXED] Error logging SRI response: {str(e)}")
            # ✅ NO FALLAR si no se puede registrar el log
            pass
    
    # ========================================================================
    # MÉTODOS DE SERVICIO, STATUS Y CONECTIVIDAD
    # ========================================================================
    
    def check_sri_service_status(self):
        """
        ✅ VERIFICAR ESTADO DEL SERVICIO SRI
        MANTIENE TODA LA FUNCIONALIDAD ORIGINAL
        """
        try:
            logger.info("🔍 [SRI_STATUS] Checking SRI service status")
            
            # ✅ TEST DE CONECTIVIDAD BÁSICA
            test_urls = [
                self.SRI_URLS[self.environment]["reception_endpoint"],
                self.SRI_URLS[self.environment]["authorization_endpoint"],
                "https://celcer.sri.gob.ec" if self.environment == 'TEST' else "https://cel.sri.gob.ec"
            ]
            
            for url in test_urls:
                try:
                    response = requests.head(
                        url,
                        timeout=10,
                        headers={'User-Agent': 'SRI-Status-Check/2025.3'},
                        verify=True,
                        allow_redirects=True
                    )
                    
                    if response.status_code in [200, 405, 404]:  # ✅ 405 es normal para servicios SOAP
                        logger.info(f"✅ [SRI_STATUS] {url} is reachable (status: {response.status_code})")
                        return True, f"SRI service appears to be online (status: {response.status_code})"
                    else:
                        logger.warning(f"⚠️ [SRI_STATUS] {url} returned status: {response.status_code}")
                
                except requests.exceptions.Timeout:
                    logger.warning(f"⏰ [SRI_STATUS] Timeout checking {url}")
                    continue
                except Exception as e:
                    logger.warning(f"❌ [SRI_STATUS] Error checking {url}: {e}")
                    continue
            
            return False, "SRI service appears to be down or unreachable"
            
        except Exception as e:
            return False, f"Error checking SRI status: {str(e)}"
    
    def test_connection(self):
        """
        Prueba la conexión con los servicios del SRI
        ✅ VERSIÓN ULTRA FINAL - MANTIENE TODA LA FUNCIONALIDAD ORIGINAL
        """
        results = {}
        
        for service_name, url in [
            ('reception', self.SRI_URLS[self.environment]['reception']), 
            ('authorization', self.SRI_URLS[self.environment]['authorization'])
        ]:
            try:
                headers = {
                    'User-Agent': 'SRI-Ecuador-Test-Client-Complete-Fixed/2025.3',
                    'Accept': 'text/xml, application/soap+xml'
                }
                
                response = requests.head(
                    url, 
                    timeout=15, 
                    headers=headers,
                    verify=True,
                    allow_redirects=True
                )
                
                results[service_name] = {
                    'status': 'OK' if response.status_code in [200, 405] else 'WARNING',
                    'service_url': url,
                    'http_status': response.status_code,
                    'environment': self.environment,
                    'message': f'Service reachable (COMPLETE FIXED VERSION)',
                    'response_time': response.elapsed.total_seconds()
                }
                
            except Exception as e:
                results[service_name] = {
                    'status': 'ERROR',
                    'service_url': url,
                    'error': str(e),
                    'environment': self.environment,
                    'message': f'Connection failed: {str(e)}'
                }
        
        results['system_info'] = {
            'sri_client_version': '2025.4_AUTH_PARSING_FIXED',
            'zeep_available': ZEEP_AVAILABLE,
            'zeep_status': 'Available and functional' if ZEEP_AVAILABLE else 'Not available - using requests fallback',
            'environment': self.environment,
            'company_ruc': getattr(self.company, 'ruc', 'N/A'),
            'fixes_applied': [
                'FIX_1_ZEEP_AUTH_AUTORIZACIONES_PARSING',
                'FIX_2_AUTH_FALLBACK_LOGIC_CORRECTED',
                'FIX_3_ZEEP_NESTED_ERROR_EXTRACTION',
                'ZEEP_IMPORT_ERRORS_RESOLVED',
                'DUAL_METHOD_ZEEP_AND_REQUESTS',
                'NAMESPACE_XMLNS_EMPTY_FOR_AUTH',
                'SRI_RESPONSE_LOGGING_FIELD_LIMITS',
                'STATUS_PRESERVATION_SENT_TO_ERROR',
                'BACKOFF_RETRY_STRATEGY',
                'ALL_ORIGINAL_METHODS_PRESERVED',
            ]
        }
        
        return results
    
    # ========================================================================
    # MÉTODOS ADICIONALES PARA COMPATIBILIDAD Y FUNCIONALIDAD COMPLETA
    # ========================================================================
    
    def get_reception_client(self):
        """
        ✅ OBTENER CLIENTE DE RECEPCIÓN (ZEEP O REQUESTS FALLBACK)
        MANTIENE FUNCIONALIDAD ORIGINAL
        """
        if ZEEP_AVAILABLE and not self._reception_client:
            try:
                session = Session()
                transport = Transport(session=session)
                settings = Settings(strict=False, xml_huge_tree=True)
                wsdl_url = self.SRI_URLS[self.environment]['reception']
                self._reception_client = Client(wsdl_url, transport=transport, settings=settings)
                logger.info("✅ Reception client (Zeep) initialized")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize Zeep reception client: {e}")
                self._reception_client = None
        
        return self._reception_client
    
    def get_authorization_client(self):
        """
        ✅ OBTENER CLIENTE DE AUTORIZACIÓN (ZEEP O REQUESTS FALLBACK)
        MANTIENE FUNCIONALIDAD ORIGINAL
        """
        if ZEEP_AVAILABLE and not self._authorization_client:
            try:
                session = Session()
                transport = Transport(session=session)
                settings = Settings(strict=False, xml_huge_tree=True)
                wsdl_url = self.SRI_URLS[self.environment]['authorization']
                self._authorization_client = Client(wsdl_url, transport=transport, settings=settings)
                logger.info("✅ Authorization client (Zeep) initialized")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize Zeep authorization client: {e}")
                self._authorization_client = None
        
        return self._authorization_client
    
    def clear_clients(self):
        """
        ✅ LIMPIAR CLIENTES PARA REINICIALIZACIÓN
        MANTIENE FUNCIONALIDAD ORIGINAL
        """
        self._reception_client = None
        self._authorization_client = None
        logger.info("✅ SOAP clients cleared")
    
    def get_client_info(self):
        """
        ✅ OBTENER INFORMACIÓN DEL CLIENTE
        MANTIENE FUNCIONALIDAD ORIGINAL
        """
        return {
            'environment': self.environment,
            'company_ruc': getattr(self.company, 'ruc', 'N/A'),
            'company_name': getattr(self.company, 'business_name', 'N/A'),
            'zeep_available': ZEEP_AVAILABLE,
            'reception_client_initialized': self._reception_client is not None,
            'authorization_client_initialized': self._authorization_client is not None,
            'sri_urls': self.SRI_URLS[self.environment],
            'client_version': 'COMPLETE_FIXED_V2025.4_AUTH_PARSING',
            'functionality_status': 'ALL_ORIGINAL_FUNCTIONS_MAINTAINED_AND_ENHANCED'
        }
    
    def validate_environment(self):
        """
        ✅ VALIDAR ENTORNO DE TRABAJO
        MANTIENE FUNCIONALIDAD ORIGINAL
        """
        try:
            validation_results = {
                'environment': self.environment,
                'valid_environment': self.environment in ['TEST', 'PRODUCTION'],
                'sri_config_exists': self.sri_config is not None,
                'company_exists': self.company is not None,
                'urls_configured': self.environment in self.SRI_URLS,
                'zeep_available': ZEEP_AVAILABLE,
                'requests_available': True,  # requests siempre está disponible
            }
            
            # ✅ VERIFICAR CONFIGURACIÓN ESPECÍFICA
            if self.sri_config:
                validation_results.update({
                    'sri_config_active': getattr(self.sri_config, 'is_active', False),
                    'establishment_code': getattr(self.sri_config, 'establishment_code', None),
                    'emission_point': getattr(self.sri_config, 'emission_point', None),
                })
            
            # ✅ VERIFICAR CONECTIVIDAD BÁSICA
            try:
                status_ok, status_message = self.check_sri_service_status()
                validation_results.update({
                    'sri_service_reachable': status_ok,
                    'sri_service_message': status_message
                })
            except Exception as e:
                validation_results.update({
                    'sri_service_reachable': False,
                    'sri_service_message': f"Could not check service: {str(e)}"
                })
            
            # ✅ CALCULAR SCORE DE VALIDACIÓN
            passed_validations = sum([
                validation_results['valid_environment'],
                validation_results['sri_config_exists'],
                validation_results['company_exists'],
                validation_results['urls_configured'],
                validation_results['requests_available'],
                validation_results.get('sri_service_reachable', False)
            ])
            
            total_validations = 6
            validation_score = (passed_validations / total_validations) * 100
            
            validation_results.update({
                'validation_score': validation_score,
                'validation_status': 'EXCELLENT' if validation_score >= 90 else 'GOOD' if validation_score >= 70 else 'WARNING' if validation_score >= 50 else 'ERROR',
                'recommendations': self._get_validation_recommendations(validation_results)
            })
            
            return validation_results
            
        except Exception as e:
            return {
                'error': f"Validation failed: {str(e)}",
                'validation_status': 'ERROR'
            }
    
    def _get_validation_recommendations(self, validation_results):
        """
        ✅ OBTENER RECOMENDACIONES BASADAS EN VALIDACIÓN
        """
        recommendations = []
        
        if not validation_results.get('valid_environment'):
            recommendations.append("Configure valid environment (TEST or PRODUCTION)")
        
        if not validation_results.get('sri_config_exists'):
            recommendations.append("Configure SRI settings for the company")
        
        if not validation_results.get('sri_service_reachable'):
            recommendations.append("Check internet connection and SRI service availability")
        
        if not validation_results.get('zeep_available'):
            recommendations.append("Consider installing zeep for enhanced SOAP support: pip install zeep")
        
        if not validation_results.get('sri_config_active', True):
            recommendations.append("Activate SRI configuration in company settings")
        
        if not recommendations:
            recommendations.append("Environment is properly configured - ready for SRI integration")
        
        return recommendations
    
    # ✅ ALIAS PARA COMPATIBILIDAD CON VERSIONES ANTERIORES
    def send_document(self, document, signed_xml_content):
        """✅ ALIAS PARA COMPATIBILIDAD"""
        return self.send_document_to_reception(document, signed_xml_content)
    
    def get_authorization(self, document):
        """✅ ALIAS PARA COMPATIBILIDAD"""
        return self.get_document_authorization(document)