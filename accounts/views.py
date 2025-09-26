# accounts/views.py
import json
import requests
import base64
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db.models import Q
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import User
from django.db import transaction
from accounts.models import ReferralCommission
from accounts.services.settings_service import SettingsService
from .forms import (UserLoginForm, UserProfileForm,
    PasswordChangeForm, EmailVerificationForm, PaidUserRegistrationForm  # Add this import
)
from payments.mpesa import initiate_stk_push
import uuid
import secrets
from payments.mpesa import MPesaService
from surveyearn.services.email_service import EmailService
import logging

logger = logging.getLogger(__name__)

def user_register(request):
    """Paid user registration with M-Pesa STK push and referral processing"""
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    # Use SettingsService for dynamic configuration
    settings_service = SettingsService()

    # Check for referral info in session
    referral_info = None
    referral_code = request.session.get('referral_code')

    if referral_code:
        try:
            referrer = User.objects.get(referral_code=referral_code)
            # Use dynamic fee and commission rate
            amount = settings_service.get_registration_fee()
            commission_rate = settings_service.get_referral_commission_rate()

            # Only show commission info for non-admin/staff referrers
            if referrer.is_staff or referrer.is_superuser:
                commission_amount = Decimal('0.00')  # No commission for admin/staff
                logger.info(
                    f"Registration with admin/staff referral from {referrer.username} - no commission will be paid")
            else:
                commission_amount = Decimal(str(amount)) * commission_rate
                logger.info(f"Registration with referral from {referrer.username}")

            referral_info = {
                'referrer_name': referrer.get_full_name() or referrer.username,
                'referrer_username': referrer.username,
                'referral_code': referral_code,
                'commission_amount': commission_amount,
                'registration_fee': amount,
                'is_admin_staff': referrer.is_staff or referrer.is_superuser
            }

        except User.DoesNotExist:
            logger.warning(f"Invalid referral code in session: {referral_code}")
            # Clean up invalid referral code
            del request.session['referral_code']
            if 'referrer_username' in request.session:
                del request.session['referrer_username']

    if request.method == 'POST':
        form = PaidUserRegistrationForm(request.POST)

        if form.is_valid():
            # Create user account (inactive until payment)
            user = form.save()

            # Process referral relationship with atomic transaction and verification
            referral_code = request.session.get('referral_code')
            referral_established = False

            if referral_code:
                try:
                    # Use atomic transaction to ensure consistency
                    with transaction.atomic():
                        referrer = User.objects.get(referral_code=referral_code)

                        # Set the referral relationship
                        user.referred_by = referrer
                        user.save()

                        # Update referrer's total count (even for admin/staff for tracking purposes)
                        referrer.total_referrals += 1
                        referrer.save()

                        # Verify the relationship was saved correctly
                        user.refresh_from_db()
                        if user.referred_by == referrer:
                            referral_established = True

                            # Different logging for admin/staff vs regular referrers
                            if referrer.is_staff or referrer.is_superuser:
                                logger.info(
                                    f"User {user.username} referred by admin/staff {referrer.username} (no commission)")
                            else:
                                logger.info(f"User {user.username} successfully referred by {referrer.username}")
                        else:
                            logger.error(f"Failed to establish referral relationship for {user.username}")

                        # Only clear session if relationship was successfully established
                        if referral_established:
                            if 'referral_code' in request.session:
                                del request.session['referral_code']
                            if 'referrer_username' in request.session:
                                del request.session['referrer_username']
                            if 'referral_message' in request.session:
                                del request.session['referral_message']

                except User.DoesNotExist:
                    logger.error(f"Referral code {referral_code} not found during registration")
                except Exception as e:
                    logger.error(f"Error processing referral for {user.username}: {str(e)}")
                    import traceback
                    traceback.print_exc()

            # Prepare M-Pesa STK Push
            phone_number = form.cleaned_data['phone_number']
            username = form.cleaned_data['username']
            # Use dynamic fee from settings
            amount = settings_service.get_registration_fee()

            # Format phone number properly
            formatted_phone = MPesaService.format_phone_number(phone_number)

            # Validate phone number
            if not MPesaService.validate_phone_number(formatted_phone):
                user.delete()
                messages.error(request, "Please enter a valid Kenyan phone number (07XX XXX XXX or 01XX XXX XXX)")
                return render(request, 'accounts/register.html', {
                    'form': form,
                    'title': 'Register for SurveyEarn',
                    'registration_fee': amount,
                    'referral_info': referral_info
                })

            # Trigger M-Pesa STK Push
            stk_response = initiate_stk_push(
                phone_number=formatted_phone,
                amount=amount,
                account_reference=username,
                transaction_desc=f"SurveyEarn registration fee for {username}"
            )

            if stk_response.get('success'):
                # Store the checkout request ID for verification
                user.mpesa_checkout_request_id = stk_response.get('checkout_request_id')
                user.registration_amount = amount
                user.phone_number = formatted_phone
                user.save()

                # CREATE REGISTRATION TRANSACTION RECORD FOR ADMIN DASHBOARD
                try:
                    from payments.models import Transaction
                    transaction_record = Transaction.objects.create(
                        user=user,
                        transaction_type='registration',
                        amount=amount,
                        status='pending',
                        description=f"Registration fee for {username}",
                        reference_id=stk_response.get('checkout_request_id'),
                        balance_before=Decimal('0.00'),  # New users start with 0 balance
                        balance_after=Decimal('0.00'),   # Registration doesn't add to balance
                        notes=f"STK Push initiated for {formatted_phone}"
                    )
                    logger.info(f"Registration transaction created: {transaction_record.id} for user: {username}")
                except Exception as e:
                    logger.error(f"Failed to create registration transaction for {username}: {e}")
                    # Don't fail the registration if transaction creation fails
                    import traceback
                    traceback.print_exc()

                # CREATE MPESA TRANSACTION RECORD FOR TRACKING
                try:
                    from payments.models import MPesaTransaction
                    mpesa_transaction = MPesaTransaction.objects.create(
                        user=user,
                        transaction_type='stk_push',
                        amount=amount,
                        phone_number=formatted_phone,
                        checkout_request_id=stk_response.get('checkout_request_id'),
                        merchant_request_id=stk_response.get('merchant_request_id'),
                        status='pending',
                        api_response=stk_response
                    )
                    logger.info(f"M-Pesa transaction record created: {mpesa_transaction.id}")
                except Exception as e:
                    logger.error(f"Failed to create M-Pesa transaction record: {e}")

                # Send welcome email
                try:
                    EmailService.send_welcome_email(user)
                    logger.info(f"Welcome email sent to {user.email}")
                except Exception as e:
                    logger.error(f"Failed to send welcome email to {user.email}: {e}")

                # Success message with proper admin/staff handling
                if user.referred_by:
                    if user.referred_by.is_staff or user.referred_by.is_superuser:
                        # Admin/staff referral - mention referrer but no commission
                        messages.success(request,
                                         f"Registration initiated! You were referred by {user.referred_by.get_full_name() or user.referred_by.username}. "
                                         f"Please complete payment of KSh {amount} on your phone ({formatted_phone}) to activate your account.")
                    else:
                        # Regular referral - mention commission
                        messages.success(request,
                                         f"Registration initiated! You were referred by {user.referred_by.get_full_name() or user.referred_by.username}. "
                                         f"Please complete payment of KSh {amount} on your phone ({formatted_phone}) to activate your account.")
                else:
                    messages.success(request,
                                     f"Registration initiated! Please complete payment of KSh {amount} "
                                     f"on your phone ({formatted_phone}) to activate your account.")

                return redirect('accounts:payment_confirmation', user_id=user.id)
            else:
                # STK Push failed - clean up user record
                user.delete()
                error_msg = stk_response.get('error', 'Payment system temporarily unavailable')
                logger.error(f"STK Push failed for {username}: {error_msg}")
                messages.error(request, f"Payment initiation failed: {error_msg}")

        else:
            messages.error(request, "Please correct the errors below.")

    else:
        form = PaidUserRegistrationForm()

    # Use SettingsService for dynamic context values
    context = {
        'form': form,
        'title': 'Register for SurveyEarn',
        'registration_fee': settings_service.get_registration_fee(),
        'referral_info': referral_info,
        'commission_rate': int(settings_service.get_referral_commission_rate() * 100)
    }
    return render(request, 'accounts/register.html', context)

