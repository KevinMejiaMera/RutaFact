import os
import django
import sys

sys.path.append('/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rutafact.settings')
django.setup()

from apps.inventory.models import PurchaseItem, StockMovement, ProductStock

def backfill_movements():
    items = PurchaseItem.objects.all().select_related('purchase_invoice', 'product')
    count = 0
    for item in items:
        # Verificar si ya existe el movimiento para esta factura y producto
        exists = StockMovement.objects.filter(
            product=item.product,
            reference=item.purchase_invoice.invoice_number,
            movement_type='IN'
        ).exists()
        
        if not exists:
            # Obtener el stock que había antes (estimado)
            stock_record = ProductStock.objects.filter(product=item.product, company=item.purchase_invoice.company).first()
            current_qty = stock_record.quantity if stock_record else 0
            
            StockMovement.objects.create(
                company=item.purchase_invoice.company,
                product=item.product,
                movement_type='IN',
                quantity=item.quantity,
                previous_stock=current_qty - item.quantity, # Estimación simple
                new_stock=current_qty,
                reference=item.purchase_invoice.invoice_number,
                notes=f"Migración: Compra previa {item.purchase_invoice.invoice_number}",
                created_at=item.created_at
            )
            count += 1
    print(f"✅ Se han migrado {count} movimientos al historial.")

if __name__ == '__main__':
    backfill_movements()
