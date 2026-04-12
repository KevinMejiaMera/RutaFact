"""
ASGI config for rutafact_sri project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
import django
from django.core.asgi import get_asgi_application

# Configurar entorno de Django antes de importar consumers/routing
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rutafact.settings')
django.setup()

# IMPORTANTE: Importar después de django.setup()
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from apps.core.routing import websocket_urlpatterns

# Application definition
# ✅ SOPORTE PARA HTTP Y WEBSOCKETS (DJANGO CHANNELS)
application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            websocket_urlpatterns
        )
    ),
})

