# payments/models.py - Complete models file

import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal

User = get_user_model()


class Transaction(models.Model):
    """Track all financial transactions in the platform"""

    TRANSACTION_TYPES = [
        ('registration', 'Registration Payment'),
        ('survey_payment', 'Survey Payment'),
        ('withdrawal', 'Withdrawal'),
        ('adjustment', 'Admin Adjustment'),
        ('bonus', 'Bonus Payment'),
        ('refund', 'Refund'),
        ('fee', 'Fee Deduction'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions')

    # Transaction details
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    description = models.TextField()

    # Balance tracking
    balance_before = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Admin tracking
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_transactions'
    )

    # Additional fields
    reference_id = models.CharField(max_length=100, blank=True, null=True)
    notes = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Transaction'
        verbose_name_plural = 'Transactions'

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.user.username} - KSh {self.amount}"

    def save(self, *args, **kwargs):
        if self.status == 'completed' and not self.processed_at:
            self.processed_at = timezone.now()
        super().save(*args, **kwargs)


class WithdrawalRequest(models.Model):
    """Handle user withdrawal requests"""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    PAYMENT_METHODS = [
        ('mpesa', 'M-Pesa'),
        ('bank_transfer', 'Bank Transfer'),
        ('paypal', 'PayPal'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='withdrawal_requests')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)

    # Payment details (JSON field to store various payment info)
    payment_details = models.JSONField(default=dict, help_text="Store payment method specific details")

    # M-Pesa specific fields
    mpesa_phone_number = models.CharField(max_length=15, blank=True, null=True)
    mpesa_transaction_id = models.CharField(max_length=100, blank=True, null=True)

    # Bank transfer specific fields
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    account_number = models.CharField(max_length=50, blank=True, null=True)
    account_name = models.CharField(max_length=100, blank=True, null=True)

    # PayPal specific fields
    paypal_email = models.EmailField(blank=True, null=True)

    # Request tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_withdrawals'
    )

    # Admin notes
    admin_notes = models.TextField(blank=True)
    user_notes = models.TextField(blank=True, help_text="User's withdrawal notes/reason")

    # Fee tracking
    withdrawal_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    net_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Amount after fees")

    # External transaction reference
    external_reference = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Withdrawal Request'
        verbose_name_plural = 'Withdrawal Requests'

    def __str__(self):
        return f"{self.user.username} - KSh {self.amount} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        # Calculate net amount (subtract fees)
        if not self.net_amount:
            self.net_amount = self.amount - self.withdrawal_fee

        # Set completion timestamp
        if self.status == 'completed' and not self.completed_at:
            self.completed_at = timezone.now()

        super().save(*args, **kwargs)

    def can_be_processed(self):
        """Check if withdrawal can be processed"""
        return self.status == 'pending' and self.user.balance >= self.amount

    def can_be_approved(self):
        """Check if withdrawal can be approved"""
        return self.status == 'pending'

    def can_be_rejected(self):
        """Check if withdrawal can be rejected"""
        return self.status == 'pending'

    def get_payment_details_display(self):
        """Return formatted payment details for display"""
        if self.payment_method == 'mpesa':
            return f"M-Pesa: {self.mpesa_phone_number}"
        elif self.payment_method == 'bank_transfer':
            return f"Bank: {self.bank_name} - {self.account_number}"
        elif self.payment_method == 'paypal':
            return f"PayPal: {self.paypal_email}"
        return "Payment details not available"

    def approve(self, admin_user, notes=''):
        """Approve this withdrawal request"""
        from .services import WithdrawalService
        try:
            return WithdrawalService.approve_withdrawal(self, admin_user, notes)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error approving withdrawal {self.id}: {str(e)}")
            return False

    def reject(self, admin_user, reason, notes=''):
        """Reject this withdrawal request"""
        from .services import WithdrawalService
        try:
            return WithdrawalService.reject_withdrawal(self, admin_user, reason, notes)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error rejecting withdrawal {self.id}: {str(e)}")
            return False

    def complete(self, admin_user, external_reference='', actual_amount=None):
        """Mark withdrawal as completed"""
        from .services import WithdrawalService
        try:
            return WithdrawalService.complete_withdrawal(self, admin_user, external_reference, actual_amount)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error completing withdrawal {self.id}: {str(e)}")
            return False

    def fail_withdrawal(self, admin_user, error_reason=''):
        """Mark withdrawal as failed"""
        from .services import WithdrawalService
        try:
            return WithdrawalService.fail_withdrawal(self, admin_user, error_reason)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error failing withdrawal {self.id}: {str(e)}")
            return False

    @property
    def short_id(self):
        """Return a shortened version of the UUID for display"""
        return str(self.id)[:8]

    def can_be_processed(self):
        """Check if withdrawal can be processed"""
        return self.user.balance >= self.amount


class MPesaTransaction(models.Model):
    """Track M-Pesa transactions"""

    TRANSACTION_TYPES = [
        ('b2c', 'Business to Customer (Withdrawal)'),
        ('c2b', 'Customer to Business (Payment)'),
        ('stk_push', 'STK Push Payment'),
    ]

    STATUS_CHOICES = [
        ('initiated', 'Initiated'),
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('timeout', 'Timeout'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mpesa_transactions')
    withdrawal_request = models.ForeignKey(
        WithdrawalRequest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='mpesa_transactions'
    )

    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    phone_number = models.CharField(max_length=15)

    # M-Pesa specific fields
    conversation_id = models.CharField(max_length=100, blank=True, null=True)
    originator_conversation_id = models.CharField(max_length=100, blank=True, null=True)
    checkout_request_id = models.CharField(max_length=100, blank=True, null=True)
    merchant_request_id = models.CharField(max_length=100, blank=True, null=True)
    mpesa_receipt_number = models.CharField(max_length=100, blank=True, null=True)
    transaction_date = models.DateTimeField(blank=True, null=True)

    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='initiated')
    result_code = models.CharField(max_length=10, blank=True, null=True)
    result_desc = models.TextField(blank=True)

    # API response data (for debugging)
    api_response = models.JSONField(default=dict, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'M-Pesa Transaction'
        verbose_name_plural = 'M-Pesa Transactions'

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.user.username} - KSh {self.amount}"

    def is_successful(self):
        """Check if transaction was successful"""
        return self.status == 'completed' and self.result_code == '0'