# payments/admin_mpesa_views.py - Admin views for M-Pesa processing

from .mpesa import MPesaService
from .models import MPesaTransaction


@admin_required
def process_mpesa_withdrawal(request, withdrawal_id):
    """Process withdrawal via M-Pesa"""

    try:
        withdrawal = get_object_or_404(WithdrawalRequest, id=withdrawal_id)

        if withdrawal.status != 'approved':
            messages.error(request, 'Only approved withdrawals can be processed via M-Pesa')
            return redirect('custom_admin:withdrawal_detail', withdrawal_id=withdrawal_id)

        if withdrawal.payment_method != 'mpesa':
            messages.error(request, 'This withdrawal is not for M-Pesa payment')
            return redirect('custom_admin:withdrawal_detail', withdrawal_id=withdrawal_id)

        # Initialize M-Pesa service
        mpesa_service = MPesaService()

        # Create M-Pesa transaction record
        mpesa_transaction = MPesaTransaction.objects.create(
            user=withdrawal.user,
            withdrawal_request=withdrawal,
            transaction_type='b2c',
            amount=withdrawal.amount,
            phone_number=withdrawal.mpesa_phone_number,
            status='initiated'
        )

        # Send B2C payment
        result = mpesa_service.send_b2c_payment(
            phone_number=withdrawal.mpesa_phone_number,
            amount=withdrawal.amount,
            withdrawal_request=withdrawal
        )

        if result['success']:
            # Update M-Pesa transaction
            mpesa_transaction.conversation_id = result['conversation_id']
            mpesa_transaction.originator_conversation_id = result['originator_conversation_id']
            mpesa_transaction.status = 'pending'
            mpesa_transaction.save()

            # Update withdrawal status
            withdrawal.status = 'processing'
            withdrawal.save()

            messages.success(request,
                             f'M-Pesa payment initiated successfully. Conversation ID: {result["conversation_id"]}')
        else:
            mpesa_transaction.status = 'failed'
            mpesa_transaction.result_desc = result.get('error', 'Unknown error')
            mpesa_transaction.save()

            messages.error(request, f'M-Pesa payment failed: {result.get("error", "Unknown error")}')

        return redirect('custom_admin:withdrawal_detail', withdrawal_id=withdrawal_id)

    except Exception as e:
        messages.error(request, f'Error processing M-Pesa payment: {str(e)}')
        return redirect('custom_admin:withdrawal_detail', withdrawal_id=withdrawal_id)


@admin_required
def admin_mpesa_transactions(request):
    """View M-Pesa transactions"""

    transactions = MPesaTransaction.objects.all().order_by('-created_at')

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        transactions = transactions.filter(status=status_filter)

    # Filter by transaction type
    type_filter = request.GET.get('type', '')
    if type_filter:
        transactions = transactions.filter(transaction_type=type_filter)

    # Search by phone number or user
    search_query = request.GET.get('search', '')
    if search_query:
        transactions = transactions.filter(
            Q(phone_number__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(mpesa_receipt_number__icontains=search_query)
        )

    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(transactions, 25)
    page_number = request.GET.get('page')
    transactions = paginator.get_page(page_number)

    # Statistics
    stats = {
        'total_b2c': MPesaTransaction.objects.filter(transaction_type='b2c').count(),
        'successful_b2c': MPesaTransaction.objects.filter(transaction_type='b2c', status='completed').count(),
        'failed_b2c': MPesaTransaction.objects.filter(transaction_type='b2c', status='failed').count(),
        'pending_b2c': MPesaTransaction.objects.filter(transaction_type='b2c', status='pending').count(),
    }

    context = {
        'transactions': transactions,
        'stats': stats,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'search_query': search_query,
    }

    return render(request, 'admin/mpesa_transactions.html', context)