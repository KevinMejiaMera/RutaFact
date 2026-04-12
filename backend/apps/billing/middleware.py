# -*- coding: utf-8 -*-
"""
Middleware para control de límites de facturación - INTEGRADO CON TU SISTEMA
apps/billing/middleware.py
"""

import json
import logging
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from apps.companies.models import CompanyAPIToken
from apps.billing.models import CompanyBillingProfile, InvoiceConsumption
from apps.api.user_company_helper import get_user_companies_exact, get_user_company_by_id_exact

logger = logging.getLogger(__name__)


class BillingLimitMiddleware(MiddlewareMixin):
    """
    Middleware que controla los límites de facturación antes de crear documentos SRI.
    El consumo de facturas se realiza en DocumentProcessor al recibir autorización del SRI.
    """

    # Endpoints que verifican saldo antes de procesar
    INVOICE_CREATION_ENDPOINTS = [
        '/api/sri/documents/create_invoice/',
        '/api/sri/documents/create_credit_note/',
        '/api/sri/documents/create_debit_note/',
        '/api/sri/documents/create_retention/',
        '/api/sri/documents/create_purchase_settlement/',
    ]

    def process_request(self, request):
        """
        Verificar que la empresa tenga saldo antes de procesar endpoints de creación.
        No consume — solo bloquea si no hay facturas disponibles.
        """
        # Solo aplicar a endpoints de creación de documentos
        if not any(request.path.startswith(endpoint) for endpoint in self.INVOICE_CREATION_ENDPOINTS):
            return None

        # Solo aplicar a métodos POST (creación)
        if request.method != 'POST':
            return None

        # Obtener la empresa del request usando el sistema existente
        company = self._get_company_from_request(request)
        if not company:
            logger.warning(f"🚫 BILLING: No se pudo identificar empresa para {request.path}")
            return JsonResponse({
                'error': 'BILLING_ERROR',
                'message': 'No se pudo identificar la empresa para verificar límites de facturación',
                'code': 'COMPANY_NOT_FOUND',
                'help': 'Asegúrate de enviar el token correcto o company_id válido',
                'supported_auth': [
                    'Authorization: Token YOUR_USER_TOKEN + company_id en el body',
                    'Authorization: Token VSR_COMPANY_TOKEN (sin company_id)'
                ]
            }, status=400)

        # Obtener o crear perfil de facturación
        billing_profile, created = CompanyBillingProfile.objects.get_or_create(
            company=company,
            defaults={
                'available_invoices': 0,
                'total_invoices_purchased': 0,
                'total_invoices_consumed': 0,
            }
        )

        if created:
            logger.info(f"✅ BILLING: Perfil de facturación creado para {company.business_name}")

        # Bloquear si no tiene facturas disponibles
        if billing_profile.available_invoices <= 0:
            logger.warning(f"🚫 BILLING LIMIT: Company {company.business_name} has no invoices remaining")
            return JsonResponse({
                'error': 'BILLING_LIMIT_EXCEEDED',
                'message': 'No tienes facturas disponibles. Debes comprar un plan para continuar.',
                'details': {
                    'company': company.business_name,
                    'ruc': company.ruc,
                    'available_invoices': billing_profile.available_invoices,
                    'total_purchased': billing_profile.total_invoices_purchased,
                    'total_consumed': billing_profile.total_invoices_consumed,
                },
                'actions': {
                    'buy_plan_url': '/billing/plans/',
                    'contact_admin': 'Contacta al administrador para activar tu plan',
                    'dashboard_url': '/billing/',
                },
                'code': 'NO_INVOICES_REMAINING'
            }, status=402)  # 402 Payment Required

        # Alerta de saldo bajo
        if hasattr(billing_profile, 'is_low_balance') and billing_profile.is_low_balance:
            logger.warning(
                f"⚠️ BILLING WARNING: Company {company.business_name} has low balance: "
                f"{billing_profile.available_invoices} invoices remaining"
            )

        # Adjuntar al request para uso posterior si se necesita
        request.billing_profile = billing_profile
        request.billing_company = company

        logger.info(f"✅ BILLING CHECK: Company {company.business_name} has {billing_profile.available_invoices} invoices remaining")

        return None

    def process_response(self, request, response):
        """
        El consumo de facturas se realiza en DocumentProcessor._consume_invoice_from_plan()
        únicamente cuando el documento queda con status AUTHORIZED.
        Este método no consume para evitar doble descuento.
        """
        return response

    def _get_company_from_request(self, request):
        """
        Extraer la empresa del request.

        Orden de prioridad:
        1. Token de empresa (vsr_...) en Authorization header
        2. Token de usuario + company_id en el body/params
        3. Sesión de usuario + company_id
        """
        try:
            # MÉTODO 1: Token de empresa (CompanyAPIToken)
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.startswith('Token '):
                token_key = auth_header.split(' ')[1]

                if token_key.startswith('vsr_'):
                    try:
                        company_token = CompanyAPIToken.objects.get(key=token_key, is_active=True)
                        if company_token.company.is_active:
                            logger.info(f"✅ BILLING: Company identified via CompanyAPIToken: {company_token.company.business_name}")
                            return company_token.company
                    except CompanyAPIToken.DoesNotExist:
                        logger.warning(f"❌ BILLING: Invalid company token: {token_key[:20]}...")

            # MÉTODO 2: Token de usuario + company_id
            if request.user and request.user.is_authenticated:
                company_id = None

                # Intentar obtener company_id desde el body RAW
                try:
                    if request.body and hasattr(request, 'content_type'):
                        content_type = getattr(request, 'content_type', request.META.get('CONTENT_TYPE', ''))
                        if 'application/json' in content_type:
                            body_unicode = request.body.decode('utf-8')
                            body_data = json.loads(body_unicode)
                            company_id = body_data.get('company') or body_data.get('company_id')
                            logger.info(f"✅ BILLING: Company ID extraído del body raw: {company_id}")
                except (json.JSONDecodeError, UnicodeDecodeError, AttributeError) as e:
                    logger.debug(f"⚠️ BILLING: No se pudo parsear body como JSON: {e}")

                # Fallback: desde request.data si está disponible
                if not company_id and hasattr(request, 'data') and request.data:
                    company_id = request.data.get('company') or request.data.get('company_id')
                    logger.info(f"✅ BILLING: Company ID extraído del request.data: {company_id}")

                # Fallback: desde query params
                if not company_id:
                    company_id = request.GET.get('company') or request.GET.get('company_id')
                    if company_id:
                        logger.info(f"✅ BILLING: Company ID extraído de query params: {company_id}")

                if company_id:
                    company = get_user_company_by_id_exact(company_id, request.user)
                    if company:
                        logger.info(f"✅ BILLING: Company identified via user token + company_id: {company.business_name}")
                        return company
                    else:
                        logger.warning(f"❌ BILLING: User {request.user.username} denied access to company {company_id}")

                # MÉTODO 3: Primera empresa del usuario si no hay company_id
                user_companies = get_user_companies_exact(request.user)
                if user_companies.exists():
                    first_company = user_companies.first()
                    logger.info(f"✅ BILLING: Using default company for user {request.user.username}: {first_company.business_name}")
                    return first_company
                else:
                    logger.warning(f"❌ BILLING: User {request.user.username} has no accessible companies")

            # MÉTODO 4: Desde sesión
            if hasattr(request, 'session') and request.session.get('selected_company_id'):
                session_company_id = request.session.get('selected_company_id')
                if request.user and request.user.is_authenticated:
                    company = get_user_company_by_id_exact(session_company_id, request.user)
                    if company:
                        logger.info(f"✅ BILLING: Company identified via session: {company.business_name}")
                        return company

        except Exception as e:
            logger.error(f"❌ BILLING: Error extracting company from request: {e}")

        return None

    def _extract_invoice_id_from_response(self, response):
        """Extraer ID del documento de la respuesta (para uso futuro)."""
        try:
            if hasattr(response, 'content'):
                data = json.loads(response.content.decode('utf-8'))
                return data.get('id') or data.get('document_id') or data.get('invoice_id') or data.get('clave_acceso')
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            pass
        return None

    def _extract_document_type_from_path(self, path):
        """Extraer tipo de documento del path (para uso futuro)."""
        type_mapping = {
            'create_invoice': 'invoice',
            'create_credit_note': 'credit_note',
            'create_debit_note': 'debit_note',
            'create_retention': 'retention',
            'create_purchase_settlement': 'purchase_settlement',
        }
        for endpoint, doc_type in type_mapping.items():
            if endpoint in path:
                return doc_type
        return 'unknown'

    def _get_client_ip(self, request):
        """Obtener IP del cliente."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')


# ========== FUNCIONES AUXILIARES PARA TESTING ==========

def check_billing_limits_manually(company_id, user=None):
    """Verificar límites de facturación manualmente (útil para testing)."""
    try:
        from apps.companies.models import Company

        if user and not user.is_superuser:
            company = get_user_company_by_id_exact(company_id, user)
        else:
            company = Company.objects.get(id=company_id, is_active=True)

        if not company:
            return {
                'error': True,
                'message': f'Company {company_id} not found or no access',
                'can_create_invoice': False
            }

        billing_profile, created = CompanyBillingProfile.objects.get_or_create(
            company=company,
            defaults={'available_invoices': 0}
        )

        return {
            'error': False,
            'company_name': company.business_name,
            'available_invoices': billing_profile.available_invoices,
            'total_purchased': billing_profile.total_invoices_purchased,
            'total_consumed': billing_profile.total_invoices_consumed,
            'can_create_invoice': billing_profile.available_invoices > 0,
            'is_low_balance': getattr(billing_profile, 'is_low_balance', False),
            'created_profile': created
        }

    except Exception as e:
        return {
            'error': True,
            'message': str(e),
            'can_create_invoice': False
        }


def simulate_invoice_creation(company_id, user=None, invoice_id='TEST-001'):
    """Simular creación de factura (útil para testing)."""
    billing_check = check_billing_limits_manually(company_id, user)

    if billing_check['error'] or not billing_check['can_create_invoice']:
        return {
            'success': False,
            'message': 'Cannot create invoice - billing limits exceeded',
            'billing_status': billing_check
        }

    try:
        from apps.companies.models import Company

        company = Company.objects.get(id=company_id, is_active=True)
        billing_profile = CompanyBillingProfile.objects.get(company=company)

        balance_before = billing_profile.available_invoices

        billing_profile.available_invoices -= 1
        billing_profile.total_invoices_consumed += 1
        billing_profile.save()

        balance_after = billing_profile.available_invoices

        InvoiceConsumption.objects.create(
            company=company,
            invoice_id=invoice_id,
            invoice_type='invoice',
            balance_before=balance_before,
            balance_after=balance_after,
            api_endpoint='/test/simulate_invoice_creation',
        )

        return {
            'success': True,
            'message': f'Invoice {invoice_id} created successfully',
            'balance_before': balance_before,
            'balance_after': balance_after,
            'remaining_invoices': balance_after
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Error simulating invoice creation: {str(e)}'
        }