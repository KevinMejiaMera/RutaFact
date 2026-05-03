# -*- coding: utf-8 -*-
"""
Core views - API ONLY VERSION
apps/core/views.py
"""

import logging
import json
from django.db import models
from django.shortcuts import get_object_or_404, render, redirect
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from decimal import Decimal, ROUND_HALF_UP
from apps.companies.models import Company
from apps.sri_integration.models import SRIConfiguration, ElectronicDocument, CreditNote
from apps.certificates.models import DigitalCertificate
from apps.logistics.models import Route, Vehicle, RouteStop, RouteTemplate, RouteProduct
from apps.invoicing.models import ProductTemplate
from apps.orders.models import Order
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
def admin_routes_view(request):
    """
    Vista de gestión de rutas, destinos y asignación de pedidos
    """
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    if not company:
        messages.error(request, "No tienes una empresa asignada.")
        return redirect('admin_dashboard')

    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create_route':
            name = request.POST.get('name', '').strip()
            driver_id = request.POST.get('driver')
            destination_name = request.POST.get('destination_name', '').strip()
            google_maps_url = request.POST.get('google_maps_url', '').strip()
            date_str = request.POST.get('date', timezone.now().date().isoformat())
            
            driver = User.objects.filter(id=driver_id).first()
            
            route = Route.objects.create(
                company=company,
                name=name,
                driver=driver,
                destination_name=destination_name,
                google_maps_url=google_maps_url,
                date=date_str,
                status='PENDING'
            )
            
            # Asignar pedidos seleccionados y crear paradas (nodos) automáticamente
            order_ids = request.POST.getlist('orders')
            if order_ids:
                orders = Order.objects.filter(id__in=order_ids, company=company)
                orders.update(route=route)
                
                # Crear paradas para cada pedido
                for i, order in enumerate(orders):
                    RouteStop.objects.get_or_create(
                        route=route,
                        customer=order.customer,
                        defaults={'order': i, 'status': 'PENDING'}
                    )
            
            # Procesar Productos de Consignación (Carga de Inventario)
            product_ids = request.POST.getlist('product_id[]')
            product_quantities = request.POST.getlist('product_quantity[]')
            
            for p_id, p_qty in zip(product_ids, product_quantities):
                if p_id and p_qty:
                    product = ProductTemplate.objects.filter(id=p_id).first()
                    if product:
                        RouteProduct.objects.create(
                            route=route,
                            product=product,
                            quantity_loaded=Decimal(p_qty)
                        )
            
            messages.success(request, f"Ruta '{name}' creada y asignada correctamente.")
            
            # Opción: Guardar como plantilla si el usuario lo marcó
            if request.POST.get('save_as_template') == 'on':
                RouteTemplate.objects.get_or_create(
                    company=company,
                    name=name,
                    defaults={
                        'destination_name': destination_name,
                        'google_maps_url': google_maps_url
                    }
                )
                messages.info(request, f"Ruta '{name}' guardada en tu catálogo de rutas frecuentes.")
            
            return redirect('admin_routes')
            
        elif action == 'assign_orders':
            route_id = request.POST.get('route_id')
            order_ids = request.POST.getlist('orders')
            route = get_object_or_404(Route, id=route_id, company=company)
            
            if order_ids:
                orders = Order.objects.filter(id__in=order_ids, company=company)
                orders.update(route=route)
                
                # Crear paradas para cada pedido nuevo
                for i, order in enumerate(orders):
                    RouteStop.objects.get_or_create(
                        route=route,
                        customer=order.customer,
                        defaults={'order': i, 'status': 'PENDING'}
                    )
                messages.success(request, f"Pedidos asignados a la ruta {route.name}.")
            return redirect('admin_routes')

        elif action == 'complete_route':
            route_id = request.POST.get('route_id')
            route = get_object_or_404(Route, id=route_id, company=company)
            route.status = 'COMPLETED'
            route.save()
            messages.success(request, f"Ruta {route.name} marcada como completada.")
            return redirect('admin_routes')

    # GET: Listar datos
    routes = Route.objects.filter(company=company).order_by('-date', '-created_at')
    route_templates = RouteTemplate.objects.filter(company=company)
    drivers = User.objects.filter(is_active=True)
    pending_orders = Order.objects.filter(company=company, route__isnull=True).exclude(status='COMPLETED')
    available_products = ProductTemplate.objects.filter(company=company, product_type='PRODUCT')
    
    context = {
        'routes': routes,
        'route_templates': route_templates,
        'drivers': drivers,
        'pending_orders': pending_orders,
        'available_products': available_products,
        'company': company,
    }
    return render(request, 'admin/routes.html', context)

