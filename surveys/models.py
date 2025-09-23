# surveys/models.py
import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from decimal import Decimal

User = get_user_model()


class Survey(models.Model):
    """
    Main Survey model that contains questions and payout information
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('closed', 'Closed'),
    ]

    # UUID Primary Key
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the survey"
    )

    title = models.CharField(
        max_length=200,
        help_text="Survey title that users will see"
    )

    description = models.TextField(
        help_text="Description of what the survey is about"
    )

    payout = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Amount paid to users for completing this survey"
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='draft',
        help_text="Current status of the survey"
    )

    # Survey targeting (optional)
    min_age = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Minimum age for survey participants"
    )

    max_age = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Maximum age for survey participants"
    )

    target_location = models.CharField(
        max_length=100,
        blank=True,
        help_text="Target location/region for survey"
    )

    # Survey limits
    max_responses = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Maximum number of responses needed (optional)"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Admin who created this survey
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_surveys',
        help_text="Admin user who created this survey"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Survey'
        verbose_name_plural = 'Surveys'

    def __str__(self):
        return f"{self.title} (${self.payout})"

    @property
    def short_id(self):
        """Return a shortened version of the UUID for display"""
        return str(self.id)[:8]

    @property
    def total_responses(self):
        """Get total number of responses for this survey"""
        return self.responses.count()

    @property
    def total_payout_cost(self):
        """Calculate total amount paid out for this survey"""
        return self.total_responses * self.payout

    @property
    def is_available(self):
        """Check if survey is available for new responses"""
        if self.status != 'active':
            return False

        if self.max_responses and self.total_responses >= self.max_responses:
            return False

        return True

    def can_user_take_survey(self, user):
        """Check if a specific user can take this survey"""
        # Check if survey is available
        if not self.is_available:
            return False, "Survey is not currently available"

        # Check if user already completed this survey
        if self.responses.filter(user=user).exists():
            return False, "You have already completed this survey"

        # Check age restrictions
        if user.date_of_birth:
            from django.utils import timezone
            age = (timezone.now().date() - user.date_of_birth).days // 365

            if self.min_age and age < self.min_age:
                return False, f"Minimum age requirement: {self.min_age}"

            if self.max_age and age > self.max_age:
                return False, f"Maximum age requirement: {self.max_age}"

        # Check location targeting
        if self.target_location and user.location:
            if self.target_location.lower() not in user.location.lower():
                return False, "This survey is not available in your location"

        return True, "Survey available"


class Question(models.Model):
    """
    Individual questions within a survey
    """
    QUESTION_TYPES = [
        ('text', 'Text Answer (Short)'),
        ('textarea', 'Textarea (Long Answer)'),
        ('mcq', 'Multiple Choice'),
        ('checkbox', 'Checkbox (Multiple Select)'),
        ('rating', 'Rating Scale'),
        ('yes_no', 'Yes/No'),
    ]

    # UUID Primary Key
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the question"
    )

    survey = models.ForeignKey(
        Survey,
        on_delete=models.CASCADE,
        related_name='questions',
        help_text="Survey this question belongs to"
    )

    question_text = models.TextField(
        help_text="The actual question text"
    )

    question_type = models.CharField(
        max_length=10,
        choices=QUESTION_TYPES,
        default='mcq',
        help_text="Type of question"
    )

    is_required = models.BooleanField(
        default=True,
        help_text="Whether this question must be answered"
    )

    order = models.PositiveIntegerField(
        default=1,
        help_text="Order of this question in the survey"
    )

    # For rating questions
    rating_min = models.PositiveIntegerField(
        default=1,
        blank=True,
        null=True,
        help_text="Minimum rating value (for rating questions)"
    )

    rating_max = models.PositiveIntegerField(
        default=5,
        blank=True,
        null=True,
        help_text="Maximum rating value (for rating questions)"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['survey', 'order']
        verbose_name = 'Question'
        verbose_name_plural = 'Questions'

    def __str__(self):
        return f"{self.survey.title} - Q{self.order}: {self.question_text[:50]}..."

    @property
    def short_id(self):
        """Return a shortened version of the UUID for display"""
        return str(self.id)[:8]


class Choice(models.Model):
    """
    Answer choices for multiple choice questions
    """
    # UUID Primary Key
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the choice"
    )

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='choices',
        help_text="Question this choice belongs to"
    )

    choice_text = models.CharField(
        max_length=200,
        help_text="Text for this choice option"
    )

    order = models.PositiveIntegerField(
        default=1,
        help_text="Order of this choice in the question"
    )

    # Correct answer tracking
    is_correct = models.BooleanField(
        default=False,
        help_text="Mark this choice as a correct answer"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['question', 'order']
        verbose_name = 'Choice'
        verbose_name_plural = 'Choices'

    def __str__(self):
        correct_indicator = " ✓" if self.is_correct else ""
        return f"{self.choice_text}{correct_indicator}"

    @property
    def short_id(self):
        """Return a shortened version of the UUID for display"""
        return str(self.id)[:8]


class Response(models.Model):
    """
    User's response to a complete survey
    """
    # UUID Primary Key
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the response"
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='survey_responses',
        help_text="User who submitted this response"
    )

    survey = models.ForeignKey(
        Survey,
        on_delete=models.CASCADE,
        related_name='responses',
        help_text="Survey that was responded to"
    )

    # Add this field for payment service integration
    completed = models.BooleanField(
        default=False,
        help_text="Whether this response has been completed"
    )

    completed_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the survey was completed"
    )

    payout_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Amount paid for this response"
    )

    # Tracking
    ip_address = models.GenericIPAddressField(
        blank=True,
        null=True,
        help_text="IP address of respondent"
    )

    user_agent = models.TextField(
        blank=True,
        help_text="Browser/device information"
    )

    class Meta:
        unique_together = ['user', 'survey']  # One response per user per survey
        ordering = ['-completed_at']
        verbose_name = 'Survey Response'
        verbose_name_plural = 'Survey Responses'

    def __str__(self):
        return f"{self.user.username} - {self.survey.title} (${self.payout_amount})"

    @property
    def short_id(self):
        """Return a shortened version of the UUID for display"""
        return str(self.id)[:8]

    def mark_complete_and_pay(self):
        """
        Mark response as complete and process payment
        """
        # Add earnings to user account
        self.user.add_earnings(self.payout_amount)

        # Create transaction record
        from payments.models import Transaction
        Transaction.objects.create(
            user=self.user,
            transaction_type='survey_payment',
            amount=self.payout_amount,
            status='completed',
            description=f"Payment for completing survey: {self.survey.title}",
            reference_id=str(self.id)
        )


class Answer(models.Model):
    """
    Individual answers to questions within a survey response
    """
    # UUID Primary Key
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the answer"
    )

    response = models.ForeignKey(
        Response,
        on_delete=models.CASCADE,
        related_name='answers',
        help_text="Survey response this answer belongs to"
    )

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='answers',
        help_text="Question this answer is for"
    )

    # Different answer types
    choice = models.ForeignKey(
        Choice,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        help_text="Selected choice (for MCQ questions)"
    )

    text_answer = models.TextField(
        blank=True,
        help_text="Text answer (for text questions)"
    )

    rating_answer = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Rating value (for rating questions)"
    )

    boolean_answer = models.BooleanField(
        blank=True,
        null=True,
        help_text="Yes/No answer (for boolean questions)"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['response', 'question']  # One answer per question per response
        ordering = ['response', 'question__order']
        verbose_name = 'Answer'
        verbose_name_plural = 'Answers'

    def __str__(self):
        if self.choice:
            return f"{self.question.question_text[:30]}... -> {self.choice.choice_text}"
        elif self.text_answer:
            return f"{self.question.question_text[:30]}... -> {self.text_answer[:50]}..."
        elif self.rating_answer is not None:
            return f"{self.question.question_text[:30]}... -> {self.rating_answer}"
        elif self.boolean_answer is not None:
            return f"{self.question.question_text[:30]}... -> {'Yes' if self.boolean_answer else 'No'}"
        return f"{self.question.question_text[:30]}... -> (No answer)"

    @property
    def short_id(self):
        """Return a shortened version of the UUID for display"""
        return str(self.id)[:8]

    @property
    def answer_display(self):
        """Get the answer in a display-friendly format"""
        if self.choice:
            return self.choice.choice_text
        elif self.text_answer:
            return self.text_answer
        elif self.rating_answer is not None:
            return str(self.rating_answer)
        elif self.boolean_answer is not None:
            return 'Yes' if self.boolean_answer else 'No'
        return 'No answer provided'