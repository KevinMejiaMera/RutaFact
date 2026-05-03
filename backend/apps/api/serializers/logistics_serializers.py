# -*- coding: utf-8 -*-
from rest_framework import serializers
from apps.logistics.models import Vehicle, Route, RouteStop, RouteProduct, RouteDelivery, RouteDeliveryItem

class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = '__all__'

class RouteProductSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    
    class Meta:
        model = RouteProduct
        fields = ['id', 'product', 'product_name', 'quantity_loaded', 'quantity_sold', 'quantity_returned']

class RouteDeliveryItemSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    class Meta:
        model = RouteDeliveryItem
        fields = ['id', 'product', 'product_name', 'quantity']

class RouteDeliverySerializer(serializers.ModelSerializer):
    items = RouteDeliveryItemSerializer(many=True, read_only=True)
    time = serializers.SerializerMethodField()
    
    class Meta:
        model = RouteDelivery
        fields = ['id', 'customer_name', 'notes', 'items', 'time', 'created_at']
        
    def get_time(self, obj):
        return obj.created_at.strftime('%H:%M')

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
    products = RouteProductSerializer(many=True, read_only=True)
    deliveries = RouteDeliverySerializer(many=True, read_only=True)
    
    class Meta:
        model = Route
        fields = [
            'id', 'company', 'name', 'date', 'driver', 'driver_name', 
            'vehicle', 'vehicle_plate', 'status', 'destination_name', 
            'google_maps_url', 'notes', 'stops_count', 'products', 'deliveries', 'created_at'
        ]

class RouteDetailSerializer(RouteSerializer):
    from apps.orders.serializers import OrderSerializer
    stops = RouteStopSerializer(many=True, read_only=True)
    orders = OrderSerializer(many=True, read_only=True)
    
    class Meta(RouteSerializer.Meta):
        fields = RouteSerializer.Meta.fields + ['stops', 'orders']