@login_required
@user_passes_test(is_admin)
def admin_users_view(request):
    """Vista dedicada para la gestión de Usuarios y Roles"""
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    # Traemos a TODOS los usuarios del sistema con su perfil de cliente asociado
    all_users = User.objects.all().select_related('customer_profile').order_by('email')

    context = {
        'company': company,
        'mobile_users': all_users, # Ahora enviamos a todos
        'user': request.user,
    }
    return render(request, 'admin/users.html', context)

@login_required
@user_passes_test(is_admin)
def admin_customers_view(request):
    """Vista dedicada para la gestión de Clientes"""
    from apps.invoicing.models import Customer
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    customers = []
    if company:
        customers = Customer.objects.filter(company=company).order_by('name')

    context = {
        'company': company,
        'customers': customers,
        'user': request.user,
    }
    return render(request, 'admin/customers.html', context)

@login_required
@user_passes_test(is_admin)
def admin_create_user(request):
    """Crear un nuevo usuario y asignar rol/empresa directamente"""
    if request.method == 'POST':
        import json
        try:
            data = json.loads(request.body)
            email = data.get('email')
            first_name = data.get('first_name', '')
            last_name = data.get('last_name', '')
            password = data.get('password')
            role = data.get('role', 'client')
            
            if not email or not password:
                return JsonResponse({'status': 'error', 'message': 'Email y contraseña son requeridos'})
                
            if User.objects.filter(email=email).exists():
                return JsonResponse({'status': 'error', 'message': 'El email ya está registrado'})
                
            # Crear usuario
            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role=role,
                user_status='active'
            )
            
            # Asignar a la empresa del admin
            companies = get_user_companies_secure(request.user)
            company = companies.first()
            if company:
                user.company = company
                user.save()
                
            return JsonResponse({'status': 'success', 'message': 'Usuario creado y asignado exitosamente'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'})

@login_required
@user_passes_test(is_admin)
def admin_update_user(request, user_id):
    """Vista para actualizar datos de un usuario desde el admin"""
    if request.method == 'POST':
        try:
            from apps.users.models import User
            user = User.objects.get(id=user_id)
            data = json.loads(request.body)
            
            user.email = data.get('email', user.email)
            user.first_name = data.get('first_name', user.first_name)
            user.last_name = data.get('last_name', user.last_name)
            user.role = data.get('role', user.role)
            
            password = data.get('password')
            if password and password.strip():
                user.set_password(password)
                
            user.save()

            # Sincronizar/Crear perfil de Cliente asociado
            from apps.invoicing.models import Customer
            identification = data.get('identification')
            address = data.get('address')
            phone = data.get('phone', user.phone)

            customer, created = Customer.objects.get_or_create(
                user=user,
                defaults={
                    'company': user.company,
                    'name': f"{user.first_name} {user.last_name}".strip() or user.email,
                    'identification': identification or '9999999999',
                    'identification_type': '05',
                    'email': user.email,
                    'phone': phone,
                    'address': address or 'S/N'
                }
            )

            if not created:
                if identification: customer.identification = identification
                if address: customer.address = address
                if phone: customer.phone = phone
                customer.name = f"{user.first_name} {user.last_name}".strip() or user.email
                customer.email = user.email
                customer.save()

            return JsonResponse({'status': 'success', 'message': 'Usuario y perfil de cliente actualizados exitosamente'})
        except User.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Usuario no encontrado'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'})

@login_required
@user_passes_test(is_admin)
def admin_delivery_notes_view(request):
    """Vista para listar Notas de Entrega (Internas) de Pedidos y Rutas"""
    from apps.logistics.models import RouteDelivery
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    order_notes = []
    route_sales = []
    
    if company:
        # 1. Pedidos completados como Nota de Entrega (sin factura)
        order_notes = Order.objects.filter(
            company=company,
            status='COMPLETED',
            invoice__isnull=True
        ).select_related('customer', 'seller', 'created_by').order_by('-updated_at')
        
        # 2. Ventas directas de ruta (RouteDelivery)
        route_sales = RouteDelivery.objects.filter(
            route__company=company
        ).select_related('route', 'seller', 'invoice').order_by('-created_at')

    context = {
        'company': company,
        'order_notes': order_notes,
        'route_sales': route_sales,
        'user': request.user,
    }
    return render(request, 'admin/delivery_notes.html', context)

