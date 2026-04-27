# -*- coding: utf-8 -*-
"""
Generador de PDF (RIDE) para documentos del SRI
"""

import logging
import io
import os
import qrcode
import tempfile
from decimal import Decimal
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, KeepTogether
from reportlab.platypus.flowables import HRFlowable
from reportlab.graphics.barcode import code128, createBarcodeDrawing
from reportlab.graphics.shapes import Drawing
from django.conf import settings
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)


class PDFGenerator:
    """
    Generador de PDF (RIDE) para documentos electrónicos del SRI
    """
    
    def __init__(self, document=None):
        self.document = document
        self.company = None
        self.sri_config = None
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
        
        if document:
            self._setup_context(document)
            
    def _setup_context(self, document):
        """Inicializa el contexto del documento si se proporciona"""
        self.document = document
        self.company = document.company
        self.sri_config = self.company.sri_configuration
    
    def _setup_custom_styles(self):
        """
        Configura estilos personalizados para el PDF
        """
        # Estilo para título principal
        self.styles.add(ParagraphStyle(
            name='CompanyTitle',
            parent=self.styles['Title'],
            fontSize=16,
            textColor=colors.black,
            alignment=0,  # Izquierda
            spaceAfter=6
        ))
        
        # Estilo para subtítulos
        self.styles.add(ParagraphStyle(
            name='SectionTitle',
            parent=self.styles['Heading2'],
            fontSize=12,
            textColor=colors.black,
            alignment=0,  # Izquierda
            spaceBefore=12,
            spaceAfter=6
        ))
        
        # Estilo para datos de empresa (negrita pequeña)
        self.styles.add(ParagraphStyle(
            name='CompanyDataBold',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.black,
            alignment=0,
            fontName='Helvetica-Bold'
        ))

        # Estilo para datos de etiquetas (izq)
        self.styles.add(ParagraphStyle(
            name='LabelStyle',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.black,
            alignment=0,
            fontName='Helvetica-Bold'
        ))

        # Estilo para datos de valores (der)
        self.styles.add(ParagraphStyle(
            name='ValueStyle',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.black,
            alignment=0,
            fontName='Helvetica'
        ))

        # Estilo para encabezados de tabla
        self.styles.add(ParagraphStyle(
            name='TableHeader',
            parent=self.styles['Normal'],
            fontSize=7,
            textColor=colors.black,
            alignment=1,
            fontName='Helvetica-Bold'
        ))
        
        # Estilo para celdas de tabla
        self.styles.add(ParagraphStyle(
            name='TableCell',
            parent=self.styles['Normal'],
            fontSize=7,
            textColor=colors.black,
            alignment=0,
            fontName='Helvetica'
        ))

        # Estilo para totales (tabla derecha)
        self.styles.add(ParagraphStyle(
            name='TotalLabel',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.black,
            alignment=0,
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='TotalValue',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.black,
            alignment=2,
            fontName='Helvetica'
        ))
    
    def generate_invoice_pdf(self, document=None, auth_response=None):
        """
        Genera PDF para factura electrónica
        Retorna (success, pdf_path) para compatibilidad con el resto del sistema
        """
        if document:
            self._setup_context(document)
            
        if not self.document:
            return False, "No se proporcionó un documento para generar el PDF"
            
        try:
            # Crear buffer para el PDF
            buffer = io.BytesIO()
            
            # Crear documento
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                rightMargin=20*mm,
                leftMargin=20*mm,
                topMargin=20*mm,
                bottomMargin=20*mm
            )
            
            # Construir contenido
            story = []
            story.extend(self._build_header())
            story.extend(self._build_invoice_info())
            story.extend(self._build_customer_info())
            story.extend(self._build_invoice_details())
            story.extend(self._build_invoice_totals())
            story.extend(self._build_additional_info())
            story.extend(self._build_authorization_info())
            story.extend(self._build_footer())
            
            # Construir PDF
            doc.build(story)
            
            # Obtener contenido del buffer
            pdf_content = buffer.getvalue()
            buffer.close()
            
            # Guardar en archivo temporal para retornar la ruta (compatible con views.py y sri_processor.py)
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
            temp_file.write(pdf_content)
            temp_file.close()
            
            return True, temp_file.name
            
        except Exception as e:
            logger.error(f"Error generating invoice PDF: {str(e)}")
            return False, str(e)

    def generate_credit_note_pdf(self, document=None, auth_response=None):
        """
        Genera PDF para nota de crédito
        """
        if document:
            self._setup_context(document)
            
        if not self.document:
            return False, "No se proporcionó un documento"
            
        try:
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(
                buffer, pagesize=A4,
                rightMargin=20*mm, leftMargin=20*mm,
                topMargin=20*mm, bottomMargin=20*mm
            )
            story = []
            
            story.extend(self._build_header())
            story.extend(self._build_invoice_info()) 
            story.extend(self._build_modified_doc_info()) 
            story.extend(self._build_customer_info())
            story.extend(self._build_invoice_details()) 
            story.extend(self._build_invoice_totals())
            story.extend(self._build_additional_info())
            story.extend(self._build_authorization_info())
            story.extend(self._build_footer())
            
            doc.build(story)
            pdf_content = buffer.getvalue()
            buffer.close()
            
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
            temp_file.write(pdf_content)
            temp_file.close()
            
            return True, temp_file.name
        except Exception as e:
            logger.error(f"Error generating credit note PDF: {str(e)}")
            return False, str(e)

    def generate_debit_note_pdf(self, document=None, auth_response=None):
        """
        Genera PDF para nota de débito
        """
        if document:
            self._setup_context(document)
            
        if not self.document:
            return False, "No se proporcionó un documento"
            
        try:
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(
                buffer, pagesize=A4,
                rightMargin=20*mm, leftMargin=20*mm,
                topMargin=20*mm, bottomMargin=20*mm
            )
            story = []
            
            story.extend(self._build_header())
            story.extend(self._build_invoice_info())
            story.extend(self._build_modified_doc_info())
            story.extend(self._build_customer_info())
            story.extend(self._build_debit_note_reasons()) 
            story.extend(self._build_invoice_totals()) 
            story.extend(self._build_additional_info())
            story.extend(self._build_authorization_info())
            story.extend(self._build_footer())
            
            doc.build(story)
            pdf_content = buffer.getvalue()
            buffer.close()
            
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
            temp_file.write(pdf_content)
            temp_file.close()
            
            return True, temp_file.name
        except Exception as e:
            logger.error(f"Error generating debit note PDF: {str(e)}")
            return False, str(e)

    def _build_modified_doc_info(self):
        """
        Construye información del documento modificado (para NC/ND)
        """
        elements = []
        if hasattr(self.document, 'modified_document_number') and self.document.modified_document_number:
            elements.append(Paragraph("DOCUMENTO MODIFICADO", self.styles['SectionTitle']))
            
            data = [
                [f"Comprobante Modificado ({self.document.get_modified_document_type_display()}):", self.document.modified_document_number],
                ["Fecha Emisión (Sustento):", self.document.modified_document_date.strftime('%d/%m/%Y') if self.document.modified_document_date else ""],
                ["Razón de Modificación:", getattr(self.document, 'modification_reason', '')]
            ]
            
            table = Table(data, colWidths=[2.5*inch, 3*inch])
            table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 5*mm))
        return elements

    def _build_debit_note_reasons(self):
        """
        Construye tabla de motivos para Nota de Débito
        """
        elements = []
        elements.append(Paragraph("RAZONES DE LA MODIFICACIÓN", self.styles['SectionTitle']))
        
        headers = ["Razón", "Valor"]
        table_data = [headers]
        
        items = getattr(self.document, 'items', None) or getattr(self.document, 'motives', None)
        if items and items.exists():
            for item in items.all():
                desc = getattr(item, 'description', getattr(item, 'reason', ''))
                val = getattr(item, 'value', getattr(item, 'subtotal', 0))
                row = [desc, f"${val:.2f}"]
                table_data.append(row)
        
        table = Table(table_data, colWidths=[4*inch, 1.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 5*mm))
        return elements
    
    def _build_header(self):
        """
        Construye el encabezado del documento siguiendo el formato SRI (RIDE)
        """
        elements = []
        
        # --- COLUMNA IZQUIERDA: LOGO Y DATOS EMPRESA ---
        left_column = []
        
        # 1. Logo
        logo_added = False
        if self.company.logo:
            try:
                import io
                from reportlab.platypus import Image as RLImage
                
                try:
                    logo_file = self.company.logo.path
                except (NotImplementedError, AttributeError):
                    logo_content = self.company.logo.read()
                    logo_file = io.BytesIO(logo_content)
                
                logo_img = RLImage(logo_file)
                aspect = logo_img.imageHeight / float(logo_img.imageWidth)
                logo_width = 45 * mm
                logo_height = logo_width * aspect
                
                if logo_height > 35 * mm:
                    logo_height = 35 * mm
                    logo_width = logo_height / aspect
                
                logo_img.drawHeight = logo_height
                logo_img.drawWidth = logo_width
                left_column.append(logo_img)
                left_column.append(Spacer(1, 2*mm))
                logo_added = True
            except Exception as e:
                logger.error(f"Error loading company logo for PDF: {str(e)}")

        if not logo_added:
             left_column.append(Spacer(1, 20*mm)) # Espacio si no hay logo

        # 2. Box de datos de la empresa (Matriz, Sucursal, Obligado)
        company_box_data = [
            [Paragraph(self.company.business_name.upper(), self.styles['CompanyTitle'])],
            [Paragraph(f"<b>Dirección Matriz:</b> {self.company.address.upper()}", self.styles['ValueStyle'])],
        ]
        
        # Si hay dirección sucursal (usamos la misma si no hay campo específico, o podemos buscar en settings)
        company_box_data.append([Paragraph(f"<b>Dirección Sucursal:</b> {self.company.address.upper()}", self.styles['ValueStyle'])])
        
        if self.sri_config.special_taxpayer:
             company_box_data.append([Paragraph(f"<b>Contribuyente Especial Nro:</b> {self.sri_config.special_taxpayer_number}", self.styles['ValueStyle'])])
        
        company_box_data.append([Paragraph(f"<b>OBLIGADO A LLEVAR CONTABILIDAD:</b> {'SÍ' if self.sri_config.accounting_required else 'NO'}", self.styles['ValueStyle'])])
        
        # Régimen si aplica
        if hasattr(self.sri_config, 'regimen') and self.sri_config.regimen != 'GENERAL':
            regimen_text = self.sri_config.get_regimen_display().upper()
            company_box_data.append([Paragraph(f"<b>CONTRIBUYENTE RÉGIMEN {regimen_text}</b>", self.styles['ValueStyle'])])

        company_box_table = Table(company_box_data, colWidths=[85*mm])
        company_box_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        left_column.append(company_box_table)

        # --- COLUMNA DERECHA: DATOS DEL COMPROBANTE ---
        right_column = []
        
        # Info Box (RUC, Factura, Autorización, etc)
        doc_info_data = [
            [Paragraph(f"<b>R.U.C.:</b> {self.company.ruc}", self.styles['CompanyTitle'])],
            [Paragraph(self.document.get_document_type_display().upper(), self.styles['CompanyTitle'])],
            [Paragraph(f"No. {self.document.document_number}", self.styles['ValueStyle'])],
            [Paragraph("NÚMERO DE AUTORIZACIÓN", self.styles['LabelStyle'])],
            [Paragraph(self.document.sri_authorization_code or "PENDIENTE", self.styles['ValueStyle'])],
            [Paragraph(f"<b>FECHA Y HORA DE AUTORIZACIÓN:</b> {self.document.sri_authorization_date.strftime('%d/%m/%Y %H:%M:%S') if self.document.sri_authorization_date else 'PENDIENTE'}", self.styles['ValueStyle'])],
            [Paragraph(f"<b>AMBIENTE:</b> {self.sri_config.get_environment_display().upper()}", self.styles['ValueStyle'])],
            [Paragraph(f"<b>EMISIÓN:</b> NORMAL", self.styles['ValueStyle'])],
            [Paragraph("CLAVE DE ACCESO", self.styles['LabelStyle'])],
        ]
        
        # Barcode Drawing
        try:
            # Usar createBarcodeDrawing para mejor compatibilidad y escalado automático
            barcode_drawing = createBarcodeDrawing('Code128', value=self.document.access_key, 
                                                   barHeight=10*mm, width=80*mm, humanReadable=False)
            doc_info_data.append([barcode_drawing])
        except Exception as e:
            logger.error(f"Error generating barcode: {str(e)}")
            doc_info_data.append([Paragraph("Error al generar código de barras", self.styles['ValueStyle'])])
        
        doc_info_data.append([Paragraph(self.document.access_key, self.styles['ValueStyle'])])

        doc_info_table = Table(doc_info_data, colWidths=[85*mm])
        doc_info_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('ALIGN', (0, 9), (0, 9), 'CENTER'), # Barcode align
            ('ALIGN', (0, 10), (0, 10), 'CENTER'), # Access key text align
        ]))
        right_column.append(doc_info_table)

        # Unir ambas columnas
        header_master_data = [[left_column, right_column]]
        header_master_table = Table(header_master_data, colWidths=[90*mm, 90*mm])
        header_master_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        elements.append(header_master_table)
        elements.append(Spacer(1, 5*mm))
        
        return elements

    def _build_invoice_info(self):
        """Ya incluido en _build_header"""
        return []
    
    def _build_customer_info(self):
        """
        Construye la información del cliente siguiendo el formato SRI
        """
        elements = []
        
        customer_data = [
            [Paragraph(f"<b>Razón Social / Nombres y Apellidos:</b> {self.document.customer_name.upper()}", self.styles['ValueStyle']), ""],
            [Paragraph(f"<b>Identificación:</b> {self.document.customer_identification}", self.styles['ValueStyle']), 
             Paragraph(f"<b>Guía:</b> {getattr(self.document, 'remission_guide_number', '') or ''}", self.styles['ValueStyle'])],
            [Paragraph(f"<b>Fecha:</b> {self.document.issue_date.strftime('%d/%m/%Y')}", self.styles['ValueStyle']), 
             Paragraph(f"<b>Dirección:</b> {self.document.customer_address.upper() if self.document.customer_address else ''}", self.styles['ValueStyle'])],
        ]
        
        customer_table = Table(customer_data, colWidths=[100*mm, 80*mm])
        customer_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('SPAN', (0, 0), (1, 0)), # Razón social ocupa toda la fila
        ]))
        
        elements.append(customer_table)
        elements.append(Spacer(1, 5*mm))
        return elements
    
    def _build_invoice_details(self):
        """
        Construye la tabla de detalles siguiendo el formato SRI (RIDE)
        """
        elements = []
        
        # Cabeceras exactas del SRI
        headers = [
            Paragraph("<b>Cod. Principal</b>", self.styles['TableHeader']),
            Paragraph("<b>Cod. Auxiliar</b>", self.styles['TableHeader']),
            Paragraph("<b>Cant</b>", self.styles['TableHeader']),
            Paragraph("<b>Descripción</b>", self.styles['TableHeader']),
            Paragraph("<b>Detalle Adicional</b>", self.styles['TableHeader']),
            Paragraph("<b>Precio Unitario</b>", self.styles['TableHeader']),
            Paragraph("<b>Subsidio</b>", self.styles['TableHeader']),
            Paragraph("<b>Precio sin Subsidio</b>", self.styles['TableHeader']),
            Paragraph("<b>Descuento</b>", self.styles['TableHeader']),
            Paragraph("<b>Precio Total</b>", self.styles['TableHeader']),
        ]
        
        table_data = [headers]
        
        # Obtener items de la relación directa
        items = list(self.document.items.all())
        
        # Si no hay items en la relación, buscar en additional_data (pos_items)
        if not items and self.document.additional_data and 'pos_items' in self.document.additional_data:
            pos_items = self.document.additional_data['pos_items']
            if isinstance(pos_items, list):
                for pi in pos_items:
                    # Mapear campos del JSON a lo esperado por el PDF
                    row = [
                        Paragraph(str(pi.get('main_code', pi.get('id', ''))), self.styles['TableCell']),
                        Paragraph(str(pi.get('auxiliary_code', '')), self.styles['TableCell']),
                        Paragraph(f"{float(pi.get('quantity', 1)):.2f}", self.styles['TableCell']),
                        Paragraph(str(pi.get('description', pi.get('name', ''))), self.styles['TableCell']),
                        Paragraph("", self.styles['TableCell']),
                        Paragraph(f"{float(pi.get('unit_price', pi.get('price', 0))):.2f}", self.styles['TableCell']),
                        Paragraph("0.00", self.styles['TableCell']),
                        Paragraph("0.00", self.styles['TableCell']),
                        Paragraph(f"{float(pi.get('discount', 0)):.2f}", self.styles['TableCell']),
                        Paragraph(f"{float(pi.get('subtotal', pi.get('total_price', 0))):.2f}", self.styles['TableCell']),
                    ]
                    table_data.append(row)
        else:
            # Usar items de la relación normal
            for item in items:
                add_info = ""
                if item.additional_details:
                    add_info = ", ".join([f"{v}" for k, v in item.additional_details.items()])
                
                row = [
                    Paragraph(item.main_code, self.styles['TableCell']),
                    Paragraph(item.auxiliary_code or "", self.styles['TableCell']),
                    Paragraph(f"{item.quantity:.2f}", self.styles['TableCell']),
                    Paragraph(item.description, self.styles['TableCell']),
                    Paragraph(add_info, self.styles['TableCell']),
                    Paragraph(f"{item.unit_price:.2f}", self.styles['TableCell']),
                    Paragraph("0.00", self.styles['TableCell']),
                    Paragraph("0.00", self.styles['TableCell']),
                    Paragraph(f"{item.discount:.2f}", self.styles['TableCell']),
                    Paragraph(f"{item.subtotal:.2f}", self.styles['TableCell']),
                ]
                table_data.append(row)
        
        # Si sigue vacío, añadir una fila vacía para mantener la estructura
        if len(table_data) == 1:
            table_data.append([Paragraph("", self.styles['TableCell'])] * 10)

        # Anchos de columna optimizados (Total ~180mm)
        col_widths = [18*mm, 18*mm, 12*mm, 42*mm, 20*mm, 15*mm, 13*mm, 15*mm, 13*mm, 14*mm]
        
        details_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        details_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'), # Header align
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
        ]))
        
        elements.append(details_table)
        elements.append(Spacer(1, 5*mm))
        return elements
    
    def _build_invoice_totals(self):
        """
        Construye la sección inferior con info adicional y totales
        """
        elements = []
        
        # --- LADO IZQUIERDO: INFO ADICIONAL Y FORMA DE PAGO ---
        left_side = []
        
        # 1. Info Adicional
        if self.document.additional_data:
            add_data = [[Paragraph("Información Adicional", self.styles['LabelStyle'])]]
            for key, value in self.document.additional_data.items():
                # OMITIR pos_items de la visualización de info adicional ya que se muestra en la tabla
                if key == 'pos_items':
                    continue
                add_data.append([Paragraph(f"<b>{key}:</b> {value}", self.styles['ValueStyle'])])
            
            if len(add_data) > 1: # Solo si hay algo más que el título
                add_table = Table(add_data, colWidths=[90*mm])
                add_table.setStyle(TableStyle([
                    ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                    ('LEFTPADDING', (0, 0), (-1, -1), 5),
                ]))
                left_side.append(add_table)
                left_side.append(Spacer(1, 5*mm))

        # 2. Forma de Pago
        # Buscamos en additional_data o usamos uno por defecto
        payment_method = "Sin utilización del sistema financiero"
        if self.document.additional_data and 'Forma de Pago' in self.document.additional_data:
             payment_method = self.document.additional_data['Forma de Pago']
        
        payment_data = [
            [Paragraph("Forma de Pago", self.styles['LabelStyle']), Paragraph("Valor", self.styles['LabelStyle'])],
            [Paragraph(payment_method, self.styles['ValueStyle']), Paragraph(f"{self.document.total_amount:.2f}", self.styles['ValueStyle'])]
        ]
        payment_table = Table(payment_data, colWidths=[65*mm, 25*mm])
        payment_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ]))
        left_side.append(payment_table)

        # --- LADO DERECHO: TOTALES ---
        right_side = []
        
        # Calcular subtotales por tarifa
        subtotal_0 = Decimal('0.00')
        subtotal_15 = Decimal('0.00')
        subtotal_no_objeto = Decimal('0.00')
        subtotal_exento = Decimal('0.00')
        iva_15 = Decimal('0.00')
        
        for tax in self.document.taxes.all():
            if tax.tax_code == '2': # IVA
                if tax.percentage_code == '0':
                    subtotal_0 += tax.taxable_base
                elif tax.percentage_code == '4': # 15%
                    subtotal_15 += tax.taxable_base
                    iva_15 += tax.tax_amount
                elif tax.percentage_code == '6':
                    subtotal_no_objeto += tax.taxable_base
                elif tax.percentage_code == '7':
                    subtotal_exento += tax.taxable_base
        
        # Si no hay impuestos (ej. borrador), usar subtotal general
        if not self.document.taxes.exists():
            subtotal_15 = self.document.subtotal_without_tax

        totals_data = [
            [Paragraph("SUBTOTAL 15%", self.styles['TotalLabel']), Paragraph(f"{subtotal_15:.2f}", self.styles['TotalValue'])],
            [Paragraph("SUBTOTAL 0%", self.styles['TotalLabel']), Paragraph(f"{subtotal_0:.2f}", self.styles['TotalValue'])],
            [Paragraph("SUBTOTAL NO OBJETO DE IVA", self.styles['TotalLabel']), Paragraph(f"{subtotal_no_objeto:.2f}", self.styles['TotalValue'])],
            [Paragraph("SUBTOTAL EXENTO DE IVA", self.styles['TotalLabel']), Paragraph(f"{subtotal_exento:.2f}", self.styles['TotalValue'])],
            [Paragraph("SUBTOTAL SIN IMPUESTOS", self.styles['TotalLabel']), Paragraph(f"{self.document.subtotal_without_tax:.2f}", self.styles['TotalValue'])],
            [Paragraph("TOTAL DESCUENTO", self.styles['TotalLabel']), Paragraph(f"{self.document.total_discount:.2f}", self.styles['TotalValue'])],
            [Paragraph("ICE", self.styles['TotalLabel']), Paragraph("0.00", self.styles['TotalValue'])],
            [Paragraph("IRBPNR", self.styles['TotalLabel']), Paragraph("0.00", self.styles['TotalValue'])],
            [Paragraph("IVA 15%", self.styles['TotalLabel']), Paragraph(f"{iva_15:.2f}", self.styles['TotalValue'])],
            [Paragraph("PROPINA", self.styles['TotalLabel']), Paragraph("0.00", self.styles['TotalValue'])],
            [Paragraph("VALOR TOTAL", self.styles['TotalLabel']), Paragraph(f"{self.document.total_amount:.2f}", self.styles['TotalValue'])],
        ]
        
        totals_table = Table(totals_data, colWidths=[55*mm, 30*mm])
        totals_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('RIGHTPADDING', (1, 0), (1, -1), 5),
        ]))
        right_side.append(totals_table)

        # Master Table para unir ambos lados
        master_data = [[left_side, right_side]]
        master_table = Table(master_data, colWidths=[95*mm, 85*mm])
        master_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        elements.append(master_table)
        return elements
    
    def _build_additional_info(self):
        """Ya incluido en _build_invoice_totals"""
        return []
    
    def _build_authorization_info(self):
        """Ya incluido en el box del encabezado"""
        return []
    
    def _build_footer(self):
        """Pie de página vacío para coincidir con imagen"""
        return []
    
    def _generate_qr_code(self):
        """
        Genera código QR con la clave de acceso
        """
        try:
            qr = qrcode.QRCode(version=1, box_size=3, border=1)
            qr.add_data(self.document.access_key)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            img_buffer = io.BytesIO()
            qr_img.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            return Image(img_buffer, width=1*inch, height=1*inch)
        except Exception as e:
            logger.error(f"Error generating QR code: {str(e)}")
            return None