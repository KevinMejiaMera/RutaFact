# -*- coding: utf-8 -*-
"""
Formularios para sistema de planes y facturación
apps/billing/forms.py
"""

from django import forms
from django.core.exceptions import ValidationError
import magic
from .models import PlanPurchase


class PlanPurchaseForm(forms.ModelForm):
    """
    Formulario para compra de planes
    """
    
    class Meta:
        model = PlanPurchase
        fields = [
            'payment_method',
            'payer_name', 
            'payer_document',
            'payment_amount',
            'payment_date',
            'payment_reference',
            'bank_name',
            'payment_receipt',
            'customer_notes'
        ]
        
        widgets = {
            'payment_method': forms.Select(
                attrs={
                    'class': 'form-select',
                    'required': True
                }
            ),
            'payer_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Nombre completo del pagador',
                    'required': True
                }
            ),
            'payer_document': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Cédula, RUC o pasaporte',
                    'required': True
                }
            ),
            'payment_amount': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'min': '0',
                    'required': True
                }
            ),
            'payment_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                    'required': True
                }
            ),
            'payment_reference': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Número de transacción o referencia',
                }
            ),
            'bank_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Banco desde donde se realizó el pago',
                }
            ),
            'payment_receipt': forms.FileInput(
                attrs={
                    'class': 'form-control',
                    'accept': '.jpg,.jpeg,.png,.pdf',
                    'required': True
                }
            ),
            'customer_notes': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': 'Observaciones adicionales (opcional)',
                }
            ),
        }
        
        labels = {
            'payment_method': 'Método de Pago',
            'payer_name': 'Nombre del Pagador',
            'payer_document': 'Documento del Pagador',
            'payment_amount': 'Monto Pagado (USD)',
            'payment_date': 'Fecha de Pago',
            'payment_reference': 'Referencia de Transacción',
            'bank_name': 'Banco',
            'payment_receipt': 'Comprobante de Pago',
            'customer_notes': 'Observaciones',
        }
        
        help_texts = {
            'payer_document': 'Ingresa tu cédula, RUC o número de pasaporte',
            'payment_reference': 'Número de transacción o código de referencia del banco',
            'bank_name': 'Nombre del banco desde donde realizaste el pago',
            'payment_receipt': 'Sube una imagen (JPG, PNG) o PDF del comprobante. Máximo 5MB.',
            'customer_notes': 'Cualquier información adicional que consideres importante',
        }
    
    def clean_payment_receipt(self):
        """
        Validar archivo de comprobante de pago
        """
        receipt = self.cleaned_data.get('payment_receipt')
        
        if not receipt:
            raise ValidationError('El comprobante de pago es obligatorio.')
        
        # Validar tamaño (máximo 5MB)
        if receipt.size > 5 * 1024 * 1024:
            raise ValidationError('El archivo no puede ser mayor a 5MB.')
        
        # Validar tipo de archivo usando python-magic
        try:
            # Leer una muestra del archivo para determinar el tipo
            file_sample = receipt.read(1024)
            receipt.seek(0)  # Volver al inicio del archivo
            
            # Determinar tipo MIME
            mime_type = magic.from_buffer(file_sample, mime=True)
            
            allowed_types = [
                'image/jpeg', 
                'image/png', 
                'application/pdf'
            ]
            
            if mime_type not in allowed_types:
                raise ValidationError(
                    'Solo se permiten archivos JPG, PNG o PDF. '
                    f'Tipo detectado: {mime_type}'
                )
                
        except Exception as e:
            # Si falla la detección por magic, validar por extensión
            file_name = receipt.name.lower()
            allowed_extensions = ['.jpg', '.jpeg', '.png', '.pdf']
            
            if not any(file_name.endswith(ext) for ext in allowed_extensions):
                raise ValidationError(
                    'Solo se permiten archivos con extensiones: '
                    'JPG, JPEG, PNG, PDF'
                )
        
        return receipt
    
    def clean_payment_amount(self):
        """
        Validar monto de pago
        """
        amount = self.cleaned_data.get('payment_amount')
        
        if amount is None:
            raise ValidationError('El monto de pago es obligatorio.')
        
        if amount <= 0:
            raise ValidationError('El monto debe ser mayor a 0.')
        
        if amount > 10000:  # Límite máximo razonable
            raise ValidationError('El monto no puede ser mayor a $10,000.')
        
        return amount
    
    def clean_payer_document(self):
        """
        Validar documento del pagador
        """
        document = self.cleaned_data.get('payer_document', '').strip()
        
        if not document:
            raise ValidationError('El documento del pagador es obligatorio.')
        
        # Validación básica de longitud
        if len(document) < 8:
            raise ValidationError('El documento debe tener al menos 8 caracteres.')
        
        if len(document) > 20:
            raise ValidationError('El documento no puede tener más de 20 caracteres.')
        
        # Remover espacios y caracteres especiales para validación
        clean_document = ''.join(c for c in document if c.isalnum())
        
        if len(clean_document) < 8:
            raise ValidationError('El documento debe contener al menos 8 caracteres alfanuméricos.')
        
        return document
    
    def clean_payment_date(self):
        """
        Validar fecha de pago
        """
        from datetime import date, timedelta
        
        payment_date = self.cleaned_data.get('payment_date')
        
        if not payment_date:
            raise ValidationError('La fecha de pago es obligatoria.')
        
        today = date.today()
        
        # No permitir fechas futuras
        if payment_date > today:
            raise ValidationError('La fecha de pago no puede ser futura.')
        
        # No permitir fechas muy antiguas (más de 30 días)
        max_old_date = today - timedelta(days=30)
        if payment_date < max_old_date:
            raise ValidationError(
                'La fecha de pago no puede ser anterior a 30 días. '
                'Si necesitas registrar un pago más antiguo, contacta al administrador.'
            )
        
        return payment_date
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Agregar clases CSS adicionales y configuraciones
        for field_name, field in self.fields.items():
            # Marcar campos obligatorios
            if field.required:
                field.widget.attrs['required'] = True
                
            # Agregar placeholder dinámico si no existe
            if 'placeholder' not in field.widget.attrs and hasattr(field, 'label'):
                field.widget.attrs['placeholder'] = f'Ingresa {field.label.lower()}'