# -*- coding: utf-8 -*-
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import logging

logger = logging.getLogger(__name__)

def send_queue_update(company_id, document_id, status, message="", extra_data=None):
    """
    ✅ HELPER: Enviar actualización de cola a WebSockets
    company_id: ID de la empresa para el grupo
    document_id: ID del documento afectado
    status: Nuevo estado para la UI (e.g., 'GENERATING', 'SIGNING', 'SENDING', 'AUTHORIZED', 'ERROR')
    message: Mensaje amigable para la UI
    extra_data: Datos adicionales (e.g., número de documento, nombre cliente, etc)
    """
    try:
        channel_layer = get_channel_layer()
        group_name = f'company_{company_id}_queue'
        
        # Preparar payload
        update_data = {
            'document_id': document_id,
            'status': status,
            'message': message,
            'timestamp': str(extra_data.get('timestamp')) if extra_data and 'timestamp' in extra_data else None,
            'extra': extra_data or {}
        }
        
        # Enviar al grupo
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'queue_update',
                'message': update_data
            }
        )
        
        logger.debug(f"📡 [WS_HELPER] Sent update for Doc {document_id} [Status: {status}] to Company {company_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ [WS_HELPER] Error sending WebSocket update: {e}")
        return False
