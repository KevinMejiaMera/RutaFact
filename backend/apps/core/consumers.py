# -*- coding: utf-8 -*-
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.apps import apps

logger = logging.getLogger(__name__)

class QueueConsumer(AsyncWebsocketConsumer):
    """
    Consumer para actualización de cola SRI en tiempo real
    ✅ MONITOREO POR EMPRESA
    ✅ SEGURIDAD: Solo usuarios con acceso a la empresa
    ✅ ACTUALIZACIONES DE CELERY -> FRONTEND
    """
    
    async def connect(self):
        self.company_id = self.scope['url_route']['kwargs']['company_id']
        self.room_group_name = f'company_{self.company_id}_queue'
        self.user = self.scope["user"]

        # 🔒 SEGURIDAD: Verificar acceso del usuario a la empresa
        if not self.user.is_authenticated:
            await self.close()
            return

        has_access = await self.check_company_access(self.user, self.company_id)
        if not has_access:
            logger.warning(f"🚫 [WS] Access denied: User {self.user.id} tried to connect to company {self.company_id}")
            await self.close()
            return

        # Unirse al grupo de la empresa
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()
        logger.info(f"✅ [WS] Connected: User {self.user.id} to company {self.company_id} queue")

    async def disconnect(self, close_code):
        # Salir del grupo
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
        logger.info(f"🔌 [WS] Disconnected: User {self.user.id if hasattr(self, 'user') else 'Unknown'}")

    # Recepción de mensajes del grupo (desde Celery)
    async def queue_update(self, event):
        """
        Recibe actualización de estado de un documento
        """
        message = event['message']

        # Enviar mensaje al WebSocket
        await self.send(text_data=json.dumps({
            'type': 'queue_update',
            'data': message
        }))

    @database_sync_to_async
    def check_company_access(self, user, company_id):
        """
        Verifica si el usuario tiene acceso a la empresa
        """
        try:
            # Importar dinámicamente para evitar import circular al inicio
            from apps.core.views import get_user_companies_secure
            from apps.companies.models import Company
            
            # Si es staff/superuser, tiene acceso total
            if user.is_staff or user.is_superuser:
                return True
                
            user_companies = get_user_companies_secure(user)
            return user_companies.filter(id=company_id).exists()
            
        except Exception as e:
            logger.error(f"Error checking company access in WS: {e}")
            return False

class UserConsumer(AsyncWebsocketConsumer):
    """
    Consumer para notificaciones personalizadas al usuario
    ✅ PERMISOS (can_track, role)
    ✅ ESTADO (active, suspended)
    """
    
    async def connect(self):
        self.user = self.scope["user"]
        
        if not self.user.is_authenticated:
            await self.close()
            return
            
        self.room_group_name = f'user_{self.user.id}'
        
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        logger.info(f"👤 [WS] User {self.user.id} connected for personal notifications")

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def user_update(self, event):
        """Notificación de cambio en el perfil/permisos del usuario"""
        await self.send(text_data=json.dumps({
            'type': 'user_update',
            'data': event['data']
        }))
