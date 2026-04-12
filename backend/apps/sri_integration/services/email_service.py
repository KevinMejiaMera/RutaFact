# -*- coding: utf-8 -*-
"""
Servicio de envío de emails para documentos electrónicos
USANDO SENDGRID EXCLUSIVAMENTE
"""

import logging
from django.utils import timezone
from apps.core.models import AuditLog

logger = logging.getLogger(__name__)


class EmailService:
    """
    Servicio para envío de documentos electrónicos por email
    USA SOLO SENDGRID - NO USA DJANGO MAIL
    """
    
    def __init__(self, company):
        self.company = company
        self.sri_config = company.sri_configuration
    
    def send_document_email(self, document):
        """
        Envía un documento electrónico por email.
        Prioridad: 1. SendGrid, 2. SMTP (Django Mail)
        """
        try:
            # Validaciones básicas
            if not document.customer_email:
                return False, "Customer email not provided"
            
            # 0. VERIFICA GLOBALMENTE DESDE SETTINGS (KILL-SWITCH)
            from django.conf import settings
            if not getattr(settings, 'SRI_AUTO_EMAIL', True):
                logger.warning("📩 [EMAIL_SERVICE] Global email sending is DISABLED. Skipping.")
                return False, "Global email sending is disabled"

            if not self.sri_config.email_enabled:
                return False, "Email sending is disabled for this company"
            
            # Obtener contenidos de archivos del almacenamiento
            xml_content = None
            pdf_content = None
            
            if document.signed_xml_file:
                try: xml_content = document.signed_xml_file.read()
                except: pass
            
            if not xml_content and document.xml_file:
                try: xml_content = document.xml_file.read()
                except: pass
                
            if document.pdf_file:
                try: pdf_content = document.pdf_file.read()
                except: pass

            if not xml_content and not pdf_content:
                return False, "No files available to send"

            # 1. INTENTAR SENDGRID
            from apps.sri_integration.services.sendgrid_service import SendGridService
            sendgrid = SendGridService()
            
            if sendgrid.api_key:
                logger.info("📤 Usando SENDGRID para enviar factura")
                success = sendgrid.send_invoice(
                    to_email=document.customer_email,
                    invoice_number=document.document_number,
                    xml_content=xml_content,
                    pdf_content=pdf_content,
                    cliente_nombre=document.customer_name
                )
                if success:
                    self._after_send_success(document)
                    return True, "Email sent via SendGrid"

            # 2. FALLBACK A SMTP (DJANGO MAIL)
            logger.info("📤 Usando SMTP (Django Mail) como fallback")
            from django.core.mail import EmailMessage, get_connection
            from django.conf import settings
            from apps.settings.models import SystemSetting
            
            # Obtener configuración SMTP (Prioridad: Base de Datos > Settings/ENV)
            def get_setting(key, default):
                s = SystemSetting.objects.filter(key=key).first()
                if s and s.value:
                    return s.get_typed_value()
                return default

            host = get_setting('SMTP_HOST', settings.EMAIL_HOST)
            port = get_setting('SMTP_PORT', settings.EMAIL_PORT)
            user = get_setting('SMTP_USER', settings.EMAIL_HOST_USER)
            password = get_setting('SMTP_PASSWORD', settings.EMAIL_HOST_PASSWORD)
            use_tls = get_setting('USE_TLS', settings.EMAIL_USE_TLS)
            use_ssl = get_setting('USE_SSL', getattr(settings, 'EMAIL_USE_SSL', False))
            from_email = get_setting('FROM_EMAIL', settings.DEFAULT_FROM_EMAIL)

            if not user or not password:
                logger.error("❌ SMTP not configured (no user or password)")
                return False, "SMTP or SendGrid not configured"

            logger.info(f"Connecting to SMTP: {host}:{port} (TLS={use_tls}, SSL={use_ssl})")
            
            connection = get_connection(
                backend='django.core.mail.backends.smtp.EmailBackend',
                host=host, 
                port=port, 
                username=user, 
                password=password, 
                use_tls=use_tls,
                use_ssl=use_ssl,
                timeout=20  # Timeout de 20 segundos para evitar bloqueos infinitos
            )
            
            subject = f"Factura Electrónica {document.document_number}"
            body = f"Estimado/a {document.customer_name or 'Cliente'},\n\nAdjuntamos su documento electrónico {document.document_number}.\n\nSaludos."
            
            email = EmailMessage(
                subject=subject,
                body=body,
                from_email=from_email or user,
                to=[document.customer_email],
                connection=connection
            )
            
            if xml_content:
                email.attach(f"factura_{document.document_number}.xml", xml_content, 'application/xml')
            if pdf_content:
                email.attach(f"factura_{document.document_number}.pdf", pdf_content, 'application/pdf')
            
            email.send()
            self._after_send_success(document)
            return True, "Email sent via SMTP"
                
        except Exception as e:
            logger.error(f"❌ Error enviando email: {str(e)}")
            return False, f"Error: {str(e)}"

    def _after_send_success(self, document):
        """Acciones post-envío exitoso"""
        document.email_sent = True
        document.email_sent_date = timezone.now()
        document.save(update_fields=['email_sent', 'email_sent_date'])
        
        try:
            AuditLog.objects.create(
                action='SEND_EMAIL',
                model_name='ElectronicDocument',
                object_id=str(document.id),
                object_representation=f"Email a: {document.customer_email}",
                additional_data={'document_number': document.document_number}
            )
        except: pass
    
    def send_authorization_notification(self, document):
        """
        Notificación de autorización usando SendGrid o SMTP
        """
        return self.send_document_email(document)