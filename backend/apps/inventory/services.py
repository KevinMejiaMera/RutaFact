# -*- coding: utf-8 -*-
from decimal import Decimal
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from apps.inventory.models import PurchaseInvoice, PurchaseItem, ProductStock, StockMovement
from apps.invoicing.models import ProductTemplate

class InventoryService:
    @staticmethod
    @transaction.atomic
    def process_purchase(company, provider, invoice_data, items_data, user):
        """
        Procesa una factura de compra y actualiza el inventario de forma sincronizada.
        
        items_data: Lista de diccionarios con:
            - product_name (opcional si hay product_id)
            - product_id (opcional si es nuevo)
            - quantity
            - cost_inclusive (precio con IVA)
            - tax_rate
            - image (opcional)
        """
        print(f"📦 [InventoryService] Processing purchase: {invoice_data.get('invoice_number')} for provider {provider.name}")
        
        purchase = PurchaseInvoice.objects.create(
            company=company,
            provider=provider,
            invoice_number=invoice_data.get('invoice_number'),
            issue_date=invoice_data.get('issue_date'),
            notes=invoice_data.get('notes', ''),
            total_amount=0,
            created_by=user
        )

        total_purchase = Decimal('0')
        print(f"✅ [InventoryService] Purchase record created. ID: {purchase.id}")
        
        for i, item in enumerate(items_data):
            name = item.get('product_name', '').strip()
            product_id = item.get('product_id')
            qty = Decimal(str(item.get('quantity', 0)))
            cost_inclusive = Decimal(str(item.get('cost_inclusive', 0)))
            # El usuario ahora puede enviar un unit_price (venta) sugerido
            selling_price = Decimal(str(item.get('unit_price', cost_inclusive)))
            tax_rate = Decimal(str(item.get('tax_rate', 15.00)))
            image = item.get('image')

            print(f"🔹 [Item {i}] Name: {name}, Qty: {qty}, Cost: {cost_inclusive}, Sale: {selling_price}")

            if product_id:
                print(f"  - Using existing product_id: {product_id}")
                product = get_object_or_404(ProductTemplate, id=product_id, company=company)
            elif name:
                # Buscar por nombre exacto (case insensitive)
                product = ProductTemplate.objects.filter(company=company, name__iexact=name).first()
                if not product:
                    print(f"  - Product '{name}' not found. Creating new...")
                    # Generar un código principal si no existe
                    import time
                    main_code = f"P-{int(time.time())}-{i}"
                    
                    product = ProductTemplate.objects.create(
                        company=company,
                        name=name,
                        main_code=main_code,
                        description=name,
                        purchase_price=cost_inclusive,
                        unit_price=selling_price,
                        tax_rate=tax_rate,
                        tax_code='2',
                        track_inventory=True,
                        created_by=user
                    )
                    print(f"  - New product created: {product.id} (Code: {main_code})")
                else:
                    print(f"  - Existing product found by name: {product.id}")
            else:
                print(f"  - Skipping empty item at index {i}")
                continue

            # Actualizar datos del producto
            product.purchase_price = cost_inclusive
            # Si el usuario envió un precio de venta diferente al de compra, lo actualizamos
            if selling_price > cost_inclusive:
                product.unit_price = selling_price
            
            product.tax_rate = tax_rate
            if image:
                print(f"  - Saving product image for item {i}")
                product.image = image
            
            # Sincronizar stock en el template (redundancia)
            product.current_stock += qty
            product.save()

            # Calcular subtotal
            subtotal = qty * cost_inclusive
            total_purchase += subtotal

            # Crear item de compra
            PurchaseItem.objects.create(
                purchase_invoice=purchase,
                product=product,
                quantity=qty,
                cost_price=cost_inclusive,
                subtotal=subtotal,
                created_by=user
            )

            # Actualizar stock físico
            stock, created = ProductStock.objects.get_or_create(
                company=company,
                product=product,
                defaults={'quantity': 0}
            )
            
            prev_stock = stock.quantity
            stock.quantity += qty
            stock.last_purchase_price = cost_inclusive
            stock.save()
            print(f"  - Stock updated: {prev_stock} -> {stock.quantity}")

            # Registrar movimiento
            StockMovement.objects.create(
                company=company,
                product=product,
                movement_type='IN',
                quantity=qty,
                previous_stock=prev_stock,
                new_stock=stock.quantity,
                reference=purchase.invoice_number,
                notes=f"Compra a {provider.name}",
                created_by=user
            )

        purchase.total_amount = total_purchase
        purchase.is_processed = True
        purchase.save()
        print(f"🏁 [InventoryService] Purchase processing complete. Total: {purchase.total_amount}")
        
        return purchase

    @staticmethod
    @transaction.atomic
    def register_movement(company, product, movement_type, quantity, reference='', notes='', user=None):
        """
        Registra un movimiento de stock manual o automático.
        movement_type: 'IN' o 'OUT'
        """
        from apps.inventory.models import ProductStock, StockMovement
        from decimal import Decimal, ROUND_HALF_UP
        
        quantity = Decimal(str(quantity)).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)
        
        stock, created = ProductStock.objects.get_or_create(
            company=company,
            product=product,
            defaults={'quantity': Decimal('0')}
        )
        
        prev_stock = stock.quantity
        if movement_type == 'IN':
            stock.quantity += quantity
        else:
            stock.quantity -= quantity
            
        stock.save()
        
        # También actualizar el current_stock en el template (redundancia para búsqueda rápida)
        product.current_stock = stock.quantity
        product.save()

        StockMovement.objects.create(
            company=company,
            product=product,
            movement_type=movement_type,
            quantity=quantity,
            previous_stock=prev_stock,
            new_stock=stock.quantity,
            reference=reference,
            notes=notes,
            created_by=user
        )
        return stock
