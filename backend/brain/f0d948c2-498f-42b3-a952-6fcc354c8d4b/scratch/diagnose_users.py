import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rutafact.settings')
django.setup()

from apps.users.models import User, UserCompanyAssignment
from apps.companies.models import Company

print("--- DIAGNÓSTICO DE USUARIOS ---")
print(f"Total Usuarios: {User.objects.count()}")
print(f"Total Empresas: {Company.objects.count()}")

for user in User.objects.all():
    print(f"\nUsuario: {user.email}")
    print(f" - Company Directa: {user.company.business_name if user.company else 'Ninguna'}")
    print(f" - Is Staff: {user.is_staff}, Is Superuser: {user.is_superuser}")
    
    try:
        assignment = UserCompanyAssignment.objects.get(user=user)
        assigned_cos = [c.business_name for c in assignment.assigned_companies.all()]
        print(f" - Asignaciones Nucleares: {assigned_cos if assigned_cos else 'Ninguna'}")
        print(f" - Estado Asignación: {assignment.status}")
    except UserCompanyAssignment.DoesNotExist:
        print(f" - Asignaciones Nucleares: Sin registro de asignación")

print("\n--- EMPRESA MATRIZ ---")
# Ver cuál es la empresa que el código está detectando como "first()"
from apps.core.views import get_user_companies_secure
# Simulamos un request mock o simplemente usamos un usuario admin
admin_user = User.objects.filter(is_superuser=True).first()
if admin_user:
    cos = get_user_companies_secure(admin_user)
    print(f"Admin detectado: {admin_user.email}")
    print(f"Empresas accesibles para admin: {[c.business_name for c in cos]}")
    if cos.exists():
        print(f"Matriz detectada: {cos.first().business_name} (ID: {cos.first().id})")
