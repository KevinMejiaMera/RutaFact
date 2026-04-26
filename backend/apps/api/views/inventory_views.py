# -*- coding: utf-8 -*-
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from decimal import Decimal

from apps.inventory.models import Provider, PurchaseInvoice, PurchaseItem, ProductStock, StockMovement
from apps.inventory.services import InventoryService
from apps.invoicing.models import ProductTemplate
from apps.companies.models import Company

class ProviderViewSet(viewsets.ViewSet):
    """API para proveedores"""
    permission_classes = [IsAuthenticated]

    def list(self, request):
        company_id = request.query_params.get('company_id')
        if not company_id:
            return Response({'error': 'company_id is required'}, status=400)
        
        providers = Provider.objects.filter(company_id=company_id, is_active=True).order_by('name')
        data = []
        for p in providers:
            data.append({
                'id': p.id,
                'name': p.name,
                'identification': p.identification,
                'identification_type': p.identification_type,
                'email': p.email,
                'phone': p.phone,
                'address': p.address,
                'regime': p.regime,
                'provider_code': p.provider_code,
                'authorization_number': p.authorization_number,
                'expiration_date': p.expiration_date,
            })
        return Response(data)

    def create(self, request):
        data = request.data
        company_id = data.get('company_id')
        if not company_id:
            return Response({'error': 'company_id is required'}, status=400)
        
        company = get_object_or_404(Company, id=company_id)
        
        provider = Provider.objects.create(
            company=company,
            name=data.get('name'),
            identification=data.get('identification'),
            identification_type=data.get('identification_type', '04'),
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            address=data.get('address', ''),
            regime=data.get('regime', 'GENERAL'),
            provider_code=data.get('provider_code', ''),
            authorization_number=data.get('authorization_number', ''),
            start_sequence=data.get('start_sequence'),
            end_sequence=data.get('end_sequence'),
            expiration_date=data.get('expiration_date'),
            created_by=request.user
        )
        
        return Response({'id': provider.id, 'name': provider.name}, status=201)

    def retrieve(self, request, pk=None):
        provider = get_object_or_404(Provider, pk=pk)
        data = {
            'id': provider.id,
            'name': provider.name,
            'identification': provider.identification,
            'identification_type': provider.identification_type,
            'email': provider.email,
            'phone': provider.phone,
            'address': provider.address,
            'regime': provider.regime,
            'provider_code': provider.provider_code,
            'authorization_number': provider.authorization_number,
            'start_sequence': provider.start_sequence,
            'end_sequence': provider.end_sequence,
            'expiration_date': provider.expiration_date,
        }
        return Response(data)

