# apps/sri_integration/services/sendgrid_service.py
import os
import logging
import base64
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition

logger = logging.getLogger("sri_integration")

class SendGridService:
    def __init__(self):
        # 1. Intentar desde variables de entorno
        self.api_key = os.getenv("SENDGRID_API_KEY")
        
        # 2. Fallback: Intentar desde SystemSetting (Base de Datos)
        if not self.api_key:
            try:
                from apps.settings.models import SystemSetting
                setting = SystemSetting.objects.filter(key="SENDGRID_API_KEY").first()
                if setting:
                    self.api_key = setting.value
                    logger.info("SendGrid API Key recuperada desde SystemSetting")
            except:
                pass
                
        if not self.api_key:
            logger.warning("SENDGRID_API_KEY no configurada (ni en ENV ni en DB)")
        
        self.sg = SendGridAPIClient(self.api_key) if self.api_key else None
        
        # 3. Configurar Remitente (Prioridad: ENV > Valor por defecto verificado)
        self.from_email = os.getenv("SENDGRID_FROM_EMAIL", "wandreszv@rutafact.ec")
        self.from_name = os.getenv("SENDGRID_FROM_NAME", "RutaFact")
    
    def send_invoice(self, to_email, invoice_number, xml_content=None, pdf_content=None, cliente_nombre=None):
        """Envía factura con archivos adjuntos usando SendGrid API directamente"""
        if not self.sg:
            logger.error("SendGrid no está configurado")
            return False
        
        try:
            # HTML del email - Estilo minimalista y profesional
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{
                        font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif;
                        margin: 0;
                        padding: 0;
                        background-color: #f5f5f5;
                    }}
                    .container {{
                        max-width: 600px;
                        margin: 0 auto;
                        background-color: #ffffff;
                    }}
                    .header {{
                        background-color: #1e3a8a;
                        color: white;
                        padding: 20px 30px;
                        font-size: 18px;
                        font-weight: 500;
                    }}
                    .content {{
                        padding: 30px;
                    }}
                    .greeting {{
                        color: #333;
                        font-size: 16px;
                        margin-bottom: 20px;
                    }}
                    .invoice-box {{
                        background-color: #f8f9fa;
                        border-radius: 8px;
                        padding: 20px;
                        margin: 25px 0;
                    }}
                    .invoice-label {{
                        color: #6c757d;
                        font-size: 12px;
                        text-transform: uppercase;
                        letter-spacing: 0.5px;
                        margin-bottom: 5px;
                    }}
                    .invoice-number {{
                        color: #1e3a8a;
                        font-size: 20px;
                        font-weight: 600;
                    }}
                    .files {{
                        margin: 25px 0;
                        padding: 15px;
                        border: 1px solid #dee2e6;
                        border-radius: 8px;
                    }}
                    .file-item {{
                        padding: 8px 0;
                        color: #495057;
                        font-size: 14px;
                    }}
                    .footer {{
                        background-color: #f8f9fa;
                        padding: 20px 30px;
                        border-top: 1px solid #dee2e6;
                    }}
                    .no-reply {{
                        color: #dc3545;
                        font-size: 12px;
                        font-weight: 600;
                        text-align: center;
                        padding: 10px;
                        background-color: #fff5f5;
                        border-radius: 4px;
                        margin-bottom: 10px;
                    }}
                    .footer-text {{
                        color: #6c757d;
                        font-size: 11px;
                        text-align: center;
                        line-height: 1.4;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        Facturación Electrónica
                    </div>
                    
                    <div class="content">
                        <div class="greeting">
                            Estimado/a {cliente_nombre or "Cliente"}
                        </div>
                        
                        <div class="invoice-box">
                            <div class="invoice-label">Documento Electrónico</div>
                            <div class="invoice-number">{invoice_number}</div>
                        </div>
                        
                        <div class="files">
                            <div style="font-weight: 600; margin-bottom: 10px; color: #333;">
                                Archivos adjuntos
                            </div>
                            <div class="file-item">📄 Comprobante XML (SRI)</div>
                            <div class="file-item">📄 Factura PDF</div>
                        </div>
                    </div>
                    
                    <div class="footer">
                        <div class="no-reply">
                            NO RESPONDER - Mensaje automático
                        </div>
                        <div class="footer-text">
                            {self.from_name} © 2025<br>
                            Sistema autorizado por el SRI
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """
            
            # Crear mensaje
            message = Mail(
                from_email=(self.from_email, self.from_name),
                to_emails=to_email,
                subject=f"Factura Electrónica {invoice_number}",
                html_content=html_content
            )
            
            # Adjuntar XML
            if xml_content:
                xml_data = base64.b64encode(xml_content).decode()
                xml_attachment = Attachment(
                    FileContent(xml_data),
                    FileName(f"factura_{invoice_number}.xml"),
                    FileType("application/xml"),
                    Disposition("attachment")
                )
                message.add_attachment(xml_attachment)
                logger.info(f"XML adjuntado desde contenido")
            
            # Adjuntar PDF
            if pdf_content:
                pdf_data = base64.b64encode(pdf_content).decode()
                pdf_attachment = Attachment(
                    FileContent(pdf_data),
                    FileName(f"factura_{invoice_number}.pdf"),
                    FileType("application/pdf"),
                    Disposition("attachment")
                )
                message.add_attachment(pdf_attachment)
                logger.info(f"PDF adjuntado desde contenido")
            
            # Enviar
            response = self.sg.send(message)
            logger.info(f"Email enviado exitosamente. Status: {response.status_code}")
            return True
            
        except Exception as e:
            logger.error(f"Error enviando email con SendGrid: {str(e)}")
            return False