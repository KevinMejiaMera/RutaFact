# -*- coding: utf-8 -*-
import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from apps.companies.models import Company
from apps.api.serializers.company_serializers import CompanySerializer
from apps.api.authentication import VirtualCompanyUser

logger = logging.getLogger(__name__)

class CompanyViewSet(viewsets.ModelViewSet):
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    
    def get_queryset(self):
        """
        Determinar empresas según tipo de token:
        - Token de empresa (vsr_): solo esa empresa
        - Token de usuario: empresas asignadas al usuario
        """
        user = self.request.user
        
        # 🔥 CASO 1: TOKEN DE EMPRESA (Usuario Virtual)
        if isinstance(user, VirtualCompanyUser):
            logger.error(f"🔥🔥🔥 COMPANY TOKEN: {user.company.business_name} (ID: {user.company.id})")
            # Solo retornar la empresa del token
            return Company.objects.filter(id=user.company.id, is_active=True)
        
        # 🔥 CASO 2: TOKEN DE USUARIO (Sistema nuclear original)
        from apps.api.user_company_helper import get_user_companies_exact
        companies = get_user_companies_exact(user)
        logger.error(f"🔥🔥🔥 USER TOKEN: User {user.username} = {companies.count()} companies")
        return companies
    
    def retrieve(self, request, *args, **kwargs):
        """
        Acceso a empresa específica con validación dual
        """
        company_id = kwargs.get("pk")
        user = request.user
        
        try:
            company_id = int(company_id)
        except (ValueError, TypeError):
            return Response({"error": "Invalid company ID"}, status=status.HTTP_400_BAD_REQUEST)
        
        # 🔥 CASO 1: TOKEN DE EMPRESA
        if isinstance(user, VirtualCompanyUser):
            logger.error(f"🔥🔥🔥 COMPANY TOKEN ACCESS: {user.company.business_name} -> Company {company_id}")
            
            # Solo puede acceder a SU empresa
            if company_id != user.company.id:
                logger.error(f"🚨🚨🚨 COMPANY TOKEN BLOCK: Company {company_id} BLOCKED (only {user.company.id} allowed)")
                return Response({
                    "error": "COMPANY_TOKEN_BLOCK",
                    "message": "Token only has access to its own company",
                    "token_company": user.company.business_name,
                    "token_company_id": user.company.id,
                    "requested_company_id": company_id,
                    "token_type": "company_token"
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Acceso permitido a su propia empresa
            logger.info(f"✅ Company token access granted: {user.company.business_name}")
            return super().retrieve(request, *args, **kwargs)
        
        # 🔥 CASO 2: TOKEN DE USUARIO (Nuclear existente)
        from apps.api.user_company_helper import get_user_companies_exact
        user_companies = get_user_companies_exact(request.user)
        user_company_ids = [c.id for c in user_companies]
        
        logger.error(f"🔥🔥🔥 USER TOKEN ACCESS: {request.user.username} -> Company {company_id}")
        
        if company_id not in user_company_ids:
            logger.error(f"🚨🚨🚨 USER TOKEN BLOCK: Company {company_id} BLOCKED")
            return Response({
                "error": "USER_TOKEN_BLOCK",
                "message": "User does not have access to this company",
                "user": request.user.username,
                "requested_company_id": company_id,
                "allowed_company_ids": user_company_ids,
                "token_type": "user_token"
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Acceso permitido
        logger.info(f"✅ User token access granted: {request.user.username} -> Company {company_id}")
        return super().retrieve(request, *args, **kwargs)
    
    def list(self, request, *args, **kwargs):
        """
        Listar empresas con información adicional del tipo de token
        """
        response = super().list(request, *args, **kwargs)
        
        # Agregar metadata sobre el tipo de token usado
        if isinstance(request.user, VirtualCompanyUser):
            response.data = {
                "results": response.data,
                "token_info": {
                    "type": "company_token",
                    "company_name": request.user.company.business_name,
                    "company_id": request.user.company.id,
                    "total_companies": 1,
                    "message": "Using company-specific token"
                }
            }
        else:
            # Token de usuario
            company_count = len(response.data) if isinstance(response.data, list) else response.data.get('count', 0)
            if hasattr(response, 'data') and isinstance(response.data, dict) and 'results' in response.data:
                # Paginado
                company_count = len(response.data['results'])
                response.data["token_info"] = {
                    "type": "user_token",
                    "user": request.user.username,
                    "total_companies": company_count,
                    "message": "Using user token with assigned companies"
                }
            else:
                # No paginado
                response.data = {
                    "results": response.data,
                    "token_info": {
                        "type": "user_token",
                        "user": request.user.username,
                        "total_companies": company_count,
                        "message": "Using user token with assigned companies"
                    }
                }
        
        return response
    
    def create(self, request, *args, **kwargs):
        """
        Crear empresa - Solo permitido para tokens de usuario con permisos admin
        """
        if isinstance(request.user, VirtualCompanyUser):
            return Response({
                "error": "OPERATION_NOT_ALLOWED",
                "message": "Company tokens cannot create new companies",
                "token_type": "company_token"
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Solo usuarios con permisos especiales pueden crear empresas
        if not request.user.is_staff and not request.user.is_superuser:
            return Response({
                "error": "INSUFFICIENT_PERMISSIONS",
                "message": "Only admin users can create companies",
                "token_type": "user_token"
            }, status=status.HTTP_403_FORBIDDEN)
        
        return super().create(request, *args, **kwargs)
    
    def update(self, request, *args, **kwargs):
        """
        Actualizar empresa - Restringido según tipo de token
        """
        company_id = kwargs.get("pk")
        
        try:
            company_id = int(company_id)
        except (ValueError, TypeError):
            return Response({"error": "Invalid company ID"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Token de empresa: solo puede actualizar su propia empresa
        if isinstance(request.user, VirtualCompanyUser):
            if company_id != request.user.company.id:
                return Response({
                    "error": "COMPANY_TOKEN_BLOCK",
                    "message": "Can only update own company",
                    "token_company_id": request.user.company.id,
                    "requested_company_id": company_id
                }, status=status.HTTP_403_FORBIDDEN)
        
        # Token de usuario: verificar acceso normal
        else:
            from apps.api.user_company_helper import get_user_companies_exact
            user_companies = get_user_companies_exact(request.user)
            user_company_ids = [c.id for c in user_companies]
            
            if company_id not in user_company_ids:
                return Response({
                    "error": "USER_TOKEN_BLOCK",
                    "message": "No access to this company",
                    "allowed_company_ids": user_company_ids
                }, status=status.HTTP_403_FORBIDDEN)
        
        return super().update(request, *args, **kwargs)
    
    
    @action(detail=True, methods=['post'])
    def update_master_config(self, request, pk=None):
        """Actualización completa de configuración de empresa (Matriz)"""
        company = self.get_object()
        
        # ✅ SINCRONIZACIÓN PRIORITARIA CON LA FIRMA
        from apps.certificates.models import DigitalCertificate
        active_cert = DigitalCertificate.objects.filter(company=company, status='ACTIVE').first()
        if active_cert and active_cert.extracted_ruc:
            if company.ruc != active_cert.extracted_ruc:
                company.ruc = active_cert.extracted_ruc
                if active_cert.extracted_name and not request.data.get('business_name'):
                    company.business_name = active_cert.extracted_name
                company.save()
        
        # Usar el serializador para validar y actualizar campos de texto
        serializer = self.get_serializer(company, data=request.data, partial=True)
        
        if serializer.is_valid():
            # Manejo especial para el logo si se envió
            if 'logo' in request.FILES:
                company.logo = request.FILES['logo']
            
            serializer.save()
            
            return Response({
                'status': 'success',
                'message': 'Configuración maestra actualizada correctamente',
                'data': serializer.data
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def sync_from_certificate(self, request, pk=None):
        """Forzar sincronización de datos de la empresa desde la firma activa"""
        company = self.get_object()
        from apps.certificates.models import DigitalCertificate
        active_cert = DigitalCertificate.objects.filter(company=company, status='ACTIVE').first()
        
        if not active_cert:
            return Response({'error': 'No hay una firma activa para sincronizar'}, status=400)
            
        company.ruc = active_cert.extracted_ruc
        if active_cert.extracted_name:
            company.business_name = active_cert.extracted_name
        
        company.save()
        return Response({'status': 'success', 'ruc': company.ruc})

    def destroy(self, request, *args, **kwargs):
        """
        Eliminar empresa - No permitido para tokens de empresa
        """
        if isinstance(request.user, VirtualCompanyUser):
            return Response({
                "error": "OPERATION_NOT_ALLOWED",
                "message": "Company tokens cannot delete companies",
                "token_type": "company_token"
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Solo superusuarios pueden eliminar empresas
        if not request.user.is_superuser:
            return Response({
                "error": "INSUFFICIENT_PERMISSIONS",
                "message": "Only superusers can delete companies"
            }, status=status.HTTP_403_FORBIDDEN)
        
        return super().destroy(request, *args, **kwargs)