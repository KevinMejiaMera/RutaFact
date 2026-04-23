from django.urls import path
from . import views

urlpatterns = [
    path('', views.tracking_map_view, name='tracking_map'),
    path('<int:route_id>/', views.tracking_map_view, name='tracking_map_detail'),
]