def user_login(request):
    """User login view"""
    if request.user.is_authenticated:
        # Check if user is staff and redirect to appropriate dashboard
        if request.user.is_staff:
            return redirect('/management/')
        return redirect('surveys:survey_list')

    if request.method == 'POST':
        form = UserLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']

            user = authenticate(request, username=username, password=password)
            if user is not None:
                if user.is_active:
                    login(request, user)

                    # Check if user is staff and redirect accordingly
                    if user.is_staff:
                        messages.success(request, f'Welcome back, {user.first_name or user.username}!')
                        return redirect('/management/')
                    else:
                        # Regular user redirect
                        next_page = request.GET.get('next', 'surveys:survey_list')
                        messages.success(request, f'Welcome back, {user.first_name or user.username}!')
                        return redirect(next_page)
                else:
                    messages.error(request, 'Your account has been deactivated.')
            else:
                messages.error(request, 'Invalid username or password.')

    else:
        form = UserLoginForm()

    context = {
        'form': form,
        'title': 'Login'
    }
    return render(request, 'accounts/login.html', context)



@login_required
def user_logout(request):
    """User logout view"""
    username = request.user.username
    logout(request)
    messages.success(request, f'Goodbye {username}! You have been logged out.')
    return redirect('landing_page')


@login_required
def user_dashboard(request):
    """User dashboard with overview of activities"""
    user = request.user

    # Get user's recent transactions
    recent_transactions = user.get_recent_transactions(5)

    # Get available surveys
    available_surveys = user.get_available_surveys()[:5]

    # Get pending withdrawals
    pending_withdrawals = user.get_pending_withdrawals()

    # Get recent survey responses
    recent_responses = user.survey_responses.select_related('survey').order_by('-completed_at')[:5]

    # Calculate stats
    stats = {
        'total_balance': user.balance,
        'total_earnings': user.total_earnings,
        'surveys_completed': user.total_surveys_completed,
        'surveys_this_month': user.surveys_completed_this_month,
        'earnings_this_month': user.earnings_this_month,
        'available_surveys_count': available_surveys.count(),
        'pending_withdrawals_count': pending_withdrawals.count(),
        'profile_completion': user.profile_completion_percentage,
    }

    context = {
        'user': user,
        'stats': stats,
        'recent_transactions': recent_transactions,
        'available_surveys': available_surveys,
        'pending_withdrawals': pending_withdrawals,
        'recent_responses': recent_responses,
        'can_take_surveys': user.can_take_surveys(),
        'eligibility_issues': user.survey_eligibility_issues,
    }

    return render(request, 'accounts/dashboard.html', context)



@login_required
def user_profile(request):
    """User profile view and edit"""
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save()
            user.update_profile_completion_status()
            messages.success(request, 'Profile updated successfully!')
            return redirect('accounts:profile')
    else:
        form = UserProfileForm(instance=request.user)

    context = {
        'form': form,
        'user': request.user,
        'profile_completion': request.user.profile_completion_percentage,
        'title': 'My Profile'
    }
    return render(request, 'accounts/profile.html', context)



