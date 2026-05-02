import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rutafact.settings')
django.setup()

from apps.sri_integration.models import ElectronicDocument, CreditNote
from apps.companies.models import Company

# Get the first company for testing
company = Company.objects.first()
print(f"Company: {company.name}")

voided = ElectronicDocument.objects.filter(company=company, status='VOIDED')
print(f"Voided Invoices: {voided.count()}")
for inv in voided:
    print(f"  - {inv.document_number} (ID: {inv.id})")

cns = CreditNote.objects.filter(company=company)
print(f"Credit Notes: {cns.count()}")
for cn in cns:
    print(f"  - CN for {cn.original_document.document_number} - Status: {cn.status}")
