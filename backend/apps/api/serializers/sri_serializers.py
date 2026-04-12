# -*- coding: utf-8 -*-
"""
Serializers for SRI integration - VERSIÓN FINAL INTEGRADA Y CORREGIDA
"""

from rest_framework import serializers
from django.db import transaction
from decimal import Decimal, ROUND_HALF_UP
from apps.sri_integration.models import (
    ElectronicDocument, 
    DocumentItem, 
    DocumentTax,
    SRIConfiguration,
    SRIResponse,
    CreditNote, 
    DebitNote, 
    Retention, 
    RetentionDetail, 
    PurchaseSettlement, 
    PurchaseSettlementItem
)
from apps.companies.models import Company


# ========== SERIALIZERS BASE CORREGIDOS CON VALIDACIONES SEGURAS ==========

class DocumentTaxSerializer(serializers.ModelSerializer):
    """
    Serializer para impuestos de documentos
    """
    tax_code_display = serializers.CharField(source='get_tax_code_display', read_only=True)
    percentage_code_display = serializers.CharField(source='get_percentage_code_display', read_only=True)
    
    class Meta:
        model = DocumentTax
        fields = [
            'id',
            'tax_code',
            'tax_code_display',
            'percentage_code', 
            'percentage_code_display',
            'rate',
            'taxable_base',
            'tax_amount'
        ]


class DocumentItemSerializer(serializers.ModelSerializer):
    """
    Serializer para items de documentos - VERSIÓN CORREGIDA CON VALIDACIONES SEGURAS
    """
    taxes = DocumentTaxSerializer(many=True, required=False)
    
    class Meta:
        model = DocumentItem
        fields = [
            'id',
            'main_code',
            'auxiliary_code',
            'description',
            'quantity',
            'unit_price',
            'discount',
            'subtotal',
            'additional_details',
            'taxes'
        ]
        read_only_fields = ['subtotal', 'id']  # CRÍTICO: subtotal es solo lectura
    
    def validate_quantity(self, value):
        """Validar quantity con límites seguros"""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        
        # Límite máximo para evitar overflow en cálculos
        if value > Decimal('999999.999999'):
            raise serializers.ValidationError("Quantity too large. Maximum allowed: 999,999.999999")
        
        return value
    
    def validate_unit_price(self, value):
        """Validar unit_price con límites seguros"""
        if value <= 0:
            raise serializers.ValidationError("Unit price must be greater than 0")
        
        # Límite máximo para evitar overflow
        if value > Decimal('999999.999999'):
            raise serializers.ValidationError("Unit price too large. Maximum allowed: 999,999.999999")
        
        return value
    
    def validate_discount(self, value):
        """Validar discount con límites seguros"""
        if value < 0:
            raise serializers.ValidationError("Discount cannot be negative")
        
        # Límite máximo para descuentos
        if value > Decimal('9999999999.99'):
            raise serializers.ValidationError("Discount too large. Maximum allowed: 9,999,999,999.99")
        
        return value
    
    def validate(self, attrs):
        """Validación cruzada para evitar overflow en subtotal"""
        quantity = Decimal(str(attrs.get('quantity', 0)))
        unit_price = Decimal(str(attrs.get('unit_price', 0)))
        discount = Decimal(str(attrs.get('discount', 0)))
        
        # Calcular subtotal estimado
        estimated_subtotal = (quantity * unit_price) - discount
        
        # CRÍTICO: Validar que el subtotal no exceda los límites del campo
        # Campo: max_digits=12, decimal_places=2 = máximo 9999999999.99
        max_allowed = Decimal('9999999999.99')
        
        if estimated_subtotal > max_allowed:
            raise serializers.ValidationError({
                'non_field_errors': [
                    f"Calculated subtotal ({estimated_subtotal}) exceeds maximum allowed value ({max_allowed}). "
                    f"Please reduce quantity, unit_price, or increase discount."
                ]
            })
        
        if estimated_subtotal < 0:
            raise serializers.ValidationError({
                'discount': ["Discount cannot be greater than (quantity × unit_price)"]
            })
        
        return attrs
    
    def create(self, validated_data):
        """Crear item con cálculo seguro de subtotal"""
        taxes_data = validated_data.pop('taxes', [])
        
        # CRÍTICO: Asegurar que subtotal no esté en validated_data
        # Se calcula automáticamente en el modelo
        if 'subtotal' in validated_data:
            validated_data.pop('subtotal')
        
        # El subtotal se calcula automáticamente en el modelo
        item = DocumentItem.objects.create(**validated_data)
        
        # Crear impuestos asociados si los hay
        for tax_data in taxes_data:
            DocumentTax.objects.create(item=item, **tax_data)
        
        return item


