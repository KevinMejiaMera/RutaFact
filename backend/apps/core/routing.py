# -*- coding: utf-8 -*-
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Ruta para el monitoreo de colas SRI en tiempo real
    # Aseguramos el anclaje con ^ y $ para evitar 404 en producción
    re_path(r'^ws/queue/(?P<company_id>\d+)/$', consumers.QueueConsumer.as_asgi()),
    re_path(r'^ws/user/$', consumers.UserConsumer.as_asgi()),
]