@login_required
def profile_complete(request):
    """Profile completion wizard for new users"""
    user = request.user

    if user.profile_completed:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=user)
        if form.is_valid():
            user = form.save()
            user.update_profile_completion_status()

            if user.profile_completed:
                messages.success(request, 'Profile completed! You can now start taking surveys.')
                return redirect('accounts:dashboard')
            else:
                messages.warning(request, 'Please complete all required fields to start taking surveys.')
    else:
        form = UserProfileForm(instance=user)

    context = {
        'form': form,
        'user': user,
        'profile_completion': user.profile_completion_percentage,
        'required_fields': ['first_name', 'last_name', 'email', 'date_of_birth'],
        'title': 'Complete Your Profile'
    }
    return render(request, 'accounts/profile_complete.html', context)



@login_required
def user_transactions(request):
    """User transaction history"""
    transactions = request.user.get_recent_transactions(limit=None)

    # Filter by transaction type
    transaction_type = request.GET.get('type', '')
    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)

    # Filter by date range
    date_filter = request.GET.get('date', '')
    if date_filter == 'week':
        week_ago = timezone.now() - timezone.timedelta(days=7)
        transactions = transactions.filter(created_at__gte=week_ago)
    elif date_filter == 'month':
        transactions = transactions.filter(created_at__month=timezone.now().month)

    # Pagination
    paginator = Paginator(transactions, 20)
    page_number = request.GET.get('page')
    transactions = paginator.get_page(page_number)

    context = {
        'transactions': transactions,
        'transaction_type': transaction_type,
        'date_filter': date_filter,
        'title': 'Transaction History'
    }
    return render(request, 'accounts/transaction_history.html', context)



@login_required
def user_surveys(request):
    """User's available and completed surveys"""
    # Available surveys
    available_surveys = request.user.get_available_surveys()

    # Completed surveys
    completed_responses = request.user.survey_responses.select_related('survey').order_by('-completed_at')

    # Search functionality for available surveys
    search_query = request.GET.get('search', '')
    if search_query:
        available_surveys = available_surveys.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    # Filter by payout range
    payout_filter = request.GET.get('payout', '')
    if payout_filter == 'low':
        available_surveys = available_surveys.filter(payout__lt=5)
    elif payout_filter == 'medium':
        available_surveys = available_surveys.filter(payout__gte=5, payout__lt=15)
    elif payout_filter == 'high':
        available_surveys = available_surveys.filter(payout__gte=15)

    # Pagination for available surveys
    paginator = Paginator(available_surveys, 12)
    page_number = request.GET.get('page')
    available_surveys = paginator.get_page(page_number)

    context = {
        'available_surveys': available_surveys,
        'completed_responses': completed_responses[:10],  # Show recent 10
        'search_query': search_query,
        'payout_filter': payout_filter,
        'can_take_surveys': request.user.can_take_surveys(),
        'eligibility_issues': request.user.survey_eligibility_issues,
        'title': 'Surveys'
    }
    return render(request, 'accounts/surveys.html', context)



@login_required
def user_withdrawals(request):
    """User withdrawal requests and payment methods"""
    withdrawals = request.user.withdrawal_requests.order_by('-created_at')
    payment_methods = request.user.get_payment_methods()

    # Pagination for withdrawals
    paginator = Paginator(withdrawals, 15)
    page_number = request.GET.get('page')
    withdrawals = paginator.get_page(page_number)

    context = {
        'withdrawals': withdrawals,
        'payment_methods': payment_methods,
        'user': request.user,
        'minimum_withdrawal': getattr(settings, 'MINIMUM_WITHDRAWAL_AMOUNT', 10.00),
        'title': 'Withdrawals'
    }
    return render(request, 'accounts/withdrawals.html', context)



@login_required
def change_password(request):
    """Change user password"""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            # Update session to prevent logout
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, user)
            messages.success(request, 'Password changed successfully!')
            return redirect('accounts:profile')
    else:
        form = PasswordChangeForm(request.user)

    context = {
        'form': form,
        'title': 'Change Password'
    }
    return render(request, 'accounts/change_password.html', context)



@login_required
def verify_email(request):
    """Email verification view"""
    user = request.user

    if user.email_verified:
        messages.info(request, 'Your email is already verified.')
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        # Send verification email
        send_verification_email(user)
        messages.success(request, 'Verification email sent! Please check your inbox.')
        return redirect('accounts:verify_email')

    context = {
        'user': user,
        'title': 'Verify Email'
    }
    return render(request, 'accounts/verify_email.html', context)



def confirm_email(request, token):
    """Confirm email with token"""
    try:
        # In a real implementation, you'd verify the token properly
        # For now, we'll just mark email as verified
        user = request.user if request.user.is_authenticated else None
        if user:
            user.email_verified = True
            user.save()
            user.update_profile_completion_status()
            messages.success(request, 'Email verified successfully!')
        else:
                    messages.error(request, 'Invalid verification link.')

    except:
                    messages.error(request, 'Invalid verification link.')


    return redirect('accounts:dashboard' if request.user.is_authenticated else 'accounts:login')


def payment_confirmation(request, user_id):
    """Show payment confirmation page with real-time polling"""

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        messages.error(request, "Invalid user.")
        return redirect('accounts:register')

    # If user is already activated, redirect to success
    if user.registration_paid and user.is_active:
        messages.success(request, "Your registration is already complete! You can now login.")
        return redirect('accounts:login')

    # If user doesn't have a checkout request ID, something went wrong
    if not user.mpesa_checkout_request_id:
        messages.error(request, "Payment session not found. Please try registering again.")
        return redirect('accounts:register')

    context = {
        'user': user,
        'checkout_request_id': user.mpesa_checkout_request_id,
        'registration_fee': user.registration_amount or getattr(settings, 'REGISTRATION_FEE', 1),
        # Add these missing variables that your template expects:
        'amount': user.registration_amount or getattr(settings, 'REGISTRATION_FEE', 1),
        'phone_number': user.phone_number,
        'title': 'Complete Your Payment - SurveyEarn'
    }

    return render(request, 'accounts/payment_confirmation.html', context)