class ElectronicDocumentSerializer(serializers.ModelSerializer):
    """
    Serializer para documentos electrónicos (lectura)
    """
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    company_ruc = serializers.CharField(source='company.ruc', read_only=True)
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    customer_identification_type_display = serializers.CharField(
        source='get_customer_identification_type_display', read_only=True
    )
    
    items = DocumentItemSerializer(many=True, read_only=True)
    taxes = DocumentTaxSerializer(many=True, read_only=True)
    
    # URLs de archivos
    xml_file_url = serializers.SerializerMethodField()
    signed_xml_file_url = serializers.SerializerMethodField()
    pdf_file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = ElectronicDocument
        fields = [
            'id',
            'company',
            'company_name',
            'company_ruc',
            'document_type',
            'document_type_display',
            'document_number',
            'access_key',
            'issue_date',
            'status',
            'status_display',
            
            # Cliente
            'customer_identification_type',
            'customer_identification_type_display',
            'customer_identification',
            'customer_name',
            'customer_address',
            'customer_email',
            'customer_phone',
            
            # Totales
            'subtotal_without_tax',
            'subtotal_with_tax',
            'total_discount',
            'total_tax',
            'total_amount',
            
            # SRI
            'sri_authorization_code',
            'sri_authorization_date',
            'sri_response',
            
            # Email
            'email_sent',
            'email_sent_date',
            
            # Archivos
            'xml_file_url',
            'signed_xml_file_url',
            'pdf_file_url',
            
            # Relaciones
            'items',
            'taxes',
            
            # Metadata
            'additional_data',
            'created_at',
            'updated_at'
        ]
    
    def get_xml_file_url(self, obj):
        if obj.xml_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.xml_file.url)
        return None
    
    def get_signed_xml_file_url(self, obj):
        if obj.signed_xml_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.signed_xml_file.url)
        return None
    
    def get_pdf_file_url(self, obj):
        if obj.pdf_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.pdf_file.url)
        return None


