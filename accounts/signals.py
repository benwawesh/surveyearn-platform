# accounts/signals.py - Create this file
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum, Count
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender='payments.Transaction')
def update_user_totals_on_transaction_save(sender, instance, created, **kwargs):
    """Update user totals when transactions are saved"""
    if instance.status == 'completed':
        update_user_financial_fields(instance.user)


@receiver(post_delete, sender='payments.Transaction')
def update_user_totals_on_transaction_delete(sender, instance, **kwargs):
    """Update user totals when transactions are deleted"""
    update_user_financial_fields(instance.user)


def update_user_financial_fields(user):
    """
    Update all financial fields on a user based on their completed transactions
    """
    try:
        # Import here to avoid circular imports
        from payments.models import Transaction

        # Get all completed transactions for this user
        completed_transactions = Transaction.objects.filter(
            user=user,
            status='completed'
        )

        # Calculate survey earnings and count
        survey_transactions = completed_transactions.filter(
            transaction_type='survey_payment'
        )

        survey_earnings = survey_transactions.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        survey_count = survey_transactions.count()

        # Calculate total balance (earnings minus withdrawals, excluding registration fees)
        # Registration fees don't go to user balance - they're platform revenue
        positive_transactions = completed_transactions.filter(
            transaction_type__in=['survey_payment', 'bonus', 'referral_commission']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        negative_transactions = completed_transactions.filter(
            transaction_type__in=['withdrawal', 'fee']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # Calculate current balance
        current_balance = positive_transactions - abs(negative_transactions)
        current_balance = max(current_balance, Decimal('0.00'))  # Never negative

        # Calculate total lifetime earnings (all positive transactions)
        total_earnings = positive_transactions

        # Update user fields
        user.balance = current_balance
        user.total_earnings = total_earnings
        user.total_surveys_completed = survey_count

        # Save without triggering signals again
        user.save(update_fields=['balance', 'total_earnings', 'total_surveys_completed'])

        logger.info(
            f"Updated user {user.username}: balance=KSh{current_balance}, earnings=KSh{total_earnings}, surveys={survey_count}")

    except Exception as e:
        logger.error(f"Error updating user financial fields for {user.username}: {str(e)}")


# Signal to update user on registration payment completion
@receiver(post_save, sender='payments.MPesaTransaction')
def update_user_on_mpesa_completion(sender, instance, created, **kwargs):
    """Update user fields when M-Pesa transaction completes"""
    if instance.status == 'completed' and instance.transaction_type == 'stk_push':
        # This will trigger the transaction signal above
        update_user_financial_fields(instance.user)