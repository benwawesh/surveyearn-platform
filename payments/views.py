# payments/views.py - Complete payments views with proper imports

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.utils import timezone
from decimal import Decimal
import json
import logging

from .models import WithdrawalRequest, Transaction, MPesaTransaction
from .services import WithdrawalService
from .mpesa import MPesaService

logger = logging.getLogger(__name__)


# M-Pesa Callback Views (existing)
@csrf_exempt
@require_POST
def mpesa_callback(request):
    """Handle M-Pesa STK Push callbacks"""

    try:
        callback_data = json.loads(request.body)

        # Extract callback data
        stk_callback = callback_data.get('Body', {}).get('stkCallback', {})
        checkout_request_id = stk_callback.get('CheckoutRequestID')
        result_code = stk_callback.get('ResultCode')
        result_desc = stk_callback.get('ResultDesc')

        # Find the transaction
        try:
            mpesa_transaction = MPesaTransaction.objects.get(
                checkout_request_id=checkout_request_id
            )
        except MPesaTransaction.DoesNotExist:
            logger.error(f"M-Pesa callback: Transaction not found for checkout_request_id: {checkout_request_id}")
            return HttpResponse("OK")

        # Update transaction status
        mpesa_transaction.result_code = str(result_code)
        mpesa_transaction.result_desc = result_desc
        mpesa_transaction.api_response = callback_data

        if result_code == 0:  # Success
            mpesa_transaction.status = 'completed'

            # Extract transaction details
            callback_metadata = stk_callback.get('CallbackMetadata', {}).get('Item', [])
            for item in callback_metadata:
                name = item.get('Name')
                value = item.get('Value')

                if name == 'MpesaReceiptNumber':
                    mpesa_transaction.mpesa_receipt_number = value
                elif name == 'TransactionDate':
                    # Convert M-Pesa timestamp to datetime
                    from datetime import datetime
                    transaction_date = datetime.strptime(str(value), '%Y%m%d%H%M%S')
                    mpesa_transaction.transaction_date = timezone.make_aware(transaction_date)

        else:  # Failed
            mpesa_transaction.status = 'failed'

        mpesa_transaction.save()
        logger.info(f"M-Pesa callback processed: {checkout_request_id}, status: {mpesa_transaction.status}")
        return HttpResponse("OK")

    except Exception as e:
        logger.error(f"M-Pesa callback error: {str(e)}")
        return HttpResponse("ERROR", status=400)


@csrf_exempt
@require_POST
def mpesa_b2c_result(request):
    """Handle M-Pesa B2C (withdrawal) result callbacks"""

    try:
        result_data = json.loads(request.body)

        # Extract result data
        result = result_data.get('Result', {})
        conversation_id = result.get('ConversationID')
        result_code = result.get('ResultCode')
        result_desc = result.get('ResultDesc')

        # Find the transaction
        try:
            mpesa_transaction = MPesaTransaction.objects.get(
                conversation_id=conversation_id
            )
        except MPesaTransaction.DoesNotExist:
            logger.error(f"M-Pesa B2C result: Transaction not found for conversation_id: {conversation_id}")
            return HttpResponse("OK")

        # Update transaction status
        mpesa_transaction.result_code = str(result_code)
        mpesa_transaction.result_desc = result_desc
        mpesa_transaction.api_response = result_data

        if result_code == 0:  # Success
            mpesa_transaction.status = 'completed'

            # Extract transaction details from result parameters
            result_parameters = result.get('ResultParameters', {}).get('ResultParameter', [])
            for param in result_parameters:
                key = param.get('Key')
                value = param.get('Value')

                if key == 'TransactionReceipt':
                    mpesa_transaction.mpesa_receipt_number = value
                elif key == 'TransactionCompletedDateTime':
                    try:
                        from datetime import datetime
                        transaction_date = datetime.strptime(value, '%d.%m.%Y %H:%M:%S')
                        mpesa_transaction.transaction_date = timezone.make_aware(transaction_date)
                    except ValueError:
                        pass

            # Mark the withdrawal as completed
            if mpesa_transaction.withdrawal_request:
                withdrawal = mpesa_transaction.withdrawal_request
                withdrawal.status = 'completed'
                withdrawal.external_reference = mpesa_transaction.mpesa_receipt_number
                withdrawal.save()

                # Update related transaction
                Transaction.objects.filter(
                    user=withdrawal.user,
                    transaction_type='withdrawal',
                    amount=-withdrawal.amount,
                    status__in=['pending', 'processing']
                ).update(
                    status='completed',
                    description=f'M-Pesa withdrawal completed - Ref: {mpesa_transaction.mpesa_receipt_number}'
                )
        else:
            mpesa_transaction.status = 'failed'

            # Mark withdrawal as failed and restore balance
            if mpesa_transaction.withdrawal_request:
                withdrawal = mpesa_transaction.withdrawal_request
                WithdrawalService.fail_withdrawal(
                    withdrawal,
                    None,
                    f"M-Pesa payment failed: {result_desc}"
                )

        mpesa_transaction.save()
        logger.info(f"M-Pesa B2C result processed: {conversation_id}, status: {mpesa_transaction.status}")
        return HttpResponse("OK")

    except Exception as e:
        logger.error(f"M-Pesa B2C result error: {str(e)}")
        return HttpResponse("ERROR", status=400)