class ElectronicDocumentCreateSerializer(serializers.ModelSerializer):
    """
    Serializer para crear documentos electrónicos - VERSIÓN CORREGIDA Y SEGURA
    """
    items = DocumentItemSerializer(many=True)
    
    class Meta:
        model = ElectronicDocument
        fields = [
            'company',
            'document_type',
            'issue_date',
            'customer_identification_type',
            'customer_identification',
            'customer_name',
            'customer_address',
            'customer_email',
            'customer_phone',
            'items',
            'additional_data'
        ]
    
    def validate_company(self, value):
        """Valida que la empresa tenga configuración SRI activa"""
        try:
            sri_config = value.sri_configuration
            if not sri_config.is_active:
                raise serializers.ValidationError("Company SRI configuration is not active")
        except Exception:
            raise serializers.ValidationError("Company does not have SRI configuration")
        
        return value
    
    def validate_items(self, value):
        """Valida items con verificaciones adicionales de seguridad"""
        if not value:
            raise serializers.ValidationError("At least one item is required")
        
        if len(value) > 100:  # Límite razonable de items
            raise serializers.ValidationError("Too many items. Maximum allowed: 100")
        
        total_estimated = Decimal('0.00')
        
        for i, item_data in enumerate(value):
            # Validar cada item individualmente
            quantity = Decimal(str(item_data.get('quantity', 0)))
            unit_price = Decimal(str(item_data.get('unit_price', 0)))
            discount = Decimal(str(item_data.get('discount', 0)))
            
            if quantity <= 0:
                raise serializers.ValidationError(f"Item {i+1}: quantity must be greater than 0")
            if unit_price <= 0:
                raise serializers.ValidationError(f"Item {i+1}: unit_price must be greater than 0")
            if discount < 0:
                raise serializers.ValidationError(f"Item {i+1}: discount cannot be negative")
            
            # Calcular subtotal del item
            item_subtotal = (quantity * unit_price) - discount
            
            if item_subtotal < 0:
                raise serializers.ValidationError(f"Item {i+1}: discount cannot exceed quantity × unit_price")
            
            # Verificar límites del campo DecimalField
            if item_subtotal > Decimal('9999999999.99'):
                raise serializers.ValidationError(
                    f"Item {i+1}: calculated subtotal too large. "
                    f"Please reduce quantity or unit_price."
                )
            
            total_estimated += item_subtotal
        
        # Verificar que el total del documento no sea excesivo
        if total_estimated > Decimal('99999999999.99'):  # Límite total del documento
            raise serializers.ValidationError(
                "Document total too large. Please reduce item quantities or prices."
            )
        
        return value
    
    @transaction.atomic
    def create(self, validated_data):
        """Crear documento con manejo seguro de totales"""
        items_data = validated_data.pop('items')
        
        # Obtener secuencial y generar número de documento
        company = validated_data['company']
        sri_config = company.sri_configuration
        document_number = sri_config.get_full_document_number(validated_data['document_type'])
        
        # Crear documento
        document = ElectronicDocument.objects.create(
            document_number=document_number,
            **validated_data
        )
        
        # Crear items y calcular totales con precisión decimal
        subtotal_without_tax = Decimal('0.00')
        total_discount = Decimal('0.00')
        
        for item_data in items_data:
            taxes_data = item_data.pop('taxes', [])
            
            # CRÍTICO: Asegurar que subtotal no esté en item_data
            # Se calcula automáticamente en el modelo
            if 'subtotal' in item_data:
                item_data.pop('subtotal')
            
            # Crear item - el subtotal se calcula automáticamente
            item = DocumentItem.objects.create(document=document, **item_data)
            
            # Acumular totales usando el subtotal calculado
            subtotal_without_tax += item.subtotal
            total_discount += item.discount
            
            # Crear impuestos del item
            for tax_data in taxes_data:
                # Usar el subtotal del item como base gravable
                tax_data['taxable_base'] = item.subtotal
                tax_rate = Decimal(str(tax_data['rate'])) / 100
                tax_data['tax_amount'] = (item.subtotal * tax_rate).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
                DocumentTax.objects.create(document=document, item=item, **tax_data)
        
        # Calcular totales del documento con redondeo adecuado
        total_tax = sum(tax.tax_amount for tax in document.taxes.all())
        
        # Asignar totales con verificación de límites
        document.subtotal_without_tax = subtotal_without_tax.quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        document.total_discount = total_discount.quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        document.total_tax = Decimal(str(total_tax)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        document.total_amount = (document.subtotal_without_tax + document.total_tax).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        # Verificar que los totales no excedan los límites antes de guardar
        max_field_value = Decimal('9999999999.99')
        
        if document.total_amount > max_field_value:
            raise serializers.ValidationError(
                f"Document total amount ({document.total_amount}) exceeds maximum allowed value. "
                f"Please reduce item quantities or prices."
            )
        
        document.save()
        
        return document


class SRIConfigurationSerializer(serializers.ModelSerializer):
    """
    Serializer para configuración SRI
    """
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    environment_display = serializers.CharField(source='get_environment_display', read_only=True)
    
    class Meta:
        model = SRIConfiguration
        fields = [
            'id',
            'company',
            'company_name',
            'environment',
            'environment_display',
            'reception_url',
            'authorization_url',
            'establishment_code',
            'emission_point',
            'invoice_sequence',
            'credit_note_sequence',
            'debit_note_sequence',
            'retention_sequence',
            'remission_guide_sequence',
            'purchase_settlement_sequence',
            'email_enabled',
            'email_subject_template',
            'email_body_template',
            'special_taxpayer',
            'special_taxpayer_number',
            'accounting_required',
            'is_active',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'invoice_sequence',
            'credit_note_sequence', 
            'debit_note_sequence',
            'retention_sequence',
            'remission_guide_sequence',
            'purchase_settlement_sequence'
        ]


class SRIResponseSerializer(serializers.ModelSerializer):
    """
    Serializer para respuestas del SRI
    """
    document_number = serializers.CharField(source='document.document_number', read_only=True)
    operation_type_display = serializers.CharField(source='get_operation_type_display', read_only=True)
    
    class Meta:
        model = SRIResponse
        fields = [
            'id',
            'document',
            'document_number',
            'operation_type',
            'operation_type_display',
            'response_code',
            'response_message',
            'raw_response',
            'created_at'
        ]


# ========== SERIALIZERS PARA NOTAS DE CRÉDITO ==========

class CreditNoteItemSerializer(serializers.Serializer):
    """
    Serializer para items de nota de crédito - VERSIÓN CORREGIDA
    """
    main_code = serializers.CharField(max_length=25)
    auxiliary_code = serializers.CharField(max_length=25, required=False, allow_blank=True)
    description = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=6)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=6)
    discount = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    def validate_quantity(self, value):
        """Validar quantity con límites seguros"""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        if value > Decimal('999999.999999'):
            raise serializers.ValidationError("Quantity too large")
        return value
    
    def validate_unit_price(self, value):
        """Validar unit_price con límites seguros"""
        if value <= 0:
            raise serializers.ValidationError("Unit price must be greater than 0")
        if value > Decimal('999999.999999'):
            raise serializers.ValidationError("Unit price too large")
        return value
    
    def validate_discount(self, value):
        """Validar discount"""
        if value < 0:
            raise serializers.ValidationError("Discount cannot be negative")
        if value > Decimal('9999999999.99'):
            raise serializers.ValidationError("Discount too large")
        return value
    
    def validate(self, attrs):
        """Validación cruzada para evitar overflow"""
        quantity = Decimal(str(attrs.get('quantity', 0)))
        unit_price = Decimal(str(attrs.get('unit_price', 0)))
        discount = Decimal(str(attrs.get('discount', 0)))
        
        estimated_subtotal = (quantity * unit_price) - discount
        
        if estimated_subtotal > Decimal('9999999999.99'):
            raise serializers.ValidationError(
                "Calculated subtotal too large. Please reduce quantity, unit_price, or increase discount."
            )
        
        if estimated_subtotal < 0:
            raise serializers.ValidationError({
                'discount': ["Discount cannot be greater than (quantity × unit_price)"]
            })
        
        return attrs


