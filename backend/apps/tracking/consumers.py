import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

class TrackingConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.company_id = self.scope['url_route']['kwargs'].get('company_id')
        self.group_name = f'tracking_{self.company_id}'

        # Unirse al grupo de la empresa
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Salir del grupo
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    # Recibir mensaje del grupo
    async def tracking_update(self, event):
        # Enviar mensaje al WebSocket
        await self.send(text_data=json.dumps(event['data']))
