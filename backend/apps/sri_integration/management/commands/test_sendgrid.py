from django.core.management.base import BaseCommand
from apps.sri_integration.services.sendgrid_service import SendGridService


class Command(BaseCommand):
    help = 'Prueba el envío de emails con SendGrid'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--to',
            type=str,
            default='test@example.com',
            help='Email destinatario'
        )
    
    def handle(self, *args, **options):
        service = SendGridService()
        
        if not service.sg:
            self.stdout.write(
                self.style.ERROR('SendGrid no configurado. Verifica SENDGRID_API_KEY')
            )
            return
            
        success = service.send_invoice(
            to_email=options['to'],
            invoice_number='001-001-000000001',
            invoice_data={
                'cliente': 'Cliente de Prueba',
                'fecha': '2025-09-16',
                'total': '100.00'
            }
        )
        
        if success:
            self.stdout.write(
                self.style.SUCCESS(f'Email enviado a {options["to"]}')
            )
        else:
            self.stdout.write(
                self.style.ERROR('Error enviando email')
            )