# -*- coding: utf-8 -*-
"""
Core views - API ONLY VERSION
apps/core/views.py
"""

import logging
from django.db import models
from django.shortcuts import get_object_or_404, render, redirect
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from decimal import Decimal
from apps.companies.models import Company
from apps.sri_integration.models import SRIConfiguration, ElectronicDocument, CreditNote
from apps.certificates.models import DigitalCertificate
from django.contrib.auth import get_user_model
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

User = get_user_model()

def notify_user_update(user):
    """Notificar al usuario vía WebSocket sobre cambios en su perfil"""
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'user_{user.id}',
            {
                'type': 'user_update',
                'data': {
                    'id': user.id,
                    'can_track': user.can_track,
                    'user_status': user.user_status,
                    'role': user.role,
                    'is_active': user.is_active
                }
            }
        )
    except Exception as e:
        logger.error(f"Error notifying user via WS: {e}")

logger = logging.getLogger(__name__)

def get_user_companies_secure(user):
    """
    Función auxiliar SEGURA - Obtiene las empresas del usuario.
    Utilizada por WebSockets y otros módulos de la API.
    """
    try:
        from apps.api.user_company_helper import get_user_companies_exact
        return get_user_companies_exact(user)
    except ImportError:
        pass
    
    # Si es admin, puede ver todas las empresas
    if user.is_staff or user.is_superuser:
        return Company.objects.filter(is_active=True)
    
    # Intento de obtener empresas vía relación ManyToMany si existe
    if hasattr(user, 'companies'):
        return user.companies.filter(is_active=True)
        
    return Company.objects.none()

def get_user_company_by_id(company_id, user):
    """
    Verifica si un usuario tiene acceso a una empresa específica por ID.
    """
    try:
        company = Company.objects.get(id=company_id, is_active=True)
        if user.is_staff or user.is_superuser:
            return company
            
        user_companies = get_user_companies_secure(user)
        if user_companies.filter(id=company.id).exists():
            return company
        return None
    except Company.DoesNotExist:
        return None

def health_check(request):
    """
    Endpoint de salud del sistema.
    """
    return JsonResponse({
        'status': 'OK',
        'message': 'RutaFact Core API is running',
        'frontend': 'Web Dashboard Matrix Ready',
    })

# ==========================================
# VISTAS PARA EL DASHBOARD WEB (MATRIZ)
# ==========================================

def is_admin(user):
    return user.is_staff or user.is_superuser

@login_required
@user_passes_test(is_admin)
def admin_dashboard(request):
    """Vista principal del Dashboard de Administración"""
    # Usamos tu lógica segura para obtener la empresa matriz
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    # Estadísticas básicas
    from django.utils import timezone
    first_day = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    invoices_count = ElectronicDocument.objects.filter(company=company, created_at__gte=first_day).count() if company else 0

    context = {
        'companies': companies,
        'company': company,
        'user': request.user,
        'companies_count': companies.count(),
        'invoices_month': invoices_count,
    }
    return render(request, 'admin/dashboard.html', context)

@login_required
@user_passes_test(is_admin)
def admin_config_sri(request):
    """Vista de configuración del SRI y Firma Electrónica"""
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    if not company:
        messages.error(request, "No se detectó una empresa activa. Por favor, crea tu perfil de empresa primero.")
        return redirect('admin_dashboard')
    
    config = None
    certificate = None
    
    if company:
        config = SRIConfiguration.objects.filter(company=company, is_active=True).first()
        certificate = DigitalCertificate.objects.filter(company=company, is_active=True).first()
    
    # Obtener usuarios vinculados a esta empresa (Usuarios del Móvil)
    mobile_users = []
    if company:
        # 1. Usuarios con vínculo directo
        # 2. Usuarios asignados vía UserCompanyAssignment (ManyToManyField)
        mobile_users = User.objects.filter(
            models.Q(company=company) | 
            models.Q(company_assignment__assigned_companies=company)
        ).distinct().order_by('email')

    context = {
        'company': company,
        'config': config,
        'certificate': certificate,
        'mobile_users': mobile_users,
        'user': request.user,
    }
    # 🔍 DEBUG: Ver qué valor tiene company en el GET
    print(f"🔍 [GET CONFIG] company.id={company.pk}, codigo_establecimiento='{company.codigo_establecimiento}', codigo_punto_emision='{company.codigo_punto_emision}'")
    return render(request, 'admin/config_sri.html', context)

