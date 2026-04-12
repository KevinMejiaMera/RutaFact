# apps/sri_integration/management/commands/check_sri_documents.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.sri_integration.models import ElectronicDocument
from apps.companies.models import Company
from decimal import Decimal
import random

class Command(BaseCommand):
    help = 'Verifica y crea documentos SRI de prueba si no existen'

    def handle(self, *args, **options):
        self.stdout.write("=== VERIFICANDO DOCUMENTOS SRI ===")
        
        # 1. Verificar cuántos documentos existen
        total_docs = ElectronicDocument.objects.count()
        self.stdout.write(f"Total de documentos en BD: {total_docs}")
        
        # 2. Verificar empresas
        companies = Company.objects.filter(is_active=True)
        self.stdout.write(f"Empresas activas: {companies.count()}")
        
        if companies.count() == 0:
            self.stdout.write(self.style.ERROR("No hay empresas activas. Creando una empresa de prueba..."))
            company = Company.objects.create(
                ruc='9999999999001',
                business_name='Empresa de Prueba S.A.',
                trade_name='PRUEBA SA',
                email='prueba@example.com',
                phone='0999999999',
                address='Av. Principal 123',
                city='Quito',
                province='Pichincha',
                is_active=True
            )
            self.stdout.write(self.style.SUCCESS(f"Empresa creada: {company.business_name}"))
        else:
            company = companies.first()
            self.stdout.write(f"Usando empresa: {company.business_name}")
        
        # 3. Si no hay documentos, crear algunos de prueba
        if total_docs == 0:
            self.stdout.write(self.style.WARNING("No hay documentos. Creando documentos de prueba..."))
            
            # Tipos de documentos a crear
            doc_types = [
                ('INVOICE', 'Factura'),
                ('RETENTION', 'Retención'),
                ('CREDIT_NOTE', 'Nota de Crédito'),
                ('DEBIT_NOTE', 'Nota de Débito'),
            ]
            
            estados = ['DRAFT', 'AUTHORIZED', 'REJECTED', 'SENT']
            
            for i in range(20):  # Crear 20 documentos de prueba
                doc_type, doc_name = random.choice(doc_types)
                status = random.choice(estados)
                
                # Generar número de documento
                secuencial = str(i + 1).zfill(9)
                numero = f"001-001-{secuencial}"
                
                # Crear documento
                doc = ElectronicDocument.objects.create(
                    company=company,
                    document_type=doc_type,
                    document_number=numero,
                    status=status,
                    customer_name=f"Cliente {i + 1}",
                    customer_identification=f"{random.randint(1000000000, 1999999999)}",
                    customer_email=f"cliente{i+1}@example.com",
                    issue_date=timezone.now().date() - timezone.timedelta(days=random.randint(0, 30)),
                    total_amount=Decimal(str(random.uniform(10, 1000))).quantize(Decimal('0.01')),
                    access_key=f"{random.randint(1000000000000000, 9999999999999999)}" if status == 'AUTHORIZED' else None,
                )
                
                self.stdout.write(f"Creado: {doc_name} {numero} - Estado: {status}")
            
            self.stdout.write(self.style.SUCCESS("✓ 20 documentos de prueba creados"))
        
        # 4. Mostrar resumen
        self.stdout.write("\n=== RESUMEN DE DOCUMENTOS ===")
        for doc_type in ['INVOICE', 'RETENTION', 'CREDIT_NOTE', 'DEBIT_NOTE']:
            count = ElectronicDocument.objects.filter(document_type=doc_type).count()
            self.stdout.write(f"{doc_type}: {count}")
        
        self.stdout.write("\n=== RESUMEN POR ESTADO ===")
        for status in ['DRAFT', 'GENERATED', 'SIGNED', 'SENT', 'AUTHORIZED', 'REJECTED', 'ERROR', 'CANCELLED']:
            count = ElectronicDocument.objects.filter(status=status).count()
            if count > 0:
                self.stdout.write(f"{status}: {count}")
        
        # 5. Verificar campos del modelo
        if ElectronicDocument.objects.exists():
            doc = ElectronicDocument.objects.first()
            self.stdout.write("\n=== CAMPOS DEL MODELO ===")
            for field in doc._meta.fields:
                value = getattr(doc, field.name, 'N/A')
                self.stdout.write(f"{field.name}: {value}")