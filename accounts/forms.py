# accounts/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm as DjangoPasswordChangeForm
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from .models import User
from decimal import Decimal
import re


class PaidUserRegistrationForm(UserCreationForm):
    """Paid registration form with M-Pesa STK push integration"""

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': 'Enter your email address'
        })
    )

    phone_number = forms.CharField(
        max_length=15,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': '+254712345678'
        }),
        help_text='Enter your M-Pesa number for payment (must be a Kenyan number)'
    )

    country = forms.CharField(
        max_length=100,
        required=True,
        initial='Kenya',
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': 'Enter your country'
        })
    )

    # Registration fee info (read-only display)
    registration_fee = forms.CharField(
        initial='KSh 500',
        required=False,  # Make this not required
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 bg-gray-100 border border-gray-300 rounded-md text-gray-700',
            'readonly': True
        }),
        label='Registration Fee',
        help_text='One-time payment for platform access'
    )

    terms_accepted = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded'
        }),
        label='I agree to pay the registration fee and accept Terms of Service'
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'phone_number', 'country', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Customize default fields
        self.fields['username'].widget.attrs.update({
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': 'Choose a username'
        })

        self.fields['password1'].widget.attrs.update({
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': 'Create a strong password'
        })

        self.fields['password2'].widget.attrs.update({
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': 'Confirm your password'
        })

        # Update help texts
        self.fields['username'].help_text = 'Choose a unique username (letters, numbers, and @/./+/-/_ only)'
        self.fields['password1'].help_text = 'At least 8 characters with letters and numbers'

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError('A user with this email already exists.')
        return email

    def clean_username(self):
        username = self.cleaned_data.get('username')

        if not re.match(r'^[\w.@+-]+$', username):
            raise ValidationError('Username can only contain letters, numbers, and @/./+/-/_ characters.')

        if len(username) < 3:
            raise ValidationError('Username must be at least 3 characters long.')

        return username

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        if phone:
            # Remove any spaces or special characters except +
            phone_clean = re.sub(r'[^\d+]', '', phone)

            # Kenya phone number validation
            if phone_clean.startswith('+254'):
                if len(phone_clean) != 13:
                    raise ValidationError('Kenyan phone number should be +254XXXXXXXXX (13 digits total)')
            elif phone_clean.startswith('254'):
                if len(phone_clean) != 12:
                    raise ValidationError('Kenyan phone number should be 254XXXXXXXXX (12 digits total)')
                phone_clean = '+' + phone_clean
            elif phone_clean.startswith('07') or phone_clean.startswith('01'):
                if len(phone_clean) != 10:
                    raise ValidationError('Kenyan phone number should be 07XXXXXXXX or 01XXXXXXXX (10 digits total)')
                # Convert to international format
                phone_clean = '+254' + phone_clean[1:]
            else:
                raise ValidationError('Please enter a valid Kenyan phone number starting with +254, 254, 07, or 01')

            # Check if phone number already exists
            if User.objects.filter(phone_number=phone_clean).exists():
                raise ValidationError('A user with this phone number already exists.')

            return phone_clean
        return phone

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.phone_number = self.cleaned_data['phone_number']
        user.country = self.cleaned_data['country']
        user.location = self.cleaned_data['country']

        # Set user as inactive until payment is confirmed
        user.is_active = False
        user.registration_paid = False
        user.registration_amount = Decimal('500.00')

        if commit:
            user.save()
        return user


class UserLoginForm(forms.Form):
    """User login form"""

    username = forms.CharField(
        max_length=254,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': 'Username or Email',
            'autofocus': True
        })
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': 'Password'
        })
    )

    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded'
        }),
        label='Remember me'
    )

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if username and password:
            # Try to authenticate with username first, then email
            user = authenticate(username=username, password=password)
            if not user:
                # Try email authentication
                try:
                    user_obj = User.objects.get(email=username)
                    user = authenticate(username=user_obj.username, password=password)
                except User.DoesNotExist:
                    pass

            if not user:
                raise ValidationError('Invalid username/email or password.')

            if not user.is_active:
                if hasattr(user, 'registration_paid') and not user.registration_paid:
                    raise ValidationError(
                        'Please complete your registration payment to activate your account. Check your phone for M-Pesa prompt or contact support.')
                else:
                    raise ValidationError('This account has been deactivated.')

        return self.cleaned_data


