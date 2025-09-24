# payments/services.py - Complete withdrawal processing services

from django.db import transaction, models
from django.utils import timezone
from decimal import Decimal
from .models import WithdrawalRequest, Transaction
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class WithdrawalService:
    """Service class to handle withdrawal processing"""

    # Withdrawal limits and fees - TESTING VALUES
    MIN_WITHDRAWAL = Decimal('30.00')  # Minimum KSh 30 (for testing)
    MAX_WITHDRAWAL = Decimal('50000.00')  # Maximum KSh 50,000
    WITHDRAWAL_FEE_PERCENTAGE = Decimal('0.02')  # 2% fee
    MIN_WITHDRAWAL_FEE = Decimal('1.00')  # Minimum KSh 1 fee (for testing)

    @classmethod
    def create_withdrawal_request(cls, user, amount, payment_method, payment_details):
        """Create a new withdrawal request"""

        # Validate withdrawal amount
        if amount < cls.MIN_WITHDRAWAL:
            raise ValueError(f"Minimum withdrawal amount is KSh {cls.MIN_WITHDRAWAL}")

        if amount > cls.MAX_WITHDRAWAL:
            raise ValueError(f"Maximum withdrawal amount is KSh {cls.MAX_WITHDRAWAL}")

        # Check user balance
        if user.balance < amount:
            raise ValueError("Insufficient balance")

        # Calculate withdrawal fee
        fee = max(amount * cls.WITHDRAWAL_FEE_PERCENTAGE, cls.MIN_WITHDRAWAL_FEE)

        # Check if user has enough balance including fees
        total_required = amount + fee
        if user.balance < total_required:
            raise ValueError(f"Insufficient balance. Required: KSh {total_required} (including KSh {fee} fee)")

        # Create withdrawal request
        withdrawal = WithdrawalRequest.objects.create(
            user=user,
            amount=amount,
            payment_method=payment_method,
            withdrawal_fee=fee,
            net_amount=amount - fee,
            payment_details=payment_details,
            **cls._extract_payment_fields(payment_method, payment_details)
        )

        logger.info(f"Withdrawal request created: {withdrawal.id} for user {user.username}, amount KSh {amount}")

        return withdrawal

    @classmethod
    def _extract_payment_fields(cls, payment_method, payment_details):
        """Extract payment method specific fields"""
        fields = {}

        if payment_method == 'mpesa':
            fields['mpesa_phone_number'] = payment_details.get('phone_number', '')
        elif payment_method == 'bank_transfer':
            fields['bank_name'] = payment_details.get('bank_name', '')
            fields['account_number'] = payment_details.get('account_number', '')
            fields['account_name'] = payment_details.get('account_name', '')
        elif payment_method == 'paypal':
            fields['paypal_email'] = payment_details.get('email', '')

        return fields

    @classmethod
    def approve_withdrawal(cls, withdrawal, admin_user, notes=''):
        """Approve a withdrawal request"""

        if withdrawal.status != 'pending':
            raise ValueError("Only pending withdrawals can be approved")

        if not withdrawal.can_be_processed():
            raise ValueError("Withdrawal cannot be processed - insufficient balance")

        with transaction.atomic():
            # Update withdrawal status
            withdrawal.status = 'approved'
            withdrawal.processed_at = timezone.now()
            withdrawal.processed_by = admin_user
            withdrawal.admin_notes = notes
            withdrawal.save()

            # Reserve the amount from user balance
            user = withdrawal.user
            balance_before = user.balance
            user.balance -= withdrawal.amount
            user.save()

            # Create transaction record
            Transaction.objects.create(
                user=user,
                amount=-withdrawal.amount,
                transaction_type='withdrawal',
                status='pending',
                description=f'Withdrawal approved - {withdrawal.payment_method}',
                balance_before=balance_before,
                balance_after=user.balance,
                processed_by=admin_user
            )

            logger.info(f"Withdrawal approved: {withdrawal.id} by {admin_user.username}")

        return withdrawal

    @classmethod
    def reject_withdrawal(cls, withdrawal, admin_user, reason, notes=''):
        """Reject a withdrawal request"""

        if withdrawal.status != 'pending':
            raise ValueError("Only pending withdrawals can be rejected")

        withdrawal.status = 'rejected'
        withdrawal.processed_at = timezone.now()
        withdrawal.processed_by = admin_user
        withdrawal.admin_notes = f"Rejected: {reason}. {notes}".strip()
        withdrawal.save()

        logger.info(f"Withdrawal rejected: {withdrawal.id} by {admin_user.username}, reason: {reason}")

        return withdrawal

    @classmethod
    def mark_as_processing(cls, withdrawal, admin_user):
        """Mark withdrawal as being processed"""

        if withdrawal.status != 'approved':
            raise ValueError("Only approved withdrawals can be marked as processing")

        withdrawal.status = 'processing'
        withdrawal.save()

        # Update related transaction
        Transaction.objects.filter(
            user=withdrawal.user,
            transaction_type='withdrawal',
            amount=-withdrawal.amount,
            status='pending'
        ).update(status='processing')

        logger.info(f"Withdrawal marked as processing: {withdrawal.id}")

        return withdrawal

    @classmethod
    def complete_withdrawal(cls, withdrawal, admin_user, external_reference='', actual_amount=None):
        """Mark withdrawal as completed"""

        if withdrawal.status not in ['approved', 'processing']:
            raise ValueError("Only approved or processing withdrawals can be completed")

        with transaction.atomic():
            withdrawal.status = 'completed'
            withdrawal.external_reference = external_reference
            withdrawal.save()

            # Update related transaction
            Transaction.objects.filter(
                user=withdrawal.user,
                transaction_type='withdrawal',
                amount=-withdrawal.amount,
                status__in=['pending', 'processing']
            ).update(
                status='completed',
                description=f'Withdrawal completed - {withdrawal.payment_method} - Ref: {external_reference}'
            )

            logger.info(f"Withdrawal completed: {withdrawal.id}, ref: {external_reference}")

        return withdrawal

    @classmethod
    def fail_withdrawal(cls, withdrawal, admin_user, error_reason=''):
        """Mark withdrawal as failed and restore user balance"""

        if withdrawal.status not in ['approved', 'processing']:
            raise ValueError("Only approved or processing withdrawals can be failed")

        with transaction.atomic():
            # Restore user balance
            user = withdrawal.user
            balance_before = user.balance
            user.balance += withdrawal.amount
            user.save()

            # Update withdrawal status
            withdrawal.status = 'failed'
            withdrawal.admin_notes = f"Failed: {error_reason}"
            withdrawal.save()

            # Update related transaction
            Transaction.objects.filter(
                user=withdrawal.user,
                transaction_type='withdrawal',
                amount=-withdrawal.amount,
                status__in=['pending', 'processing']
            ).update(status='failed')

            # Create reversal transaction
            Transaction.objects.create(
                user=user,
                amount=withdrawal.amount,
                transaction_type='refund',
                status='completed',
                description=f'Withdrawal failed - balance restored: {error_reason}',
                balance_before=balance_before,
                balance_after=user.balance,
                processed_by=admin_user
            )

            logger.info(f"Withdrawal failed and balance restored: {withdrawal.id}, reason: {error_reason}")

        return withdrawal

    @classmethod
    def get_user_withdrawal_stats(cls, user):
        """Get user's withdrawal statistics"""

        withdrawals = WithdrawalRequest.objects.filter(user=user)

        return {
            'total_requested': withdrawals.aggregate(total=models.Sum('amount'))['total'] or 0,
            'total_completed': withdrawals.filter(status='completed').aggregate(total=models.Sum('amount'))['total'] or 0,
            'pending_count': withdrawals.filter(status='pending').count(),
            'pending_amount': withdrawals.filter(status='pending').aggregate(total=models.Sum('amount'))['total'] or 0,
            'last_withdrawal': withdrawals.filter(status='completed').order_by('-processed_at').first(),
        }

    @classmethod
    def get_user_withdrawal_stats(cls, user):
        """Get user's withdrawal statistics"""

        withdrawals = WithdrawalRequest.objects.filter(user=user)

        return {
            'total_requested': withdrawals.aggregate(total=models.Sum('amount'))['total'] or 0,
            'total_completed': withdrawals.filter(status='completed').aggregate(total=models.Sum('amount'))[
                                   'total'] or 0,
            'pending_count': withdrawals.filter(status='pending').count(),
            'pending_amount': withdrawals.filter(status='pending').aggregate(total=models.Sum('amount'))['total'] or 0,
            'last_withdrawal': withdrawals.filter(status='completed').order_by('-processed_at').first(),
        }

    # ADD THIS NEW METHOD HERE:
    @classmethod
    def process_mpesa_withdrawal(cls, withdrawal):
        """Process M-Pesa B2C withdrawal"""
        try:
            # Import your existing M-Pesa service
            from payments.mpesa import MPesaService

            # Initialize M-Pesa service
            mpesa = MPesaService()

            # Get payment details
            phone_number = withdrawal.payment_details.get('phone_number')
            if not phone_number:
                phone_number = withdrawal.mpesa_phone_number

            if not phone_number:
                return {
                    'success': False,
                    'error': 'No phone number found for M-Pesa withdrawal'
                }

            # Validate phone number format
            if not MPesaService.validate_phone_number(phone_number):
                return {
                    'success': False,
                    'error': f'Invalid phone number format: {phone_number}'
                }

            # Send B2C payment using your existing service method
            result = mpesa.send_b2c_payment(
                phone_number=phone_number,
                amount=float(withdrawal.net_amount),
                withdrawal_request=withdrawal
            )

            if result.get('success'):
                # Payment initiated successfully
                return {
                    'success': True,
                    'receipt_number': result.get('conversation_id', ''),
                    'transaction_id': result.get('originator_conversation_id', ''),
                    'message': result.get('response_description', 'M-Pesa payment initiated successfully')
                }
            else:
                # Payment failed
                return {
                    'success': False,
                    'error': result.get('error', 'M-Pesa B2C payment failed'),
                    'error_code': result.get('response_code')
                }

        except ImportError:
            # M-Pesa module not found - for testing
            logger.warning(f"M-Pesa module not found. Simulating payment for withdrawal {withdrawal.id}")

            # Simulate successful payment for testing
            return {
                'success': True,
                'receipt_number': f'TEST{withdrawal.short_id}',
                'transaction_id': f'TXN{withdrawal.id}',
                'message': 'Simulated M-Pesa payment (testing mode)'
            }

        except Exception as e:
            logger.error(f"M-Pesa withdrawal error for {withdrawal.id}: {str(e)}")
            return {
                'success': False,
                'error': f'M-Pesa processing error: {str(e)}'
            }