@csrf_exempt
@require_http_methods(["POST"])
def mpesa_callback(request):
    """Handle M-Pesa STK Push callback notifications with referral commission processing"""

    try:
        # Parse the callback data
        callback_data = json.loads(request.body.decode('utf-8'))
        logger.info(f"M-Pesa callback received: {callback_data}")

        # Extract callback information
        stk_callback = callback_data.get('Body', {}).get('stkCallback', {})
        checkout_request_id = stk_callback.get('CheckoutRequestID')
        result_code = stk_callback.get('ResultCode')

        if not checkout_request_id:
            logger.warning("M-Pesa callback missing CheckoutRequestID")
            return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Missing CheckoutRequestID'})

        # Find the user with this checkout request ID
        try:
            user = User.objects.get(mpesa_checkout_request_id=checkout_request_id)
        except User.DoesNotExist:
            logger.warning(f"No user found for checkout request ID: {checkout_request_id}")
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

        # Get settings service for dynamic configuration
        settings_service = SettingsService()

        # Get channel layer for WebSocket communication
        channel_layer = get_channel_layer()
        group_name = f'payment_{user.id}'

        if result_code == 0:  # Payment successful
            # Extract payment details from callback metadata
            callback_metadata = stk_callback.get('CallbackMetadata', {}).get('Item', [])
            receipt_number = None
            amount = None
            phone_number = None

            for item in callback_metadata:
                name = item.get('Name')
                value = item.get('Value')

                if name == 'MpesaReceiptNumber':
                    receipt_number = value
                elif name == 'Amount':
                    amount = value
                elif name == 'PhoneNumber':
                    phone_number = value

            # CRITICAL: Use database transaction for all updates
            with transaction.atomic():
                # Get dynamic settings for processing
                expected_fee = settings_service.get_registration_fee()
                commission_rate = settings_service.get_referral_commission_rate()
                auto_approve = settings_service.auto_approve_referral_commissions()

                # Verify payment amount matches expected registration fee
                if amount and Decimal(str(amount)) != expected_fee:
                    logger.warning(f"Payment amount mismatch: expected KSh {expected_fee}, received KSh {amount}")

                # Update user account
                user.registration_paid = True
                user.is_active = True
                user.registration_payment_date = timezone.now()
                user.mpesa_receipt_number = receipt_number or checkout_request_id[:10]

                if amount:
                    user.registration_amount = amount

                user.save()

                logger.info(f"User {user.username} payment confirmed via callback. Receipt: {receipt_number}")

                # UPDATE EXISTING REGISTRATION TRANSACTION (FIXED)
                registration_amount = Decimal(str(amount or user.registration_amount or expected_fee))
                try:
                    from payments.models import Transaction

                    # Find the pending registration transaction created during registration
                    registration_transaction = Transaction.objects.get(
                        user=user,
                        transaction_type='registration',
                        reference_id=checkout_request_id,
                        status='pending'
                    )

                    # Update it to completed
                    registration_transaction.status = 'completed'
                    registration_transaction.processed_at = timezone.now()
                    registration_transaction.notes += f' | M-Pesa Receipt: {receipt_number or "N/A"}'
                    registration_transaction.save()

                    logger.info(f"Registration transaction updated to completed: {registration_transaction.id}")

                except Transaction.DoesNotExist:
                    logger.warning(
                        f"No pending registration transaction found for {user.username} with checkout ID: {checkout_request_id}")

                    # Fallback: Create a new registration transaction if none exists
                    registration_transaction = Transaction.objects.create(
                        user=user,
                        transaction_type='registration',
                        amount=registration_amount,
                        status='completed',
                        description=f'Registration fee payment via M-Pesa. Receipt: {receipt_number or "N/A"}',
                        reference_id=checkout_request_id,
                        processed_at=timezone.now(),
                        balance_before=Decimal('0.00'),
                        balance_after=Decimal('0.00')
                    )
                    logger.info(f"New registration transaction created: {registration_transaction.id}")

                except Exception as e:
                    logger.error(f"Error updating registration transaction for {user.username}: {str(e)}")
                    # Don't fail the payment processing if transaction update fails

                # Update MPesa transaction record if exists
                try:
                    from payments.models import MPesaTransaction
                    mpesa_transaction = MPesaTransaction.objects.get(
                        checkout_request_id=checkout_request_id
                    )
                    mpesa_transaction.status = 'completed'
                    mpesa_transaction.result_code = str(result_code)
                    mpesa_transaction.mpesa_receipt_number = receipt_number
                    mpesa_transaction.api_response = callback_data
                    mpesa_transaction.save()
                    logger.info(f"M-Pesa transaction updated: {mpesa_transaction.id}")
                except MPesaTransaction.DoesNotExist:
                    logger.info(f"No M-Pesa transaction record found for {checkout_request_id}")
                except Exception as e:
                    logger.error(f"Error updating M-Pesa transaction: {str(e)}")

                # ENHANCED: Create referral commission with duplicate prevention
                commission_created = False
                if user.referred_by:
                    # Check if referrer is admin/staff - they shouldn't earn commissions
                    if user.referred_by.is_staff or user.referred_by.is_superuser:
                        logger.info(f"Skipping commission for admin/staff referrer: {user.referred_by.username}")
                    else:
                        try:
                            # Check for existing commission first to prevent duplicates
                            existing_commission = ReferralCommission.objects.filter(
                                referrer=user.referred_by,
                                referred_user=user,
                                commission_type='registration'
                            ).first()

                            if existing_commission:
                                logger.info(
                                    f"Commission already exists for {user.username} -> {user.referred_by.username}")
                                commission_created = True  # Mark as created for messaging purposes
                            else:
                                # Import the service at the top of your file
                                from accounts.services.referral_service import ReferralService

                                commission = ReferralService.create_registration_commission(user)

                                if commission:
                                    commission_created = True
                                    logger.info(
                                        f"Registration commission created: {commission.referrer.username} earns KSh {commission.commission_amount}")

                                    # Use dynamic auto-approval setting
                                    if auto_approve:
                                        result = ReferralService.process_pending_commissions(
                                            referrer_user=user.referred_by,
                                            auto_approve=True
                                        )
                                        logger.info(
                                            f"Auto-approved commission: KSh {result['total_amount']} to {user.referred_by.username}")
                                else:
                                    logger.error(
                                        f"ReferralService.create_registration_commission returned None for {user.username}")

                        except Exception as e:
                            logger.error(f"Error creating referral commission for {user.username}: {str(e)}")
                            import traceback
                            logger.error(traceback.format_exc())
                else:
                    logger.info(f"User {user.username} has no referrer - no commission to create")

            # Send payment confirmation email
            try:
                EmailService.send_payment_confirmation_email(
                    user=user,
                    amount=str(amount or user.registration_amount or expected_fee),
                    receipt_number=receipt_number or 'N/A'
                )
                logger.info(f"Payment confirmation email sent to {user.email}")
            except Exception as e:
                logger.error(f"Failed to send payment confirmation email to {user.email}: {e}")

            # Send WebSocket notification for successful payment
            if channel_layer:
                success_message = 'Payment successful! Your account is now active.'
                if user.referred_by and not (
                        user.referred_by.is_staff or user.referred_by.is_superuser) and commission_created:
                    payment_amount = Decimal(str(amount or user.registration_amount or expected_fee))
                    commission_amount = payment_amount * commission_rate
                    success_message += f' Your referrer {user.referred_by.get_full_name() or user.referred_by.username} will earn KSh {commission_amount}.'
                elif user.referred_by and (user.referred_by.is_staff or user.referred_by.is_superuser):
                    success_message += f' You were referred by {user.referred_by.get_full_name() or user.referred_by.username}.'

                async_to_sync(channel_layer.group_send)(
                    group_name,
                    {
                        'type': 'payment_update',
                        'data': {
                            'type': 'payment_success',
                            'status': 'success',
                            'message': success_message,
                            'data': {
                                'receipt_number': receipt_number or 'N/A',
                                'amount': str(amount or user.registration_amount or expected_fee),
                                'username': user.username,
                                'referrer': user.referred_by.username if user.referred_by else None
                            }
                        }
                    }
                )

        else:
            # Payment failed
            logger.info(f"Payment failed for user {user.username}. Result code: {result_code}")

            # Update transaction status to failed
            try:
                from payments.models import Transaction
                registration_transaction = Transaction.objects.get(
                    user=user,
                    transaction_type='registration',
                    reference_id=checkout_request_id,
                    status='pending'
                )
                registration_transaction.status = 'failed'
                registration_transaction.notes += f' | Payment failed: Code {result_code}'
                registration_transaction.save()
                logger.info(f"Registration transaction marked as failed: {registration_transaction.id}")
            except Transaction.DoesNotExist:
                logger.warning(f"No pending transaction found to mark as failed for {user.username}")
            except Exception as e:
                logger.error(f"Error marking transaction as failed: {str(e)}")

            # Send WebSocket notification for failed payment
            if channel_layer:
                failure_messages = {
                    '1032': 'Payment was cancelled by user',
                    '1': 'Payment failed due to insufficient funds',
                    '1001': 'Payment failed',
                    '1019': 'Payment failed - transaction timeout'
                }

                failure_message = failure_messages.get(
                    str(result_code),
                    f'Payment failed (Code: {result_code})'
                )

                async_to_sync(channel_layer.group_send)(
                    group_name,
                    {
                        'type': 'payment_update',
                        'data': {
                            'type': 'payment_failed',
                            'status': 'failed',
                            'message': failure_message
                        }
                    }
                )

        # Always return success to M-Pesa to prevent retries
        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

    except json.JSONDecodeError:
        logger.error("Invalid JSON in M-Pesa callback")
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Invalid JSON'})

    except Exception as e:
        logger.error(f"Error processing M-Pesa callback: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Processing error'})


@csrf_exempt
@require_http_methods(["POST"])
def check_payment_status(request):
    """
    AJAX endpoint to check M-Pesa payment status
    Expects JSON with checkout_request_id and user_id
    """
    try:
        # Parse JSON data from request body
        data = json.loads(request.body)
        checkout_request_id = data.get('checkout_request_id')
        user_id = data.get('user_id')

        if not checkout_request_id or not user_id:
            return JsonResponse({
                'status': 'error',
                'message': 'Missing required parameters (checkout_request_id, user_id)'
            }, status=400)

        # Get the user
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': 'User not found'
            }, status=404)

        # Verify the checkout request ID matches the user
        if user.mpesa_checkout_request_id != checkout_request_id:
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid checkout request ID for this user'
            }, status=400)

        # Check if user is already activated (payment already processed)
        if user.registration_paid and user.is_active:
            return JsonResponse({
                'status': 'success',
                'message': 'Payment already confirmed',
                'amount': str(user.registration_amount or 1),
                'receipt_number': user.mpesa_receipt_number or 'N/A'
            })

        # Query M-Pesa API directly to check payment status
        mpesa_service = MPesaService()
        try:
            status_response = mpesa_service.query_transaction_status(checkout_request_id)
            logger.info(f"M-Pesa status query for {checkout_request_id}: {status_response}")

            if status_response.get('success'):
                result = status_response.get('result', {})
                result_code = result.get('ResultCode')

                if result_code == '0':  # Payment successful
                    user.registration_paid = True
                    user.is_active = True
                    user.registration_payment_date = timezone.now()
                    user.mpesa_receipt_number = result.get('ReceiptNumber', checkout_request_id[:10])
                    user.save()

                    logger.info(f"Payment confirmed for user {user.username}, receipt: {user.mpesa_receipt_number}")

                    # Send payment confirmation email
                    try:
                        EmailService.send_payment_confirmation_email(
                            user=user,
                            amount=str(user.registration_amount or 1),
                            receipt_number=user.mpesa_receipt_number
                        )
                        logger.info(f"Payment confirmation email sent to {user.email}")
                    except Exception as e:
                        logger.error(f"Failed to send payment confirmation email to {user.email}: {e}")
                        # Don't fail the payment process if email fails

                    return JsonResponse({
                        'status': 'success',
                        'message': 'Payment confirmed successfully',
                        'amount': str(user.registration_amount or 1),
                        'receipt_number': user.mpesa_receipt_number
                    })
                elif result_code in ['1032', '1', '1001', '1019']:  # Failed/Cancelled
                    return JsonResponse({
                        'status': 'failed',
                        'message': 'Payment failed or was cancelled'
                    })
                else:
                    # Still pending or unknown status
                    return JsonResponse({
                        'status': 'pending',
                        'message': f'Payment processing... (Status: {result_code})'
                    })
            else:
                # API call failed or still pending
                return JsonResponse({
                    'status': 'pending',
                    'message': 'Checking payment status...'
                })

        except Exception as e:
            logger.error(f"Error querying M-Pesa status: {e}")
            return JsonResponse({
                'status': 'pending',
                'message': 'Verifying payment...'
            })

    except json.JSONDecodeError:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid JSON data'
        }, status=400)

    except Exception as e:
        logger.error(f"Error in check_payment_status: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Internal server error'
        }, status=500)