class CreateCreditNoteSerializer(serializers.Serializer):
    """
    Serializer para crear nota de crédito
    """
    company = serializers.IntegerField()
    original_invoice_id = serializers.IntegerField()
    reason_code = serializers.ChoiceField(choices=CreditNote.CREDIT_NOTE_REASONS, default='07')
    reason_description = serializers.CharField(max_length=300)
    issue_date = serializers.DateField(required=False)
    items = CreditNoteItemSerializer(many=True)
    
    def validate_company(self, value):
        """Valida que la empresa exista y tenga configuración SRI"""
        try:
            company = Company.objects.get(id=value)
            if not hasattr(company, 'sri_configuration'):
                raise serializers.ValidationError("Company does not have SRI configuration")
            return value
        except Company.DoesNotExist:
            raise serializers.ValidationError("Company not found")
    
    def validate_original_invoice_id(self, value):
        """Valida que la factura original exista"""
        try:
            invoice = ElectronicDocument.objects.get(id=value, document_type='INVOICE')
            return value
        except ElectronicDocument.DoesNotExist:
            raise serializers.ValidationError("Original invoice not found")
    
    def validate_items(self, value):
        """Valida que haya al menos un item"""
        if not value:
            raise serializers.ValidationError("At least one item is required")
        
        if len(value) > 100:
            raise serializers.ValidationError("Too many items. Maximum allowed: 100")
        
        total_estimated = Decimal('0.00')
        
        for i, item_data in enumerate(value):
            quantity = Decimal(str(item_data.get('quantity', 0)))
            unit_price = Decimal(str(item_data.get('unit_price', 0)))
            discount = Decimal(str(item_data.get('discount', 0)))
            
            item_subtotal = (quantity * unit_price) - discount
            
            if item_subtotal > Decimal('9999999999.99'):
                raise serializers.ValidationError(
                    f"Item {i+1}: calculated subtotal too large"
                )
            
            total_estimated += item_subtotal
        
        if total_estimated > Decimal('99999999999.99'):
            raise serializers.ValidationError("Document total too large")
        
        return value


