# -*- coding: utf-8 -*-
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.auth import get_user_model
from ..serializers.user_serializers import UserSerializer, UserUpdateSerializer

User = get_user_model()

class UserViewSet(viewsets.ModelViewSet):
    """
    ViewSet para que los administradores gestionen usuarios de su empresa
    o todos los usuarios si es superusuario.
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return User.objects.all()
        
        # Si es admin de empresa, solo ve usuarios de su empresa
        if user.role == 'admin' and user.company:
            return User.objects.filter(company=user.company)
        
        # Usuarios normales solo se ven a sí mismos
        return User.objects.filter(id=user.id)

    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            return UserUpdateSerializer
        return UserSerializer

    @action(detail=True, methods=['post'])
    def change_status(self, request, pk=None):
        """Cambiar estado del usuario (active, suspended, etc)"""
        user = self.get_object()
        new_status = request.data.get('status')
        
        if new_status not in dict(User.USER_STATUS_CHOICES):
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)
        
        user.user_status = new_status
        user.save()
        return Response({'status': 'User status updated'})
