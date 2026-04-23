from django.db import models
from django.conf import settings
from apps.core.models import BaseModel

class TrackingRoute(BaseModel):
    """
    Representa una sesión de seguimiento (ej. un día de trabajo o una entrega)
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='tracking_routes'
    )
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='tracking_routes',
        null=True,
        blank=True
    )
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    
    # Identificador único generado por el móvil para evitar duplicados en reconexión
    mobile_route_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    
    # Metadata adicional
    device_info = models.JSONField(default=dict, blank=True)
    
    class Meta:
        verbose_name = "Ruta de Seguimiento"
        verbose_name_plural = "Rutas de Seguimiento"
        ordering = ['-start_time']

    def __str__(self):
        return f"Ruta {self.mobile_route_id or self.id} - {self.user.email}"

    @property
    def duration_display(self):
        if not self.end_time:
            return "En proceso"
        duration = self.end_time - self.start_time
        seconds = duration.total_seconds()
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @property
    def google_maps_link(self):
        """Genera un link de Google Maps con el recorrido (inicio y fin)"""
        first_point = self.points.order_by('timestamp').first()
        last_point = self.points.order_by('timestamp').last()
        
        if not first_point:
            return None
            
        # Forzar formato con punto para evitar problemas de locale
        lat1, lng1 = f"{first_point.latitude:.8f}", f"{first_point.longitude:.8f}"
        
        if not last_point or last_point == first_point:
            return f"https://www.google.com/maps/search/?api=1&query={lat1},{lng1}"
            
        lat2, lng2 = f"{last_point.latitude:.8f}", f"{last_point.longitude:.8f}"
        return f"https://www.google.com/maps/dir/?api=1&origin={lat1},{lng1}&destination={lat2},{lng2}&travelmode=driving"

class TrackingPoint(models.Model):
    """
    Coordenada individual dentro de una ruta
    """
    route = models.ForeignKey(
        TrackingRoute, 
        on_delete=models.CASCADE, 
        related_name='points'
    )
    latitude = models.DecimalField(max_digits=12, decimal_places=9)
    longitude = models.DecimalField(max_digits=12, decimal_places=9)
    accuracy = models.FloatField(null=True, blank=True)
    speed = models.FloatField(null=True, blank=True)
    timestamp = models.DateTimeField()
    
    class Meta:
        verbose_name = "Punto de Seguimiento"
        verbose_name_plural = "Puntos de Seguimiento"
        ordering = ['timestamp']

    @property
    def google_maps_url(self):
        """Link directo a este punto en Google Maps"""
        lat, lng = f"{self.latitude:.8f}", f"{self.longitude:.8f}"
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