class CreditNoteResponseSerializer(serializers.ModelSerializer):
    """
    Serializer de respuesta para nota de crédito
    """
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    original_document_number = serializers.CharField(source='original_document.document_number', read_only=True)
    reason_code_display = serializers.CharField(source='get_reason_code_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = CreditNote
        fields = [
            'id', 'company', 'company_name', 'document_number', 'access_key',
            'issue_date', 'reason_code', 'reason_code_display', 'reason_description',
            'original_document_number', 'customer_identification_type',
            'customer_identification', 'customer_name', 'customer_address',
            'customer_email', 'subtotal_without_tax', 'total_tax', 'total_amount',
            'status', 'status_display', 'sri_authorization_code', 'sri_authorization_date',
            'created_at', 'updated_at'
        ]


# ========== SERIALIZERS PARA NOTAS DE DÉBITO ==========

class DebitNoteItemSerializer(serializers.Serializer):
    """
    Serializer para motivos de nota de débito
    """
    reason = serializers.CharField(max_length=300)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    
    def validate_amount(self, value):
        """Validar que el monto sea positivo y no exceda límites"""
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than 0")
        if value > Decimal('9999999999.99'):
            raise serializers.ValidationError("Amount too large")
        return value


class CreateDebitNoteSerializer(serializers.Serializer):
    """
    Serializer para crear nota de débito
    """
    company = serializers.IntegerField()
    original_invoice_id = serializers.IntegerField()
    reason_code = serializers.ChoiceField(choices=DebitNote.DEBIT_NOTE_REASONS)
    reason_description = serializers.CharField(max_length=300)
    issue_date = serializers.DateField(required=False)
    motives = DebitNoteItemSerializer(many=True)
    
    def validate_company(self, value):
        """Valida que la empresa exista y tenga configuración SRI"""
        try:
            company = Company.objects.get(id=value)
            if not hasattr(company, 'sri_configuration'):
                raise serializers.ValidationError("Company does not have SRI configuration")
            return value
        except Company.DoesNotExist:
            raise serializers.ValidationError("Company not found")
    
    def validate_original_invoice_id(self, value):
        """Valida que la factura original exista"""
        try:
            invoice = ElectronicDocument.objects.get(id=value, document_type='INVOICE')
            return value
        except ElectronicDocument.DoesNotExist:
            raise serializers.ValidationError("Original invoice not found")
    
    def validate_motives(self, value):
        """Valida motivos de débito"""
        if not value:
            raise serializers.ValidationError("At least one motive is required")
        
        # Validar total de motivos
        total_amount = sum(Decimal(str(motive.get('amount', 0))) for motive in value)
        if total_amount > Decimal('9999999999.99'):
            raise serializers.ValidationError("Total amount too large")
        
        return value


class DebitNoteResponseSerializer(serializers.ModelSerializer):
    """
    Serializer de respuesta para nota de débito
    """
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    original_document_number = serializers.CharField(source='original_document.document_number', read_only=True)
    reason_code_display = serializers.CharField(source='get_reason_code_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = DebitNote
        fields = [
            'id', 'company', 'company_name', 'document_number', 'access_key',
            'issue_date', 'reason_code', 'reason_code_display', 'reason_description',
            'original_document_number', 'customer_identification_type',
            'customer_identification', 'customer_name', 'customer_address',
            'customer_email', 'subtotal_without_tax', 'total_tax', 'total_amount',
            'status', 'status_display', 'sri_authorization_code', 'sri_authorization_date',
            'created_at', 'updated_at'
        ]


# ========== SERIALIZERS PARA RETENCIONES ==========

class RetentionDetailSerializer(serializers.Serializer):
    """
    Serializer para detalles de retención
    """
    support_document_type = serializers.CharField(max_length=2)
    support_document_number = serializers.CharField(max_length=20)
    support_document_date = serializers.DateField()
    tax_code = serializers.CharField(max_length=4)
    retention_code = serializers.CharField(max_length=5)
    retention_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    taxable_base = serializers.DecimalField(max_digits=12, decimal_places=2)
    
    def validate_retention_percentage(self, value):
        """Validar porcentaje de retención"""
        if value < 0 or value > 100:
            raise serializers.ValidationError("Retention percentage must be between 0 and 100")
        return value
    
    def validate_taxable_base(self, value):
        """Validar base imponible"""
        if value <= 0:
            raise serializers.ValidationError("Taxable base must be greater than 0")
        if value > Decimal('9999999999.99'):
            raise serializers.ValidationError("Taxable base too large")
        return value


class CreateRetentionSerializer(serializers.Serializer):
    """
    Serializer para crear comprobante de retención
    """
    company = serializers.IntegerField()
    supplier_identification_type = serializers.ChoiceField(choices=[
        ('04', 'RUC'),
        ('05', 'Cedula'),
        ('06', 'Passport'),
        ('08', 'Foreign ID'),
    ])
    supplier_identification = serializers.CharField(max_length=20)
    supplier_name = serializers.CharField(max_length=300)
    supplier_address = serializers.CharField(required=False, allow_blank=True)
    issue_date = serializers.DateField(required=False)
    fiscal_period = serializers.CharField(max_length=7, required=False)  # MM/YYYY
    retention_details = RetentionDetailSerializer(many=True)
    
    def validate_company(self, value):
        """Valida que la empresa exista y tenga configuración SRI"""
        try:
            company = Company.objects.get(id=value)
            if not hasattr(company, 'sri_configuration'):
                raise serializers.ValidationError("Company does not have SRI configuration")
            return value
        except Company.DoesNotExist:
            raise serializers.ValidationError("Company not found")
    
    def validate_retention_details(self, value):
        """Valida que haya al menos un detalle de retención"""
        if not value:
            raise serializers.ValidationError("At least one retention detail is required")
        
        # Validar total retenido
        total_retained = Decimal('0.00')
        for detail in value:
            taxable_base = Decimal(str(detail.get('taxable_base', 0)))
            percentage = Decimal(str(detail.get('retention_percentage', 0)))
            retained_amount = (taxable_base * percentage / 100).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            total_retained += retained_amount
        
        if total_retained > Decimal('9999999999.99'):
            raise serializers.ValidationError("Total retained amount too large")
        
        return value


class RetentionResponseSerializer(serializers.ModelSerializer):
    """
    Serializer de respuesta para comprobante de retención
    """
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = Retention
        fields = [
            'id', 'company', 'company_name', 'document_number', 'access_key',
            'issue_date', 'supplier_identification_type', 'supplier_identification',
            'supplier_name', 'supplier_address', 'fiscal_period', 'total_retained',
            'status', 'status_display', 'sri_authorization_code', 'sri_authorization_date',
            'created_at', 'updated_at'
        ]


# ========== SERIALIZERS PARA LIQUIDACIONES DE COMPRA ==========

class PurchaseSettlementItemSerializer(serializers.Serializer):
    """
    Serializer para items de liquidación de compra - VERSIÓN CORREGIDA
    """
    main_code = serializers.CharField(max_length=25)
    description = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=6)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=6)
    discount = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    def validate_quantity(self, value):
        """Validar quantity con límites seguros"""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        if value > Decimal('999999.999999'):
            raise serializers.ValidationError("Quantity too large")
        return value
    
    def validate_unit_price(self, value):
        """Validar unit_price con límites seguros"""
        if value <= 0:
            raise serializers.ValidationError("Unit price must be greater than 0")
        if value > Decimal('999999.999999'):
            raise serializers.ValidationError("Unit price too large")
        return value
    
    def validate_discount(self, value):
        """Validar discount"""
        if value < 0:
            raise serializers.ValidationError("Discount cannot be negative")
        if value > Decimal('9999999999.99'):
            raise serializers.ValidationError("Discount too large")
        return value
    
    def validate(self, attrs):
        """Validación cruzada para evitar overflow"""
        quantity = Decimal(str(attrs.get('quantity', 0)))
        unit_price = Decimal(str(attrs.get('unit_price', 0)))
        discount = Decimal(str(attrs.get('discount', 0)))
        
        estimated_subtotal = (quantity * unit_price) - discount
        
        if estimated_subtotal > Decimal('9999999999.99'):
            raise serializers.ValidationError(
                "Calculated subtotal too large. Please reduce quantity, unit_price, or increase discount."
            )
        
        if estimated_subtotal < 0:
            raise serializers.ValidationError({
                'discount': ["Discount cannot be greater than (quantity × unit_price)"]
            })
        
        return attrs


