import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rutafact.settings')
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()

print(f"Total users: {User.objects.count()}")
for user in User.objects.all():
    print(f"User: {user.email} | Active: {user.is_active} | Status: {user.user_status} | Role: {user.role}")