@csrf_exempt
@require_POST
def mpesa_timeout(request):
    """Handle M-Pesa timeout notifications"""

    try:
        timeout_data = json.loads(request.body)

        result = timeout_data.get('Result', {})
        conversation_id = result.get('ConversationID')

        # Find and mark transaction as timeout
        try:
            mpesa_transaction = MPesaTransaction.objects.get(
                conversation_id=conversation_id
            )
            mpesa_transaction.status = 'timeout'
            mpesa_transaction.result_desc = 'Transaction timed out'
            mpesa_transaction.api_response = timeout_data
            mpesa_transaction.save()

            # Handle withdrawal timeout
            if mpesa_transaction.withdrawal_request:
                withdrawal = mpesa_transaction.withdrawal_request
                WithdrawalService.fail_withdrawal(
                    withdrawal,
                    None,
                    "M-Pesa transaction timed out"
                )

            logger.info(f"M-Pesa timeout processed: {conversation_id}")

        except MPesaTransaction.DoesNotExist:
            logger.error(f"M-Pesa timeout: Transaction not found for conversation_id: {conversation_id}")

        return HttpResponse("OK")

    except Exception as e:
        logger.error(f"M-Pesa timeout error: {str(e)}")
        return HttpResponse("ERROR", status=400)


# User-facing withdrawal views
@login_required
def wallet_dashboard(request):
    """
    Main wallet/earnings dashboard for users
    """
    user = request.user

    # Get user's current balance and earnings
    current_balance = getattr(user, 'balance', Decimal('0.00')) or Decimal('0.00')
    total_earnings = getattr(user, 'total_earnings', Decimal('0.00')) or Decimal('0.00')

    # Recent transactions (last 10)
    recent_transactions = Transaction.objects.filter(
        user=user
    ).order_by('-created_at')[:10]

    # Withdrawal statistics
    withdrawal_stats = WithdrawalService.get_user_withdrawal_stats(user)

    # Survey earnings statistics
    from .services import SurveyPaymentService
    survey_earnings = SurveyPaymentService.get_user_survey_earnings(user)

    # Pending withdrawals
    pending_withdrawals = WithdrawalRequest.objects.filter(
        user=user,
        status='pending'
    ).order_by('-created_at')

    context = {
        'current_balance': current_balance,
        'total_earnings': total_earnings,
        'recent_transactions': recent_transactions,
        'withdrawal_stats': withdrawal_stats,
        'survey_earnings': survey_earnings,
        'pending_withdrawals': pending_withdrawals,
        'min_withdrawal': WithdrawalService.MIN_WITHDRAWAL,
        'max_withdrawal': WithdrawalService.MAX_WITHDRAWAL,
        'withdrawal_fee_percentage': float(WithdrawalService.WITHDRAWAL_FEE_PERCENTAGE * 100),
        'min_withdrawal_fee': WithdrawalService.MIN_WITHDRAWAL_FEE,
    }

    return render(request, 'payments/wallet_dashboard.html', context)


