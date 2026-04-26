import os
import sys
import django
from decimal import Decimal

# Configurar entorno Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rutafact.settings')
django.setup()

from apps.invoicing.models import ProductTemplate
from apps.inventory.models import ProductStock

def fix_all_data():
    print("--- INICIANDO CORRECCIÓN DE DATOS ---")
    
    # 1. Actualizar IVA a 15% para todos los productos que están en 12%
    products_to_update = ProductTemplate.objects.filter(tax_rate=Decimal('12.00'))
    count = products_to_update.count()
    print(f"Actualizando {count} productos de 12% a 15% IVA...")
    products_to_update.update(tax_rate=Decimal('15.00'))
    
    # 2. Sincronizar Stock (ProductTemplate.current_stock <-> ProductStock.quantity)
    print("Sincronizando stocks...")
    all_products = ProductTemplate.objects.all()
    for prod in all_products:
        stock = ProductStock.objects.filter(product=prod).first()
        if stock:
            if prod.current_stock != stock.quantity:
                print(f"Sync stock for {prod.name}: Template={prod.current_stock} -> Stock={stock.quantity}")
                # Preferimos el valor de ProductStock ya que es el que se usa en el panel de inventario
                prod.current_stock = stock.quantity
                prod.save()
        else:
            # Si no hay ProductStock, crearlo con el stock actual del template
            if prod.current_stock > 0:
                print(f"Creating missing ProductStock for {prod.name} with qty {prod.current_stock}")
                ProductStock.objects.create(
                    company=prod.company,
                    product=prod,
                    quantity=prod.current_stock
                )

    print("--- CORRECCIÓN COMPLETADA ---")

if __name__ == "__main__":
    fix_all_data()
