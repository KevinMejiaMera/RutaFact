# -*- coding: utf-8 -*-
"""
Generador de XML para documentos del SRI - VERSIÓN CORREGIDA 2025
ACTUALIZADO: Noviembre 2025 - Ficha Técnica v2.32
PARA: Facturas comerciales NORMALES (sin rubros de terceros)
IMPORTANTE: Versiones 2.0.0 y 2.1.0 son SOLO para casos especiales
CUMPLE: Resoluciones vigentes del SRI Ecuador
"""

import logging
import os
import re
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
from django.utils import timezone
from django.conf import settings
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from apps.sri_integration.models import ElectronicDocument

logger = logging.getLogger(__name__)


class XMLGeneratorSRI2025:
    """
    Generador de XML para documentos electrónicos del SRI
    VERSIÓN: Noviembre 2025 - Ficha Técnica v2.32
    PARA: Facturas comerciales NORMALES
    
    IMPORTANTE: Este generador usa las versiones CORRECTAS para empresas comerciales:
    - Factura: 1.1.0 (NO 2.1.0)
    - Nota de Crédito: 1.1.0 (NO 2.1.0)
    - Liquidación: 1.1.0 (NO 2.1.0)
    
    Las versiones 2.0.0 y 2.1.0 son EXCLUSIVAMENTE para:
    - Facturas con rubros de terceros (Anexo 8)
    - Facturas sustitutivas de guía de remisión (Anexo 9)
    - Casos especiales con reembolsos y compensaciones
    """
    
    # ✅ VERSIONES CORRECTAS PARA FACTURAS COMERCIALES NORMALES
    XML_VERSIONS = {
        'factura': '1.1.0',           # ✅ Para facturas comerciales normales
        'notaCredito': '1.1.0',       # ✅ Para notas de crédito normales
        'notaDebito': '1.0.0',        # ✅ Se mantiene
        'comprobanteRetencion': '2.0.0',  # ✅ Se mantiene
        'liquidacionCompra': '1.1.0', # ✅ Para liquidaciones normales
    }
    
    def __init__(self, document):
        self.document = document
        self.company = document.company
        
        # Validar existencia de configuración SRI
        try:
            self.sri_config = self.company.sri_configuration
        except Exception:
            logger.error(f"❌ La empresa {self.company.id} no tiene una configuración SRI válida.")
            raise ValueError(f"ERROR CRÍTICO: La empresa '{self.company.business_name}' no tiene configurado el SRI (Establecimiento, Punto de Emisión, etc.).")
        
        # Crear directorio base para XMLs si no existe
        self.xml_base_dir = os.path.join(settings.BASE_DIR, 'storage', 'invoices', 'xml')
        os.makedirs(self.xml_base_dir, exist_ok=True)
        
        # Validaciones iniciales críticas
        self._validate_initial_configuration()
    
    def _validate_initial_configuration(self):
        """Validaciones críticas antes de generar cualquier XML"""
        if not self.company.business_name or not self.company.business_name.strip():
            raise ValueError("ERROR CRÍTICO: business_name de la compañía está vacío")
        
        if not self.company.ruc or not self.company.ruc.strip():
            raise ValueError("ERROR CRÍTICO: RUC de la compañía está vacío")
        
        if not self.sri_config.establishment_code or not self.sri_config.establishment_code.strip():
            raise ValueError("ERROR CRÍTICO: establishment_code está vacío")
        
        if not self.sri_config.emission_point or not self.sri_config.emission_point.strip():
            raise ValueError("ERROR CRÍTICO: emission_point está vacío")
        
        if not self.document.access_key or not self.document.access_key.strip():
            raise ValueError("ERROR CRÍTICO: access_key del documento está vacía")
        
        # Validar ambiente PRODUCCIÓN vs PRUEBAS
        if self.sri_config.environment == 'PRODUCTION':
            logger.warning("ATENCIÓN: Generando XML para AMBIENTE DE PRODUCCIÓN")
        else:
            logger.info("Generando XML para AMBIENTE DE PRUEBAS")
    
    # ========== MÉTODOS PRINCIPALES ==========
    
    def generate_xml(self):
        """Método principal que determina qué tipo de XML generar"""
        from apps.sri_integration.models import CreditNote, DebitNote, Retention, PurchaseSettlement
        
        try:
            if isinstance(self.document, CreditNote):
                return self.generate_credit_note_xml()
            elif isinstance(self.document, DebitNote):
                return self.generate_debit_note_xml()
            elif isinstance(self.document, Retention):
                return self.generate_retention_xml()
            elif isinstance(self.document, PurchaseSettlement):
                return self.generate_purchase_settlement_xml()
            else:
                return self.generate_invoice_xml()
        except Exception as e:
            logger.error(f"Error en generate_xml: {str(e)}")
            raise
    
    def generate_invoice_xml(self):
        """Genera XML para factura comercial normal v1.1.0 con auto-corrección de totales e IVA"""
        try:
            logger.info(f"Generando XML Factura v{self.XML_VERSIONS['factura']} para ID {self.document.id}")
            
            # 1. Recolectar ítems primero (relación o POS)
            items_to_process = []
            if hasattr(self.document, 'items') and self.document.items.exists():
                items_to_process = list(self.document.items.all())
            elif isinstance(self.document.additional_data, dict) and 'pos_items' in self.document.additional_data:
                from types import SimpleNamespace
                for item_dict in self.document.additional_data['pos_items']:
                    from apps.invoicing.models import ProductTemplate
                    prod_name = item_dict.get('name', 'Producto')
                    tax_rate = 15.0
                    try:
                        pos_tax = item_dict.get('tax_rate')
                        if pos_tax is not None:
                            try:
                                tax_rate = float(pos_tax)
                            except:
                                p = ProductTemplate.objects.get(id=item_dict['id'])
                                tax_rate = float(p.tax_rate)
                                prod_name = p.name
                        else:
                            p = ProductTemplate.objects.get(id=item_dict['id'])
                            prod_name = p.name
                            tax_rate = float(p.tax_rate)
                    except:
                        pass

                    fake_item = SimpleNamespace(
                        main_code=str(item_dict.get('id', 'PROD001')),
                        description=prod_name,
                        quantity=Decimal(str(item_dict.get('quantity', 1))),
                        unit_price=Decimal(str(item_dict.get('price', 0))),
                        discount=Decimal(str(item_dict.get('discount', 0))),
                        tax_rate=tax_rate,
                        additional_details={}
                    )
                    items_to_process.append(fake_item)
            
            # 2. AUTO-CORRECCIÓN Y RECALCULO DE TOTALES (Diferencias fix)
            # SRI requiere que el encabezado coincida exactamente con la suma de detalles.
            # También migramos IVA 12% -> 15% si la fecha es de 2024-04-01 en adelante.
            current_subtotal = Decimal('0')
            current_tax = Decimal('0')
            current_discount = Decimal('0')
            
            # Verificar si debemos forzar 15% (Ecuador Ley Abril 2024)
            force_15 = False
            if self.document.issue_date:
                threshold_date = datetime.strptime('2024-04-01', '%Y-%m-%d').date()
                if self.document.issue_date >= threshold_date:
                    force_15 = True

            for item in items_to_process:
                # Migración de IVA si aplica
                if force_15 and getattr(item, 'tax_rate', 0) == 12.0:
                    logger.info(f"Auto-migrando item {getattr(item, 'main_code', '')} de 12% a 15% IVA")
                    item.tax_rate = 15.0
                
                # Recalcular subtotal de la línea
                qty = Decimal(str(getattr(item, 'quantity', 0)))
                price = Decimal(str(getattr(item, 'unit_price', 0)))
                disc = Decimal(str(getattr(item, 'discount', 0)))
                
                line_subtotal = (qty * price) - disc
                item.subtotal = line_subtotal # Asegurar que el objeto tiene el subtotal correcto
                
                current_subtotal += line_subtotal
                current_discount += disc
                
                # Calcular impuesto de la línea
                rate = Decimal(str(getattr(item, 'tax_rate', 15.0)))
                if rate > 0:
                    current_tax += (line_subtotal * (rate / 100))

            # Actualizar el documento en memoria para que info_factura use los valores correctos
            self.document.subtotal_without_tax = current_subtotal.quantize(Decimal('0.01'))
            self.document.total_tax = current_tax.quantize(Decimal('0.01'))
            self.document.total_discount = current_discount.quantize(Decimal('0.01'))
            self.document.total_amount = (self.document.subtotal_without_tax + self.document.total_tax).quantize(Decimal('0.01'))
            
            logger.info(f"Totales recalculados: Subtotal={self.document.subtotal_without_tax}, Tax={self.document.total_tax}, Total={self.document.total_amount}")

            # Construir resumen de impuestos correcto a partir de los items ya migrados
            # Esto evita que _get_taxes_summary() use registros DB con codigoPorcentaje viejo (ej: 12%->2)
            self._recalculated_taxes_summary = {}
            for item in items_to_process:
                rate = float(getattr(item, 'tax_rate', 15))
                pcode = self._get_iva_percentage_code(rate)
                key = ('2', pcode)
                subtotal = float(getattr(item, 'subtotal', 0))
                if key not in self._recalculated_taxes_summary:
                    self._recalculated_taxes_summary[key] = {
                        'base': Decimal('0'),
                        'valor': Decimal('0'),
                        'codigo': '2',
                        'codigoPorcentaje': pcode,
                        'tarifa': Decimal(str(rate)),
                        'descuentoAdicional': Decimal('0')
                    }
                self._recalculated_taxes_summary[key]['base'] += Decimal(str(subtotal))
                self._recalculated_taxes_summary[key]['valor'] += Decimal(str(round(subtotal * rate / 100, 2)))
            logger.info(f"Resumen de impuestos recalculado: {list(self._recalculated_taxes_summary.keys())}")

            # 3. Construir XML con los datos corregidos
            factura = Element('factura', {
                'id': 'comprobante',
                'version': self.XML_VERSIONS['factura']
            })
            
            info_tributaria = self._create_info_tributaria('01')
            factura.append(info_tributaria)
            
            info_factura = self._create_info_factura()
            factura.append(info_factura)
            
            detalles = SubElement(factura, 'detalles')
            if items_to_process:
                for item in items_to_process:
                    detalle = self._create_detalle_factura(item)
                    detalles.append(detalle)
            else:
                detalle = self._create_detalle_generico()
                detalles.append(detalle)
            
            # Información adicional
            info_adicional = self._create_info_adicional()
            if self._has_valid_content(info_adicional):
                factura.append(info_adicional)
            
            # Convertir a string con codificación correcta
            xml_str = self._prettify_xml(factura)
            
            # Validaciones finales
            self._validate_xml_structure(xml_str)
            
            logger.info(f"XML Factura v{self.XML_VERSIONS['factura']} generado exitosamente: {len(xml_str)} caracteres")
            return xml_str
            
        except Exception as e:
            logger.error(f"Error generando XML Factura: {str(e)}")
            raise ValueError(f"Error generando XML Factura: {str(e)}")
    
    def generate_credit_note_xml(self):
        """Genera XML para nota de crédito comercial normal v1.1.0"""
        try:
            logger.info(f"Generando XML NotaCredito v{self.XML_VERSIONS['notaCredito']} para ID {self.document.id}")
            
            nota_credito = Element('notaCredito', {
                'id': 'comprobante',
                'version': self.XML_VERSIONS['notaCredito']
            })
            
            # Información tributaria
            info_tributaria = self._create_info_tributaria('04')  # 04 = Nota de Crédito
            nota_credito.append(info_tributaria)
            
            # Información de la nota de crédito
            info_nota_credito = self._create_info_nota_credito()
            nota_credito.append(info_nota_credito)
            
            # Detalles
            detalles = SubElement(nota_credito, 'detalles')
            
            # Intentar obtener items de la relación 'items' (DocumentItem)
            items = []
            if hasattr(self.document, 'items') and self.document.items.exists():
                items = self.document.items.all()
            
            if items:
                for item in items:
                    detalle = self._create_detalle_nota_credito(item)
                    detalles.append(detalle)
            else:
                # Fallback a detalle genérico
                logger.info(f"Nota de Crédito {self.document.id} sin ítems detallados. Generando detalle genérico.")
                detalle = self._create_detalle_generico_nota_credito()
                detalles.append(detalle)
            
            # Información adicional
            info_adicional = self._create_info_adicional()
            if self._has_valid_content(info_adicional):
                nota_credito.append(info_adicional)
            
            xml_str = self._prettify_xml(nota_credito)
            self._validate_xml_structure(xml_str)
            
            logger.info(f"XML NotaCredito v{self.XML_VERSIONS['notaCredito']} generado exitosamente: {len(xml_str)} caracteres")
            return xml_str
            
        except Exception as e:
            logger.error(f"Error generando XML NotaCredito: {str(e)}")
            raise ValueError(f"Error generando XML NotaCredito: {str(e)}")
    
    def generate_debit_note_xml(self):
        """Genera XML para nota de débito v1.0.0"""
        try:
            logger.info(f"Generando XML NotaDebito v{self.XML_VERSIONS['notaDebito']} para ID {self.document.id}")
            
            nota_debito = Element('notaDebito', {
                'id': 'comprobante',
                'version': self.XML_VERSIONS['notaDebito']
            })
            
            # Información tributaria
            info_tributaria = self._create_info_tributaria('05')  # 05 = Nota de Débito
            nota_debito.append(info_tributaria)
            
            # Información de la nota de débito
            info_nota_debito = self._create_info_nota_debito()
            nota_debito.append(info_nota_debito)
            
            # Motivos
            motivos = SubElement(nota_debito, 'motivos')
            if hasattr(self.document, 'motives') and self.document.motives.exists():
                for motive in self.document.motives.all():
                    motivo = self._create_motivo_nota_debito(motive)
                    motivos.append(motivo)
            elif hasattr(self.document, 'items') and self.document.items.exists():
                for item in self.document.items.all():
                    motivo = self._create_motivo_item(item)
                    motivos.append(motivo)
            else:
                motivo = self._create_motivo_generico()
                motivos.append(motivo)
            
            # Información adicional
            info_adicional = self._create_info_adicional()
            if self._has_valid_content(info_adicional):
                nota_debito.append(info_adicional)
            
            xml_str = self._prettify_xml(nota_debito)
            self._validate_xml_structure(xml_str)
            
            logger.info(f"XML NotaDebito v{self.XML_VERSIONS['notaDebito']} generado exitosamente: {len(xml_str)} caracteres")
            return xml_str
            
        except Exception as e:
            logger.error(f"Error generando XML NotaDebito: {str(e)}")
            raise ValueError(f"Error generando XML NotaDebito: {str(e)}")
    
    def generate_retention_xml(self):
        """Genera XML para comprobante de retención v2.0.0"""
        try:
            logger.info(f"Generando XML Retención v{self.XML_VERSIONS['comprobanteRetencion']} para ID {self.document.id}")
            
            comp_retencion = Element('comprobanteRetencion', {
                'id': 'comprobante',
                'version': self.XML_VERSIONS['comprobanteRetencion']
            })
            
            # Información tributaria
            info_tributaria = self._create_info_tributaria('07')  # 07 = Retención
            comp_retencion.append(info_tributaria)
            
            # Información de retención
            info_comp_retencion = self._create_info_comp_retencion()
            comp_retencion.append(info_comp_retencion)
            
            # Impuestos (detalles de retención)
            impuestos = SubElement(comp_retencion, 'impuestos')
            if hasattr(self.document, 'details') and self.document.details.exists():
                for detail in self.document.details.all():
                    impuesto = self._create_impuesto_retencion(detail)
                    impuestos.append(impuesto)
            else:
                impuesto = self._create_impuesto_retencion_generico()
                impuestos.append(impuesto)
            
            # Información adicional
            info_adicional = self._create_info_adicional()
            if self._has_valid_content(info_adicional):
                comp_retencion.append(info_adicional)
            
            xml_str = self._prettify_xml(comp_retencion)
            self._validate_xml_structure(xml_str)
            
            logger.info(f"XML Retención v{self.XML_VERSIONS['comprobanteRetencion']} generado exitosamente: {len(xml_str)} caracteres")
            return xml_str
            
        except Exception as e:
            logger.error(f"Error generando XML Retención: {str(e)}")
            raise ValueError(f"Error generando XML Retención: {str(e)}")
    
    def generate_purchase_settlement_xml(self):
        """Genera XML para liquidación de compra comercial normal v1.1.0"""
        try:
            logger.info(f"Generando XML LiquidacionCompra v{self.XML_VERSIONS['liquidacionCompra']} para ID {self.document.id}")
            
            liquidacion_compra = Element('liquidacionCompra', {
                'id': 'comprobante',
                'version': self.XML_VERSIONS['liquidacionCompra']
            })
            
            # Información tributaria
            info_tributaria = self._create_info_tributaria('03')  # 03 = Liquidación de compra
            liquidacion_compra.append(info_tributaria)
            
            # Información de liquidación
            info_liquidacion_compra = self._create_info_liquidacion_compra()
            liquidacion_compra.append(info_liquidacion_compra)
            
            # Detalles
            detalles = SubElement(liquidacion_compra, 'detalles')
            if hasattr(self.document, 'items') and self.document.items.exists():
                for item in self.document.items.all():
                    detalle = self._create_detalle_liquidacion(item)
                    detalles.append(detalle)
            else:
                detalle = self._create_detalle_generico()
                detalles.append(detalle)
            
            # Información adicional
            info_adicional = self._create_info_adicional()
            if self._has_valid_content(info_adicional):
                liquidacion_compra.append(info_adicional)
            
            xml_str = self._prettify_xml(liquidacion_compra)
            self._validate_xml_structure(xml_str)
            
            logger.info(f"XML LiquidacionCompra v{self.XML_VERSIONS['liquidacionCompra']} generado exitosamente: {len(xml_str)} caracteres")
            return xml_str
            
        except Exception as e:
            logger.error(f"Error generando XML LiquidacionCompra: {str(e)}")
            raise ValueError(f"Error generando XML LiquidacionCompra: {str(e)}")
    
    # ========== VALIDACIONES ==========
    
    def _validate_xml_structure(self, xml_str):
        """Validaciones XML según Ficha Técnica v2.32 (noviembre 2025)"""
        try:
            # 1. Validar campos vacíos críticos
            problematic_patterns = [
                '<campoAdicional nombre="">',
                '<campoAdicional nombre="" />',
                '<razonSocial></razonSocial>',
                '<identificacionComprador></identificacionComprador>',
                '<ruc></ruc>',
                '<claveAcceso></claveAcceso>'
            ]
            
            for pattern in problematic_patterns:
                if pattern in xml_str:
                    raise ValueError(f"ERROR: Elemento vacío detectado: {pattern}")
            
            # 2. Validar elementos esenciales obligatorios
            essential_elements = [
                '<ambiente>', '<ruc>', '<claveAcceso>', 
                '<totalSinImpuestos>',
                '<tipoEmision>', '<codDoc>'
            ]
            
            # El tag de total varía según el tipo de documento. Identificamos el tipo por el tag raíz.
            root_tag_match = re.search(r'<(\w+)', xml_str)
            root_tag = root_tag_match.group(1) if root_tag_match else ''
            
            logger.info(f"Validando estructura para documento con tag raíz: {root_tag}")
            
            if root_tag in ['factura', 'liquidacionCompra']:
                essential_elements.append('<importeTotal>')
            elif root_tag == 'notaCredito':
                essential_elements.append('<valorModificacion>')
            elif root_tag == 'notaDebito':
                essential_elements.append('<valorTotal>')
            elif root_tag == 'comprobanteRetencion':
                # Las retenciones no tienen un tag de total global en el infoCompRetencion (están en los detalles)
                pass
            
            for element in essential_elements:
                if element not in xml_str:
                    raise ValueError(f"ERROR: Elemento esencial faltante: {element}")
            
            # 3. Validar formato de decimales (solo advertencia, no error)
            decimal_patterns = [
                r'<cantidad>(\d+\.\d{3,})</cantidad>',
                r'<precioUnitario>(\d+\.\d{3,})</precioUnitario>',
                r'<valor>(\d+\.\d{3,})</valor>'
            ]
            
            for pattern in decimal_patterns:
                matches = re.findall(pattern, xml_str)
                if matches:
                    logger.warning(f"ADVERTENCIA: Valores decimales con más de 2 decimales: {matches}")
            
            # 4. Validar longitud de campos según Ficha Técnica
            field_limits = {
                'razonSocial': 300,
                'descripcion': 300,
                'codigoPrincipal': 25,
                'codigoAuxiliar': 25
            }
            
            for field, limit in field_limits.items():
                pattern = f'<{field}>(.+?)</{field}>'
                matches = re.findall(pattern, xml_str)
                for match in matches:
                    if len(match) > limit:
                        raise ValueError(f"ERROR: Campo {field} excede límite de {limit} caracteres")
            
            # 5. Verificar que la versión sea correcta (1.1.0 para facturas normales)
            version_checks = {
                'factura': '1.1.0',
                'notaCredito': '1.1.0',
                'liquidacionCompra': '1.1.0'
            }
            
            for doc_type, expected_version in version_checks.items():
                if doc_type in xml_str.lower():
                    if f'version="{expected_version}"' not in xml_str:
                        logger.warning(f"ADVERTENCIA: Versión XML no es {expected_version} para {doc_type}")
            
            logger.info("Validación XML completada exitosamente")
            
        except Exception as e:
            logger.error(f"Error en validación XML: {str(e)}")
            raise
    
    def _has_valid_content(self, element):
        """Verificación de contenido válido"""
        if element is None:
            return False
        
        # Contar elementos hijos con contenido válido
        valid_children = 0
        for child in element:
            # Verificar texto y atributos
            has_text = child.text and child.text.strip()
            has_valid_attributes = any(
                attr_name and str(attr_value).strip() 
                for attr_name, attr_value in child.attrib.items()
            )
            
            if has_text or has_valid_attributes:
                valid_children += 1
        
        return valid_children > 0
    
    # ========== INFORMACIÓN TRIBUTARIA ==========
    
    def _create_info_tributaria(self, cod_doc):
        """Información tributaria según Ficha Técnica v2.32"""
        info_tributaria = Element('infoTributaria')
        
        # 1. ambiente - CRÍTICO: Validar configuración
        ambiente = SubElement(info_tributaria, 'ambiente')
        if self.sri_config.environment == 'PRODUCTION':
            ambiente_val = '2'  # PRODUCCIÓN
            logger.info("CONFIGURADO PARA AMBIENTE DE PRODUCCIÓN")
        else:
            ambiente_val = '1'  # PRUEBAS
            logger.info("CONFIGURADO PARA AMBIENTE DE PRUEBAS")
        ambiente.text = ambiente_val
        
        # 2. tipoEmision (siempre 1 para emisión normal)
        tipo_emision = SubElement(info_tributaria, 'tipoEmision')
        tipo_emision.text = '1'
        
        # 3. razonSocial - Validación estricta longitud
        razon_social = SubElement(info_tributaria, 'razonSocial')
        business_name = str(self.company.business_name).replace('\n', ' ').replace('\r', ' ').strip()[:300]
        razon_social.text = business_name
        
        # 4. nombreComercial - Opcional pero validado
        if (hasattr(self.company, 'trade_name') and 
            self.company.trade_name and 
            self.company.trade_name.strip()):
            nombre_comercial = SubElement(info_tributaria, 'nombreComercial')
            nombre_comercial.text = str(self.company.trade_name).replace('\n', ' ').replace('\r', ' ').strip()[:300]
        
        # 5. ruc - Validación de formato
        ruc = SubElement(info_tributaria, 'ruc')
        ruc_value = self.company.ruc.strip()
        # Validar formato RUC ecuatoriano (13 dígitos)
        if not ruc_value.isdigit() or len(ruc_value) != 13:
            logger.warning(f"ADVERTENCIA: RUC {ruc_value} podría tener formato incorrecto")
        ruc.text = ruc_value
        
        # 6. claveAcceso - Validación 49 dígitos
        clave_acceso = SubElement(info_tributaria, 'claveAcceso')
        access_key = self.document.access_key.strip()
        if len(access_key) != 49 or not access_key.isdigit():
            raise ValueError(f"ERROR: claveAcceso debe tener exactamente 49 dígitos: {access_key}")
        clave_acceso.text = access_key
        
        # 7. codDoc - Validación códigos
        cod_documento = SubElement(info_tributaria, 'codDoc')
        valid_codes = ['01', '03', '04', '05', '06', '07']
        if cod_doc not in valid_codes:
            logger.warning(f"ADVERTENCIA: Código documento {cod_doc} podría no ser válido")
        cod_documento.text = cod_doc
        
        # 8. estab - Validación 3 dígitos
        establecimiento = SubElement(info_tributaria, 'estab')
        estab_code = self.sri_config.establishment_code.strip().zfill(3)
        establecimiento.text = estab_code
        
        # 9. ptoEmi - Validación 3 dígitos
        punto_emision = SubElement(info_tributaria, 'ptoEmi')
        point_code = self.sri_config.emission_point.strip().zfill(3)
        punto_emision.text = point_code
        
        # 10. secuencial - Validación 9 dígitos
        secuencial = SubElement(info_tributaria, 'secuencial')
        seq_number = self.document.document_number.split('-')[-1].zfill(9)
        secuencial.text = seq_number
        
        # 11. dirMatriz - Validación longitud
        dir_matriz = SubElement(info_tributaria, 'dirMatriz')
        address = (str(self.company.address).replace('\n', ' ').replace('\r', ' ').strip()[:300] if self.company.address 
                  else 'Dirección no especificada')
        dir_matriz.text = address
        
        return info_tributaria
    
    # ========== INFORMACIÓN DE FACTURA ==========
    
    def _create_info_factura(self):
        """Información de factura con campos actualizados 2025"""
        info_factura = Element('infoFactura')
        
        # 1. fechaEmision
        fecha_emision = SubElement(info_factura, 'fechaEmision')
        fecha_emision.text = self.document.issue_date.strftime('%d/%m/%Y')
        
        # 2. dirEstablecimiento
        dir_establecimiento = SubElement(info_factura, 'dirEstablecimiento')
        dir_establecimiento.text = (str(self.company.address).replace('\n', ' ').replace('\r', ' ').strip()[:300] if self.company.address 
                                   else 'Dirección no especificada')
        
        # 3. contribuyenteEspecial - Campo opcional
        if (hasattr(self.sri_config, 'special_taxpayer') and 
            self.sri_config.special_taxpayer and 
            hasattr(self.sri_config, 'special_taxpayer_number') and 
            self.sri_config.special_taxpayer_number and 
            str(self.sri_config.special_taxpayer_number).strip()):
            
            contribuyente_especial = SubElement(info_factura, 'contribuyenteEspecial')
            contribuyente_especial.text = str(self.sri_config.special_taxpayer_number).strip()
        
        # 4. obligadoContabilidad
        obligado_contabilidad = SubElement(info_factura, 'obligadoContabilidad')
        obligado_contabilidad.text = 'SI' if self.sri_config.accounting_required else 'NO'
        
        # 5-7. Información del comprador - Validaciones estrictas
        tipo_identificacion_comprador = SubElement(info_factura, 'tipoIdentificacionComprador')
        customer_id_type = getattr(self.document, 'customer_identification_type', '05')
        if not customer_id_type or not str(customer_id_type).strip():
            raise ValueError("ERROR: customer_identification_type es obligatorio")
        tipo_identificacion_comprador.text = str(customer_id_type)
        
        razon_social_comprador = SubElement(info_factura, 'razonSocialComprador')
        customer_name = getattr(self.document, 'customer_name', '')
        if not customer_name or not str(customer_name).strip():
            raise ValueError("ERROR: customer_name es obligatorio")
        razon_social_comprador.text = str(customer_name).replace('\n', ' ').replace('\r', ' ').strip()[:300]
        
        identificacion_comprador = SubElement(info_factura, 'identificacionComprador')
        customer_id = getattr(self.document, 'customer_identification', '')
        if not customer_id or not str(customer_id).strip():
            raise ValueError("ERROR: customer_identification es obligatorio")
        identificacion_comprador.text = str(customer_id).strip()
        
        # 8. direccionComprador - Opcional pero validado
        if (hasattr(self.document, 'customer_address') and 
            self.document.customer_address and 
            str(self.document.customer_address).strip()):
            direccion_comprador = SubElement(info_factura, 'direccionComprador')
            direccion_comprador.text = str(self.document.customer_address).replace('\n', ' ').replace('\r', ' ').strip()[:300]
        
        # 9. totalSinImpuestos - Formato decimal estricto
        total_sin_impuestos = SubElement(info_factura, 'totalSinImpuestos')
        subtotal_value = self._format_decimal(self.document.subtotal_without_tax)
        total_sin_impuestos.text = subtotal_value
        
        # 10. totalDescuento
        total_descuento = SubElement(info_factura, 'totalDescuento')
        discount_value = self._format_decimal(getattr(self.document, 'total_discount', 0))
        total_descuento.text = discount_value
        
        # 11. totalConImpuestos - Estructura con impuestos
        total_con_impuestos = SubElement(info_factura, 'totalConImpuestos')
        taxes_summary = self._get_taxes_summary()
        
        for tax_data in taxes_summary.values():
            total_impuesto = SubElement(total_con_impuestos, 'totalImpuesto')
            
            SubElement(total_impuesto, 'codigo').text = str(tax_data['codigo'])
            SubElement(total_impuesto, 'codigoPorcentaje').text = str(tax_data['codigoPorcentaje'])
            
            # descuentoAdicional si existe
            if tax_data.get('descuentoAdicional', 0) > 0:
                descuento_adicional = SubElement(total_impuesto, 'descuentoAdicional')
                descuento_adicional.text = self._format_decimal(tax_data['descuentoAdicional'])
            
            SubElement(total_impuesto, 'baseImponible').text = self._format_decimal(tax_data['base'])
            SubElement(total_impuesto, 'valor').text = self._format_decimal(tax_data['valor'])
        
        # 12. propina
        propina = SubElement(info_factura, 'propina')
        propina.text = "0.00"
        
        # 13. importeTotal
        importe_total = SubElement(info_factura, 'importeTotal')
        total_value = self._format_decimal(self.document.total_amount)
        importe_total.text = total_value
        
        # 14. moneda
        moneda = SubElement(info_factura, 'moneda')
        moneda.text = getattr(self.document, 'currency', 'DOLAR')
        
        # 15. pagos - CAMPO OBLIGATORIO (SIEMPRE debe existir)
        pagos = SubElement(info_factura, 'pagos')  # ← CREAR SIEMPRE

        if hasattr(self.document, 'payment_methods') and self.document.payment_methods.exists():
            # Si hay payment_methods configurados, usarlos
            for payment in self.document.payment_methods.all():
                pago = SubElement(pagos, 'pago')
                SubElement(pago, 'formaPago').text = str(getattr(payment, 'payment_method_code', '01'))
                SubElement(pago, 'total').text = self._format_decimal(getattr(payment, 'amount', 0))
                
                # plazo - campo para pagos a crédito
                if hasattr(payment, 'payment_term') and payment.payment_term:
                    SubElement(pago, 'plazo').text = str(payment.payment_term)
                
                # unidadTiempo - campo complementario
                if hasattr(payment, 'time_unit') and payment.time_unit:
                    SubElement(pago, 'unidadTiempo').text = str(payment.time_unit)
        else:
            # ← AGREGAR ESTE ELSE: Si NO hay payment_methods, crear pago por defecto
            pago = SubElement(pagos, 'pago')
            SubElement(pago, 'formaPago').text = '01'  # Sin utilización sistema financiero
            SubElement(pago, 'total').text = self._format_decimal(self.document.total_amount)
            
            logger.warning(
                f"⚠️  Factura {self.document.id} sin payment_methods. "
                f"Generando pago por defecto (forma 01, total: {self.document.total_amount})"
            )

        return info_factura
    
    # ========== DETALLES DE FACTURA ==========
    
    def _create_detalle_factura(self, item):
        """Detalle de factura con validaciones"""
        detalle = Element('detalle')
        
        # codigoPrincipal - Límite 25 caracteres
        codigo_principal = SubElement(detalle, 'codigoPrincipal')
        main_code = str(getattr(item, 'main_code', 'PROD001'))[:25]
        codigo_principal.text = main_code
        
        # codigoAuxiliar - Opcional, límite 25 caracteres
        if (hasattr(item, 'auxiliary_code') and 
            item.auxiliary_code and 
            str(item.auxiliary_code).strip()):
            codigo_auxiliar = SubElement(detalle, 'codigoAuxiliar')
            codigo_auxiliar.text = str(item.auxiliary_code).strip()[:25]
        
        # descripcion - Límite 300 caracteres
        descripcion = SubElement(detalle, 'descripcion')
        desc_text = str(getattr(item, 'description', 'Producto')).replace('\n', ' ').replace('\r', ' ').strip()[:300]
        descripcion.text = desc_text
        
        # cantidad - Formato decimal (máximo 6 decimales)
        cantidad = SubElement(detalle, 'cantidad')
        qty_value = self._format_decimal(getattr(item, 'quantity', 1), max_decimals=6)
        cantidad.text = qty_value
        
        # precioUnitario - Formato decimal estricto
        precio_unitario = SubElement(detalle, 'precioUnitario')
        price_value = self._format_decimal(getattr(item, 'unit_price', 0))
        precio_unitario.text = price_value
        
        # descuento
        descuento = SubElement(detalle, 'descuento')
        discount_value = self._format_decimal(getattr(item, 'discount', 0))
        descuento.text = discount_value
        
        # precioTotalSinImpuesto
        precio_total_sin_impuesto = SubElement(detalle, 'precioTotalSinImpuesto')
        subtotal_value = self._format_decimal(getattr(item, 'subtotal', 0))
        precio_total_sin_impuesto.text = subtotal_value
        
        # detallesAdicionales - Campo opcional
        if (hasattr(item, 'additional_details') and 
            item.additional_details and 
            isinstance(item.additional_details, dict)):
            detalles_adicionales = SubElement(detalle, 'detallesAdicionales')
            for key, value in item.additional_details.items():
                if key and str(key).strip() and value and str(value).strip():
                    detalle_adicional = SubElement(detalles_adicionales, 'detAdicional', {
                        'nombre': str(key).strip()[:50],
                        'valor': str(value).strip()[:300]
                    })
        
        # impuestos - Estructura de impuestos
        impuestos = SubElement(detalle, 'impuestos')
        if hasattr(item, 'taxes') and item.taxes.exists():
            for tax in item.taxes.all():
                impuesto = self._create_tax_detail(tax, item)
                impuestos.append(impuesto)
        else:
            # Impuesto por defecto
            impuesto = self._create_default_tax(item)
            impuestos.append(impuesto)
        
        return detalle
    
    def _create_tax_detail(self, tax, item):
        """Crea detalle de impuesto corrigiendo posibles códigos erróneos de la base de datos"""
        impuesto = Element('impuesto')
        
        # Obtener tarifa y forzar 15% si es necesario (migración)
        rate = float(getattr(tax, 'rate', getattr(item, 'tax_rate', 15)))
        if hasattr(self.document, 'issue_date') and self.document.issue_date:
            threshold_date = datetime.strptime('2024-04-01', '%Y-%m-%d').date()
            if self.document.issue_date >= threshold_date and rate == 12.0:
                rate = 15.0
                
        # Forzar el código de porcentaje correcto basado en la tarifa
        p_code = self._get_iva_percentage_code(rate)
        
        SubElement(impuesto, 'codigo').text = str(getattr(tax, 'tax_code', '2'))
        SubElement(impuesto, 'codigoPorcentaje').text = p_code
        SubElement(impuesto, 'tarifa').text = self._format_decimal(rate)
        SubElement(impuesto, 'baseImponible').text = self._format_decimal(
            getattr(tax, 'taxable_base', getattr(item, 'subtotal', 0))
        )
        SubElement(impuesto, 'valor').text = self._format_decimal(getattr(tax, 'tax_amount', 0))
        
        return impuesto
    
    def _create_default_tax(self, item):
        """Crea impuesto por defecto basado en la tarifa del item"""
        impuesto = Element('impuesto')
        
        rate = float(getattr(item, 'tax_rate', 15))
        # Si la factura es después de Abril 2024 y el rate es 12, forzar 15%
        if hasattr(self.document, 'issue_date') and self.document.issue_date:
            threshold_date = datetime.strptime('2024-04-01', '%Y-%m-%d').date()
            if self.document.issue_date >= threshold_date and rate == 12.0:
                rate = 15.0

        percentage_code = self._get_iva_percentage_code(rate)
        
        SubElement(impuesto, 'codigo').text = '2'  # IVA
        SubElement(impuesto, 'codigoPorcentaje').text = percentage_code
        SubElement(impuesto, 'tarifa').text = self._format_decimal(rate)
        
        subtotal = float(getattr(item, 'subtotal', 0))
        SubElement(impuesto, 'baseImponible').text = self._format_decimal(subtotal)
        SubElement(impuesto, 'valor').text = self._format_decimal(subtotal * (rate / 100))
        
        return impuesto
    
    def _create_detalle_generico(self):
        """Detalle genérico cuando no hay items"""
        detalle = Element('detalle')
        
        SubElement(detalle, 'codigoPrincipal').text = 'PROD001'
        SubElement(detalle, 'descripcion').text = 'Producto'
        SubElement(detalle, 'cantidad').text = '1.00'
        
        subtotal = float(self.document.subtotal_without_tax)
        SubElement(detalle, 'precioUnitario').text = self._format_decimal(subtotal)
        SubElement(detalle, 'descuento').text = '0.00'
        SubElement(detalle, 'precioTotalSinImpuesto').text = self._format_decimal(subtotal)
        
        # Impuestos por defecto basados en el total del documento
        impuestos = SubElement(detalle, 'impuestos')
        impuesto = Element('impuesto')
        
        # Intentar obtener la tarifa del primer item si existe
        rate = 15.00
        if hasattr(self.document, 'items') and self.document.items.exists():
            first_item = self.document.items.first()
            rate = float(getattr(first_item, 'tax_rate', 15))
        
        percentage_code = self._get_iva_percentage_code(rate)
        
        SubElement(impuesto, 'codigo').text = '2'
        SubElement(impuesto, 'codigoPorcentaje').text = percentage_code
        SubElement(impuesto, 'tarifa').text = self._format_decimal(rate)
        SubElement(impuesto, 'baseImponible').text = self._format_decimal(subtotal)
        SubElement(impuesto, 'valor').text = self._format_decimal(float(self.document.total_tax))
        impuestos.append(impuesto)
        
        return detalle
    
    # ========== MÉTODOS DE UTILIDAD ==========
    
    def _get_iva_percentage_code(self, percentage):
        """Mapea el porcentaje de IVA al código requerido por el SRI (Tabla 17)"""
        try:
            p = float(percentage)
            if p == 0: return '0'
            if p == 12: return '2'
            if p == 14: return '3'
            if p == 15: return '4'
            if p == 5: return '5'
            if p == 8: return '8'
            if p == 13: return '10'
            # Fallback inteligente: si no coincide exactamente, buscamos el más cercano o usamos 4
            logger.warning(f"Porcentaje de IVA {p}% no estándar. Usando código 4 (15%) por defecto.")
            return '4'
        except:
            return '4'

    def _format_decimal(self, value, max_decimals=2):
        """Formatea decimales según especificaciones SRI"""
        try:
            if value is None:
                return "0.00"
            
            # Convertir a float primero para normalizar
            float_val = float(value)
            
            # Formatear según decimales máximos
            if max_decimals == 2:
                return f"{float_val:.2f}"
            elif max_decimals == 6:
                # Para cantidades, permitir hasta 6 pero quitar ceros innecesarios
                formatted = f"{float_val:.6f}"
                # Quitar ceros al final pero mantener al menos 2 decimales
                formatted = formatted.rstrip('0')
                if formatted.endswith('.'):
                    formatted += '00'
                elif len(formatted.split('.')[1]) < 2:
                    formatted += '0'
                return formatted
            else:
                return f"{float_val:.2f}"
            
        except (TypeError, ValueError, OverflowError) as e:
            logger.warning(f"Error formateando decimal {value}: {e}")
            return "0.00" if max_decimals == 2 else "0.00"
    
    def _get_taxes_summary(self):
        """Resumen de impuestos"""
        if hasattr(self, '_recalculated_taxes_summary') and self._recalculated_taxes_summary:
            logger.info("Using recalculated taxes summary for XML generation")
            return self._recalculated_taxes_summary

        taxes_summary = {}
        
        if hasattr(self.document, 'taxes') and self.document.taxes.exists():
            for tax in self.document.taxes.all():
                key = (str(tax.tax_code), str(tax.percentage_code))
                if key not in taxes_summary:
                    taxes_summary[key] = {
                        'base': Decimal('0'),
                        'valor': Decimal('0'),
                        'codigo': str(tax.tax_code),
                        'codigoPorcentaje': str(tax.percentage_code),
                        'tarifa': Decimal(str(tax.rate)),
                        'descuentoAdicional': Decimal('0')
                    }
                
                taxes_summary[key]['base'] += Decimal(str(tax.taxable_base))
                taxes_summary[key]['valor'] += Decimal(str(tax.tax_amount))
                
                # Agregar descuento adicional si existe
                if hasattr(tax, 'additional_discount') and tax.additional_discount:
                    taxes_summary[key]['descuentoAdicional'] += Decimal(str(tax.additional_discount))
        else:
            # Impuesto por defecto basado en los totales calculados del documento
            rate = 15.00
            # Si el total_tax es 0 y el subtotal_without_tax > 0, es probable que sea IVA 0%
            if float(self.document.total_tax) == 0 and float(self.document.subtotal_without_tax) > 0:
                rate = 0.00
            elif float(self.document.subtotal_without_tax) > 0:
                # Calcular tarifa implícita
                rate = (float(self.document.total_tax) / float(self.document.subtotal_without_tax)) * 100
                # Redondear a las tarifas estándar si está muy cerca
                standard_rates = [15.0, 12.0, 8.0, 5.0, 0.0]
                for sr in standard_rates:
                    if abs(rate - sr) < 0.1:
                        rate = sr
                        break
            
            percentage_code = self._get_iva_percentage_code(rate)
            
            taxes_summary[('2', percentage_code)] = {
                'base': Decimal(str(self.document.subtotal_without_tax)),
                'valor': Decimal(str(self.document.total_tax)),
                'codigo': '2',
                'codigoPorcentaje': percentage_code,
                'tarifa': Decimal(str(rate)),
                'descuentoAdicional': Decimal('0')
            }
        
        return taxes_summary
    
    def _create_info_adicional(self):
        """Información adicional con validaciones estrictas"""
        info_adicional = Element('infoAdicional')
        added_fields = 0
        
        # Información adicional del documento
        if (hasattr(self.document, 'additional_data') and 
            self.document.additional_data and 
            isinstance(self.document.additional_data, dict)):
            
            for key, value in self.document.additional_data.items():
                if (key and str(key).strip() and 
                    value and str(value).strip() and 
                    len(str(key).strip()) > 0 and 
                    len(str(value).strip()) > 0):
                    
                    # Validar longitud según especificaciones
                    key_clean = str(key).strip()[:50]
                    value_clean = str(value).strip()[:300]
                    
                    campo = SubElement(info_adicional, 'campoAdicional', {
                        'nombre': key_clean
                    })
                    campo.text = value_clean
                    added_fields += 1
        
        # Email del cliente (validación mejorada)
        if (hasattr(self.document, 'customer_email') and 
            self.document.customer_email and 
            str(self.document.customer_email).strip() and
            '@' in str(self.document.customer_email) and
            '.' in str(self.document.customer_email)):
            
            email = SubElement(info_adicional, 'campoAdicional', {
                'nombre': 'EMAIL'
            })
            email.text = str(self.document.customer_email).strip()[:300]
            added_fields += 1
        
        # Teléfono del cliente (validación mejorada)
        if (hasattr(self.document, 'customer_phone') and 
            self.document.customer_phone and 
            str(self.document.customer_phone).strip()):
            
            phone_clean = ''.join(filter(str.isdigit, str(self.document.customer_phone)))
            if len(phone_clean) >= 7:  # Mínimo 7 dígitos para ser válido
                telefono = SubElement(info_adicional, 'campoAdicional', {
                    'nombre': 'TELEFONO'
                })
                telefono.text = str(self.document.customer_phone).strip()[:50]
                added_fields += 1
        
        # Observaciones
        if (hasattr(self.document, 'observations') and 
            self.document.observations and 
            str(self.document.observations).strip()):
            
            observaciones = SubElement(info_adicional, 'campoAdicional', {
                'nombre': 'OBSERVACIONES'
            })
            observaciones.text = str(self.document.observations).replace('\n', ' ').replace('\r', ' ').strip()[:300]
            added_fields += 1
        
        logger.info(f"Campos adicionales agregados: {added_fields}")
        return info_adicional
    
    def _prettify_xml(self, elem):
        """Generar XML compacto para asegurar integridad de firma"""
        try:
            # SRI prefiere XML compacto para procesos automatizados
            xml_bytes = tostring(elem, encoding='utf-8', xml_declaration=True)
            return xml_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"Error en generación XML compacto: {str(e)}")
            # Fallback seguro
            xml_str = tostring(elem, encoding='utf-8').decode('utf-8')
            return '<?xml version="1.0" encoding="UTF-8"?>' + xml_str
    
    # ========== MÉTODOS PARA OTROS TIPOS DE DOCUMENTO ==========
    
    def _create_info_nota_credito(self):
        """Información de nota de crédito v1.1.0 - ORDEN SEGÚN FICHA TÉCNICA v2.32"""
        info_nota_credito = Element('infoNotaCredito')
        
        # 1. fechaEmision
        SubElement(info_nota_credito, 'fechaEmision').text = self.document.issue_date.strftime('%d/%m/%Y')
        
        # 2. dirEstablecimiento
        SubElement(info_nota_credito, 'dirEstablecimiento').text = (
            self.company.address[:300] if self.company.address else 'Dirección no especificada'
        )
        
        # 3. tipoIdentificacionComprador
        SubElement(info_nota_credito, 'tipoIdentificacionComprador').text = str(
            getattr(self.document, 'customer_identification_type', '05')
        )
        
        # 4. razonSocialComprador
        SubElement(info_nota_credito, 'razonSocialComprador').text = str(
            getattr(self.document, 'customer_name', 'Cliente')
        )[:300]
        
        # 5. identificacionComprador
        SubElement(info_nota_credito, 'identificacionComprador').text = str(
            getattr(self.document, 'customer_identification', '9999999999999')
        )
        
        # 6. contribuyenteEspecial (opcional)
        if (hasattr(self.sri_config, 'special_taxpayer') and self.sri_config.special_taxpayer and 
            hasattr(self.sri_config, 'special_taxpayer_number') and self.sri_config.special_taxpayer_number):
            SubElement(info_nota_credito, 'contribuyenteEspecial').text = str(self.sri_config.special_taxpayer_number)
        
        # 7. obligadoContabilidad
        SubElement(info_nota_credito, 'obligadoContabilidad').text = 'SI' if self.sri_config.accounting_required else 'NO'
        
        # 8. codDocModificado
        if hasattr(self.document, 'original_document') and self.document.original_document:
            SubElement(info_nota_credito, 'codDocModificado').text = '01'  # Factura
            
            # 9. numDocModificado
            SubElement(info_nota_credito, 'numDocModificado').text = self.document.original_document.document_number
            
            # 10. fechaEmisionDocSustento
            SubElement(info_nota_credito, 'fechaEmisionDocSustento').text = (
                self.document.original_document.issue_date.strftime('%d/%m/%Y')
            )
        
        # 11. totalSinImpuestos
        SubElement(info_nota_credito, 'totalSinImpuestos').text = self._format_decimal(
            self.document.subtotal_without_tax
        )
        
        # 12. valorModificacion
        SubElement(info_nota_credito, 'valorModificacion').text = self._format_decimal(
            self.document.total_amount
        )
        
        # 13. moneda
        SubElement(info_nota_credito, 'moneda').text = "DOLAR"
        
        # 14. totalConImpuestos
        total_con_impuestos = SubElement(info_nota_credito, 'totalConImpuestos')
        
        # Obtener impuestos del documento (resumen) si existen
        if hasattr(self.document, 'taxes') and self.document.taxes.filter(item__isnull=True).exists():
            for tax in self.document.taxes.filter(item__isnull=True):
                total_impuesto = SubElement(total_con_impuestos, 'totalImpuesto')
                SubElement(total_impuesto, 'codigo').text = str(tax.tax_code)
                SubElement(total_impuesto, 'codigoPorcentaje').text = str(tax.percentage_code)
                SubElement(total_impuesto, 'baseImponible').text = self._format_decimal(tax.taxable_base)
                SubElement(total_impuesto, 'valor').text = self._format_decimal(tax.tax_amount)
        else:
            # Fallback a resumen calculado si no hay objetos DocumentTax
            taxes_summary = self._get_taxes_summary()
            for tax_data in taxes_summary.values():
                total_impuesto = SubElement(total_con_impuestos, 'totalImpuesto')
                SubElement(total_impuesto, 'codigo').text = str(tax_data['codigo'])
                SubElement(total_impuesto, 'codigoPorcentaje').text = str(tax_data['codigoPorcentaje'])
                SubElement(total_impuesto, 'baseImponible').text = self._format_decimal(tax_data['base'])
                SubElement(total_impuesto, 'valor').text = self._format_decimal(tax_data['valor'])
        
        # 15. motivo
        SubElement(info_nota_credito, 'motivo').text = str(
            getattr(self.document, 'reason_description', 'Nota de crédito')
        )[:300]
        
        return info_nota_credito
    
    def _create_detalle_nota_credito(self, item):
        """Detalle de nota de crédito v1.1.0 - TAGS SEGÚN FICHA TÉCNICA"""
        detalle = Element('detalle')
        
        SubElement(detalle, 'codigoInterno').text = str(getattr(item, 'main_code', 'NOTAC001'))[:25]
        
        if hasattr(item, 'auxiliary_code') and item.auxiliary_code:
            SubElement(detalle, 'codigoAdicional').text = str(item.auxiliary_code)[:25]
        
        SubElement(detalle, 'descripcion').text = str(getattr(item, 'description', 'Ítem de nota de crédito'))[:300]
        SubElement(detalle, 'cantidad').text = self._format_decimal(getattr(item, 'quantity', 1), max_decimals=6)
        SubElement(detalle, 'precioUnitario').text = self._format_decimal(getattr(item, 'unit_price', 0))
        SubElement(detalle, 'descuento').text = self._format_decimal(getattr(item, 'discount', 0))
        SubElement(detalle, 'precioTotalSinImpuesto').text = self._format_decimal(getattr(item, 'subtotal', 0))
        
        # Impuestos del detalle son OBLIGATORIOS en Nota de Crédito
        impuestos = SubElement(detalle, 'impuestos')
        if hasattr(item, 'taxes') and item.taxes.exists():
            for tax in item.taxes.all():
                impuesto = self._create_tax_detail(tax, item)
                impuestos.append(impuesto)
        else:
            # Impuesto por defecto (IVA 15%)
            impuesto = self._create_default_tax(item)
            impuestos.append(impuesto)

        return detalle
    
    def _create_detalle_generico_nota_credito(self):
        """Detalle genérico de nota de crédito v1.1.0 - TAGS SEGÚN FICHA TÉCNICA"""
        detalle = Element('detalle')
        
        SubElement(detalle, 'codigoInterno').text = 'NOTAC001'
        SubElement(detalle, 'descripcion').text = str(getattr(self.document, 'reason_description', 'Nota de crédito'))[:300]
        SubElement(detalle, 'cantidad').text = '1.00'
        SubElement(detalle, 'precioUnitario').text = self._format_decimal(self.document.subtotal_without_tax)
        SubElement(detalle, 'descuento').text = '0.00'
        SubElement(detalle, 'precioTotalSinImpuesto').text = self._format_decimal(self.document.subtotal_without_tax)
        
        # Impuestos son OBLIGATORIOS
        impuestos = SubElement(detalle, 'impuestos')
        impuesto = Element('impuesto')
        
        rate = 15.0
        if float(self.document.total_tax) == 0 and float(self.document.subtotal_without_tax) > 0:
            rate = 0.00
        elif float(self.document.subtotal_without_tax) > 0:
            rate = (float(self.document.total_tax) / float(self.document.subtotal_without_tax)) * 100
            standard_rates = [15.0, 12.0, 8.0, 5.0, 0.0]
            for sr in standard_rates:
                if abs(rate - sr) < 0.1:
                    rate = sr
                    break
                    
        p_code = self._get_iva_percentage_code(rate)
        
        SubElement(impuesto, 'codigo').text = '2'
        SubElement(impuesto, 'codigoPorcentaje').text = p_code
        SubElement(impuesto, 'tarifa').text = self._format_decimal(rate)
        SubElement(impuesto, 'baseImponible').text = self._format_decimal(self.document.subtotal_without_tax)
        SubElement(impuesto, 'valor').text = self._format_decimal(self.document.total_tax)
        impuestos.append(impuesto)

        return detalle
    
    def _create_info_nota_debito(self):
        """Información de nota de débito v1.0.0"""
        info_nota_debito = Element('infoNotaDebito')
        
        SubElement(info_nota_debito, 'fechaEmision').text = self.document.issue_date.strftime('%d/%m/%Y')
        SubElement(info_nota_debito, 'dirEstablecimiento').text = (
            self.company.address[:300] if self.company.address else 'Dirección no especificada'
        )
        
        if (hasattr(self.sri_config, 'special_taxpayer') and self.sri_config.special_taxpayer):
            SubElement(info_nota_debito, 'contribuyenteEspecial').text = str(self.sri_config.special_taxpayer_number)
        
        SubElement(info_nota_debito, 'obligadoContabilidad').text = 'SI' if self.sri_config.accounting_required else 'NO'
        
        SubElement(info_nota_debito, 'tipoIdentificacionComprador').text = str(
            getattr(self.document, 'customer_identification_type', '05')
        )
        SubElement(info_nota_debito, 'razonSocialComprador').text = str(
            getattr(self.document, 'customer_name', 'Cliente')
        )[:300]
        SubElement(info_nota_debito, 'identificacionComprador').text = str(
            getattr(self.document, 'customer_identification', '9999999999999')
        )
        
        if hasattr(self.document, 'original_document') and self.document.original_document:
            SubElement(info_nota_debito, 'codDocModificado').text = '01'
            SubElement(info_nota_debito, 'numDocModificado').text = self.document.original_document.document_number
            SubElement(info_nota_debito, 'fechaEmisionDocSustento').text = (
                self.document.original_document.issue_date.strftime('%d/%m/%Y')
            )
        
        SubElement(info_nota_debito, 'totalSinImpuestos').text = self._format_decimal(self.document.subtotal_without_tax)
        
        # Impuestos
        impuestos = SubElement(info_nota_debito, 'impuestos')
        taxes_summary = self._get_taxes_summary()
        for tax_data in taxes_summary.values():
            impuesto = SubElement(impuestos, 'impuesto')
            SubElement(impuesto, 'codigo').text = str(tax_data['codigo'])
            SubElement(impuesto, 'codigoPorcentaje').text = str(tax_data['codigoPorcentaje'])
            SubElement(impuesto, 'baseImponible').text = self._format_decimal(tax_data['base'])
            SubElement(impuesto, 'tarifa').text = self._format_decimal(tax_data['tarifa'])
            SubElement(impuesto, 'valor').text = self._format_decimal(tax_data['valor'])
        
        SubElement(info_nota_debito, 'valorTotal').text = self._format_decimal(self.document.total_amount)
        
        return info_nota_debito
    
    def _create_motivo_nota_debito(self, motive):
        """Motivo de nota de débito"""
        motivo = Element('motivo')
        SubElement(motivo, 'razon').text = str(getattr(motive, 'reason', 'Motivo'))[:300]
        SubElement(motivo, 'valor').text = self._format_decimal(getattr(motive, 'amount', 0))
        return motivo
    
    def _create_motivo_item(self, item):
        """Motivo desde item"""
        motivo = Element('motivo')
        SubElement(motivo, 'razon').text = str(getattr(item, 'description', 'Motivo'))[:300]
        SubElement(motivo, 'valor').text = self._format_decimal(getattr(item, 'subtotal', 0))
        return motivo
    
    def _create_motivo_generico(self):
        """Motivo genérico"""
        motivo = Element('motivo')
        SubElement(motivo, 'razon').text = 'Nota de débito'
        SubElement(motivo, 'valor').text = self._format_decimal(self.document.total_amount)
        return motivo
    
    def _create_info_comp_retencion(self):
        """Información de retención v2.0.0"""
        info_comp_retencion = Element('infoCompRetencion')
        
        SubElement(info_comp_retencion, 'fechaEmision').text = self.document.issue_date.strftime('%d/%m/%Y')
        SubElement(info_comp_retencion, 'dirEstablecimiento').text = (
            self.company.address[:300] if self.company.address else 'Dirección no especificada'
        )
        
        if (hasattr(self.sri_config, 'special_taxpayer') and self.sri_config.special_taxpayer):
            SubElement(info_comp_retencion, 'contribuyenteEspecial').text = str(self.sri_config.special_taxpayer_number)
        
        SubElement(info_comp_retencion, 'obligadoContabilidad').text = 'SI' if self.sri_config.accounting_required else 'NO'
        
        SubElement(info_comp_retencion, 'tipoIdentificacionSujetoRetenido').text = str(
            getattr(self.document, 'customer_identification_type', '05')
        )
        SubElement(info_comp_retencion, 'razonSocialSujetoRetenido').text = str(
            getattr(self.document, 'customer_name', 'Cliente')
        )[:300]
        SubElement(info_comp_retencion, 'identificacionSujetoRetenido').text = str(
            getattr(self.document, 'customer_identification', '9999999999999')
        )
        
        SubElement(info_comp_retencion, 'periodoFiscal').text = self.document.issue_date.strftime('%m/%Y')
        
        return info_comp_retencion
    
    def _create_impuesto_retencion(self, detail):
        """Impuesto de retención"""
        impuesto = Element('impuesto')
        
        SubElement(impuesto, 'codigo').text = str(getattr(detail, 'tax_code', '1'))
        SubElement(impuesto, 'codigoRetencion').text = str(getattr(detail, 'retention_code', '332'))
        SubElement(impuesto, 'baseImponible').text = self._format_decimal(getattr(detail, 'taxable_base', 0))
        SubElement(impuesto, 'porcentajeRetener').text = self._format_decimal(getattr(detail, 'rate', 0))
        SubElement(impuesto, 'valorRetenido').text = self._format_decimal(getattr(detail, 'retention_amount', 0))
        
        if hasattr(detail, 'modified_document') and detail.modified_document:
            SubElement(impuesto, 'codDocSustento').text = '01'
            SubElement(impuesto, 'numDocSustento').text = detail.modified_document.document_number
            SubElement(impuesto, 'fechaEmisionDocSustento').text = detail.modified_document.issue_date.strftime('%d/%m/%Y')
        
        return impuesto
    
    def _create_impuesto_retencion_generico(self):
        """Impuesto de retención genérico"""
        impuesto = Element('impuesto')
        
        SubElement(impuesto, 'codigo').text = '1'
        SubElement(impuesto, 'codigoRetencion').text = '332'
        SubElement(impuesto, 'baseImponible').text = self._format_decimal(self.document.subtotal_without_tax)
        SubElement(impuesto, 'porcentajeRetener').text = '2.00'
        SubElement(impuesto, 'valorRetenido').text = self._format_decimal(self.document.total_amount)
        
        return impuesto
    
    def _create_info_liquidacion_compra(self):
        """Información de liquidación de compra v1.1.0"""
        info_liquidacion = Element('infoLiquidacionCompra')
        
        SubElement(info_liquidacion, 'fechaEmision').text = self.document.issue_date.strftime('%d/%m/%Y')
        SubElement(info_liquidacion, 'dirEstablecimiento').text = (
            self.company.address[:300] if self.company.address else 'Dirección no especificada'
        )
        
        if (hasattr(self.sri_config, 'special_taxpayer') and self.sri_config.special_taxpayer):
            SubElement(info_liquidacion, 'contribuyenteEspecial').text = str(self.sri_config.special_taxpayer_number)
        
        SubElement(info_liquidacion, 'obligadoContabilidad').text = 'SI' if self.sri_config.accounting_required else 'NO'
        
        SubElement(info_liquidacion, 'tipoIdentificacionProveedor').text = str(
            getattr(self.document, 'customer_identification_type', '05')
        )
        SubElement(info_liquidacion, 'razonSocialProveedor').text = str(
            getattr(self.document, 'customer_name', 'Proveedor')
        )[:300]
        SubElement(info_liquidacion, 'identificacionProveedor').text = str(
            getattr(self.document, 'customer_identification', '9999999999999')
        )
        
        if hasattr(self.document, 'customer_address') and self.document.customer_address:
            SubElement(info_liquidacion, 'direccionProveedor').text = str(self.document.customer_address)[:300]
        
        SubElement(info_liquidacion, 'totalSinImpuestos').text = self._format_decimal(self.document.subtotal_without_tax)
        SubElement(info_liquidacion, 'totalDescuento').text = self._format_decimal(getattr(self.document, 'total_discount', 0))
        
        # Impuestos
        total_con_impuestos = SubElement(info_liquidacion, 'totalConImpuestos')
        taxes_summary = self._get_taxes_summary()
        for tax_data in taxes_summary.values():
            total_impuesto = SubElement(total_con_impuestos, 'totalImpuesto')
            SubElement(total_impuesto, 'codigo').text = str(tax_data['codigo'])
            SubElement(total_impuesto, 'codigoPorcentaje').text = str(tax_data['codigoPorcentaje'])
            SubElement(total_impuesto, 'baseImponible').text = self._format_decimal(tax_data['base'])
            SubElement(total_impuesto, 'tarifa').text = self._format_decimal(tax_data['tarifa'])
            SubElement(total_impuesto, 'valor').text = self._format_decimal(tax_data['valor'])
        
        SubElement(info_liquidacion, 'importeTotal').text = self._format_decimal(self.document.total_amount)
        SubElement(info_liquidacion, 'moneda').text = "DOLAR"
        
        # Pagos
        if hasattr(self.document, 'payment_methods') and self.document.payment_methods.exists():
            pagos = SubElement(info_liquidacion, 'pagos')
            for payment in self.document.payment_methods.all():
                pago = SubElement(pagos, 'pago')
                SubElement(pago, 'formaPago').text = str(getattr(payment, 'payment_method_code', '01'))
                SubElement(pago, 'total').text = self._format_decimal(getattr(payment, 'amount', 0))
        
        return info_liquidacion
    
    def _create_detalle_liquidacion(self, item):
        """Detalle de liquidación de compra"""
        return self._create_detalle_factura(item)
    
    # ========== MÉTODOS DE ARCHIVO ==========
    
    def get_xml_path(self):
        """Obtiene la ruta del archivo XML"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{self.document.access_key}_{timestamp}.xml"
        return os.path.join(self.xml_base_dir, filename)
    
    def save_xml_to_file(self, xml_content):
        """Guarda XML con validaciones"""
        try:
            xml_path = self.get_xml_path()
            
            # Escribir sin BOM usando modo binario
            with open(xml_path, 'wb') as f:
                f.write(xml_content.encode('utf-8'))
            
            # Validar que el archivo se escribió correctamente
            with open(xml_path, 'rb') as f:
                saved_content = f.read()
                if saved_content.startswith(b'\xef\xbb\xbf'):
                    raise ValueError("ERROR: Archivo guardado con BOM")
            
            logger.info(f"XML guardado correctamente en: {xml_path}")
            return xml_path
            
        except Exception as e:
            logger.error(f"Error guardando XML: {str(e)}")
            raise


# ========== FIN DE LA CLASE ==========

# Mantener compatibilidad con código existente
XMLGenerator = XMLGeneratorSRI2025