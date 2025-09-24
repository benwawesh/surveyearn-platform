# accounts/models.py
import uuid
import string
import secrets
from django.db import models
from django.contrib.auth.models import AbstractUser
from decimal import Decimal

class User(AbstractUser):
    """
    Custom User model that extends Django's AbstractUser
    to include balance tracking for survey earnings
    """
    # UUID Primary Key
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the user"
    )

    # Additional fields beyond the default User fields
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="User's current balance from completed surveys"
    )

    phone_number = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        help_text="Phone number for M-Pesa payments"
    )

    date_of_birth = models.DateField(
        blank=True,
        null=True,
        help_text="Used for demographic targeting"
    )

    # Profile information
    bio = models.TextField(
        blank=True,
        max_length=500,
        help_text="Short bio or description"
    )

    location = models.CharField(
        max_length=100,
        blank=True,
        help_text="City or region for location-based surveys"
    )

    # Tracking fields
    total_surveys_completed = models.PositiveIntegerField(
        default=0,
        help_text="Total number of surveys completed by user"
    )

    total_earnings = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total amount earned (including withdrawn amounts)"
    )

    # Profile completion and verification
    profile_completed = models.BooleanField(
        default=False,
        help_text="Whether user has completed their profile"
    )

    email_verified = models.BooleanField(
        default=False,
        help_text="Whether user's email has been verified"
    )

    phone_verified = models.BooleanField(
        default=False,
        help_text="Whether user's phone number has been verified"
    )

    # NEW PAID REGISTRATION FIELDS
    registration_paid = models.BooleanField(
        default=False,
        help_text="Whether user has paid the registration fee"
    )

    registration_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('500.00'),  # Set your registration fee here
        help_text="Registration fee amount"
    )

    registration_payment_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the registration payment was completed"
    )

    mpesa_receipt_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="M-Pesa receipt number for registration payment"
    )

    mpesa_checkout_request_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="M-Pesa checkout request ID for tracking"
    )

    country = models.CharField(
        max_length=100,
        blank=True,
        default='Kenya',
        help_text="User's country"
    )

    # === REFERRAL SYSTEM FIELDS ===
    referral_code = models.CharField(
        max_length=10,
        unique=True,
        blank=True,
        help_text="Unique referral code for this user"
    )

    referred_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referrals',
        help_text="User who referred this user"
    )

    referral_earnings = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total earnings from referral commissions"
    )

    total_referrals = models.PositiveIntegerField(
        default=0,
        help_text="Total number of users referred by this user"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounts_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"{self.username} (KSh {self.balance})"

    def save(self, *args, **kwargs):
        """Override save to generate referral code if not exists"""
        if not self.referral_code:
            self.referral_code = self.generate_referral_code()
        super().save(*args, **kwargs)

    def generate_referral_code(self):
        """Generate unique 8-character referral code"""
        import random
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            if not User.objects.filter(referral_code=code).exists():
                return code

    @property
    def short_id(self):
        """Return a shortened version of the UUID for display"""
        return str(self.id)[:8]

    @property
    def full_name(self):
        """Get user's full name or username if not provided"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        return self.username

    @property
    def initials(self):
        """Get user's initials for avatar display"""
        if self.first_name and self.last_name:
            return f"{self.first_name[0]}{self.last_name[0]}".upper()
        elif self.first_name:
            return self.first_name[0].upper()
        return self.username[:2].upper()

    @property
    def referral_url(self):
        """Get the full referral URL for this user"""
        from django.conf import settings
        base_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
        return f"{base_url}/?ref={self.referral_code}"

    def get_pending_referral_commissions(self):
        """Get total pending referral commissions"""
        return self.commissions_earned.filter(processed=False).aggregate(
            total=models.Sum('commission_amount')
        )['total'] or Decimal('0.00')

    def get_processed_referral_commissions(self):
        """Get total processed referral commissions"""
        return self.commissions_earned.filter(processed=True).aggregate(
            total=models.Sum('commission_amount')
        )['total'] or Decimal('0.00')

    def add_earnings(self, amount):
        """
        Add earnings to user's balance and total earnings
        """
        self.balance += Decimal(str(amount))
        self.total_earnings += Decimal(str(amount))
        self.total_surveys_completed += 1
        self.save()

    def can_withdraw(self, amount):
        """
        Check if user can withdraw the specified amount
        """
        from django.conf import settings
        min_amount = getattr(settings, 'MINIMUM_WITHDRAWAL_AMOUNT', 10.00)

        return (
                self.balance >= Decimal(str(amount)) and
                Decimal(str(amount)) >= Decimal(str(min_amount))
        )

    def deduct_balance(self, amount):
        """
        Deduct amount from user's balance (for withdrawals)
        """
        if self.can_withdraw(amount):
            self.balance -= Decimal(str(amount))
            self.save()
            return True
        return False

    @property
    def surveys_completed_this_month(self):
        """
        Get number of surveys completed this month
        """
        from django.utils import timezone

        start_of_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Import here to avoid circular imports
        from surveys.models import Response
        return Response.objects.filter(
            user=self,
            completed_at__gte=start_of_month
        ).count()

    @property
    def earnings_this_month(self):
        """
        Get earnings for current month
        """
        from django.utils import timezone
        from decimal import Decimal

        start_of_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Import here to avoid circular imports
        from payments.models import Transaction

        transactions = Transaction.objects.filter(
            user=self,
            transaction_type='survey_payment',
            created_at__gte=start_of_month
        )

        return sum([t.amount for t in transactions], Decimal('0.00'))

    def get_payment_methods(self):
        """Return available payment methods for withdrawals"""
        return [
            ('mpesa', 'M-Pesa'),
            ('bank_transfer', 'Bank Transfer'),
            ('paypal', 'PayPal')
        ]

    def get_default_payment_method(self):
        """Return default payment method based on user's location"""
        # Since this is for Kenyan users, default to M-Pesa
        if self.phone_number:
            return 'mpesa'
        return 'bank_transfer'  # Fallback option

    def get_recent_transactions(self, limit=10):
        """
        Get user's recent transactions
        """
        from payments.models import Transaction
        return Transaction.objects.filter(user=self).order_by('-created_at')[:limit]

    def get_pending_withdrawals(self):
        """
        Get user's pending withdrawal requests
        """
        from payments.models import WithdrawalRequest
        return WithdrawalRequest.objects.filter(
            user=self,
            status__in=['pending', 'approved']
        ).order_by('-created_at')

    def get_available_surveys(self):
        """
        Get surveys that this user can take
        """
        from surveys.models import Survey

        # Get all active surveys
        available_surveys = Survey.objects.filter(status='active')

        # Filter out surveys user has already completed
        completed_survey_ids = self.survey_responses.values_list('survey_id', flat=True)
        available_surveys = available_surveys.exclude(id__in=completed_survey_ids)

        # Apply age filtering if user has date of birth
        if self.date_of_birth:
            from django.utils import timezone
            age = (timezone.now().date() - self.date_of_birth).days // 365

            available_surveys = available_surveys.filter(
                models.Q(min_age__isnull=True) | models.Q(min_age__lte=age),
                models.Q(max_age__isnull=True) | models.Q(max_age__gte=age)
            )

        # Apply location filtering if user has location
        if self.location:
            available_surveys = available_surveys.filter(
                models.Q(target_location__isnull=True) |
                models.Q(target_location__iexact='') |
                models.Q(target_location__icontains=self.location)
            )

        return available_surveys.order_by('-created_at')

    @property
    def profile_completion_percentage(self):
        """
        Calculate profile completion percentage
        """
        fields_to_check = [
            'first_name', 'last_name', 'email', 'phone_number',
            'date_of_birth', 'location', 'bio'
        ]

        completed_fields = 0
        for field in fields_to_check:
            value = getattr(self, field)
            if value:
                completed_fields += 1

        # Add verification bonuses
        if self.email_verified:
            completed_fields += 1
        if self.phone_verified:
            completed_fields += 1

        total_fields = len(fields_to_check) + 2  # +2 for verifications
        return round((completed_fields / total_fields) * 100)

    def update_profile_completion_status(self):
        """
        Update the profile_completed field based on minimum requirements
        """
        required_fields = ['first_name', 'last_name', 'email', 'date_of_birth']

        is_complete = all(getattr(self, field) for field in required_fields)
        is_complete = is_complete and self.email_verified

        if self.profile_completed != is_complete:
            self.profile_completed = is_complete
            self.save(update_fields=['profile_completed'])

        return is_complete

    def can_take_surveys(self):
        """
        Check if user meets minimum requirements to take surveys
        """
        return (
                self.is_active and
                self.registration_paid and  # NEW: Must have paid registration
                self.email_verified and
                self.date_of_birth is not None and
                self.profile_completed
        )

    @property
    def survey_eligibility_issues(self):
        """
        Get list of issues preventing user from taking surveys
        """
        issues = []

        if not self.is_active:
            issues.append("Account is not active")

        if not self.registration_paid:  # NEW: Check registration payment
            issues.append("Registration fee not paid")

        if not self.email_verified:
            issues.append("Email address not verified")

        if not self.date_of_birth:
            issues.append("Date of birth not provided")

        if not self.profile_completed:
            issues.append("Profile not completed")

        return issues


class ReferralCommission(models.Model):
    """Track all referral commissions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    referrer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='commissions_earned',
        help_text="User who earned the commission"
    )
    referred_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='commissions_generated',
        help_text="User who generated the commission"
    )
    commission_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Commission amount earned"
    )
    commission_type = models.CharField(
        max_length=20,
        choices=[
            ('registration', 'Registration'),
            ('survey', 'Survey Completion'),
        ],
        help_text="Type of activity that generated this commission"
    )
    source_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Original transaction amount that generated this commission"
    )
    processed = models.BooleanField(
        default=False,
        help_text="Whether this commission has been paid out"
    )
    processed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this commission was processed"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this commission was created"
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['referrer', '-created_at']),
            models.Index(fields=['processed', '-created_at']),
        ]

    def __str__(self):
        return f"{self.referrer.username} earned KSh {self.commission_amount} from {self.referred_user.username}"

    @property
    def short_id(self):
        """Return a shortened version of the UUID for display"""
        return str(self.id)[:8]


class SystemSettings(models.Model):
    """
    Admin-configurable system settings for fees, rates, and other parameters
    """
    SETTING_TYPES = [
        ('fee', 'Fee Amount'),
        ('rate', 'Commission Rate'),
        ('limit', 'System Limit'),
        ('config', 'Configuration'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    setting_key = models.CharField(max_length=100, unique=True, help_text="Unique identifier for this setting")
    setting_name = models.CharField(max_length=200, help_text="Human-readable name")
    setting_type = models.CharField(max_length=20, choices=SETTING_TYPES, default='config')

    # Value fields - only one should be used per setting
    decimal_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    integer_value = models.IntegerField(null=True, blank=True)
    text_value = models.TextField(null=True, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)

    # Validation and constraints
    min_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                    help_text="Minimum allowed value (for numeric settings)")
    max_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                    help_text="Maximum allowed value (for numeric settings)")

    # Metadata
    description = models.TextField(help_text="Description of what this setting controls")
    is_active = models.BooleanField(default=True)
    requires_restart = models.BooleanField(default=False, help_text="Whether changing this requires app restart")

    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "System Setting"
        verbose_name_plural = "System Settings"
        ordering = ['setting_name']

    def __str__(self):
        return f"{self.setting_name}: {self.get_value()}"

    def get_value(self):
        """Return the actual value based on setting type"""
        if self.decimal_value is not None:
            return self.decimal_value
        elif self.integer_value is not None:
            return self.integer_value
        elif self.boolean_value is not None:
            return self.boolean_value
        elif self.text_value is not None:
            return self.text_value
        return None

    def set_value(self, value):
        """Set the value, automatically determining the correct field"""
        # Clear all value fields first
        self.decimal_value = None
        self.integer_value = None
        self.text_value = None
        self.boolean_value = None

        if isinstance(value, bool):
            self.boolean_value = value
        elif isinstance(value, int):
            self.integer_value = value
        elif isinstance(value, (float, Decimal)):
            self.decimal_value = Decimal(str(value))
        else:
            self.text_value = str(value)

    def clean(self):
        """Validate that only one value field is set and within constraints"""
        from django.core.exceptions import ValidationError

        value_fields = [self.decimal_value, self.integer_value, self.text_value, self.boolean_value]
        non_null_values = [v for v in value_fields if v is not None]

        if len(non_null_values) == 0:
            raise ValidationError("At least one value field must be set")

        if len(non_null_values) > 1:
            raise ValidationError("Only one value field can be set")

        # Validate numeric ranges
        current_value = self.get_value()
        if isinstance(current_value, (int, float, Decimal)):
            if self.min_value is not None and current_value < self.min_value:
                raise ValidationError(f"Value {current_value} is below minimum {self.min_value}")

            if self.max_value is not None and current_value > self.max_value:
                raise ValidationError(f"Value {current_value} is above maximum {self.max_value}")

    @classmethod
    def get_setting(cls, key, default=None):
        """Get a setting value by key, with fallback to default"""
        try:
            setting = cls.objects.get(setting_key=key, is_active=True)
            return setting.get_value()
        except cls.DoesNotExist:
            return default

    @classmethod
    def set_setting(cls, key, value, user=None):
        """Set or update a setting value"""
        setting, created = cls.objects.get_or_create(
            setting_key=key,
            defaults={'setting_name': key.replace('_', ' ').title()}
        )
        setting.set_value(value)
        if user:
            setting.updated_by = user
        setting.save()
        return setting


class SettingsAuditLog(models.Model):
    """
    Track all changes to system settings for audit purposes
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    setting = models.ForeignKey(SystemSettings, on_delete=models.CASCADE, related_name='audit_logs')

    # Change tracking
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    change_reason = models.TextField(blank=True)

    # User tracking
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "Settings Audit Log"
        verbose_name_plural = "Settings Audit Logs"
        ordering = ['-changed_at']

    def __str__(self):
        return f"{self.setting.setting_name} changed by {self.changed_by} at {self.changed_at}"