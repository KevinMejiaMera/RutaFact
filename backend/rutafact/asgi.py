"""
ASGI config for rutafact_sri project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

# Configurar entorno de Django antes de importar consumers/routing
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rutafact.settings')
django.setup()

# IMPORTANTE: Importar después de django.setup()
from apps.core.routing import websocket_urlpatterns as core_ws
from apps.tracking.routing import websocket_urlpatterns as tracking_ws

# Application definition
# ✅ SOPORTE PARA HTTP Y WEBSOCKETS (DJANGO CHANNELS)
application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            core_ws + tracking_ws
        )
    ),
})

