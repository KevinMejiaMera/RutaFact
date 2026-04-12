# apps/custom_admin/urls.py
from django.urls import path
from . import views

app_name = 'custom_admin'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
    # Users CRUD
    path('users/', views.users_list, name='users'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/<int:user_id>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:user_id>/view/', views.user_view, name='user_view'),
    path('users/<int:user_id>/delete/', views.user_delete, name='user_delete'),
    path('users/<int:user_id>/toggle-status/', views.user_toggle_status, name='user_toggle_status'),
    
    # Companies CRUD
    path('companies/', views.companies_list, name='companies'),
    path('companies/create/', views.company_create, name='company_create'),
    path('companies/<int:company_id>/edit/', views.company_edit, name='company_edit'),
    path('companies/<int:company_id>/view/', views.company_view, name='company_view'),
    path('companies/<int:company_id>/delete/', views.company_delete, name='company_delete'),
    path('companies/<int:company_id>/toggle-status/', views.company_toggle_status, name='company_toggle_status'),
    path('companies/<int:company_id>/test-sri/', views.company_test_sri, name='company_test_sri'),
    path('companies/read-p12/', views.read_p12_data, name='company_read_p12'),
    
    # Certificates CRUD
    path('certificates/', views.certificates_list, name='certificates'),
    path('certificates/upload/', views.certificate_upload, name='certificate_upload'),
    path('certificates/<int:certificate_id>/view/', views.certificate_view, name='certificate_view'),
    path('certificates/<int:certificate_id>/edit/', views.certificate_edit, name='certificate_edit'),
    path('certificates/<int:certificate_id>/delete/', views.certificate_delete, name='certificate_delete'),
    path('certificates/<int:certificate_id>/validate/', views.certificate_validate, name='certificate_validate'),
    
    # Invoices
    path('invoices/', views.invoices_list, name='invoices'),
    path('invoices/create/', views.invoice_create, name='invoice_create'),
    path('invoices/<int:invoice_id>/view/', views.invoice_view, name='invoice_view'),
    path('invoices/<int:invoice_id>/edit/', views.invoice_edit, name='invoice_edit'),
    path('invoices/<int:invoice_id>/authorize/', views.invoice_authorize, name='invoice_authorize'),
    path('invoices/<int:invoice_id>/cancel/', views.invoice_cancel, name='invoice_cancel'),
    path('invoices/<int:invoice_id>/pdf/', views.invoice_pdf, name='invoice_pdf'),
    path('invoices/batch-authorize/', views.invoice_batch_authorize, name='invoice_batch_authorize'),
    
    # Customers (placeholder)
    path('customers/', views.customers_list, name='customers'),
    
    # Products (placeholder)
    path('products/', views.products_list, name='products'),
    
    # SRI Documents
    path('sri-documents/', views.sri_documents_list, name='sri_documents'),
    path('sri-documents/<int:document_id>/view/', views.sri_document_view, name='sri_document_view'),
    path('sri-documents/<int:document_id>/delete/', views.sri_document_delete, name='sri_document_delete'),
    path('sri-documents/<int:document_id>/authorize/', views.sri_document_authorize, name='sri_document_authorize'),
    path('sri-documents/<int:document_id>/download/', views.sri_document_download, name='sri_document_download'),
    path('sri-documents/<int:document_id>/cancel/', views.sri_document_cancel, name='sri_document_cancel'),
    path('sri-documents/<int:document_id>/resend/', views.sri_document_resend, name='sri_document_resend'),
    path('sri-documents/batch-process/', views.sri_documents_batch_process, name='sri_documents_batch_process'),
    
    # Billing / Planes
    path('billing/plans/', views.billing_plans_list, name='billing_plans'),
    path('billing/plans/create/', views.billing_plan_create, name='billing_plan_create'),
    path('billing/plans/<int:plan_id>/update/', views.billing_plan_update, name='billing_plan_update'), 
    path('billing/plans/<int:plan_id>/delete/', views.billing_plan_delete, name='billing_plan_delete'),

    # Compras de planes
    path('billing/purchases/', views.billing_purchases_list, name='billing_purchases'),
    path('billing/purchases/<uuid:purchase_id>/', views.billing_purchase_detail, name='billing_purchase_detail'),
    path('billing/purchases/<uuid:purchase_id>/approve/', views.billing_purchase_approve, name='billing_purchase_approve'),
    path('billing/purchases/<uuid:purchase_id>/reject/', views.billing_purchase_reject, name='billing_purchase_reject'),

    # Perfiles de facturación
    path('billing/profiles/', views.billing_company_profiles, name='billing_profiles'),
    path('billing/profiles/<int:company_id>/add-invoices/', views.billing_add_invoices, name='billing_add_invoices'),
   
    # Settings
    path('settings/', views.settings_list, name='settings'),
    path('settings/save/', views.settings_save, name='settings_save'),
    path('settings/test-email/', views.test_email, name='test_email'),
    path('settings/system/', views.system_settings, name='system_settings'),
    path('settings/companies/', views.company_settings, name='company_settings'),
    path('settings/storage/', views.storage_settings, name='storage_settings'),
    path('settings/storage/migrate/', views.storage_migrate, name='storage_migrate'),
    path('settings/storage/create-structure/', views.storage_create_structure, name='create_structure'),

    # Notifications
    path('notifications/', views.notifications_list, name='notifications'),
    path('notifications/<int:notification_id>/mark-read/', views.notification_mark_read, name='notification_mark_read'),
    path('notifications/<int:notification_id>/detail/', views.notification_detail, name='notification_detail'),
    path('notifications/mark-all-read/', views.notifications_mark_all_read, name='notifications_mark_all_read'),
    path('notifications/batch-mark-read/', views.notifications_batch_mark_read, name='notifications_batch_mark_read'),
    path('notifications/batch-delete/', views.notifications_batch_delete, name='notifications_batch_delete'),
    path('notifications/settings/', views.notification_settings, name='notification_settings'),

    # Audit Logs
    path('audit-logs/', views.audit_logs, name='audit_logs'),

    # Profile
    path('profile/', views.profile, name='profile'),
    path('profile/update/', views.profile_update, name='profile_update'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('profile/change-password/', views.change_password, name='change_password'),
    path('profile/sessions/', views.manage_sessions, name='manage_sessions'),
    path('profile/regenerate-token/', views.regenerate_token, name='regenerate_token'),

    # Export
    path('export/<str:model_name>/', views.export_data, name='export_data'),
    
    # API endpoints
    path('api/dashboard-stats/', views.dashboard_stats_api, name='dashboard_stats_api'),
    path('api/search/', views.global_search, name='global_search'),
]