class CreatePurchaseSettlementSerializer(serializers.Serializer):
    """
    Serializer para crear liquidación de compra - VERSIÓN CORREGIDA
    """
    company = serializers.IntegerField()
    supplier_identification_type = serializers.ChoiceField(choices=[
        ('04', 'RUC'),
        ('05', 'Cedula'),
        ('06', 'Passport'),
        ('08', 'Foreign ID'),
    ])
    supplier_identification = serializers.CharField(max_length=20)
    supplier_name = serializers.CharField(max_length=300)
    supplier_address = serializers.CharField(required=False, allow_blank=True)
    issue_date = serializers.DateField(required=False)
    items = PurchaseSettlementItemSerializer(many=True)
    
    def validate_company(self, value):
        """Valida que la empresa exista y tenga configuración SRI"""
        try:
            company = Company.objects.get(id=value)
            if not hasattr(company, 'sri_configuration'):
                raise serializers.ValidationError("Company does not have SRI configuration")
            return value
        except Company.DoesNotExist:
            raise serializers.ValidationError("Company not found")
    
    def validate_items(self, value):
        """Valida items con verificaciones de seguridad"""
        if not value:
            raise serializers.ValidationError("At least one item is required")
        
        if len(value) > 100:
            raise serializers.ValidationError("Too many items. Maximum allowed: 100")
        
        total_estimated = Decimal('0.00')
        
        for i, item_data in enumerate(value):
            quantity = Decimal(str(item_data.get('quantity', 0)))
            unit_price = Decimal(str(item_data.get('unit_price', 0)))
            discount = Decimal(str(item_data.get('discount', 0)))
            
            item_subtotal = (quantity * unit_price) - discount
            
            if item_subtotal > Decimal('9999999999.99'):
                raise serializers.ValidationError(
                    f"Item {i+1}: calculated subtotal too large"
                )
            
            total_estimated += item_subtotal
        
        if total_estimated > Decimal('99999999999.99'):
            raise serializers.ValidationError("Document total too large")
        
        return value