@login_required
def request_withdrawal(request):
    """
    Handle withdrawal request form
    """
    user = request.user
    current_balance = getattr(user, 'balance', Decimal('0.00')) or Decimal('0.00')

    if request.method == 'POST':
        try:
            # Get form data
            amount = Decimal(request.POST.get('amount', '0'))
            payment_method = request.POST.get('payment_method', '')

            # Validate payment method
            if payment_method not in ['mpesa', 'bank_transfer', 'paypal']:
                messages.error(request, 'Please select a valid payment method.')
                return redirect('payments:withdraw_request')

            # Get payment details based on method
            payment_details = {}

            if payment_method == 'mpesa':
                phone_number = request.POST.get('mpesa_phone', '').strip()
                if not phone_number:
                    messages.error(request, 'Please enter your M-Pesa phone number.')
                    return redirect('payments:withdraw_request')

                # Validate phone number
                if not MPesaService.validate_phone_number(phone_number):
                    messages.error(request, 'Please enter a valid Kenyan phone number.')
                    return redirect('payments:withdraw_request')

                payment_details['phone_number'] = MPesaService.format_phone_number(phone_number)

            elif payment_method == 'bank_transfer':
                bank_name = request.POST.get('bank_name', '').strip()
                account_number = request.POST.get('account_number', '').strip()
                account_name = request.POST.get('account_name', '').strip()

                if not all([bank_name, account_number, account_name]):
                    messages.error(request, 'Please fill in all bank transfer details.')
                    return redirect('payments:withdraw_request')

                payment_details.update({
                    'bank_name': bank_name,
                    'account_number': account_number,
                    'account_name': account_name
                })

            elif payment_method == 'paypal':
                paypal_email = request.POST.get('paypal_email', '').strip()
                if not paypal_email:
                    messages.error(request, 'Please enter your PayPal email address.')
                    return redirect('payments:withdraw_request')

                payment_details['email'] = paypal_email

            # Create withdrawal request using service
            withdrawal = WithdrawalService.create_withdrawal_request(
                user=user,
                amount=amount,
                payment_method=payment_method,
                payment_details=payment_details
            )

            messages.success(
                request,
                f'Withdrawal request submitted successfully! '
                f'Request ID: {withdrawal.short_id}. '
                f'You will receive KSh {withdrawal.net_amount} after KSh {withdrawal.withdrawal_fee} processing fee.'
            )

            return redirect('payments:withdrawal_detail', withdrawal_id=withdrawal.id)

        except ValueError as e:
            messages.error(request, str(e))
            return redirect('payments:withdraw_request')
        except Exception as e:
            messages.error(request, f'Error processing withdrawal request: {str(e)}')
            return redirect('payments:withdraw_request')

    # GET request - show withdrawal form
    # Calculate fee preview for JavaScript
    sample_amounts = [100, 500, 1000, 5000]
    fee_examples = []
    for amount in sample_amounts:
        fee = max(Decimal(str(amount)) * WithdrawalService.WITHDRAWAL_FEE_PERCENTAGE,
                  WithdrawalService.MIN_WITHDRAWAL_FEE)
        fee_examples.append({
            'amount': amount,
            'fee': float(fee),
            'net': float(Decimal(str(amount)) - fee)
        })

    context = {
        'current_balance': current_balance,
        'min_withdrawal': WithdrawalService.MIN_WITHDRAWAL,
        'max_withdrawal': WithdrawalService.MAX_WITHDRAWAL,
        'withdrawal_fee_percentage': float(WithdrawalService.WITHDRAWAL_FEE_PERCENTAGE * 100),
        'min_withdrawal_fee': WithdrawalService.MIN_WITHDRAWAL_FEE,
        'fee_examples': fee_examples,
    }

    return render(request, 'payments/request_withdrawal.html', context)


@login_required
def withdrawal_detail(request, withdrawal_id):
    """
    Display withdrawal request details and status
    """
    withdrawal = get_object_or_404(WithdrawalRequest, id=withdrawal_id, user=request.user)

    # Get related M-Pesa transaction if exists
    mpesa_transaction = None
    if withdrawal.payment_method == 'mpesa':
        mpesa_transaction = MPesaTransaction.objects.filter(
            withdrawal_request=withdrawal
        ).first()

    context = {
        'withdrawal': withdrawal,
        'mpesa_transaction': mpesa_transaction,
    }

    return render(request, 'payments/withdrawal_detail.html', context)


