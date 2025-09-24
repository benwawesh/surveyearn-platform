# custom_admin/urls.py
from django.urls import path
from django.shortcuts import redirect
from django.contrib import messages
from . import views

app_name = 'custom_admin'

urlpatterns = [
    # Authentication - redirect to main login
    path('', views.admin_dashboard, name='dashboard'),
    path('logout/', views.admin_logout, name='logout'),

    # Dashboard
    path('dashboard/', views.admin_dashboard, name='dashboard'),

    # User management - using UUID patterns
    path('users/', views.admin_users, name='users'),
    path('users/<uuid:user_id>/', views.admin_user_detail, name='user_detail'),
    path('users/<uuid:user_id>/adjust-balance/', views.adjust_user_balance, name='adjust_balance'),

    # Add these new deletion URLs
    path('users/<uuid:user_id>/delete/', views.delete_user, name='delete_user'),
    path('users/bulk-delete/', views.bulk_delete_users, name='bulk_delete_users'),
    path('users/delete-test-users/', views.delete_test_users, name='delete_test_users'),

    # Survey management - using UUID patterns
    path('surveys/', views.admin_surveys, name='surveys'),
    path('surveys/<uuid:survey_id>/', views.admin_survey_detail, name='survey_detail'),
    path('surveys/<uuid:survey_id>/edit/', views.admin_survey_edit, name='survey_edit'),
    path('surveys/<uuid:survey_id>/delete/', views.admin_survey_delete, name='survey_delete'),
    path('surveys/create/', views.admin_survey_create, name='survey_create'),
    path('surveys/<uuid:survey_id>/activate/', views.activate_survey, name='activate_survey'),
    path('surveys/<uuid:survey_id>/pause/', views.pause_survey, name='pause_survey'),

    # Withdrawal management - using UUID patterns
    path('withdrawals/', views.admin_withdrawals, name='withdrawals'),
    path('withdrawals/<uuid:withdrawal_id>/', views.admin_withdrawal_detail, name='withdrawal_detail'),
    path('withdrawals/<uuid:withdrawal_id>/approve/', views.approve_withdrawal, name='approve_withdrawal'),
    path('withdrawals/<uuid:withdrawal_id>/reject/', views.reject_withdrawal, name='reject_withdrawal'),
    path('withdrawals/<uuid:withdrawal_id>/process/', views.process_withdrawal, name='process_withdrawal'),

    # Transaction management - using UUID patterns
    path('transactions/', views.transactions, name='transactions'),
    path('transactions/<uuid:transaction_id>/', views.admin_transaction_detail, name='transaction_detail'),

    # Reports and analytics
    path('reports/', views.admin_reports, name='reports'),
    path('reports/export/', views.export_reports, name='export_reports'),

    # Question management - add these after your survey patterns
    path('surveys/<uuid:survey_id>/questions/', views.admin_survey_questions, name='survey_questions'),
    path('surveys/<uuid:survey_id>/questions/create/', views.admin_question_create, name='question_create'),
    path('surveys/<uuid:survey_id>/questions/<uuid:question_id>/edit/', views.admin_question_edit,
         name='question_edit'),
    path('surveys/<uuid:survey_id>/questions/<uuid:question_id>/delete/', views.admin_question_delete,
         name='question_delete'),

    path('reports/advanced/', views.admin_reports_advanced, name='reports_advanced'),
    path('surveys/<uuid:survey_id>/analytics/', views.survey_detailed_analytics, name='survey_analytics'),
    path('analytics/export/', views.export_analytics_data, name='export_analytics'),
    path('withdrawals/<uuid:withdrawal_id>/mpesa-process/', views.process_mpesa_withdrawal,
         name='process_mpesa_withdrawal'),
    path('mpesa/transactions/', views.admin_mpesa_transactions, name='mpesa_transactions'),

    # Settings management URLs
    path('settings/', views.settings_dashboard, name='settings_dashboard'),
    path('settings/edit/<uuid:setting_id>/', views.edit_setting, name='edit_setting'),
    path('settings/quick-edit/', views.quick_edit_settings, name='quick_update_setting'),
    path('settings/reset-defaults/', views.reset_to_defaults, name='reset_to_defaults'),
    path('settings/audit-log/', views.settings_audit_log, name='settings_audit_log'),
    path('settings/export/', views.export_settings, name='export_settings'),
    path('settings/initialize/', views.initialize_settings, name='initialize_settings'),
    path('api/settings/current/', views.current_values_api, name='current_settings_api'),

    # Financial Analytics
    path('analytics/', views.financial_analytics_dashboard, name='financial_analytics'),
    path('analytics/api/', views.financial_analytics_api, name='financial_analytics_api'),

    # Manual transaction and related features
    path('manual-transaction/', views.manual_transaction, name='manual_transaction'),
    path('transaction-search-users/', views.transaction_search_users, name='transaction_search_users'),
    path('export-transactions-csv/', views.export_transactions_csv, name='export_transactions_csv'),
    path('transaction-detail/<uuid:transaction_id>/', views.transaction_detail_modal, name='transaction_detail_modal'),

    # COMPLETE Tutorial Management URLs
    path('tutorials/', views.tutorials_dashboard, name='tutorials_dashboard'),
    path('tutorials/list/', views.tutorials_list, name='tutorials_list'),
    path('tutorials/create/', views.tutorial_create, name='tutorial_create'),
    path('tutorials/<uuid:tutorial_id>/', views.tutorial_detail, name='tutorial_detail'),
    path('tutorials/<uuid:tutorial_id>/edit/', views.tutorial_edit, name='tutorial_edit'),
    path('tutorials/<uuid:tutorial_id>/delete/', views.tutorial_delete, name='tutorial_delete'),
    path('tutorials/<uuid:tutorial_id>/toggle-status/', views.tutorial_toggle_status, name='tutorial_toggle_status'),

    # Category Management URLs - CORRECTED with UUID support
    path('tutorials/categories/', views.categories_list, name='categories_list'),
    path('tutorials/categories/create/', views.category_create, name='category_create'),
    path('tutorials/categories/<uuid:category_id>/edit/', views.category_edit, name='category_edit'),
    path('tutorials/categories/<uuid:category_id>/toggle-status/', views.category_toggle_status,
         name='category_toggle_status'),
    path('tutorials/categories/<uuid:category_id>/delete/', views.category_delete, name='category_delete'),

    # Tutorial User Progress
    path('tutorials/progress/', views.user_progress, name='user_progress'),

    # Tutorial API endpoints
    path('api/tutorials/analytics/', views.tutorial_analytics_api, name='tutorial_analytics_api'),
    path('api/tutorials/bulk-actions/', views.bulk_tutorial_actions, name='bulk_tutorial_actions'),
]