class PurchaseSettlementResponseSerializer(serializers.ModelSerializer):
    """
    Serializer de respuesta para liquidación de compra
    """
    company_name = serializers.CharField(source='company.business_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = PurchaseSettlement
        fields = [
            'id', 'company', 'company_name', 'document_number', 'access_key',
            'issue_date', 'supplier_identification_type', 'supplier_identification',
            'supplier_name', 'supplier_address', 'subtotal_without_tax', 'total_tax',
            'total_amount', 'status', 'status_display', 'sri_authorization_code',
            'sri_authorization_date', 'created_at', 'updated_at'
        ]


# ========== SERIALIZERS AUXILIARES ==========

class DocumentProcessRequestSerializer(serializers.Serializer):
    """
    Serializer para procesar documentos
    """
    certificate_password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    send_email = serializers.BooleanField(default=True)
    
    def validate_certificate_password(self, value):
        if not value:
            raise serializers.ValidationError("Certificate password is required")
        return value


class DocumentStatusSerializer(serializers.Serializer):
    """
    Serializer para estado de documentos
    """
    id = serializers.IntegerField()
    document_number = serializers.CharField()
    access_key = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    issue_date = serializers.DateField()
    customer_name = serializers.CharField()
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    
    # SRI info
    sri_authorization_code = serializers.CharField(allow_blank=True)
    sri_authorization_date = serializers.DateTimeField(allow_null=True)
    
    # Files
    has_xml = serializers.BooleanField()
    has_signed_xml = serializers.BooleanField()
    has_pdf = serializers.BooleanField()
    
    # Email
    email_sent = serializers.BooleanField()
    email_sent_date = serializers.DateTimeField(allow_null=True)
    
    # Last SRI response
    last_sri_response = serializers.DictField(allow_null=True)


# ========== SERIALIZERS PARA VALIDACIÓN MASIVA ==========

class BulkDocumentValidationSerializer(serializers.Serializer):
    """
    Serializer para validación masiva de documentos
    """
    documents = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
        max_length=50
    )
    
    def validate_documents(self, value):
        """Valida documentos en lote"""
        if not value:
            raise serializers.ValidationError("At least one document is required")
        
        if len(value) > 50:  # Límite para procesamiento masivo
            raise serializers.ValidationError("Too many documents. Maximum allowed: 50")
        
        # Validar cada documento individualmente
        for i, doc_data in enumerate(value):
            try:
                # Validar estructura básica del documento
                required_fields = ['company', 'document_type', 'items']
                for field in required_fields:
                    if field not in doc_data:
                        raise serializers.ValidationError(f"Missing required field: {field}")
                
                # Validar items
                if not doc_data.get('items'):
                    raise serializers.ValidationError("At least one item is required")
                
            except Exception as e:
                raise serializers.ValidationError(f"Document {i+1}: {str(e)}")
        
        return value


