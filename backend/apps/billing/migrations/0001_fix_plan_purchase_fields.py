# -*- coding: utf-8 -*-
"""
Migración para corregir campos plan_* en PlanPurchase
apps/billing/migrations/0001_fix_plan_purchase_fields.py
"""

from django.db import migrations


def populate_plan_fields(apps, schema_editor):
    """
    Poblar campos plan_name, plan_invoice_limit, plan_price para registros existentes
    """
    PlanPurchase = apps.get_model('billing', 'PlanPurchase')
    
    for purchase in PlanPurchase.objects.filter(
        plan__isnull=False
    ).select_related('plan'):
        if not purchase.plan_name or not purchase.plan_invoice_limit or not purchase.plan_price:
            purchase.plan_name = purchase.plan.name
            purchase.plan_invoice_limit = purchase.plan.invoice_limit
            purchase.plan_price = purchase.plan.price
            purchase.save(update_fields=['plan_name', 'plan_invoice_limit', 'plan_price'])


def reverse_populate_plan_fields(apps, schema_editor):
    """
    Función reversa - no hace nada porque no queremos borrar datos
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),  # Ajusta esto al nombre de tu migración anterior
    ]

    operations = [
        migrations.RunPython(
            populate_plan_fields,
            reverse_populate_plan_fields,
        ),
    ]