# -*- coding: utf-8 -*-
"""
Management command para crear datos de prueba
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from apps.companies.models import Company
from apps.sri_integration.models import SRIConfiguration
from apps.invoicing.models import Customer, ProductCategory, ProductTemplate, PaymentMethod
from apps.notifications.models import NotificationTemplate
from apps.settings.models import SystemSetting

User = get_user_model()


class Command(BaseCommand):
    help = 'Crea datos de prueba para el sistema'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Limpia datos existentes antes de crear nuevos',
        )
    
    def handle(self, *args, **options):
        if options['clean']:
            self.stdout.write('Limpiando datos existentes...')
            self.clean_data()
        
        with transaction.atomic():
            self.stdout.write('Creando datos de prueba...')
            
            # Crear usuarios
            users = self.create_users()
            
            # Crear empresas
            companies = self.create_companies(users)
            
            # Crear configuraciones SRI
            self.create_sri_configurations(companies)
            
            # Crear clientes
            self.create_customers(companies)
            
            # Crear productos
            self.create_products(companies)
            
            # Crear métodos de pago
            self.create_payment_methods(companies)
            
            # Crear plantillas de notificaciones
            self.create_notification_templates()
            
            # Crear configuraciones del sistema
            self.create_system_settings()
        
        self.stdout.write(
            self.style.SUCCESS('Datos de prueba creados exitosamente!')
        )
    
    def clean_data(self):
        """Limpia datos existentes"""
        Company.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()
    
    def create_users(self):
        """Crea usuarios de prueba"""
        users = {}
        
        # Usuario administrador
        admin_user, created = User.objects.get_or_create(
            email='admin@vendosri.com',
            defaults={
                'first_name': 'Admin',
                'last_name': 'Sistema',
                'is_staff': True,
                'is_superuser': True,
                'is_active': True
            }
        )
        if created:
            admin_user.set_password('admin123')
            admin_user.save()
        users['admin'] = admin_user
        
        # Usuario de empresa 1
        user1, created = User.objects.get_or_create(
            email='empresa1@vendosri.com',
            defaults={
                'first_name': 'Juan',
                'last_name': 'Pérez',
                'is_active': True
            }
        )
        if created:
            user1.set_password('empresa123')
            user1.save()
        users['empresa1'] = user1
        
        # Usuario de empresa 2
        user2, created = User.objects.get_or_create(
            email='empresa2@vendosri.com',
            defaults={
                'first_name': 'María',
                'last_name': 'González',
                'is_active': True
            }
        )
        if created:
            user2.set_password('empresa123')
            user2.save()
        users['empresa2'] = user2
        
        self.stdout.write('✓ Usuarios creados')
        return users
    
    def create_companies(self, users):
        """Crea empresas de prueba"""
        companies = {}
        
        # Empresa 1
        company1, created = Company.objects.get_or_create(
            ruc='1791234567001',
            defaults={
                'business_name': 'EMPRESA DE PRUEBA 1 S.A.',
                'trade_name': 'Empresa Prueba 1',
                'email': 'empresa1@vendosri.com',
                'phone': '02-2345678',
                'address': 'Av. Principal 123, Quito, Ecuador',
                'is_active': True
            }
        )
        companies['empresa1'] = company1
        
        # Empresa 2
        company2, created = Company.objects.get_or_create(
            ruc='0992345678001',
            defaults={
                'business_name': 'COMERCIAL PRUEBA 2 CIA. LTDA.',
                'trade_name': 'Comercial Prueba 2',
                'email': 'empresa2@vendosri.com',
                'phone': '04-2345678',
                'address': 'Av. Secundaria 456, Guayaquil, Ecuador',
                'is_active': True
            }
        )
        companies['empresa2'] = company2
        
        self.stdout.write('✓ Empresas creadas')
        return companies
    
    def create_sri_configurations(self, companies):
        """Crea configuraciones SRI"""
        for key, company in companies.items():
            config, created = SRIConfiguration.objects.get_or_create(
                company=company,
                defaults={
                    'environment': 'TEST',
                    'reception_url': 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl',
                    'authorization_url': 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl',
                    'establishment_code': '001',
                    'emission_point': '001',
                    'email_enabled': True,
                    'email_subject_template': 'Documento Electrónico - {document_type} {document_number}',
                    'email_body_template': 'Estimado cliente,\n\nEn archivo adjunto encontrará su {document_type} electrónico número {document_number}.\n\nSaludos cordiales.',
                    'accounting_required': True,
                    'is_active': True
                }
            )
        
        self.stdout.write('✓ Configuraciones SRI creadas')
    
    def create_customers(self, companies):
        """Crea clientes de prueba"""
        for key, company in companies.items():
            # Cliente 1
            Customer.objects.get_or_create(
                company=company,
                identification='1712345678',
                defaults={
                    'identification_type': '05',
                    'name': 'Juan Carlos Pérez López',
                    'email': 'juan.perez@email.com',
                    'phone': '0987654321',
                    'address': 'Calle Principal 123, Quito',
                    'city': 'Quito',
                    'province': 'Pichincha',
                    'default_payment_method': 'Efectivo'
                }
            )
            
            # Cliente 2
            Customer.objects.get_or_create(
                company=company,
                identification='0923456789001',
                defaults={
                    'identification_type': '04',
                    'name': 'EMPRESA CLIENTE S.A.',
                    'email': 'compras@empresacliente.com',
                    'phone': '04-2567890',
                    'address': 'Av. Empresarial 456, Guayaquil',
                    'city': 'Guayaquil',
                    'province': 'Guayas',
                    'default_payment_method': 'Transferencia',
                    'credit_limit': 5000.00
                }
            )
        
        self.stdout.write('✓ Clientes creados')
    
    def create_products(self, companies):
        """Crea productos de prueba"""
        for key, company in companies.items():
            # Crear categorías
            cat_productos, _ = ProductCategory.objects.get_or_create(
                company=company,
                name='Productos',
                defaults={'description': 'Productos físicos'}
            )
            
            cat_servicios, _ = ProductCategory.objects.get_or_create(
                company=company,
                name='Servicios',
                defaults={'description': 'Servicios profesionales'}
            )
            
            # Productos
            ProductTemplate.objects.get_or_create(
                company=company,
                main_code='PROD001',
                defaults={
                    'category': cat_productos,
                    'product_type': 'PRODUCT',
                    'name': 'Producto de Prueba 1',
                    'description': 'Descripción detallada del producto de prueba 1',
                    'unit_of_measure': 'u',
                    'unit_price': 25.50,
                    'tax_rate': 12.00,
                    'track_inventory': True,
                    'current_stock': 100,
                    'minimum_stock': 10
                }
            )
            
            ProductTemplate.objects.get_or_create(
                company=company,
                main_code='SERV001',
                defaults={
                    'category': cat_servicios,
                    'product_type': 'SERVICE',
                    'name': 'Servicio de Consultoría',
                    'description': 'Servicio profesional de consultoría',
                    'unit_of_measure': 'h',
                    'unit_price': 50.00,
                    'tax_rate': 12.00,
                    'track_inventory': False
                }
            )
        
        self.stdout.write('✓ Productos creados')
    
    def create_payment_methods(self, companies):
        """Crea métodos de pago"""
        methods = [
            {'name': 'Efectivo', 'code': 'CASH', 'days': 0},
            {'name': 'Transferencia', 'code': 'TRANSFER', 'days': 0},
            {'name': 'Cheque', 'code': 'CHECK', 'days': 30},
            {'name': 'Crédito 30 días', 'code': 'CREDIT30', 'days': 30},
        ]
        
        for key, company in companies.items():
            for method in methods:
                PaymentMethod.objects.get_or_create(
                    company=company,
                    code=method['code'],
                    defaults={
                        'name': method['name'],
                        'default_days_to_pay': method['days']
                    }
                )
        
        self.stdout.write('✓ Métodos de pago creados')
    
    def create_notification_templates(self):
        """Crea plantillas de notificaciones"""
        templates = [
            {
                'type': 'DOCUMENT_AUTHORIZED',
                'name': 'Documento Autorizado',
                'email_subject': 'Documento {document_number} autorizado por el SRI',
                'email_template': 'Su documento {document_number} ha sido autorizado exitosamente.',
                'browser_title': 'Documento Autorizado',
                'browser_message': 'El documento {document_number} fue autorizado.'
            },
            {
                'type': 'CERTIFICATE_EXPIRING',
                'name': 'Certificado por Expirar',
                'email_subject': 'Su certificado digital expira pronto',
                'email_template': 'Su certificado digital expira en {days} días.',
                'browser_title': 'Certificado por Expirar',
                'browser_message': 'Su certificado expira en {days} días.'
            }
        ]
        
        for template_data in templates:
            NotificationTemplate.objects.get_or_create(
                notification_type=template_data['type'],
                defaults={
                    'name': template_data['name'],
                    'email_subject': template_data['email_subject'],
                    'email_template': template_data['email_template'],
                    'browser_title': template_data['browser_title'],
                    'browser_message': template_data['browser_message']
                }
            )
        
        self.stdout.write('✓ Plantillas de notificaciones creadas')
    
    def create_system_settings(self):
        """Crea configuraciones del sistema"""
        settings = [
            {
                'key': 'SYSTEM_NAME',
                'value': 'Factu Express',
                'category': 'SYSTEM',
                'name': 'Nombre del Sistema',
                'description': 'Nombre que aparece en el sistema'
            },
            {
                'key': 'MAX_UPLOAD_SIZE',
                'value': '5242880',
                'category': 'SYSTEM',
                'setting_type': 'INTEGER',
                'name': 'Tamaño Máximo de Archivo',
                'description': 'Tamaño máximo para subir archivos (bytes)'
            },
            {
                'key': 'EMAIL_FROM',
                'value': 'noreply@vendosri.com',
                'category': 'EMAIL',
                'setting_type': 'EMAIL',
                'name': 'Email Remitente',
                'description': 'Email usado como remitente del sistema'
            }
        ]
        
        for setting_data in settings:
            SystemSetting.objects.get_or_create(
                key=setting_data['key'],
                defaults=setting_data
            )
        
        self.stdout.write('✓ Configuraciones del sistema creadas')