class UserProfileForm(forms.ModelForm):
    """User profile form for updating user information"""

    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'type': 'date'
        }),
        help_text='Required to determine survey eligibility'
    )

    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'email', 'phone_number',
            'date_of_birth', 'location', 'bio'
        ]

        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'First name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'Last name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'Email address'
            }),
            'phone_number': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': '+254 XXX XXX XXX'
            }),
            'location': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'City, Country'
            }),
            'bio': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'rows': 4,
                'placeholder': 'Tell us a bit about yourself...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Mark required fields
        required_fields = ['first_name', 'last_name', 'email', 'date_of_birth']
        for field_name in required_fields:
            if field_name in self.fields:
                self.fields[field_name].required = True
                self.fields[field_name].label = (self.fields[field_name].label or '') + ' *'

    def clean_email(self):
        email = self.cleaned_data.get('email')

        # Check if email is taken by another user
        if self.instance and self.instance.pk:
            existing_user = User.objects.filter(email=email).exclude(pk=self.instance.pk).first()
        else:
            existing_user = User.objects.filter(email=email).first()

        if existing_user:
            raise ValidationError('This email address is already in use.')

        return email

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        if phone:
            # Basic phone number validation
            phone = re.sub(r'\D', '', phone)  # Remove non-digits
            if len(phone) < 10 or len(phone) > 15:
                raise ValidationError('Please enter a valid phone number.')
        return phone

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get('date_of_birth')
        if dob:
            from django.utils import timezone
            age = (timezone.now().date() - dob).days // 365

            if age < 13:
                raise ValidationError('You must be at least 13 years old to use this platform.')
            if age > 120:
                raise ValidationError('Please enter a valid date of birth.')

        return dob


class PasswordChangeForm(DjangoPasswordChangeForm):
    """Custom password change form with styling"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add CSS classes to all fields
        for field_name, field in self.fields.items():
            field.widget.attrs.update({
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
            })

        # Update placeholders
        self.fields['old_password'].widget.attrs['placeholder'] = 'Current password'
        self.fields['new_password1'].widget.attrs['placeholder'] = 'New password'
        self.fields['new_password2'].widget.attrs['placeholder'] = 'Confirm new password'


class EmailVerificationForm(forms.Form):
    """Form for requesting email verification"""

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': 'Your email address'
        })
    )

    def __init__(self, user=None, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

        if self.user:
            self.fields['email'].initial = self.user.email
            self.fields['email'].widget.attrs['readonly'] = True

    def clean_email(self):
        email = self.cleaned_data.get('email')

        if self.user and email != self.user.email:
            raise ValidationError('Email address does not match your account.')

        return email


class ContactForm(forms.Form):
    """Contact form for user inquiries"""

    SUBJECT_CHOICES = [
        ('general', 'General Inquiry'),
        ('technical', 'Technical Support'),
        ('payment', 'Payment Issue'),
        ('survey', 'Survey Question'),
        ('account', 'Account Issue'),
        ('other', 'Other'),
    ]

    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': 'Your full name'
        })
    )

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': 'Your email address'
        })
    )

    subject = forms.ChoiceField(
        choices=SUBJECT_CHOICES,
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
        })
    )

    message = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'rows': 6,
            'placeholder': 'Please describe your question or issue in detail...'
        })
    )

    def __init__(self, user=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if user and user.is_authenticated:
            self.fields['name'].initial = user.get_full_name()
            self.fields['email'].initial = user.email