# -*- coding: utf-8 -*-
from rest_framework import serializers
from apps.logistics.models import Vehicle, Route, RouteStop

class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = '__all__'

class RouteStopSerializer(serializers.ModelSerializer):
    customer_name = serializers.ReadOnlyField(source='customer.name')
    customer_identification = serializers.ReadOnlyField(source='customer.identification')
    
    class Meta:
        model = RouteStop
        fields = '__all__'

class RouteSerializer(serializers.ModelSerializer):
    vehicle_plate = serializers.ReadOnlyField(source='vehicle.plate')
    driver_name = serializers.ReadOnlyField(source='driver.get_full_name')
    stops_count = serializers.IntegerField(source='stops.count', read_only=True)
    
    class Meta:
        model = Route
        fields = '__all__'

class RouteDetailSerializer(RouteSerializer):
    stops = RouteStopSerializer(many=True, read_only=True)
    
    class Meta(RouteSerializer.Meta):
        fields = '__all__'