class PurchaseViewSet(viewsets.ViewSet):
    """API para facturas de compra (Despachador)"""
    permission_classes = [IsAuthenticated]

    def list(self, request):
        company_id = request.query_params.get('company_id')
        if not company_id:
            return Response({'error': 'company_id is required'}, status=400)
        
        purchases = PurchaseInvoice.objects.filter(company_id=company_id).select_related('provider').order_by('-issue_date')
        data = []
        for p in purchases:
            data.append({
                'id': p.id,
                'invoice_number': p.invoice_number,
                'issue_date': p.issue_date,
                'provider_name': p.provider.name,
                'total_amount': str(p.total_amount),
                'is_processed': p.is_processed,
            })
        return Response(data)

    def create(self, request):
        data = request.data
        company_id = data.get('company_id')
        provider_id = data.get('provider_id')
        items = data.get('items', []) 

        if not company_id or not provider_id or not items:
            return Response({'error': 'company_id, provider_id and items are required'}, status=400)

        company = get_object_or_404(Company, id=company_id)
        provider = get_object_or_404(Provider, id=provider_id, company=company)

        try:
            with transaction.atomic():
                # Adaptar items del API al formato del servicio
                processed_items = []
                for item in items:
                    p_item = {
                        'quantity': item.get('quantity', 0),
                        'cost_inclusive': item.get('cost', 0),
                        'tax_rate': 15.00 # Default para API
                    }
                    
                    if item.get('is_new'):
                        product_data = item.get('new_product_data', {})
                        p_item['product_name'] = product_data.get('name')
                    else:
                        p_item['product_id'] = item.get('product_id')
                    
                    processed_items.append(p_item)

                invoice_data = {
                    'invoice_number': data.get('invoice_number'),
                    'issue_date': data.get('issue_date'),
                    'notes': data.get('notes', '')
                }
                
                purchase = InventoryService.process_purchase(
                    company, provider, invoice_data, processed_items, request.user
                )

            return Response({'id': purchase.id, 'total': str(purchase.total_amount)}, status=201)
        except Exception as e:
            return Response({'error': str(e)}, status=400)

    def retrieve(self, request, pk=None):
        purchase = get_object_or_404(PurchaseInvoice.objects.select_related('provider'), pk=pk)
        items = PurchaseItem.objects.filter(purchase_invoice=purchase).select_related('product')
        
        items_data = []
        for item in items:
            items_data.append({
                'id': item.id,
                'product_name': item.product.name,
                'product_image': item.product.image.url if item.product.image else None,
                'quantity': str(item.quantity),
                'cost': str(item.cost_price),
                'subtotal': str(item.subtotal),
            })
            
        data = {
            'id': purchase.id,
            'invoice_number': purchase.invoice_number,
            'issue_date': purchase.issue_date,
            'provider_name': purchase.provider.name,
            'provider_ruc': purchase.provider.identification,
            'notes': purchase.notes,
            'total_amount': str(purchase.total_amount),
            'is_processed': purchase.is_processed,
            'items': items_data
        }
        return Response(data)

class MovementViewSet(viewsets.ViewSet):
    """API para historial de movimientos de bodega"""
    permission_classes = [IsAuthenticated]

    def list(self, request):
        company_id = request.query_params.get('company_id')
        if not company_id:
            return Response({'error': 'company_id is required'}, status=400)
        
        movements = StockMovement.objects.filter(company_id=company_id).select_related('product', 'created_by').order_by('-created_at')
        data = []
        for m in movements:
            data.append({
                'id': m.id,
                'product_name': m.product.name,
                'movement_type': m.movement_type,
                'quantity': str(m.quantity),
                'previous_stock': str(m.previous_stock),
                'new_stock': str(m.new_stock),
                'reference': m.reference,
                'notes': m.notes,
                'created_at': m.created_at,
                'user': m.created_by.get_full_name() if m.created_by else 'Sistema',
            })
        return Response(data)

class StockViewSet(viewsets.ViewSet):
    """API para consultar stock actual"""
    permission_classes = [IsAuthenticated]

    def list(self, request):
        company_id = request.query_params.get('company_id')
        if not company_id:
            return Response({'error': 'company_id is required'}, status=400)
        
        stocks = ProductStock.objects.filter(company_id=company_id).select_related('product').order_by('product__name')
        data = []
        for s in stocks:
            data.append({
                'id': s.id,
                'product_id': s.product.id,
                'product_name': s.product.name,
                'sku': s.product.main_code,
                'quantity': str(s.quantity),
                'last_cost': str(s.last_purchase_price),
                'price': str(s.product.unit_price),
                'image': s.product.image.url if s.product.image else None,
            })
        return Response(data)

    def retrieve(self, request, pk=None):
        stock = get_object_or_404(ProductStock.objects.select_related('product'), pk=pk)
        movements = StockMovement.objects.filter(product=stock.product).order_by('-created_at')[:5]
        movements_data = []
        for m in movements:
            movements_data.append({
                'type': m.movement_type,
                'qty': str(m.quantity),
                'date': m.created_at,
                'ref': m.reference
            })

        data = {
            'id': stock.id,
            'product_id': stock.product.id,
            'product_name': stock.product.name,
            'product_image': stock.product.image.url if stock.product.image else None,
            'sku': stock.product.main_code,
            'description': stock.product.description,
            'quantity': str(stock.quantity),
            'unit': stock.product.unit_of_measure,
            'last_cost': str(stock.last_purchase_price),
            'price': str(stock.product.unit_price),
            'recent_movements': movements_data
        }
        return Response(data)