@login_required
@user_passes_test(is_admin)
def admin_users_view(request):
    """Vista dedicada para la gestión de Usuarios y Roles"""
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    # Traemos a TODOS los usuarios del sistema para poder asignarlos
    all_users = User.objects.all().order_by('email')

    context = {
        'company': company,
        'mobile_users': all_users, # Ahora enviamos a todos
        'user': request.user,
    }
    return render(request, 'admin/users.html', context)

@login_required
@user_passes_test(is_admin)
def admin_invoices_view(request):
    """Vista para listar todos los comprobantes de la empresa con trazabilidad de usuario"""
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    pending_invoices = []
    authorized_invoices = []
    
    if company:
        # Documentos en proceso o con error
        pending_invoices = ElectronicDocument.objects.filter(
            company=company,
            status__in=['DRAFT', 'GENERATED', 'SIGNED', 'SENT', 'ERROR', 'REJECTED']
        ).select_related('created_by').order_by('-created_at')
        
        # Documentos autorizados
        authorized_invoices = ElectronicDocument.objects.filter(
            company=company,
            status='AUTHORIZED'
        ).select_related('created_by').order_by('-created_at')

    context = {
        'company': company,
        'pending_invoices': pending_invoices,
        'authorized_invoices': authorized_invoices,
        'user': request.user,
    }
    return render(request, 'admin/invoices.html', context)

@login_required
@user_passes_test(is_admin)
def admin_retry_invoice(request, pk):
    """Reintentar el procesamiento de un documento que falló o fue rechazado"""
    from apps.sri_integration.models import ElectronicDocument
    from apps.sri_integration.tasks import process_document_async
    
    companies = get_user_companies_secure(request.user)
    document = get_object_or_404(ElectronicDocument, pk=pk, company__in=companies)
    
    # Solo reintentar si está en estado que lo permita
    if document.status in ['ERROR', 'REJECTED', 'GENERATED', 'SIGNED']:
        # Limpiar datos previos si es necesario
        document.status = 'GENERATED'
        document.save()
        
        # Encolar tarea asíncrona
        process_document_async.delay(document.id)
        messages.success(request, f"Procesamiento del comprobante {document.document_number} reiniciado.")
    else:
        messages.warning(request, f"El comprobante ya está en estado {document.status} y no requiere reintento.")
        
    return redirect('admin_invoices')

@login_required
@user_passes_test(is_admin)
def admin_annul_invoice(request, pk):
    """Anular una factura autorizada mediante la creación de una Nota de Crédito"""
    from apps.sri_integration.tasks import process_document_async
    
    companies = get_user_companies_secure(request.user)
    invoice = get_object_or_404(ElectronicDocument, pk=pk, company__in=companies, document_type='INVOICE')
    
    # Solo permitir anular facturas autorizadas (o enviadas)
    if invoice.status not in ['AUTHORIZED', 'SENT']:
        messages.warning(request, f"Solo se pueden anular facturas que han sido autorizadas o enviadas al SRI. Estado actual: {invoice.status}")
        return redirect('admin_invoices')
        
    # Verificar si ya existe una nota de crédito para esta factura
    if CreditNote.objects.filter(original_document=invoice, status__in=['DRAFT', 'GENERATED', 'SIGNED', 'SENT', 'AUTHORIZED']).exists():
        messages.warning(request, f"Ya existe una Nota de Crédito en proceso o autorizada para la factura {invoice.document_number}.")
        return redirect('admin_invoices')
        
    try:
        with transaction.atomic():
            # Crear la Nota de Crédito
            credit_note = CreditNote.objects.create(
                company=invoice.company,
                original_document=invoice,
                reason_code='02', # Anulación de venta
                reason_description=f"Anulacion de factura {invoice.document_number}",
                customer_identification_type=invoice.customer_identification_type,
                customer_identification=invoice.customer_identification,
                customer_name=invoice.customer_name,
                customer_address=invoice.customer_address,
                customer_email=invoice.customer_email,
                subtotal_without_tax=invoice.subtotal_without_tax,
                total_tax=invoice.total_tax,
                total_amount=invoice.total_amount,
                issue_date=timezone.localtime(timezone.now()).date(),
                status='DRAFT'
            )
            
            # Encolar procesamiento asíncrono de la Nota de Crédito
            transaction.on_commit(lambda: process_document_async.delay(credit_note.id, model_type='CreditNote'))
            
            # DEVOLVER STOCK A INVENTARIO (NUEVO)
            items = invoice.additional_data.get('pos_items', [])
            if items:
                from apps.inventory.models import ProductStock, StockMovement
                from apps.invoicing.models import ProductTemplate
                
                for item in items:
                    prod_id = item.get('id')
                    qty = Decimal(str(item.get('quantity', 0)))
                    
                    if prod_id and qty > 0:
                        prod = ProductTemplate.objects.filter(id=prod_id, company=invoice.company).first()
                        if prod:
                            stock, _ = ProductStock.objects.get_or_create(
                                company=invoice.company, 
                                product=prod,
                                defaults={'quantity': 0}
                            )
                            prev_stock = stock.quantity
                            stock.quantity += qty
                            stock.save()
                            
                            # Sincronizar Template
                            prod.current_stock += qty
                            prod.save()
                            
                            # Registrar movimiento
                            StockMovement.objects.create(
                                company=invoice.company,
                                product=prod,
                                movement_type='IN', # Entrada por devolución
                                quantity=qty,
                                previous_stock=prev_stock,
                                new_stock=stock.quantity,
                                reference=f"ANUL-{invoice.document_number}",
                                notes=f"Devolución por anulación de factura",
                                created_by=request.user
                            )
            
            messages.success(request, f"Se ha iniciado la anulación de la factura {invoice.document_number} y se ha devuelto el stock al inventario.")
            
    except Exception as e:
        messages.error(request, f"Error al intentar anular la factura: {str(e)}")
        
    return redirect('admin_invoices')

