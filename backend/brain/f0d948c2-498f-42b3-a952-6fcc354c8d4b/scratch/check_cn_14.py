import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rutafact.settings')
django.setup()

from apps.sri_integration.models import CreditNote

cn = CreditNote.objects.get(id=14)
print(f"Credit Note: {cn.document_number}")
print(f"Status: {cn.status}")
print(f"Reason: {cn.reason_description}")
print(f"SRI Response: {cn.sri_response}")

# Check items and taxes
print("\nItems:")
for item in cn.items.all():
    print(f"  - {item.description}: Qty {item.quantity}, Price {item.unit_price}, Subtotal {item.subtotal}")
    for tax in item.taxes.all():
        print(f"    * Tax: Code {tax.tax_code}, Rate {tax.rate}, Base {tax.taxable_base}, Amount {tax.tax_amount}")

print("\nDocument Taxes:")
for tax in cn.taxes.filter(item__isnull=True):
    print(f"  - Tax: Code {tax.tax_code}, Rate {tax.rate}, Base {tax.taxable_base}, Amount {tax.tax_amount}")

print(f"\nTotals: Subtotal {cn.subtotal_without_tax}, Tax {cn.total_tax}, Total {cn.total_amount}")