# Helper functions (keep your existing ones)
def send_welcome_email(user):
    """Send welcome email to new user"""
    if hasattr(settings, 'EMAIL_HOST') and settings.EMAIL_HOST:
        try:
            subject = 'Welcome to SurveyEarn!'
            message = f"""
            Hi {user.first_name or user.username},

            Welcome to SurveyEarn! Thank you for joining our community and completing your registration payment.

            To get started:
            1. Complete your profile
            2. Verify your email address
            3. Start taking surveys and earning money!

            Best regards,
            The SurveyEarn Team
            """

            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=True,
            )
        except:
            pass  # Email sending failed, but don't block registration


def send_verification_email(user):
    """Send email verification link"""
    if hasattr(settings, 'EMAIL_HOST') and settings.EMAIL_HOST:
        try:
            token = secrets.token_urlsafe(32)
            verification_url = request.build_absolute_uri(
                reverse('accounts:confirm_email', args=[token])
            )

            subject = 'Verify your email address'
            message = f"""
            Hi {user.first_name or user.username},

            Please click the link below to verify your email address:
            {verification_url}

            If you didn't request this, please ignore this email.

            Best regards,
            The SurveyEarn Team
            """

            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=True,
            )
        except:
            pass  # Email sending failed


# AJAX Views (keep your existing ones)
@login_required
def ajax_profile_completion(request):
    """AJAX endpoint to get profile completion status"""
    user = request.user
    return JsonResponse({
        'completion_percentage': user.profile_completion_percentage,
        'is_completed': user.profile_completed,
        'can_take_surveys': user.can_take_surveys(),
        'eligibility_issues': user.survey_eligibility_issues,
    })


