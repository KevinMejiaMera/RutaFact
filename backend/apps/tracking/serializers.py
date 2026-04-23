from rest_framework import serializers
from .models import TrackingRoute, TrackingPoint

class TrackingPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrackingPoint
        fields = ['latitude', 'longitude', 'accuracy', 'speed', 'timestamp']

class TrackingSyncSerializer(serializers.Serializer):
    """
    Serializador para recibir un lote de coordenadas y la ruta asociada
    """
    mobile_route_id = serializers.CharField(max_length=100)
    points = TrackingPointSerializer(many=True)
    device_info = serializers.JSONField(required=False, default=dict)
