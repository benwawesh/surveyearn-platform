# Create accounts/consumers.py

import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.conf import settings
from accounts.models import User
from payments.mpesa import MPesaService
import logging

logger = logging.getLogger(__name__)


class PaymentStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Get user_id from URL route
        self.user_id = self.scope['url_route']['kwargs']['user_id']
        self.group_name = f'payment_{self.user_id}'

        # Join group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

        # Start checking payment status
        await self.start_payment_monitoring()

    async def disconnect(self, close_code):
        # Leave group
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

        # Cancel monitoring task if it exists
        if hasattr(self, 'monitoring_task'):
            self.monitoring_task.cancel()

    async def start_payment_monitoring(self):
        """Start monitoring payment status"""
        try:
            user = await self.get_user()
            if not user:
                await self.send_error("User not found")
                return

            # If already paid, send success immediately
            if user.registration_paid:
                await self.send_payment_success(user)
                return

            # Start monitoring task
            self.monitoring_task = asyncio.create_task(
                self.monitor_payment_status(user)
            )

        except Exception as e:
            logger.error(f"Error starting payment monitoring: {e}")
            await self.send_error("Failed to start payment monitoring")

    async def monitor_payment_status(self, user):
        """Monitor payment status with periodic checks"""
        max_attempts = 40  # 40 * 3 seconds = 2 minutes
        attempt = 0

        await self.send_status_update("Checking payment status...", "pending")

        while attempt < max_attempts:
            attempt += 1

            try:
                # Check if user is now paid
                updated_user = await self.get_user()
                if updated_user and updated_user.registration_paid:
                    await self.send_payment_success(updated_user)
                    return

                # In development mode, simulate payment processing
                if settings.DEBUG:
                    # Simulate payment completion after some attempts
                    if attempt > 5 and (attempt % 10 == 0):  # Complete after 10th, 20th, etc. attempt
                        await self.complete_development_payment(updated_user)
                        return
                    else:
                        await self.send_status_update(
                            f"Processing payment... ({attempt}/{max_attempts})",
                            "pending"
                        )
                else:
                    # Production mode - check M-Pesa API
                    payment_status = await self.check_mpesa_status(updated_user)

                    if payment_status == 'success':
                        await self.send_payment_success(updated_user)
                        return
                    elif payment_status == 'failed':
                        await self.send_payment_failed("Payment was cancelled or failed")
                        return
                    else:
                        await self.send_status_update(
                            f"Verifying payment... ({attempt}/{max_attempts})",
                            "pending"
                        )

                # Wait 3 seconds before next check
                await asyncio.sleep(3)

            except Exception as e:
                logger.error(f"Error in payment monitoring loop: {e}")
                await asyncio.sleep(3)  # Continue trying

        # Timeout reached
        await self.send_payment_timeout()

    async def complete_development_payment(self, user):
        """Complete payment in development mode"""
        try:
            await self.update_user_payment_status(
                user,
                paid=True,
                active=True,
                receipt=f"DEV_{user.id}_{asyncio.get_event_loop().time()}"
            )

            updated_user = await self.get_user()
            await self.send_payment_success(updated_user)

        except Exception as e:
            logger.error(f"Error completing development payment: {e}")
            await self.send_error("Failed to complete payment")

    @database_sync_to_async
    def get_user(self):
        """Get user from database"""
        try:
            return User.objects.get(id=self.user_id)
        except User.DoesNotExist:
            return None

    @database_sync_to_async
    def update_user_payment_status(self, user, paid=True, active=True, receipt=None):
        """Update user payment status in database"""
        from django.utils import timezone

        user.registration_paid = paid
        user.is_active = active
        user.registration_payment_date = timezone.now()
        if receipt:
            user.mpesa_receipt_number = receipt
        user.save()
        return user

    @database_sync_to_async
    def check_mpesa_status(self, user):
        """Check M-Pesa payment status"""
        if not user.mpesa_checkout_request_id:
            return 'pending'

        try:
            mpesa_service = MPesaService()
            status_response = mpesa_service.query_transaction_status(
                user.mpesa_checkout_request_id
            )

            if status_response.get('success'):
                result = status_response.get('result', {})
                result_code = result.get('ResultCode')

                if result_code == '0':  # Success
                    # Update user in database
                    self.update_user_payment_status(
                        user,
                        paid=True,
                        active=True,
                        receipt=result.get('ReceiptNumber', user.mpesa_checkout_request_id[:10])
                    )
                    return 'success'
                elif result_code in ['1032', '1', '1001', '1019']:  # Failed/Cancelled
                    return 'failed'
                else:
                    return 'pending'
            else:
                return 'pending'

        except Exception as e:
            logger.error(f"M-Pesa status check error: {e}")
            return 'pending'

    async def send_status_update(self, message, status):
        """Send status update to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'status': status,
            'message': message
        }))

    async def send_payment_success(self, user):
        """Send payment success message"""
        await self.send(text_data=json.dumps({
            'type': 'payment_success',
            'status': 'success',
            'message': 'Payment successful! Your account is now active.',
            'data': {
                'receipt_number': user.mpesa_receipt_number or 'N/A',
                'amount': str(user.registration_amount or 1),
                'username': user.username
            }
        }))

    async def send_payment_failed(self, message):
        """Send payment failed message"""
        await self.send(text_data=json.dumps({
            'type': 'payment_failed',
            'status': 'failed',
            'message': message
        }))

    async def send_payment_timeout(self):
        """Send payment timeout message"""
        await self.send(text_data=json.dumps({
            'type': 'payment_timeout',
            'status': 'timeout',
            'message': 'Payment verification timed out. Please contact support if you completed the payment.'
        }))

    async def send_error(self, message):
        """Send error message"""
        await self.send(text_data=json.dumps({
            'type': 'error',
            'status': 'error',
            'message': message
        }))

    # Handle group messages (if needed for admin notifications)
    async def payment_update(self, event):
        """Handle payment update from group"""
        await self.send(text_data=json.dumps(event['data']))