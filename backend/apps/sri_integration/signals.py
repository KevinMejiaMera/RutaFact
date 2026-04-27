# -*- coding: utf-8 -*-
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
import logging

from apps.certificates.models import DigitalCertificate

logger = logging.getLogger(__name__)

@receiver(post_save, sender=DigitalCertificate)
def handle_certificate_changes(sender, instance, created, **kwargs):
    """
    1. Limpia el cache global de certificados.
    2. Si el RUC del certificado es diferente al de los documentos existentes, resetea datos.
    """
    try:
        from apps.sri_integration.services.global_certificate_manager import get_certificate_manager
        from apps.sri_integration.models import ElectronicDocument, CreditNote
        
        manager = get_certificate_manager()
        company_id = instance.company_id
        company = instance.company
        
        # 1. Recargar el certificado en el manager (limpia cache)
        manager.reload_certificate(company_id)
        logger.info(f"✅ Cache de certificado recargado para empresa {company_id}.")
        
        # 2. Detectar si debemos limpiar datos por cambio de RUC o por petición de "reinicio"
        extracted_ruc = instance.extracted_ruc
        if not extracted_ruc:
            return

        # Verificar si existen documentos con un RUC diferente al del certificado
        # (El RUC está en la clave de acceso, posiciones 11 a 23)
        has_mismatching_docs = ElectronicDocument.objects.filter(company=company).exclude(access_key__contains=extracted_ruc).exists()
        
        if has_mismatching_docs:
            logger.info(f"🔄 Detectados documentos con RUC antiguo. Iniciando limpieza total para nuevo RUC {extracted_ruc}...")
            
            # Resetear secuenciales en SRIConfiguration
            if hasattr(company, 'sri_configuration'):
                config = company.sri_configuration
                config.invoice_sequence = 1
                config.credit_note_sequence = 1
                config.debit_note_sequence = 1
                config.retention_sequence = 1
                config.remission_guide_sequence = 1
                config.purchase_settlement_sequence = 1
                config.save()
            
            # Resetear secuenciales en Company
            company.secuencial_factura = 1
            company.secuencial_nota_credito = 1
            company.secuencial_nota_debito = 1
            company.secuencial_retencion = 1
            company.save()
            
            # Eliminar TODOS los documentos (incluyendo autorizados) porque pertenecen a la identidad/RUC anterior
            # y bloquean el uso de los mismos números secuenciales para el nuevo RUC.
            deleted_docs = ElectronicDocument.objects.filter(company=company).delete()
            deleted_cn = CreditNote.objects.filter(company=company).delete()
            
            logger.info(f"🗑️ Limpieza total completada. Documentos eliminados: {deleted_docs[0] + deleted_cn[0]}")
            
    except Exception as e:
        logger.error(f"❌ Error en signal de cambio de certificado: {e}")

@receiver(post_delete, sender=DigitalCertificate)
def clear_certificate_cache_on_delete(sender, instance, **kwargs):
    """
    1. Limpia el cache global de certificados.
    2. Limpia los datos de identidad de la empresa para permitir un "borrón y cuenta nueva".
    """
    try:
        from apps.sri_integration.services.global_certificate_manager import get_certificate_manager
        manager = get_certificate_manager()
        company_id = instance.company_id
        company = instance.company
        
        # 1. Eliminar del cache
        with manager._operation_lock:
            if company_id in manager._certificates_cache:
                del manager._certificates_cache[company_id]
                logger.info(f"🗑️ Cache de certificado eliminado para empresa {company_id} tras borrado.")
        
        # 2. Limpiar datos de identidad de la empresa
        # Reseteamos a valores genéricos para que el usuario vea que se "limpió"
        # y la nueva firma pueda sobreescribirlos.
        logger.info(f"🧹 Limpiando datos de identidad de la empresa {company_id} tras eliminar firma.")
        
        company.business_name = "PENDIENTE DE FIRMA"
        company.trade_name = ""
        # No podemos dejar el RUC vacío si es unique=True, pero podemos poner uno temporal 
        # o mantenerlo si es necesario para la sesión, pero el usuario quiere ver "limpieza".
        # Vamos a poner un RUC genérico único por empresa si el actual es el que queremos borrar.
        company.ruc = f"9999{company.id:09d}"[:13] 
        company.obligado_contabilidad = 'NO'
        company.contribuyente_especial = None
        company.regimen = 'GENERAL'
        
        # Removed sequence resetting from post_delete to prevent sequence collisions
        # if the user uploads a certificate with the same RUC later.
        # The true "reset" logic is handled in post_save when a RUC mismatch is confirmed.
        company.save()

        # Removed document deletion from post_delete.
        # Document deletion should only occur in post_save on confirmed RUC mismatch.
        
    except Exception as e:
        logger.error(f"❌ Error al intentar limpiar datos tras borrado de firma: {e}")
