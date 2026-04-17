# -*- coding: utf-8 -*-
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from apps.logistics.models import Vehicle, Route, RouteStop
from apps.api.serializers.logistics_serializers import (
    VehicleSerializer, RouteSerializer, RouteDetailSerializer, RouteStopSerializer
)
from apps.api.user_company_helper import get_user_companies_exact

class VehicleViewSet(viewsets.ModelViewSet):
    serializer_class = VehicleSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['company', 'is_active']

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Vehicle.objects.all()
        user_companies = get_user_companies_exact(user)
        return Vehicle.objects.filter(company__in=user_companies)

class RouteViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['company', 'status', 'date', 'driver', 'vehicle']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return RouteDetailSerializer
        return RouteSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Route.objects.all()
        user_companies = get_user_companies_exact(user)
        return Route.objects.filter(company__in=user_companies)

    @action(detail=True, methods=['post'])
    def start_route(self, request, pk=None):
        route = self.get_object()
        if route.status != 'DRAFT':
            return Response({'error': 'Only draft routes can be started'}, status=status.HTTP_400_BAD_REQUEST)
        route.status = 'ACTIVE'
        route.save()
        return Response({'status': 'Route is now active'})

    @action(detail=True, methods=['post'])
    def complete_route(self, request, pk=None):
        route = self.get_object()
        route.status = 'COMPLETED'
        route.save()
        return Response({'status': 'Route completed'})

class RouteStopViewSet(viewsets.ModelViewSet):
    serializer_class = RouteStopSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        # Filtrar por las rutas que el usuario puede ver
        user = self.request.user
        user_companies = get_user_companies_exact(user)
        return RouteStop.objects.filter(route__company__in=user_companies)

    @action(detail=True, methods=['post'])
    def mark_visited(self, request, pk=None):
        stop = self.get_object()
        from django.utils import timezone
        stop.status = 'VISITED'
        stop.arrival_time = timezone.now()
        stop.save()
        return Response({'status': 'Stop marked as visited'})
