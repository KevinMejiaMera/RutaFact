from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings
from .models import TrackingRoute, TrackingPoint

def is_admin(user):
    return user.is_staff or user.is_superuser

@login_required
@user_passes_test(is_admin)
def tracking_map_view(request, route_id=None):
    """
    Vista para visualizar el mapa de rutas en la web
    """
    from apps.core.views import get_user_companies_secure
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    # Filtrar rutas solo de la empresa del admin
    if company:
        # Asignar automáticamente rutas huérfanas de este usuario a su empresa principal (limpieza)
        TrackingRoute.objects.filter(user=request.user, company__isnull=True).update(company=company)
        
        routes = TrackingRoute.objects.filter(company=company).order_by('-start_time')
        
        # Filtro por fecha si existe en GET
        date_filter = request.GET.get('date')
        if date_filter:
            from django.utils.dateparse import parse_date
            parsed_date = parse_date(date_filter)
            if parsed_date:
                routes = routes.filter(start_time__date=parsed_date)
    else:
        routes = TrackingRoute.objects.none()
    
    selected_route = None
    points = []
    
    if route_id:
        selected_route = get_object_or_404(TrackingRoute, id=route_id)
        # Verificar que la ruta pertenece a la empresa
        if selected_route.company != company and not request.user.is_superuser:
            selected_route = None
    
    if not selected_route and routes.exists():
        selected_route = routes.first()
    
    if selected_route:
        points = selected_route.points.all()

    context = {
        'routes': routes,
        'selected_route': selected_route,
        'points': points,
        'user': request.user,
        'company': company,
        'google_maps_key': settings.GOOGLE_MAPS_API_KEY
    }
    return render(request, 'admin/tracking_map.html', context)

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .serializers import TrackingSyncSerializer

class TrackingViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        """Listar el historial de rutas del usuario"""
        # Si es admin, puede ver todo. Si no, solo lo suyo.
        if request.user.is_staff or request.user.is_superuser:
            routes = TrackingRoute.objects.all().order_by('-start_time')[:50]
        else:
            routes = TrackingRoute.objects.filter(user=request.user).order_by('-start_time')[:50]
        
        data = []
        for r in routes:
            data.append({
                'id': r.id,
                'mobile_route_id': r.mobile_route_id,
                'start_time': r.start_time,
                'end_time': r.end_time,
                'points_count': r.points.count(),
                'duration': r.duration_display
            })
        return Response(data)

    @action(detail=False, methods=['post'])
    def sync(self, request):
        """
        Sincroniza un lote de puntos de GPS desde el móvil
        """
        serializer = TrackingSyncSerializer(data=request.data)
        if serializer.is_valid():
            mobile_route_id = serializer.validated_data['mobile_route_id']
            points_data = serializer.validated_data['points']
            device_info = serializer.validated_data.get('device_info', {})

            # Obtener empresa del usuario
            from apps.companies.models import Company
            user_company = getattr(request.user, 'company', None)
            
            # Si no tiene empresa directa, buscar en sus asignaciones
            if not user_company:
                from apps.users.models import UserCompanyAssignment
                assignment = UserCompanyAssignment.objects.filter(user=request.user).first()
                if assignment:
                    user_company = assignment.assigned_companies.first()

            # Obtener o crear la ruta
            route, created = TrackingRoute.objects.get_or_create(
                mobile_route_id=mobile_route_id,
                defaults={
                    'user': request.user,
                    'company': user_company,
                    'device_info': device_info
                }
            )
            
            # Si la ruta existía pero no tenía empresa, asignarla ahora
            if not created and not route.company and user_company:
                route.company = user_company
                route.save(update_fields=['company'])

            # Crear los puntos en masa
            points_to_create = []
            from decimal import Decimal
            
            for p in points_data:
                # NORMALIZACIÓN DE COORDENADAS:
                # Si los valores son extremadamente altos (> 180), dividimos por un factor (posible error de escala)
                lat = Decimal(str(p['latitude']))
                lng = Decimal(str(p['longitude']))
                
                # Heurística para detectar escala de millonésimas (muy común en algunos dispositivos)
                if abs(lat) > 180: lat = lat / Decimal('10000000')
                if abs(lng) > 180: lng = lng / Decimal('10000000')
                
                # Segunda heurística: Si aún es muy alto, podría ser escala de milmillonésimas (como se vio en el error)
                if abs(lat) > 180: lat = lat / Decimal('100')
                if abs(lng) > 180: lng = lng / Decimal('100')

                # Evitar duplicados exactos en el mismo timestamp
                if not TrackingPoint.objects.filter(route=route, timestamp=p['timestamp']).exists():
                    points_to_create.append(
                        TrackingPoint(
                            route=route,
                            latitude=lat,
                            longitude=lng,
                            accuracy=p.get('accuracy'),
                            speed=p.get('speed'),
                            timestamp=p['timestamp']
                        )
                    )
            
            if points_to_create:
                TrackingPoint.objects.bulk_create(points_to_create)
                
                # TRANSMISIÓN EN TIEMPO REAL (WEBSOCKETS)
                try:
                    from asgiref.sync import async_to_sync
                    from channels.layers import get_channel_layer
                    
                    if user_company:
                        channel_layer = get_channel_layer()
                        async_to_sync(channel_layer.group_send)(
                            f'tracking_{user_company.id}',
                            {
                                'type': 'tracking_update',
                                'data': {
                                    'user': request.user.email,
                                    'route_id': route.id,
                                    'points': [
                                        {
                                            'latitude': float(p.latitude),
                                            'longitude': float(p.longitude),
                                            'timestamp': p.timestamp.isoformat()
                                        } for p in points_to_create
                                    ]
                                }
                            }
                        )
                except Exception as e:
                    import logging
                    logging.error(f"Error broadcasting tracking update: {e}")

            return Response({
                'status': 'success',
                'points_processed': len(points_data),
                'points_created': len(points_to_create),
                'normalized': True
            }, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