@login_required
def request_withdrawal(request):
    """
    Placeholder view for withdrawal requests.
    This will be fully implemented when the payments app is complete.
    """
    messages.info(request,
                  "Withdrawal request feature is coming soon! We're working on integrating secure payment processing.")
    return redirect('accounts:withdrawals')


# accounts/views.py (updated referral_dashboard function)

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q, F, Case, When
from django.conf import settings
from django.utils import timezone
from django.http import JsonResponse
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views import View
from django.core.cache import cache
from datetime import timedelta
from decimal import Decimal
import logging

from .models import ReferralCommission
from surveys.models import Response, Survey
from payments.models import Transaction

logger = logging.getLogger(__name__)


@login_required
def referral_dashboard(request):
    user = request.user

    # Cache key for user's referral data
    cache_key = f'referral_dashboard_{user.id}'
    cached_data = cache.get(cache_key)

    if not cached_data:
        # Basic referral stats
        referral_stats = {
            'total_referrals': user.total_referrals or 0,
            'total_earnings': user.referral_earnings or Decimal('0.00'),
        }

        # Get pending commissions with optimized query
        pending_commissions_total = ReferralCommission.objects.filter(
            referrer=user,
            processed=False
        ).aggregate(
            total=Sum('commission_amount')
        )['total'] or Decimal('0.00')

        # Get recent commissions (last 10) with select_related optimization
        recent_commissions = ReferralCommission.objects.filter(
            referrer=user
        ).select_related('referred_user').order_by('-created_at')[:10]

        # Survey statistics with single query
        user_survey_stats = Response.objects.filter(
            user=user,
            completed=True
        ).aggregate(
            count=Count('id'),
            total_earnings=Sum('survey__payout')
        )

        completed_surveys_count = user_survey_stats['count'] or 0
        survey_earnings = user_survey_stats['total_earnings'] or Decimal('0.00')

        # Calculate total earnings and percentage breakdown
        total_earnings = survey_earnings + (user.referral_earnings or Decimal('0.00'))
        percentage_from_referrals = 0
        if total_earnings > 0:
            percentage_from_referrals = round(
                ((user.referral_earnings or Decimal('0.00')) / total_earnings) * 100, 1
            )

        cached_data = {
            'referral_stats': referral_stats,
            'pending_commissions_total': pending_commissions_total,
            'completed_surveys_count': completed_surveys_count,
            'survey_earnings': survey_earnings,
            'total_earnings': total_earnings,
            'percentage_from_referrals': percentage_from_referrals,
        }

        # Cache for 5 minutes
        cache.set(cache_key, cached_data, 300)

    # Get recent activities (not cached for real-time updates)
    recent_activities = get_recent_activities(user)

    # Build referral URL
    site_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
    if not site_url.endswith('/'):
        site_url += '/'
    referral_url = f"{site_url}?ref={user.referral_code}"

    # Get recent commissions for display
    recent_commissions = ReferralCommission.objects.filter(
        referrer=user
    ).select_related('referred_user').order_by('-created_at')[:10]

    context = {
        **cached_data,
        'recent_commissions': recent_commissions,
        'referral_code': user.referral_code,
        'referral_url': referral_url,
        'recent_activities': recent_activities,
    }

    return render(request, 'accounts/referral_dashboard.html', context)