@login_required
@user_passes_test(is_admin)
def admin_invoices_view(request):
    """Vista para listar todos los comprobantes de la empresa con trazabilidad de usuario"""
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    pending_invoices = []
    authorized_invoices = []
    voided_invoices = []
    
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

        # Documentos anulados o con nota de crédito (Anulaciones totales o parciales)
        from django.db.models import Q
        voided_invoices = ElectronicDocument.objects.filter(
            company=company
        ).filter(
            Q(status='VOIDED') | Q(credit_notes__isnull=False)
        ).distinct().select_related('created_by').prefetch_related('credit_notes').order_by('-created_at')

    context = {
        'company': company,
        'pending_invoices': pending_invoices,
        'authorized_invoices': authorized_invoices,
        'voided_invoices': voided_invoices,
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
def admin_retry_credit_note(request, pk):
    """Reintentar el procesamiento de una nota de crédito que falló o fue rechazada"""
    from apps.sri_integration.models import CreditNote
    from apps.sri_integration.tasks import process_document_async
    
    companies = get_user_companies_secure(request.user)
    cn = get_object_or_404(CreditNote, pk=pk, company__in=companies)
    
    # Solo reintentar si está en estado que lo permita
    if cn.status in ['ERROR', 'REJECTED', 'GENERATED', 'SIGNED']:
        cn.status = 'GENERATED'
        cn.save()
        
        # Encolar tarea asíncrona especificando el tipo de modelo
        process_document_async.delay(cn.id, model_type='CreditNote')
        messages.success(request, f"Procesamiento de la nota de crédito {cn.document_number} reiniciado.")
    else:
        messages.warning(request, f"La nota de crédito ya está en estado {cn.status} y no requiere reintento.")
        
    return redirect('admin_invoices')

@login_required
@user_passes_test(is_admin)
def admin_annul_invoice(request, pk):
    """
    Anular una factura autorizada mediante la creación de una Nota de Crédito.
    Soporta:
    1. GET: Anulación total (tradicional)
    2. POST: Anulación parcial o total con selección de ítems (Profesional)
    """
    from apps.sri_integration.tasks import process_document_async
    from apps.sri_integration.models import DocumentItem, DocumentTax
    import json
    
    companies = get_user_companies_secure(request.user)
    invoice = get_object_or_404(ElectronicDocument, pk=pk, company__in=companies, document_type='INVOICE')
    
    # Solo permitir anular facturas autorizadas (o enviadas)
    if invoice.status not in ['AUTHORIZED', 'SENT']:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.method == 'POST':
            return JsonResponse({'status': 'error', 'message': f"Estado actual {invoice.status} no permite anulación."}, status=400)
        messages.warning(request, f"Solo se pueden anular facturas que han sido autorizadas o enviadas al SRI. Estado actual: {invoice.status}")
        return redirect('admin_invoices')
        
    # Verificar si ya existe una nota de crédito para esta factura
    # (Permitimos múltiples si son parciales? SRI permite varias notas de crédito por factura hasta agotar el total)
    # Por ahora, si es anulación TOTAL, bloqueamos si ya existe algo.
    
    is_partial = False
    items_to_annul = []
    reason_description = f"Anulacion de factura {invoice.document_number}"
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            items_data = data.get('items', [])
            reason_description = data.get('reason', reason_description)
            
            if items_data:
                is_partial = True
                items_to_annul = items_data
            elif data.get('total_annullation', False):
                is_partial = False
            else:
                return JsonResponse({'status': 'error', 'message': "Debe seleccionar ítems o confirmar anulación total."}, status=400)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f"Error en datos: {str(e)}"}, status=400)

    try:
        with transaction.atomic():
            # 1. Crear la cabecera de la Nota de Crédito
            credit_note = CreditNote.objects.create(
                company=invoice.company,
                original_document=invoice,
                reason_code='02', # Anulación de venta
                reason_description=reason_description,
                customer_identification_type=invoice.customer_identification_type,
                customer_identification=invoice.customer_identification,
                customer_name=invoice.customer_name,
                customer_address=invoice.customer_address,
                customer_email=invoice.customer_email,
                # Totales iniciales, se ajustarán si es parcial
                subtotal_without_tax=invoice.subtotal_without_tax,
                total_tax=invoice.total_tax,
                total_amount=invoice.total_amount,
                issue_date=timezone.localtime(timezone.now()).date(),
                status='DRAFT'
            )
            
            nc_items_to_process = []
            
            if is_partial:
                nc_subtotal = Decimal('0.00')
                nc_total_tax = Decimal('0.00')
                
                for item_data in items_to_annul:
                    original_item = DocumentItem.objects.get(id=item_data.get('id'), document=invoice)
                    qty = Decimal(str(item_data.get('quantity')))
                    
                    if qty > original_item.quantity:
                        raise ValueError(f"Cantidad a anular ({qty}) excede la original ({original_item.quantity})")
                    
                    item_subtotal = (qty * original_item.unit_price) - Decimal(str(item_data.get('discount', '0.00')))
                    
                    nc_item = DocumentItem.objects.create(
                        credit_note=credit_note,
                        main_code=original_item.main_code,
                        auxiliary_code=original_item.auxiliary_code,
                        description=original_item.description,
                        quantity=qty,
                        unit_price=original_item.unit_price,
                        discount=Decimal(str(item_data.get('discount', '0.00'))),
                        subtotal=item_subtotal
                    )
                    nc_items_to_process.append({'id': original_item.main_code, 'quantity': qty, 'description': original_item.description})
                    
                    # Impuestos del ítem
                    item_taxes = original_item.taxes.all()
                    if not item_taxes.exists():
                        # Fallback: Usar impuestos del documento si el ítem no tiene vinculados (Datos legados)
                        doc_taxes = invoice.taxes.filter(tax_code='2', item__isnull=True)
                        if doc_taxes.exists():
                            main_tax = doc_taxes.first()
                            tax_amount = (item_subtotal * main_tax.rate / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                            DocumentTax.objects.create(
                                credit_note=credit_note,
                                item=nc_item,
                                tax_code=main_tax.tax_code,
                                percentage_code=main_tax.percentage_code,
                                rate=main_tax.rate,
                                taxable_base=item_subtotal.quantize(Decimal('0.01')),
                                tax_amount=tax_amount
                            )
                            nc_total_tax += tax_amount
                    else:
                        for tax in item_taxes:
                            tax_amount = (item_subtotal * tax.rate / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                            DocumentTax.objects.create(
                                credit_note=credit_note,
                                item=nc_item,
                                tax_code=tax.tax_code,
                                percentage_code=tax.percentage_code,
                                rate=tax.rate,
                                taxable_base=item_subtotal.quantize(Decimal('0.01')),
                                tax_amount=tax_amount
                            )
                            nc_total_tax += tax_amount
                    
                    nc_subtotal += item_subtotal
                
                # Actualizar cabecera con totales parciales
                credit_note.subtotal_without_tax = nc_subtotal
                credit_note.total_tax = nc_total_tax
                credit_note.total_amount = nc_subtotal + nc_total_tax
                credit_note.save()
            else:
                # Anulación Total: Replicar todos los ítems
                for original_item in invoice.items.all():
                    nc_item = DocumentItem.objects.create(
                        credit_note=credit_note,
                        main_code=original_item.main_code,
                        auxiliary_code=original_item.auxiliary_code,
                        description=original_item.description,
                        quantity=original_item.quantity,
                        unit_price=original_item.unit_price,
                        discount=original_item.discount,
                        subtotal=original_item.subtotal
                    )
                    nc_items_to_process.append({'id': original_item.main_code, 'quantity': original_item.quantity, 'description': original_item.description})
                    
                    # Impuestos del ítem
                    item_taxes = original_item.taxes.all()
                    if not item_taxes.exists():
                        doc_taxes = invoice.taxes.filter(tax_code='2', item__isnull=True)
                        for tax in doc_taxes:
                            # Proporcionar el impuesto al ítem
                            DocumentTax.objects.create(
                                credit_note=credit_note,
                                item=nc_item,
                                tax_code=tax.tax_code,
                                percentage_code=tax.percentage_code,
                                rate=tax.rate,
                                taxable_base=original_item.subtotal.quantize(Decimal('0.01')),
                                tax_amount=(original_item.subtotal * tax.rate / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                            )
                    else:
                        for tax in item_taxes:
                            DocumentTax.objects.create(
                                credit_note=credit_note,
                                item=nc_item,
                                tax_code=tax.tax_code,
                                percentage_code=tax.percentage_code,
                                rate=tax.rate,
                                taxable_base=tax.taxable_base,
                                tax_amount=tax.tax_amount
                            )
            
            # 2. Crear resumen de impuestos a nivel de documento
            from django.db.models import Sum
            dt_summary = DocumentTax.objects.filter(credit_note=credit_note, item__isnull=False).values(
                'tax_code', 'percentage_code', 'rate'
            ).annotate(total_base=Sum('taxable_base'), total_amount=Sum('tax_amount'))
            
            for dt in dt_summary:
                DocumentTax.objects.create(
                    credit_note=credit_note,
                    item=None,
                    tax_code=dt['tax_code'],
                    percentage_code=dt['percentage_code'],
                    rate=dt['rate'],
                    taxable_base=dt['total_base'],
                    tax_amount=dt['total_amount']
                )

            # 3. Encolar procesamiento asíncrono
            transaction.on_commit(lambda: process_document_async.delay(credit_note.id, model_type='CreditNote'))
            
            # 4. Marcar factura como VOIDED (solo si es anulación total, o siempre?)
            # El SRI permite anular PARCIALMENTE sin anular la factura completa en la DB.
            # Pero si el usuario dijo "Anular", usualmente es porque ya no quiere la factura original.
            # Si es parcial, la factura original sigue siendo válida por el resto.
            # REGLA: Si es TOTAL, marcar VOIDED. Si es PARCIAL, dejar como AUTHORIZED pero con NC asociada.
            if not is_partial:
                invoice.status = 'VOIDED'
                invoice.save()
            
            # 5. DEVOLVER STOCK (Solo para los ítems anulados)
            from apps.inventory.models import ProductStock, StockMovement
            from apps.invoicing.models import ProductTemplate
            
            for item in nc_items_to_process:
                qty = item['quantity']
                # Buscar producto por código principal
                prod = ProductTemplate.objects.filter(main_code=item['id'], company=invoice.company).first()
                if prod:
                    stock, _ = ProductStock.objects.get_or_create(company=invoice.company, product=prod, defaults={'quantity': 0})
                    prev_stock = stock.quantity
                    stock.quantity += qty
                    stock.save()
                    prod.current_stock += qty
                    prod.save()
                    
                    StockMovement.objects.create(
                        company=invoice.company, product=prod, movement_type='IN',
                        quantity=qty, previous_stock=prev_stock, new_stock=stock.quantity,
                        reference=f"NC-{credit_note.document_number or 'PEND'}",
                        notes=f"Devolución por NC de factura {invoice.document_number}",
                        created_by=request.user
                    )
            
            msg = f"Se ha generado la Nota de Crédito {'parcial' if is_partial else 'total'} para la factura {invoice.document_number}."
            if request.method == 'POST':
                return JsonResponse({'status': 'success', 'message': msg, 'credit_note_id': credit_note.id})
            messages.success(request, msg)
            
    except Exception as e:
        if request.method == 'POST':
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
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
            
            if not customer_id:
                # Find or create Consumidor Final
                customer, _ = Customer.objects.get_or_create(
                    company=company,
                    identification='9999999999999',
                    defaults={
                        'name': 'CONSUMIDOR FINAL',
                        'identification_type': '07',
                        'email': 'consumidor@final.com',
                        'address': 'ECUADOR'
                    }
                )
            else:
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
                    
                    # VALIDACIÓN DE STOCK: Evitar negativos
                    if product.track_inventory and product.current_stock < qty:
                        raise ValueError(f"Stock insuficiente para {product.name}. Disponible: {product.current_stock}")
                        
                    price_inclusive = Decimal(str(item['price']))
                    discount_inclusive = Decimal(str(item.get('discount', 0)))
                    
                    tax_rate = product.tax_rate
                    
                    if tax_rate > 0:
                        rate_factor = Decimal('1') + (tax_rate / Decimal('100'))
                        price_exclusive = (price_inclusive / rate_factor).quantize(Decimal('0.000001')) # Mantener algo de precisión antes del final
                        discount_exclusive = (discount_inclusive / rate_factor).quantize(Decimal('0.01'))
                    else:
                        price_exclusive = price_inclusive
                        discount_exclusive = discount_inclusive
                        
                    line_subtotal_exclusive = ((qty * price_exclusive) - discount_exclusive).quantize(Decimal('0.01'))
                    
                    if tax_rate > 0:
                        subtotal_iva += line_subtotal_exclusive
                        total_tax += (line_subtotal_exclusive * (tax_rate / Decimal('100'))).quantize(Decimal('0.01'))
                    else:
                        subtotal_0 += line_subtotal_exclusive
                    
                    total_discount += discount_exclusive
                    
                    # Agregar a lista limpia para el XML
                    clean_items.append({
                        'id': item['id'],
                        'name': product.name,
                        'quantity': float(qty),
                        'price': float(price_exclusive),
                        'tax_rate': float(tax_rate),
                        'discount': float(discount_exclusive)
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
                
                # Registrar forma de pago real para el SRI
                from apps.sri_integration.models import DocumentPayment
                DocumentPayment.objects.create(
                    document=doc,
                    payment_method_code=payment_method_code,
                    amount=total_amount,
                    payment_term=0,
                    time_unit='dias'
                )
                # 2. Registrar ítems sanitizados en adicionales Y en tablas oficiales
                from apps.sri_integration.models import DocumentItem, DocumentTax
                for ci in clean_items:
                    prod = ProductTemplate.objects.get(id=ci['id'])
                    item_obj = DocumentItem.objects.create(
                        document=doc,
                        main_code=prod.main_code,
                        description=prod.name,
                        quantity=Decimal(str(ci['quantity'])),
                        unit_price=Decimal(str(ci['price'])).quantize(Decimal('0.000001')),
                        discount=Decimal(str(ci['discount'])).quantize(Decimal('0.01')),
                        subtotal=Decimal(str(ci['quantity'] * ci['price'] - ci.get('discount', 0))).quantize(Decimal('0.01'))
                    )
                    
                    # Registrar impuesto del ítem (Simplificado para el POS)
                    tax_rate = Decimal(str(ci['tax_rate']))
                    # Mapeo básico de porcentajes SRI (0:0%, 2:12%, 4:15%)
                    perc_code = '0' if tax_rate == 0 else '2' if tax_rate == 12 else '4' if tax_rate == 15 else '2'
                    
                    DocumentTax.objects.create(
                        document=doc,
                        item=item_obj,
                        tax_code='2', # IVA
                        percentage_code=perc_code,
                        rate=tax_rate,
                        taxable_base=item_obj.subtotal,
                        tax_amount=(item_obj.subtotal * (tax_rate / Decimal('100'))).quantize(Decimal('0.01'))
                    )

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

    # Cargar datos para el POS: Solo productos con stock > 0 o que no controlen inventario
    from django.db.models import Q
    products = ProductTemplate.objects.filter(
        company=company, 
        is_active=True
    ).filter(
        Q(track_inventory=False) | Q(current_stock__gt=0)
    ).order_by('name')
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

@login_required
@user_passes_test(is_admin)
def admin_reports_view(request):
    """Vista para reportes de ventas filtrados por fechas y vendedores."""
    from datetime import datetime
    from django.db import models
    from decimal import Decimal
    
    companies = get_user_companies_secure(request.user)
    if not companies.exists():
        messages.error(request, "No tienes una empresa asignada.")
        return redirect('home')
    company = companies.first()
    
    # Base query
    invoices = ElectronicDocument.objects.filter(
        company=company,
        document_type='INVOICE',
        status__in=['AUTHORIZED', 'DRAFT', 'PENDING']
    ).order_by('-issue_date', '-created_at')
    
    # Get filters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    seller_id = request.GET.get('seller_id')
    
    if start_date:
        invoices = invoices.filter(issue_date__gte=start_date)
    if end_date:
        invoices = invoices.filter(issue_date__lte=end_date)
    if seller_id:
        invoices = invoices.filter(created_by_id=seller_id)
        
    # Totals
    total_sales = invoices.count()
    total_revenue = invoices.aggregate(models.Sum('total_amount'))['total_amount__sum'] or Decimal('0')
    
    # Sellers for filter dropdown
    sellers = User.objects.filter(company=company, is_active=True).order_by('first_name')
    
    context = {
        'invoices': invoices,
        'total_sales': total_sales,
        'total_revenue': total_revenue,
        'sellers': sellers,
        'current_start': start_date,
        'current_end': end_date,
        'current_seller': int(seller_id) if seller_id else None
    }
    
    return render(request, 'admin/reports.html', context)

@login_required
@user_passes_test(is_admin)
def admin_orders_view(request):
    """Vista para gestión de Pedidos de clientes"""
    from apps.orders.models import Order
    companies = get_user_companies_secure(request.user)
    company = companies.first()
    
    pending_orders = []
    completed_orders = []
    
    if company:
        pending_orders = Order.objects.filter(company=company, status='PENDING').select_related('customer').order_by('-created_at')
        completed_orders = Order.objects.filter(company=company, status='COMPLETED').select_related('customer', 'seller', 'invoice').order_by('-created_at')

    context = {
        'company': company,
        'pending_orders': pending_orders,
        'completed_orders': completed_orders,
        'user': request.user,
    }
    return render(request, 'admin/orders.html', context)

@login_required
@user_passes_test(is_admin)
def admin_complete_order(request, pk):
    """Procesar un pedido desde la web (Acción manual del admin)"""
    from apps.orders.models import Order
    from apps.api.views.order_views import OrderViewSet
    from rest_framework.request import Request
    
    companies = get_user_companies_secure(request.user)
    order = get_object_or_404(Order, pk=pk, company__in=companies)
    
    # Obtener el tipo de documento (factura o nota_de_entrega)
    document_type = request.POST.get('document_type') or request.GET.get('document_type', 'factura')
    
    # Simular un request de DRF con datos
    from rest_framework.test import APIRequestFactory
    factory = APIRequestFactory()
    # Creamos un request POST aunque sea GET para que tenga .data
    drf_request = factory.post(f'/api/orders/{pk}/complete_and_invoice/', {'document_type': document_type})
    drf_request.user = request.user
    
    # Envolverlo en el Request de DRF que espera el viewset
    from rest_framework.request import Request as DRFRequest
    wrapped_request = DRFRequest(drf_request)
    
    # Forzar autenticación en el request de DRF
    from rest_framework.test import force_authenticate
    force_authenticate(wrapped_request, user=request.user)
    
    viewset = OrderViewSet()
    viewset.request = wrapped_request
    viewset.action = 'complete_and_invoice'
    viewset.kwargs = {'pk': pk}
    
    try:
        response = viewset.complete_and_invoice(wrapped_request, pk=pk)
        if response.status_code == 200:
            messages.success(request, f"Pedido #{pk} completado como {document_type} exitosamente.")
        else:
            error_msg = response.data.get('message', response.data.get('error', 'Error desconocido'))
            messages.error(request, f"Error al procesar pedido: {error_msg}")
    except Exception as e:
        messages.error(request, f"Error crítico: {str(e)}")
        
    return redirect('admin_orders')

@login_required
@user_passes_test(is_admin)
def admin_cancel_order(request, pk):
    """Cancelar un pedido desde la web (Reutiliza lógica del API)"""
    from apps.orders.models import Order
    from apps.api.views.order_views import OrderViewSet
    from rest_framework.request import Request
    
    companies = get_user_companies_secure(request.user)
    order = get_object_or_404(Order, pk=pk, company__in=companies)
    
    # Simular un request de DRF
    factory = Request(request)
    factory._user = request.user
    viewset = OrderViewSet()
    viewset.request = factory
    viewset.action = 'cancel'
    viewset.kwargs = {'pk': pk}
    
    response = viewset.cancel(factory, pk=pk)
    
    if response.status_code == 200:
        messages.success(request, "Pedido cancelado correctamente y stock revertido.")
    else:
        error_msg = response.data.get('message', response.data.get('error', 'Error desconocido'))
        messages.error(request, f"Error al cancelar pedido: {error_msg}")
        
    return redirect('admin_orders')
