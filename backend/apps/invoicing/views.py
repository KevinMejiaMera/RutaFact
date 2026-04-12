# -*- coding: utf-8 -*-
"""
Views for invoicing app
"""

from rest_framework import permissions, viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import (
    Customer, ProductCategory, ProductTemplate,
    InvoiceTemplate, TemplateProduct, PaymentMethod
)
from .serializers import (
    CustomerSerializer, ProductCategorySerializer, ProductTemplateSerializer,
    InvoiceTemplateSerializer, TemplateProductSerializer, PaymentMethodSerializer
)

class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['company', 'identification_type']
    search_fields = ['name', 'identification', 'email']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

class ProductCategoryViewSet(viewsets.ModelViewSet):
    queryset = ProductCategory.objects.all()
    serializer_class = ProductCategorySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['company', 'parent']
    search_fields = ['name', 'description']

class ProductTemplateViewSet(viewsets.ModelViewSet):
    queryset = ProductTemplate.objects.all()
    serializer_class = ProductTemplateSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['company', 'category', 'product_type', 'track_inventory']
    search_fields = ['name', 'main_code', 'description']
    ordering_fields = ['name', 'unit_price', 'created_at']
    
    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        """Productos con stock bajo"""
        low_stock_products = [p for p in self.get_queryset() if p.is_low_stock]
        serializer = self.get_serializer(low_stock_products, many=True)
        return Response(serializer.data)

class InvoiceTemplateViewSet(viewsets.ModelViewSet):
    queryset = InvoiceTemplate.objects.all()
    serializer_class = InvoiceTemplateSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['company']
    search_fields = ['name', 'description']

class PaymentMethodViewSet(viewsets.ModelViewSet):
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['company']
    search_fields = ['name', 'code']