# -*- coding: utf-8 -*-
"""
Comando para sincronizar certificados a storage
"""

from django.core.management.base import BaseCommand
from apps.certificates.signals import sync_all_certificates_to_storage, verify_storage_integrity


class Command(BaseCommand):
    help = 'Sincroniza certificados existentes a storage/certificates/'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--verify-only',
            action='store_true',
            help='Solo verificar integridad sin copiar archivos',
        )
        
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forzar copia incluso si el archivo ya existe',
        )
    
    def handle(self, *args, **options):
        if options['verify_only']:
            self.stdout.write("🔍 Verificando integridad de certificados...")
            report = verify_storage_integrity()
            
            self.stdout.write(f"📊 Total de certificados: {report['total_certificates']}")
            self.stdout.write(f"✅ En ambos locations: {len(report['in_both'])}")
            self.stdout.write(f"📄 Solo en media: {len(report['in_media_only'])}")
            self.stdout.write(f"💾 Solo en storage: {len(report['in_storage_only'])}")
            self.stdout.write(f"❌ Faltantes completamente: {len(report['missing_completely'])}")
        else:
            self.stdout.write("🔄 Sincronizando certificados a storage...")
            report = sync_all_certificates_to_storage()
            
            self.stdout.write(f"📊 Total procesados: {report['total_processed']}")
            self.stdout.write(f"✅ Copiados exitosamente: {report['successful_copies']}")
            self.stdout.write(f"❌ Fallos: {report['failed_copies']}")
            self.stdout.write(f"💾 Ya en storage: {report['already_in_storage']}")
            
            if report.get('errors'):
                self.stdout.write("🚨 Errores encontrados:")
                for error in report['errors']:
                    self.stdout.write(f"  - {error}")
        
        self.stdout.write(self.style.SUCCESS("✅ Operación completada"))