def get_recent_activities(user, limit=10):
    """Get combined recent activities from surveys and referrals"""
    recent_activities = []

    try:
        # Get recent survey completions
        recent_surveys = Response.objects.filter(
            user=user,
            completed=True
        ).select_related('survey').order_by('-completed_at')[:5]

        for response in recent_surveys:
            recent_activities.append({
                'type': 'survey',
                'survey_title': response.survey.title,
                'amount': response.survey.payout,
                'date': response.completed_at,
            })

        # Get recent referral commissions
        recent_referral_commissions = ReferralCommission.objects.filter(
            referrer=user
        ).select_related('referred_user').order_by('-created_at')[:5]

        for commission in recent_referral_commissions:
            recent_activities.append({
                'type': 'referral',
                'referred_username': commission.referred_user.username if commission.referred_user else 'Anonymous',
                'commission_type': commission.commission_type,
                'amount': commission.commission_amount,
                'date': commission.created_at,
            })

        # Sort by date and limit
        recent_activities.sort(key=lambda x: x['date'], reverse=True)
        return recent_activities[:limit]

    except Exception as e:
        logger.error(f"Error fetching recent activities for user {user.id}: {e}")
        return []


def get_referral_analytics(user):
    """Get detailed referral analytics for a user with error handling"""
    try:
        # Monthly referral performance
        monthly_data = []
        for i in range(6):  # Last 6 months
            start_date = timezone.now() - timedelta(days=(i + 1) * 30)
            end_date = timezone.now() - timedelta(days=i * 30)

            month_commissions = ReferralCommission.objects.filter(
                referrer=user,
                created_at__range=[start_date, end_date]
            ).aggregate(
                total_amount=Sum('commission_amount'),
                total_referrals=Count('id')
            )

            monthly_data.append({
                'month': start_date.strftime('%B'),
                'earnings': month_commissions['total_amount'] or Decimal('0.00'),
                'referrals': month_commissions['total_referrals'] or 0
            })

        return {
            'monthly_performance': monthly_data,
            'conversion_rate': calculate_conversion_rate(user),
            'top_performing_referrals': get_top_performing_referrals(user)
        }
    except Exception as e:
        logger.error(f"Error getting referral analytics for user {user.id}: {e}")
        return {
            'monthly_performance': [],
            'conversion_rate': {'clicks': 0, 'registrations': 0, 'rate': 0},
            'top_performing_referrals': []
        }


def calculate_conversion_rate(user):
    """Calculate referral conversion rate"""
    try:
        # This would require tracking referral link clicks
        # For now, we'll return actual registrations data
        total_clicks = 0  # Would come from ReferralClick model if implemented
        registrations = user.total_referrals or 0
        rate = (registrations / total_clicks * 100) if total_clicks > 0 else 0

        return {
            'clicks': total_clicks,
            'registrations': registrations,
            'rate': rate
        }
    except Exception as e:
        logger.error(f"Error calculating conversion rate for user {user.id}: {e}")
        return {'clicks': 0, 'registrations': 0, 'rate': 0}


def get_top_performing_referrals(user):
    """Get referrals that have generated the most survey earnings"""
    try:
        from accounts.models import User

        # Optimized query with annotation
        referred_users = User.objects.filter(
            referred_by=user
        ).annotate(
            total_survey_earnings=Sum(
                'response__survey__payout',
                filter=Q(response__completed=True)
            ),
            surveys_completed=Count(
                'response',
                filter=Q(response__completed=True)
            )
        ).order_by('-total_survey_earnings')[:5]

        top_referrals = []
        for referred_user in referred_users:
            # Calculate commission earned from this referral
            commissions_from_user = ReferralCommission.objects.filter(
                referrer=user,
                referred_user=referred_user
            ).aggregate(
                total=Sum('commission_amount')
            )['total'] or Decimal('0.00')

            top_referrals.append({
                'username': referred_user.username,
                'join_date': referred_user.date_joined,
                'survey_earnings': referred_user.total_survey_earnings or Decimal('0.00'),
                'commission_earned': commissions_from_user,
                'surveys_completed': referred_user.surveys_completed or 0
            })

        return top_referrals
    except Exception as e:
        logger.error(f"Error getting top performing referrals for user {user.id}: {e}")
        return []


@login_required
def referral_analytics_dashboard(request):
    """Advanced referral analytics page with error handling"""
    user = request.user

    try:
        # Get basic dashboard context
        basic_context = referral_dashboard(request).context_data

        # Get detailed analytics
        analytics = get_referral_analytics(user)

        # Referral performance over time (optimized query)
        thirty_days_ago = timezone.now().date() - timedelta(days=30)
        daily_performance = ReferralCommission.objects.filter(
            referrer=user,
            created_at__date__gte=thirty_days_ago
        ).extra(
            select={'date': 'date(created_at)'}
        ).values('date').annotate(
            earnings=Sum('commission_amount'),
            referrals=Count('id')
        ).order_by('date')

        # Fill in missing dates with zero values
        performance_data = []
        for i in range(30):
            date = (timezone.now().date() - timedelta(days=29 - i))
            daily_data = next(
                (item for item in daily_performance if str(item['date']) == str(date)),
                {'earnings': 0, 'referrals': 0}
            )
            performance_data.append({
                'date': date.strftime('%Y-%m-%d'),
                'earnings': float(daily_data['earnings'] or 0),
                'referrals': daily_data['referrals'] or 0
            })

        # Commission breakdown by type
        commission_breakdown = ReferralCommission.objects.filter(
            referrer=user
        ).values('commission_type').annotate(
            total_amount=Sum('commission_amount'),
            total_count=Count('id')
        ).order_by('-total_amount')

        # Referral leaderboard (top referrers on the platform)
        from accounts.models import User
        leaderboard = User.objects.exclude(
            id=user.id
        ).order_by('-total_referrals', '-referral_earnings')[:10]

        user_rank = User.objects.filter(
            total_referrals__gt=user.total_referrals or 0
        ).count() + 1

        context = {
            **basic_context,
            'analytics': analytics,
            'performance_data': performance_data,
            'commission_breakdown': list(commission_breakdown),
            'leaderboard': leaderboard,
            'user_rank': user_rank,
        }

        return render(request, 'accounts/referral_analytics.html', context)

    except Exception as e:
        logger.error(f"Error in referral analytics dashboard for user {user.id}: {e}")
        # Fallback to basic dashboard
        return referral_dashboard(request)


