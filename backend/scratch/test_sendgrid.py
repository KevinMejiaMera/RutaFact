import os
import django
import sys

# Configurar Django
sys.path.append('/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rutafact.settings')
django.setup()

from apps.sri_integration.services.sendgrid_service import SendGridService
from apps.companies.models import Company

def test_sendgrid():
    print("🚀 Iniciando prueba de SendGrid...")
    
    # 1. Obtener la primera empresa
    company = Company.objects.first()
    if not company:
        print("❌ No se encontró ninguna empresa en la base de datos.")
        return

    print(f"🏢 Usando empresa: {company.business_name}")
    
    # 2. Inicializar servicio
    service = SendGridService()
    print(f"🔑 API Key detectada: {'SÍ' if service.api_key else 'NO'}")
    print(f"📧 Remitente configurado: {service.from_email}")
    print(f"👤 Nombre configurado: {service.from_name}")
    
    # 3. Intentar envío simple
    recipient = "wandreszv@rutafact.ec"
    subject_num = "TEST-001"
    
    print(f"✉️ Enviando correo de prueba a {recipient}...")
    success = service.send_invoice(
        to_email=recipient, 
        invoice_number=subject_num,
        cliente_nombre="Andrés Zabala"
    )
    
    if success:
        print(f"✅ ¡ÉXITO! Correo enviado satisfactoriamente.")
    else:
        print(f"❌ FALLÓ el envío. Error: {message}")

if __name__ == "__main__":
    test_sendgrid()

