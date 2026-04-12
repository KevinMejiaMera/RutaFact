# -*- coding: utf-8 -*-
# Generated for storage_path field
# apps/certificates/migrations/0002_add_storage_path.py

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('certificates', '0001_initial'),  # Ajusta según tu migración anterior
    ]

    operations = [
        migrations.AddField(
            model_name='digitalcertificate',
            name='storage_path',
            field=models.CharField(
                blank=True,
                help_text='Path to certificate file in storage/certificates/ directory',
                max_length=500,
                null=True,
                verbose_name='storage path'
            ),
        ),
    ]