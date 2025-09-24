# accounts/urls.py
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Authentication URLs
    path('register/', views.user_register, name='register'),  # Now uses paid registration
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),

    # Paid Registration URLs (NEW)
    path('payment-confirmation/<uuid:user_id>/', views.payment_confirmation, name='payment_confirmation'),
    path('mpesa-callback/', views.mpesa_callback, name='mpesa_callback'),
    path('check-payment-status/', views.check_payment_status, name='check_payment_status'),

    # Main user pages
    path('dashboard/', views.user_dashboard, name='dashboard'),
    path('profile/', views.user_profile, name='profile'),
    path('profile/complete/', views.profile_complete, name='profile_complete'),

    # User activities
    path('transactions/', views.user_transactions, name='transactions'),
    path('withdrawals/', views.user_withdrawals, name='withdrawals'),
    path('withdrawals/request/', views.request_withdrawal, name='request_withdrawal'),

    # Account management
    path('change-password/', views.change_password, name='change_password'),
    path('verify-email/', views.verify_email, name='verify_email'),
    path('confirm-email/<str:token>/', views.confirm_email, name='confirm_email'),

    # AJAX endpoints
    path('ajax/profile-completion/', views.ajax_profile_completion, name='ajax_profile_completion'),

    # Default redirect to dashboard
    path('', views.user_dashboard, name='dashboard'),
    path('referrals/', views.referral_dashboard, name='referral_dashboard'),
    path('referrals/', views.referral_dashboard, name='referral_dashboard'),
    path('referrals/analytics/', views.referral_analytics_dashboard, name='referral_analytics'),
    path('api/referral-stats/', views.referral_stats_api, name='referral_stats_api'),
    path('api/referral-click/', views.ReferralClickTracker.as_view(), name='referral_click_tracker'),

]