@login_required
@user_passes_test(is_admin)
def admin_providers_view(request):
    """Vista para gestión de Proveedores"""
    from apps.inventory.models import Provider
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    if request.method == 'POST':
        try:
            # Crear proveedor
            Provider.objects.create(
                company=company,
                identification_type=request.POST.get('identification_type', '04'),
                identification=request.POST.get('identification'),
                name=request.POST.get('name'),
                email=request.POST.get('email', ''),
                phone=request.POST.get('phone', ''),
                address=request.POST.get('address', ''),
                regime=request.POST.get('regime', 'GENERAL'),
                provider_code=request.POST.get('provider_code', ''),
                authorization_number=request.POST.get('authorization_number', ''),
                start_sequence=request.POST.get('start_sequence') or None,
                end_sequence=request.POST.get('end_sequence') or None,
                expiration_date=request.POST.get('expiration_date') or None,
                created_by=request.user
            )
            messages.success(request, f"Proveedor {request.POST.get('name')} creado exitosamente")
            return redirect('admin_suppliers')
        except Exception as e:
            messages.error(request, f"Error al crear proveedor: {str(e)}")
    
    providers = []
    if company:
        providers = Provider.objects.filter(company=company).order_by('name')

    context = {
        'company': company,
        'providers': providers,
        'user': request.user,
        'today': timezone.now().date(),
    }
    return render(request, 'admin/suppliers.html', context)

@login_required
@user_passes_test(is_admin)
def admin_edit_provider(request, provider_id):
    """Editar un proveedor existente"""
    from apps.inventory.models import Provider
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    provider = get_object_or_404(Provider, id=provider_id, company=company)
    
    if request.method == 'POST':
        try:
            provider.identification_type = request.POST.get('identification_type', '04')
            provider.identification = request.POST.get('identification')
            provider.name = request.POST.get('name')
            provider.email = request.POST.get('email', '')
            provider.phone = request.POST.get('phone', '')
            provider.address = request.POST.get('address', '')
            provider.regime = request.POST.get('regime', 'GENERAL')
            provider.provider_code = request.POST.get('provider_code', '')
            provider.authorization_number = request.POST.get('authorization_number', '')
            provider.start_sequence = request.POST.get('start_sequence') or None
            provider.end_sequence = request.POST.get('end_sequence') or None
            provider.expiration_date = request.POST.get('expiration_date') or None
            provider.save()
            
            messages.success(request, f"Proveedor {provider.name} actualizado exitosamente")
            return redirect('admin_suppliers')
        except Exception as e:
            messages.error(request, f"Error al editar proveedor: {str(e)}")
            
    return redirect('admin_suppliers')

@login_required
@user_passes_test(is_admin)
def admin_delete_provider(request, provider_id):
    """Eliminar un proveedor"""
    from apps.inventory.models import Provider
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    provider = get_object_or_404(Provider, id=provider_id, company=company)
    
    try:
        if provider.purchases.exists():
            messages.warning(request, f"No se puede eliminar {provider.name} porque tiene facturas registradas. Inactívelo en su lugar.")
            provider.is_active = False
            provider.save()
        else:
            provider.delete()
            messages.success(request, "Proveedor eliminado correctamente")
    except Exception as e:
        messages.error(request, f"Error al eliminar: {str(e)}")
        
    return redirect('admin_suppliers')

