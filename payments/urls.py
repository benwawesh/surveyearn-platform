# payments/urls.py

from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    # Wallet/Dashboard
    path('wallet/', views.wallet_dashboard, name='wallet_dashboard'),

    # Withdrawals - Updated to match your existing URL names
    path('withdraw/', views.request_withdrawal, name='withdraw_request'),
    path('withdraw/<uuid:withdrawal_id>/', views.withdrawal_detail, name='withdrawal_detail'),
    path('withdraw/<uuid:withdrawal_id>/cancel/', views.cancel_withdrawal, name='cancel_withdrawal'),
    path('withdrawals/', views.withdrawal_history, name='withdrawal_status'),

    # Transactions
    path('transactions/', views.transaction_history, name='transaction_history'),

    # AJAX endpoints
    path('api/calculate-fee/', views.calculate_withdrawal_fee, name='calculate_withdrawal_fee'),

    # M-Pesa callbacks (existing)
    path('mpesa-callback/', views.mpesa_callback, name='mpesa_callback'),
    path('mpesa/result/', views.mpesa_b2c_result, name='mpesa_b2c_result'),
    path('mpesa/timeout/', views.mpesa_timeout, name='mpesa_timeout'),

    # Legacy/placeholder URLs (keeping for compatibility)
    path('withdraw/success/', views.wallet_dashboard, name='withdraw_success'),
    path('payment-methods/', views.wallet_dashboard, name='payment_methods'),
    path('payment-methods/add/', views.request_withdrawal, name='add_payment_method'),
]