class SurveyPaymentService:
    """
    Service to handle automatic payments when users complete surveys
    """

    @classmethod
    @transaction.atomic
    def process_survey_completion_payment(cls, survey_response):
        """
        Process payment when a user completes a survey

        Args:
            survey_response: The completed Response object from surveys app

        Returns:
            dict: {'success': bool, 'transaction': Transaction or None, 'message': str}
        """
        try:
            # Import here to avoid circular imports
            from surveys.models import Response

            # Check if user has already been paid for this survey
            existing_payment = Transaction.objects.filter(
                user=survey_response.user,
                transaction_type='survey_payment',
                reference_id=str(survey_response.id),
                status='completed'
            ).first()

            if existing_payment:
                return {
                    'success': False,
                    'transaction': existing_payment,
                    'message': 'User already paid for this survey'
                }

            # Check if survey response is actually completed
            if not survey_response.completed:
                return {
                    'success': False,
                    'transaction': None,
                    'message': 'Survey response is not marked as completed'
                }

            # Get the survey payout amount
            payout_amount = survey_response.survey.payout
            if payout_amount <= 0:
                return {
                    'success': False,
                    'transaction': None,
                    'message': 'Survey has no payout amount set'
                }

            # Get user's current balance
            user = survey_response.user
            current_balance = user.balance or Decimal('0.00')
            new_balance = current_balance + payout_amount

            # Create the payment transaction
            payment_transaction = Transaction.objects.create(
                user=user,
                transaction_type='survey_payment',
                amount=payout_amount,
                status='completed',
                description=f'Payment for completing survey: {survey_response.survey.title}',
                balance_before=current_balance,
                balance_after=new_balance,
                reference_id=str(survey_response.id),
                notes=f'Survey ID: {survey_response.survey.id}, Response ID: {survey_response.id}',
                processed_at=timezone.now()
            )

            # Update user's balance
            user.balance = new_balance
            user.total_earnings = (user.total_earnings or Decimal('0.00')) + payout_amount
            user.save(update_fields=['balance', 'total_earnings'])

            # Update survey response to mark as paid
            survey_response.payout_amount = payout_amount
            survey_response.save(update_fields=['payout_amount'])

            logger.info(f"Survey payment processed: User {user.username} paid KSh {payout_amount} for survey {survey_response.survey.title}")

            return {
                'success': True,
                'transaction': payment_transaction,
                'message': f'Successfully paid KSh {payout_amount} for survey completion'
            }

        except Exception as e:
            logger.error(f"Error processing survey payment: {str(e)}")
            return {
                'success': False,
                'transaction': None,
                'message': f'Payment processing error: {str(e)}'
            }

    @classmethod
    def get_user_survey_earnings(cls, user):
        """Get total earnings from surveys for a user"""
        survey_transactions = Transaction.objects.filter(
            user=user,
            transaction_type='survey_payment',
            status='completed'
        ).order_by('-created_at')

        total_earnings = sum(t.amount for t in survey_transactions)
        survey_count = survey_transactions.count()

        return {
            'total_earnings': Decimal(str(total_earnings)),
            'survey_count': survey_count,
            'transactions': survey_transactions
        }