@login_required
@user_passes_test(is_admin)
def admin_purchases_view(request):
    """Vista para gestión de Compras e Ingreso de Inventario"""
    from apps.inventory.models import Provider, PurchaseInvoice, StockMovement, ProductStock
    from apps.inventory.services import InventoryService
    from apps.invoicing.models import ProductTemplate
    
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    if request.method == 'POST':
        print("🚀 [POST] admin_purchases_view started")
        if not company:
            print("❌ [POST] No company found")
            messages.error(request, "No se encontró una empresa asociada a su usuario.")
            return redirect('admin_purchases')
            
        try:
            with transaction.atomic():
                provider_id = request.POST.get('provider')
                print(f"🔹 Provider ID: {provider_id}")
                if not provider_id:
                    raise ValueError("Debe seleccionar un proveedor.")
                    
                provider = get_object_or_404(Provider, id=provider_id, company=company)
                
                # Procesar ítems
                product_names = request.POST.getlist('product_name[]')
                quantities = request.POST.getlist('quantity[]')
                costs = request.POST.getlist('cost[]')
                tax_rates = request.POST.getlist('tax_rate[]')
                product_images = request.FILES.getlist('product_image[]')
                
                print(f"🔹 Items to process: {len(product_names)}")
                
                # Helper para conversión segura a Decimal
                def safe_decimal(val, default='0'):
                    if not val: return Decimal(default)
                    try:
                        import re
                        clean_val = re.sub(r'[^\d.,-]', '', str(val)).replace(',', '.')
                        return Decimal(clean_val)
                    except:
                        return Decimal(default)

                # Preparar items para el servicio
                items_data = []
                for i in range(len(product_names)):
                    name = product_names[i].strip()
                    if not name: continue
                    
                    items_data.append({
                        'product_name': name,
                        'quantity': safe_decimal(quantities[i] if i < len(quantities) else '1', '1'),
                        'cost_inclusive': safe_decimal(costs[i] if i < len(costs) else '0', '0'),
                        'tax_rate': safe_decimal(tax_rates[i] if i < len(tax_rates) else '15.00', '15.00'),
                        'image': product_images[i] if i < len(product_images) else None
                    })

                print(f"🔹 Prepared items_data: {len(items_data)} items")

                # Llamar al servicio centralizado
                invoice_data = {
                    'invoice_number': request.POST.get('invoice_number'),
                    'issue_date': request.POST.get('issue_date'),
                    'notes': request.POST.get('notes', '')
                }
                print(f"🔹 Invoice data: {invoice_data['invoice_number']}")
                
                InventoryService.process_purchase(company, provider, invoice_data, items_data, request.user)
                print("✅ [POST] InventoryService finished successfully")
                
            messages.success(request, "Compra registrada y stock actualizado exitosamente")
            return redirect('admin_purchases')
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"🔥 [CRITICAL ERROR] {str(e)}")
            print(error_trace)
            logger.error(f"❌ Error al registrar compra: {str(e)}\n{error_trace}")
            messages.error(request, f"Error al registrar compra: {str(e)}")
            return redirect('admin_purchases')

    purchases = []
    providers = []
    products = []
    
    if company:
        purchases = PurchaseInvoice.objects.filter(company=company).select_related('provider').order_by('-issue_date')
        providers = Provider.objects.filter(company=company, is_active=True).order_by('name')
        products = ProductTemplate.objects.filter(company=company, is_active=True).order_by('name')

    context = {
        'company': company,
        'purchases': purchases,
        'providers': providers,
        'products': products,
        'user': request.user,
    }
    return render(request, 'admin/purchases.html', context)

@login_required
@user_passes_test(is_admin)
def admin_delete_purchase(request, purchase_id):
    """Eliminar compra y REVERTIR STOCK"""
    from apps.inventory.models import PurchaseInvoice, ProductStock, StockMovement
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    purchase = get_object_or_404(PurchaseInvoice, id=purchase_id, company=company)
    
    try:
        with transaction.atomic():
            # Revertir stock para cada ítem
            products_to_check = []
            for item in purchase.items.all():
                stock = ProductStock.objects.filter(company=company, product=item.product).first()
                if stock:
                    prev_stock = stock.quantity
                    stock.quantity -= Decimal(str(item.quantity))
                    stock.save()
                    
                    # SINCRONIZAR CON PRODUCT TEMPLATE
                    item.product.current_stock -= Decimal(str(item.quantity))
                    item.product.save()
                    products_to_check.append(item.product)
                    
                    # Registrar movimiento de reversión
                    StockMovement.objects.create(
                        company=company,
                        product=item.product,
                        movement_type='OUT',
                        quantity=Decimal(str(item.quantity)),
                        previous_stock=prev_stock,
                        new_stock=stock.quantity,
                        reference=f"REVERSO-{purchase.invoice_number}",
                        notes=f"Eliminación de factura {purchase.invoice_number}",
                        created_by=request.user
                    )
            
            purchase.delete()
            
            # Limpiar productos que quedaron en stock 0 y no tienen más compras asociadas
            for prod in products_to_check:
                if prod.current_stock <= 0:
                    # Verificar si no tiene otras compras
                    if getattr(prod, 'purchase_items', None) and prod.purchase_items.count() == 0:
                        try:
                            prod.delete()
                        except Exception as e:
                            print(f"No se pudo eliminar producto huerfano {prod.name}: {str(e)}")
            messages.success(request, f"Factura {purchase.invoice_number} eliminada y stock revertido")
    except Exception as e:
        messages.error(request, f"Error al eliminar compra: {str(e)}")
        
    return redirect('admin_purchases')

