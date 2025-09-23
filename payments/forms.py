# payments/forms.py - Forms for withdrawal requests

from django import forms
from .models import WithdrawalRequest


class WithdrawalRequestForm(forms.ModelForm):
    """Form for users to create withdrawal requests"""

    phone_number = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': '254712345678',
            'class': 'form-input'
        })
    )

    bank_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'e.g., KCB Bank',
            'class': 'form-input'
        })
    )

    account_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Account number',
            'class': 'form-input'
        })
    )

    account_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Account holder name',
            'class': 'form-input'
        })
    )

    paypal_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'placeholder': 'your.email@example.com',
            'class': 'form-input'
        })
    )

    user_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'placeholder': 'Any additional notes (optional)',
            'class': 'form-textarea',
            'rows': 3
        })
    )

    class Meta:
        model = WithdrawalRequest
        fields = ['amount', 'payment_method', 'user_notes']
        widgets = {
            'amount': forms.NumberInput(attrs={
                'min': '100',
                'max': '50000',
                'step': '0.01',
                'class': 'form-input',
                'placeholder': 'Amount in KSh'
            }),
            'payment_method': forms.Select(attrs={
                'class': 'form-select',
                'onchange': 'togglePaymentFields(this.value)'
            })
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount:
            if amount < 100:
                raise forms.ValidationError("Minimum withdrawal amount is KSh 100")
            if amount > 50000:
                raise forms.ValidationError("Maximum withdrawal amount is KSh 50,000")
        return amount

    def clean(self):
        cleaned_data = super().clean()
        payment_method = cleaned_data.get('payment_method')

        # Validate payment method specific fields
        if payment_method == 'mpesa':
            phone_number = cleaned_data.get('phone_number')
            if not phone_number:
                raise forms.ValidationError("M-Pesa phone number is required")
            # Basic validation for Kenyan phone numbers
            if not phone_number.startswith('254') or len(phone_number) != 12:
                raise forms.ValidationError("Please enter a valid Kenyan phone number (254XXXXXXXXX)")

        elif payment_method == 'bank_transfer':
            bank_name = cleaned_data.get('bank_name')
            account_number = cleaned_data.get('account_number')
            account_name = cleaned_data.get('account_name')

            if not all([bank_name, account_number, account_name]):
                raise forms.ValidationError(
                    "Bank name, account number, and account name are required for bank transfers")

        elif payment_method == 'paypal':
            paypal_email = cleaned_data.get('paypal_email')
            if not paypal_email:
                raise forms.ValidationError("PayPal email is required")

        return cleaned_data