@login_required
def referral_stats_api(request):
    """API endpoint for real-time referral statistics"""
    user = request.user

    try:
        # Get pending commissions count
        pending_count = ReferralCommission.objects.filter(
            referrer=user,
            processed=False
        ).count()

        # Recent activity (last 24 hours)
        last_24h = timezone.now() - timedelta(hours=24)
        recent_activity = ReferralCommission.objects.filter(
            referrer=user,
            created_at__gte=last_24h
        ).aggregate(
            new_referrals=Count(
                'id',
                filter=Q(commission_type='registration')
            ),
            new_commissions=Sum('commission_amount')
        )

        return JsonResponse({
            'status': 'success',
            'total_referrals': user.total_referrals or 0,
            'total_earnings': str(user.referral_earnings or Decimal('0.00')),
            'current_balance': str(user.balance or Decimal('0.00')),
            'pending_commissions': pending_count,
            'recent_activity': {
                'new_referrals': recent_activity['new_referrals'] or 0,
                'new_commissions': str(recent_activity['new_commissions'] or Decimal('0.00'))
            }
        })
    except Exception as e:
        logger.error(f"Error in referral stats API for user {user.id}: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Unable to fetch stats at this time'
        }, status=500)


def notify_referral_success(referrer, referred_user, commission_amount, commission_type):
    """Send notification when a referral generates a commission"""
    try:
        # Email notification
        subject = f"New Referral Commission: KSh {commission_amount}"

        context = {
            'referrer': referrer,
            'referred_user': referred_user,
            'commission_amount': commission_amount,
            'commission_type': commission_type,
            'total_referrals': referrer.total_referrals,
            'total_earnings': referrer.referral_earnings,
            'site_url': getattr(settings, 'SITE_URL', 'http://localhost:8000')
        }

        # Check if email templates exist before sending
        try:
            html_message = render_to_string(
                'accounts/emails/referral_commission.html',
                context
            )
            plain_message = render_to_string(
                'accounts/emails/referral_commission.txt',
                context
            )
        except Exception as template_error:
            logger.warning(f"Email template not found: {template_error}")
            # Fallback to simple text message
            plain_message = f"You've earned KSh {commission_amount} from referral commission!"
            html_message = None

        send_mail(
            subject=subject,
            message=plain_message,
            html_message=html_message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@surveyearn.co.ke'),
            recipient_list=[referrer.email],
            fail_silently=True
        )

        logger.info(f"Referral commission notification sent to {referrer.email}")

        # Clear user's cache to reflect new earnings
        cache.delete(f'referral_dashboard_{referrer.id}')

    except Exception as e:
        logger.error(f"Error sending referral notification: {e}")


@method_decorator(csrf_exempt, name='dispatch')
class ReferralClickTracker(View):
    """Track referral link clicks for analytics"""

    def post(self, request):
        try:
            referral_code = request.POST.get('referral_code')
            if not referral_code:
                return JsonResponse({'status': 'error', 'message': 'No referral code provided'})

            user_agent = request.META.get('HTTP_USER_AGENT', '')
            ip_address = self.get_client_ip(request)

            # Log the click for now (you can implement ReferralClick model later)
            logger.info(f"Referral click tracked: {referral_code} from {ip_address}")

            # Store click data if you implement ReferralClick model
            # ReferralClick.objects.create(
            #     referral_code=referral_code,
            #     ip_address=ip_address,
            #     user_agent=user_agent,
            #     timestamp=timezone.now()
            # )

            return JsonResponse({'status': 'success'})

        except Exception as e:
            logger.error(f"Error tracking referral click: {e}")
            return JsonResponse({'status': 'error'}, status=500)

    def get_client_ip(self, request):
        """Get the client's IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        return ip


# Utility function to invalidate referral cache
def invalidate_referral_cache(user_id):
    """Invalidate referral dashboard cache for a user"""
    cache.delete(f'referral_dashboard_{user_id}')


# Bulk referral operations
@login_required
def bulk_referral_actions(request):
    """Handle bulk referral actions like mass invitations"""
    if request.method == 'POST':
        action = request.POST.get('action')
        user = request.user

        if action == 'generate_invite_links':
            # Generate multiple referral links with tracking
            links = []
            for i in range(int(request.POST.get('count', 5))):
                campaign = request.POST.get('campaign', 'general')
                link = f"{getattr(settings, 'SITE_URL', 'http://localhost:8000')}?ref={user.referral_code}&campaign={campaign}&batch={i}"
                links.append(link)

            return JsonResponse({
                'status': 'success',
                'links': links
            })

        elif action == 'export_referrals':
            # Export referral data
            referrals = ReferralCommission.objects.filter(
                referrer=user
            ).select_related('referred_user')

            data = []
            for ref in referrals:
                data.append({
                    'username': ref.referred_user.username if ref.referred_user else 'Anonymous',
                    'commission_type': ref.commission_type,
                    'amount': str(ref.commission_amount),
                    'date': ref.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'processed': ref.processed
                })

            return JsonResponse({
                'status': 'success',
                'data': data
            })

    return JsonResponse({'status': 'error', 'message': 'Invalid request'})