@login_required
@user_passes_test(is_admin)
def admin_inventory_view(request):
    """Vista para consultar el stock actual de productos"""
    from apps.inventory.models import ProductStock
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    stocks = []
    if company:
        stocks = ProductStock.objects.filter(company=company).select_related('product').order_by('product__name')

    context = {
        'company': company,
        'stocks': stocks,
        'user': request.user,
    }
    return render(request, 'admin/inventory.html', context)

@login_required
@user_passes_test(is_admin)
def admin_pos_view(request):
    """Vista del Punto de Venta (POS)"""
    from apps.invoicing.models import ProductTemplate, Customer, PaymentMethod
    from apps.inventory.models import ProductStock
    
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    if not company:
        messages.error(request, "No tienes una empresa asignada. Por favor, crea una empresa o pide que te asignen a una.")
        return redirect('admin_dashboard')
    
    # Validar Configuración SRI y Firma antes de permitir ventas
    sri_config = SRIConfiguration.objects.filter(company=company, is_active=True).first()
    certificate = DigitalCertificate.objects.filter(company=company, is_active=True).first()
    
    if not sri_config:
        messages.warning(request, "⚠️ ATENCIÓN: Tu empresa no tiene configuración del SRI activa. Las facturas quedarán en error.")
    elif not certificate:
        messages.warning(request, "⚠️ ATENCIÓN: No tienes una firma electrónica (P12) cargada. No podrás firmar documentos.")
    
    if request.method == 'POST':
        # Procesar la venta (Creación de factura)
        import json
        try:
            data = json.loads(request.body)
            customer_id = data.get('customer_id')
            items = data.get('items', [])
            payment_method_code = data.get('payment_method', '01') # Default efectivo
            
            customer = get_object_or_404(Customer, id=customer_id, company=company)
            
            with transaction.atomic():
                # 1. Obtener o crear configuración SRI para la empresa
                config, _ = SRIConfiguration.objects.get_or_create(
                    company=company,
                    defaults={
                        'environment': 'TEST' if company.ambiente_sri == '1' else 'PRODUCTION',
                        'establishment_code': company.codigo_establecimiento,
                        'emission_point': company.codigo_punto_emision,
                        'invoice_sequence': company.secuencial_factura,
                        'regimen': company.regimen,
                    }
                )
                
                # Calcular totales y preparar items limpios
                subtotal_0 = Decimal('0')
                subtotal_iva = Decimal('0')
                total_tax = Decimal('0')
                total_discount = Decimal('0')
                clean_items = []
                
                for item in items:
                    product = ProductTemplate.objects.get(id=item['id'], company=company)
                    qty = Decimal(str(item['quantity']))
                    price = Decimal(str(item['price']))
                    discount = Decimal(str(item.get('discount', 0)))
                    
                    line_subtotal = (qty * price) - discount
                    
                    # Determinar tasa de impuesto (usar la del producto en DB)
                    tax_rate = product.tax_rate
                    
                    if tax_rate > 0:
                        subtotal_iva += line_subtotal
                        total_tax += line_subtotal * (tax_rate / 100)
                    else:
                        subtotal_0 += line_subtotal
                    
                    total_discount += discount
                    
                    # Agregar a lista limpia para el XML
                    clean_items.append({
                        'id': item['id'],
                        'name': product.name,
                        'quantity': float(qty),
                        'price': float(price),
                        'tax_rate': float(tax_rate),
                        'discount': float(discount)
                    })
                
                # Redondear a 2 decimales para evitar errores de validación
                subtotal_0 = subtotal_0.quantize(Decimal('0.01'))
                subtotal_iva = subtotal_iva.quantize(Decimal('0.01'))
                total_tax = total_tax.quantize(Decimal('0.01'))
                total_discount = total_discount.quantize(Decimal('0.01'))
                total_amount = (subtotal_0 + subtotal_iva + total_tax).quantize(Decimal('0.01'))
                
                doc = ElectronicDocument.objects.create(
                    company=company,
                    document_type='INVOICE',
                    document_number=config.get_full_document_number('INVOICE'),
                    access_key='', 
                    issue_date=timezone.localtime(timezone.now()).date(),
                    status='DRAFT',
                    customer_identification_type=customer.identification_type,
                    customer_identification=customer.identification,
                    customer_name=customer.name,
                    customer_address=customer.address,
                    customer_email=customer.email,
                    customer_phone=customer.phone,
                    subtotal_without_tax=subtotal_0 + subtotal_iva,
                    subtotal_with_tax=subtotal_iva,
                    total_tax=total_tax,
                    total_discount=total_discount,
                    total_amount=total_amount,
                    created_by=request.user
                )
                
                # 2. Registrar ítems sanitizados en adicionales
                doc.additional_data = {'pos_items': clean_items}
                doc.save()
                
                # 3. Disparar procesamiento asíncrono para el SRI (Al confirmar transacción)
                from apps.sri_integration.tasks import process_document_async
                transaction.on_commit(lambda: process_document_async.delay(doc.id))
                
                # 4. Descontar Inventario
                for item in items:
                    product = ProductTemplate.objects.get(id=item['id'], company=company)
                    stock = ProductStock.objects.filter(company=company, product=product).first()
                    if stock:
                        prev_stock = stock.quantity
                        stock.quantity -= Decimal(str(item['quantity']))
                        stock.save()
                        
                        # SINCRONIZAR CON PRODUCT TEMPLATE
                        product.current_stock -= Decimal(str(item['quantity']))
                        product.save()
                        
                        from apps.inventory.models import StockMovement
                        StockMovement.objects.create(
                            company=company,
                            product=product,
                            movement_type='OUT',
                            quantity=Decimal(str(item['quantity'])),
                            previous_stock=prev_stock,
                            new_stock=stock.quantity,
                            reference=doc.document_number,
                            notes=f"Venta POS a {customer.name}",
                            created_by=request.user
                        )
                
            return JsonResponse({
                'status': 'success', 
                'message': f'Factura {doc.document_number} generada correctamente',
                'document_id': doc.id
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    # Cargar datos para el POS
    products = ProductTemplate.objects.filter(company=company, is_active=True).order_by('name')
    customers = Customer.objects.filter(company=company, is_active=True).order_by('name')
    payment_methods = PaymentMethod.objects.filter(company=company, is_active=True).order_by('name')
    
    context = {
        'company': company,
        'products': products,
        'customers': customers,
        'payment_methods': payment_methods,
        'user': request.user,
    }
    return render(request, 'admin/pos.html', context)

@login_required
@user_passes_test(is_admin)
def admin_add_customer_ajax(request):
    """Añadir cliente rápidamente desde el POS"""
    if request.method == 'POST':
        from apps.invoicing.models import Customer
        companies = get_user_companies_secure(request.user)
        company = companies.first()
        
        try:
            customer = Customer.objects.create(
                company=company,
                identification_type=request.POST.get('identification_type'),
                identification=request.POST.get('identification'),
                name=request.POST.get('name'),
                email=request.POST.get('email', ''),
                phone=request.POST.get('phone', ''),
                address=request.POST.get('address', ''),
                created_by=request.user
            )
            return JsonResponse({
                'status': 'success', 
                'id': customer.id, 
                'name': customer.name,
                'identification': customer.identification
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

@login_required
@user_passes_test(is_admin)
def admin_edit_product(request, product_id):
    """Editar información básica del producto (nombre, precio, imagen)"""
    from apps.invoicing.models import ProductTemplate
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    product = get_object_or_404(ProductTemplate, id=product_id, company=company)
    
    if request.method == 'POST':
        try:
            product.name = request.POST.get('name')
            product.description = request.POST.get('description', '')
            product.unit_price = Decimal(request.POST.get('unit_price', '0'))
            product.tax_rate = Decimal(request.POST.get('tax_rate', '15')) # Default 15% IVA
            
            if 'image' in request.FILES:
                product.image = request.FILES['image']
                
            product.save()
            messages.success(request, f"Producto '{product.name}' actualizado correctamente.")
        except Exception as e:
            messages.error(request, f"Error al actualizar producto: {str(e)}")
            
        return redirect('admin_inventory')
    
    # Si es AJAX, retornar datos para el modal
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'id': product.id,
            'name': product.name,
            'description': product.description,
            'unit_price': float(product.unit_price),
            'tax_rate': float(product.tax_rate),
            'image_url': product.image.url if product.image else None
        })
    
    return redirect('admin_inventory')

@login_required
@user_passes_test(is_admin)
def admin_delete_product(request, product_id):
    """Eliminar producto permanentemente (y sus stocks/movimientos)"""
    from apps.invoicing.models import ProductTemplate
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    product = get_object_or_404(ProductTemplate, id=product_id, company=company)
    
    try:
        name = product.name
        # Eliminamos el producto. El on_delete=CASCADE en Stock y Movement se encargará del resto.
        product.delete()
        messages.success(request, f"Producto '{name}' eliminado exitosamente.")
    except Exception as e:
        messages.error(request, f"Error al eliminar producto: {str(e)}")
        
    return redirect('admin_inventory')

@login_required
@user_passes_test(is_admin)
def admin_sync_all_data(request):
    """Sincronización masiva de IVA 15% y stocks (Para mantenimiento)"""
    from apps.invoicing.models import ProductTemplate
    from apps.inventory.models import ProductStock
    
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    try:
        # 1. IVA 15%
        ProductTemplate.objects.filter(company=company, tax_rate=Decimal('12.00')).update(tax_rate=Decimal('15.00'))
        
        # 2. Stocks
        products = ProductTemplate.objects.filter(company=company)
        for prod in products:
            stock = ProductStock.objects.filter(product=prod, company=company).first()
            if stock:
                if prod.current_stock != stock.quantity:
                    prod.current_stock = stock.quantity
                    prod.save()
            else:
                if prod.current_stock > 0:
                    ProductStock.objects.create(company=company, product=prod, quantity=prod.current_stock)
        
        messages.success(request, "Sincronización de IVA 15% y stocks completada.")
    except Exception as e:
        messages.error(request, f"Error en sincronización: {str(e)}")
        
    return redirect('admin_inventory')

@login_required
@user_passes_test(is_admin)
def admin_adjust_stock(request, stock_id):
    """Ajuste manual de inventario"""
    from apps.inventory.models import ProductStock, StockMovement
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    stock = get_object_or_404(ProductStock, id=stock_id, company=company)
    
    if request.method == 'POST':
        try:
            new_qty = Decimal(request.POST.get('quantity', '0'))
            notes = request.POST.get('notes', 'Ajuste manual desde panel')
            
            prev_stock = stock.quantity
            stock.quantity = new_qty
            stock.save()
            
            # SINCRONIZAR CON PRODUCT TEMPLATE
            stock.product.current_stock = new_qty
            stock.product.save()
            
            # Registrar movimiento
            StockMovement.objects.create(
                company=company,
                product=stock.product,
                movement_type='IN' if new_qty > prev_stock else 'OUT',
                quantity=abs(new_qty - prev_stock),
                previous_stock=prev_stock,
                new_stock=new_qty,
                reference="AJUSTE-MANUAL",
                notes=notes,
                created_by=request.user
            )
            
            messages.success(request, f"Stock de {stock.product.name} ajustado correctamente")
        except Exception as e:
            messages.error(request, f"Error al ajustar stock: {str(e)}")
            
    return redirect('admin_inventory')

@login_required
@user_passes_test(is_admin)
def admin_delete_user(request, user_id):
    """Eliminar usuario permanentemente"""
    target_user = get_object_or_404(User, id=user_id)
    
    # Seguridad básica: no permitirse eliminar a uno mismo
    if target_user == request.user:
        messages.error(request, "No puedes eliminar tu propia cuenta de administrador.")
        return redirect('admin_users')
        
    try:
        email = target_user.email
        target_user.delete()
        messages.success(request, f"Usuario {email} eliminado permanentemente del sistema.")
    except Exception as e:
        messages.error(request, f"Error al eliminar usuario: {str(e)}")
        
    return redirect('admin_users')

@login_required
@user_passes_test(is_admin)
def toggle_user_assignment(request, user_id):
    """Vincular o desvincular un usuario de la empresa matriz"""
    if request.method == 'POST':
        target_user = get_object_or_404(User, id=user_id)
        companies = get_user_companies_secure(request.user)
        company = companies.first()
        
        if not company:
            return JsonResponse({'status': 'error', 'message': 'No se detectó empresa matriz'}, status=400)
            
        # Lógica de toggle
        if target_user.company == company:
            target_user.company = None
            message = f"Acceso revocado para {target_user.email}"
            status_text = "revoked"
        else:
            target_user.company = company
            message = f"Acceso concedido para {target_user.email}"
            status_text = "granted"
        
        target_user.save()
        notify_user_update(target_user)
        return JsonResponse({
            'status': 'success', 
            'message': message,
            'assignment': status_text
        })
    
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'}, status=405)
@login_required
@user_passes_test(is_admin)
def update_user_role(request, user_id):
    """Actualizar el rol de un usuario (admin, dispatcher, seller, driver, client)"""
    if request.method == 'POST':
        import json
        try:
            data = json.loads(request.body)
            new_role = data.get('role')
            
            target_user = get_object_or_404(User, id=user_id)
            
            # Validar rol
            if new_role not in dict(User.USER_ROLE_CHOICES):
                return JsonResponse({'status': 'error', 'message': f'Rol inválido: {new_role}'}, status=400)
            
            # Solo permitir si el usuario pertenece a la misma empresa, no tiene empresa, o el admin es superusuario
            companies = get_user_companies_secure(request.user)
            company = companies.first()
            
            if not request.user.is_superuser and target_user.company and target_user.company != company:
                 return JsonResponse({'status': 'error', 'message': 'No tienes permiso para editar este usuario (ya pertenece a otra empresa)'}, status=403)
            
            target_user.role = new_role
            target_user.save()
            notify_user_update(target_user)
            
            return JsonResponse({
                'status': 'success', 
                'message': f'Rol de {target_user.email} actualizado a {target_user.get_role_display()}'
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
            
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'}, status=405)

@login_required
@user_passes_test(is_admin)
def update_user_status(request, user_id):
    """Actualizar el estado del usuario (active, waiting, suspended, rejected)"""
    if request.method == 'POST':
        import json
        try:
            data = json.loads(request.body)
            new_status = data.get('status')
            
            target_user = get_object_or_404(User, id=user_id)
            
            # Validar estado
            if new_status not in dict(User.USER_STATUS_CHOICES):
                return JsonResponse({'status': 'error', 'message': f'Estado inválido: {new_status}'}, status=400)
            
            # Solo permitir si el admin tiene permiso sobre la empresa o es superusuario
            companies = get_user_companies_secure(request.user)
            company = companies.first()
            
            if not request.user.is_superuser and target_user.company and target_user.company != company:
                 return JsonResponse({'status': 'error', 'message': 'No tienes permiso para editar este usuario'}, status=403)
            
            target_user.user_status = new_status
            
            # Sincronizar con is_active de Django si es necesario
            if new_status == 'active':
                target_user.is_active = True
            elif new_status in ['suspended', 'rejected']:
                target_user.is_active = False
                
            target_user.save()
            notify_user_update(target_user)
            
            return JsonResponse({
                'status': 'success', 
                'message': f'Estado de {target_user.email} actualizado a {target_user.get_user_status_display()}'
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
            
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'}, status=405)

@login_required
@user_passes_test(is_admin)
def toggle_user_tracking(request, user_id):
    """Activar/Desactivar permiso de rastreo GPS"""
    if request.method == 'POST':
        target_user = get_object_or_404(User, id=user_id)
        
        # Validar permisos (admin de empresa o superusuario)
        companies = get_user_companies_secure(request.user)
        company = companies.first()
        
        if not request.user.is_superuser and target_user.company and target_user.company != company:
             return JsonResponse({'status': 'error', 'message': 'No tienes permiso para editar este usuario'}, status=403)
        
        target_user.can_track = not target_user.can_track
        target_user.save()
        notify_user_update(target_user)
        
        return JsonResponse({
            'status': 'success', 
            'message': f'Rastreo {"activado" if target_user.can_track else "desactivado"} para {target_user.email}',
            'can_track': target_user.can_track
        })

@login_required
@user_passes_test(is_admin)
def admin_retry_invoice(request, pk):
    """Reintenta el envío de una factura al SRI de forma manual"""
    from apps.sri_integration.models import ElectronicDocument
    from apps.sri_integration.tasks import process_document_async
    
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    invoice = get_object_or_404(ElectronicDocument, id=pk, company=company)
    
    # Solo permitir reintentar si no está autorizada
    if invoice.status == 'AUTHORIZED':
        messages.warning(request, "Esta factura ya está autorizada.")
    else:
        # Resetear estado y disparar tarea
        invoice.status = 'DRAFT'
        invoice.save()
        process_document_async.delay(invoice.id)
        messages.success(request, f"Reintento de envío programado para la factura {invoice.document_number}")
    
    return redirect('admin_invoices')