class DocumentSummarySerializer(serializers.Serializer):
    """
    Serializer para resumen de documentos
    """
    total_documents = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    by_status = serializers.DictField()
    by_type = serializers.DictField()
    recent_documents = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=True
    )


# ========== FUNCIONES AUXILIARES ==========

def validate_subtotal_calculation(quantity, unit_price, discount=0):
    """
    Función auxiliar para validar cálculos de subtotal de forma segura
    """
    try:
        qty = Decimal(str(quantity))
        price = Decimal(str(unit_price))
        disc = Decimal(str(discount))
        
        # Validar límites
        if qty <= 0 or price <= 0:
            return False, None, "Quantity and unit price must be greater than 0"
        
        if disc < 0:
            return False, None, "Discount cannot be negative"
        
        # Calcular subtotal
        subtotal = (qty * price) - disc
        
        if subtotal < 0:
            return False, None, "Discount cannot exceed total price"
        
        if subtotal > Decimal('9999999999.99'):
            return False, None, "Calculated subtotal too large"
        
        return True, subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), None
        
    except Exception as e:
        return False, None, f"Calculation error: {str(e)}"


def get_document_totals_summary(document):
    """
    Función auxiliar para obtener resumen de totales de un documento
    """
    return {
        'subtotal_without_tax': document.subtotal_without_tax,
        'total_discount': document.total_discount,
        'total_tax': document.total_tax,
        'total_amount': document.total_amount,
        'items_count': document.items.count(),
        'taxes_count': document.taxes.count()
    }