@login_required
def withdrawal_history(request):
    """
    Display user's withdrawal history with pagination and filtering
    """
    withdrawals = WithdrawalRequest.objects.filter(
        user=request.user
    ).order_by('-created_at')

    # Filter by status if requested
    status_filter = request.GET.get('status', '')
    if status_filter and status_filter in ['pending', 'approved', 'processing', 'completed', 'rejected', 'failed']:
        withdrawals = withdrawals.filter(status=status_filter)

    # Filter by payment method if requested
    method_filter = request.GET.get('method', '')
    if method_filter and method_filter in ['mpesa', 'bank_transfer', 'paypal']:
        withdrawals = withdrawals.filter(payment_method=method_filter)

    # Search by amount or ID
    search_query = request.GET.get('search', '')
    if search_query:
        try:
            # Try to search by amount
            search_amount = Decimal(search_query)
            withdrawals = withdrawals.filter(amount=search_amount)
        except:
            # Search by partial ID
            withdrawals = withdrawals.filter(
                Q(id__icontains=search_query)
            )

    # Pagination
    paginator = Paginator(withdrawals, 20)  # 20 withdrawals per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Summary statistics for this user
    summary = {
        'total_requested': withdrawals.aggregate(total=Sum('amount'))['total'] or 0,
        'total_completed': withdrawals.filter(status='completed').aggregate(total=Sum('amount'))['total'] or 0,
        'pending_amount': withdrawals.filter(status='pending').aggregate(total=Sum('amount'))['total'] or 0,
    }

    context = {
        'page_obj': page_obj,
        'withdrawals': page_obj,
        'summary': summary,
        'status_filter': status_filter,
        'method_filter': method_filter,
        'search_query': search_query,
    }

    return render(request, 'payments/withdrawal_history.html', context)


@login_required
def transaction_history(request):
    """
    Display user's complete transaction history
    """
    transactions = Transaction.objects.filter(
        user=request.user
    ).order_by('-created_at')

    # Filter by transaction type
    type_filter = request.GET.get('type', '')
    if type_filter and type_filter in ['survey_payment', 'withdrawal', 'refund', 'registration_fee']:
        transactions = transactions.filter(transaction_type=type_filter)

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter and status_filter in ['pending', 'completed', 'failed']:
        transactions = transactions.filter(status=status_filter)

    # Date range filter
    from datetime import timedelta

    date_filter = request.GET.get('date_range', '')
    if date_filter:
        today = timezone.now().date()
        if date_filter == '7days':
            start_date = today - timedelta(days=7)
            transactions = transactions.filter(created_at__date__gte=start_date)
        elif date_filter == '30days':
            start_date = today - timedelta(days=30)
            transactions = transactions.filter(created_at__date__gte=start_date)
        elif date_filter == '90days':
            start_date = today - timedelta(days=90)
            transactions = transactions.filter(created_at__date__gte=start_date)

    # Pagination
    paginator = Paginator(transactions, 25)  # 25 transactions per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Calculate summary stats
    summary = {
        'total_earned': transactions.filter(
            transaction_type='survey_payment',
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or 0,
        'total_withdrawn': abs(transactions.filter(
            transaction_type='withdrawal',
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or 0),
        'pending_withdrawals': abs(transactions.filter(
            transaction_type='withdrawal',
            status__in=['pending', 'processing']
        ).aggregate(total=Sum('amount'))['total'] or 0),
    }

    context = {
        'page_obj': page_obj,
        'transactions': page_obj,
        'summary': summary,
        'type_filter': type_filter,
        'status_filter': status_filter,
        'date_filter': date_filter,
    }

    return render(request, 'payments/transaction_history.html', context)


@login_required
@require_POST
@csrf_protect
def calculate_withdrawal_fee(request):
    """
    AJAX endpoint to calculate withdrawal fee in real-time
    """
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount', '0')))

        if amount <= 0:
            return JsonResponse({'error': 'Invalid amount'}, status=400)

        # Calculate fee
        fee = max(amount * WithdrawalService.WITHDRAWAL_FEE_PERCENTAGE, WithdrawalService.MIN_WITHDRAWAL_FEE)
        net_amount = amount - fee

        return JsonResponse({
            'amount': float(amount),
            'fee': float(fee),
            'net_amount': float(net_amount),
            'fee_percentage': float(WithdrawalService.WITHDRAWAL_FEE_PERCENTAGE * 100)
        })

    except (ValueError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid request data'}, status=400)


@login_required
def cancel_withdrawal(request, withdrawal_id):
    """
    Allow users to cancel pending withdrawal requests
    """
    withdrawal = get_object_or_404(WithdrawalRequest, id=withdrawal_id, user=request.user)

    if withdrawal.status != 'pending':
        messages.error(request, 'Only pending withdrawals can be cancelled.')
        return redirect('payments:withdrawal_detail', withdrawal_id=withdrawal.id)

    if request.method == 'POST':
        # Update withdrawal status
        withdrawal.status = 'cancelled'
        withdrawal.admin_notes = 'Cancelled by user'
        withdrawal.processed_at = timezone.now()
        withdrawal.save()

        messages.success(request, 'Withdrawal request cancelled successfully.')
        return redirect('payments:wallet_dashboard')

    context = {'withdrawal': withdrawal}
    return render(request, 'payments/cancel_withdrawal.html', context)