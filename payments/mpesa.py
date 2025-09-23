# payments/mpesa.py - M-Pesa integration service

import requests
import base64
from datetime import datetime
from django.conf import settings
from django.utils import timezone
import json
import logging

logger = logging.getLogger(__name__)


class MPesaService:
    """Service class for M-Pesa API integration"""

    def __init__(self):
        # M-Pesa API Configuration
        self.consumer_key = getattr(settings, 'MPESA_CONSUMER_KEY', '')
        self.consumer_secret = getattr(settings, 'MPESA_CONSUMER_SECRET', '')
        self.business_shortcode = getattr(settings, 'MPESA_BUSINESS_SHORTCODE', '')
        self.passkey = getattr(settings, 'MPESA_PASSKEY', '')
        self.environment = getattr(settings, 'MPESA_ENVIRONMENT', 'sandbox')  # 'sandbox' or 'production'

        # API URLs
        if self.environment == 'production':
            self.base_url = 'https://api.safaricom.co.ke'
        else:
            self.base_url = 'https://sandbox.safaricom.co.ke'

        self.auth_url = f'{self.base_url}/oauth/v1/generate?grant_type=client_credentials'
        self.b2c_url = f'{self.base_url}/mpesa/b2c/v1/paymentrequest'
        self.c2b_url = f'{self.base_url}/mpesa/c2b/v1/simulate'
        self.stk_push_url = f'{self.base_url}/mpesa/stkpush/v1/processrequest'
        self.query_url = f'{self.base_url}/mpesa/b2c/v1/paymentrequest'

    def get_access_token(self):
        """Get M-Pesa API access token"""
        try:
            # Create basic auth header
            credentials = f"{self.consumer_key}:{self.consumer_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()

            headers = {
                'Authorization': f'Basic {encoded_credentials}',
                'Content-Type': 'application/json'
            }

            response = requests.get(self.auth_url, headers=headers)

            if response.status_code == 200:
                result = response.json()
                return result.get('access_token')
            else:
                logger.error(f"Failed to get M-Pesa access token: {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error getting M-Pesa access token: {str(e)}")
            return None

    def generate_password(self, timestamp=None):
        """Generate M-Pesa password for STK Push"""
        if not timestamp:
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

        password_string = f"{self.business_shortcode}{self.passkey}{timestamp}"
        password = base64.b64encode(password_string.encode()).decode()

        return password, timestamp

    def send_b2c_payment(self, phone_number, amount, withdrawal_request):
        """Send Business to Customer (B2C) payment - for withdrawals"""

        access_token = self.get_access_token()
        if not access_token:
            return {'success': False, 'error': 'Failed to get access token'}

        # Clean phone number (ensure it starts with 254)
        phone_number = self.format_phone_number(phone_number)

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        payload = {
            "InitiatorName": getattr(settings, 'MPESA_INITIATOR_NAME', 'testapi'),
            "SecurityCredential": self.get_security_credential(),
            "CommandID": "BusinessPayment",  # or "SalaryPayment" for bulk payments
            "Amount": str(int(amount)),  # M-Pesa expects integer
            "PartyA": self.business_shortcode,
            "PartyB": phone_number,
            "Remarks": f"SurveyEarn withdrawal for KSh {amount}",
            "QueueTimeOutURL": f"{getattr(settings, 'SITE_URL', 'https://yourdomain.com')}/payments/mpesa/timeout/",
            "ResultURL": f"{getattr(settings, 'SITE_URL', 'https://yourdomain.com')}/payments/mpesa/result/",
            "Occasion": f"Withdrawal-{withdrawal_request.id}"
        }

        try:
            response = requests.post(self.b2c_url, json=payload, headers=headers)
            result = response.json()

            if response.status_code == 200 and result.get('ResponseCode') == '0':
                return {
                    'success': True,
                    'conversation_id': result.get('ConversationID'),
                    'originator_conversation_id': result.get('OriginatorConversationID'),
                    'response_description': result.get('ResponseDescription')
                }
            else:
                logger.error(f"M-Pesa B2C failed: {result}")
                return {
                    'success': False,
                    'error': result.get('errorMessage', 'Unknown error'),
                    'response_code': result.get('ResponseCode')
                }

        except Exception as e:
            logger.error(f"M-Pesa B2C exception: {str(e)}")
            return {'success': False, 'error': str(e)}

    def initiate_stk_push(self, phone_number, amount, reference, description="Survey payment"):
        """Initiate STK Push for payments to the platform"""

        # Make sure this block is commented out:
        # if settings.DEBUG:
        #     print(f"DEVELOPMENT MODE: Auto-approving M-Pesa payment")
        #     return {...}


        # Real M-Pesa integration
        access_token = self.get_access_token()

        if not access_token:
            return {'success': False, 'error': 'Failed to get access token'}

        # Generate password and timestamp
        password, timestamp = self.generate_password()

        # Clean phone number
        phone_number = self.format_phone_number(phone_number)

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        payload = {
            "BusinessShortCode": self.business_shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": str(int(amount)),
            "PartyA": phone_number,
            "PartyB": self.business_shortcode,
            "PhoneNumber": phone_number,
            "CallBackURL": f"{getattr(settings, 'SITE_URL', 'https://yourdomain.com')}/accounts/mpesa-callback/",
            "AccountReference": reference,
            "TransactionDesc": description
        }


        try:
            response = requests.post(self.stk_push_url, json=payload, headers=headers)
            result = response.json()


            if response.status_code == 200 and result.get('ResponseCode') == '0':
                return {
                    'success': True,
                    'checkout_request_id': result.get('CheckoutRequestID'),
                    'merchant_request_id': result.get('MerchantRequestID'),
                    'response_description': result.get('ResponseDescription')
                }
            else:
                logger.error(f"M-Pesa STK Push failed: {result}")
                return {
                    'success': False,
                    'error': result.get('errorMessage', 'Unknown error'),
                    'response_code': result.get('ResponseCode')
                }

        except Exception as e:
            logger.error(f"M-Pesa STK Push exception: {str(e)}")
            return {'success': False, 'error': str(e)}

    def query_transaction_status(self, checkout_request_id):
        """Query the status of an STK Push transaction"""

        access_token = self.get_access_token()
        if not access_token:
            return {'success': False, 'error': 'Failed to get access token'}

        password, timestamp = self.generate_password()

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        payload = {
            "BusinessShortCode": self.business_shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id
        }

        query_url = f'{self.base_url}/mpesa/stkpushquery/v1/query'

        try:
            response = requests.post(query_url, json=payload, headers=headers)
            result = response.json()

            return {
                'success': response.status_code == 200,
                'result': result
            }

        except Exception as e:
            logger.error(f"M-Pesa query exception: {str(e)}")
            return {'success': False, 'error': str(e)}

    def get_security_credential(self):
        """Get security credential for B2C (this would need proper implementation with certificates)"""
        # In production, this should be properly encrypted using M-Pesa's public certificate
        # For now, returning the initiator password (this is NOT production-ready)
        initiator_password = getattr(settings, 'MPESA_INITIATOR_PASSWORD', 'Safcom@2019')

        # TODO: Implement proper encryption using M-Pesa's public certificate
        # For sandbox testing, you can use the plain password
        # For production, you MUST encrypt this using M-Pesa's certificate

        return initiator_password

    @staticmethod
    def format_phone_number(phone_number):
        """Format phone number to M-Pesa format (254XXXXXXXXX)"""
        # Remove any spaces, dashes, or plus signs
        phone_number = phone_number.replace(' ', '').replace('-', '').replace('+', '')

        # Convert to 254 format
        if phone_number.startswith('0'):
            phone_number = '254' + phone_number[1:]
        elif phone_number.startswith('7') or phone_number.startswith('1'):
            phone_number = '254' + phone_number
        elif not phone_number.startswith('254'):
            phone_number = '254' + phone_number

        return phone_number

    @staticmethod
    def validate_phone_number(phone_number):
        """Validate Kenyan phone number"""
        formatted = MPesaService.format_phone_number(phone_number)

        # Check if it's a valid Kenyan number
        if len(formatted) != 12:
            return False

        if not formatted.startswith('254'):
            return False

        # Check if the number after 254 is valid (7XX or 1XX)
        if not (formatted[3] == '7' or formatted[3] == '1'):
            return False

        return True


# Wrapper functions for easy importing in views
def initiate_stk_push(phone_number, amount, account_reference, transaction_desc):
    """
    Wrapper function for STK Push - called from views
    """
    mpesa_service = MPesaService()
    return mpesa_service.initiate_stk_push(
        phone_number=phone_number,
        amount=amount,
        reference=account_reference,
        description=transaction_desc
    )


def send_payment(phone_number, amount, withdrawal_request):
    """
    Wrapper function for B2C payments - for withdrawals
    """
    mpesa_service = MPesaService()
    return mpesa_service.send_b2c_payment(phone_number, amount, withdrawal_request)


def query_payment_status(checkout_request_id):
    """
    Wrapper function for querying payment status
    """
    mpesa_service = MPesaService()
    return mpesa_service.query_transaction_status(checkout_request_id)