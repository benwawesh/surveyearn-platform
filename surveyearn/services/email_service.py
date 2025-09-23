# Updated surveyearn/services/email_service.py with SendGrid support

import logging
import os
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.contrib.auth import get_user_model
from typing import List, Optional, Dict, Any

# SendGrid imports
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, From, To, Subject, Content

    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False

User = get_user_model()
logger = logging.getLogger(__name__)


class EmailService:
    """
    Centralized email service for SurveyEarn platform
    Supports both Django SMTP and SendGrid
    """

    @staticmethod
    def get_sendgrid_client():
        """Get SendGrid client if configured"""
        api_key = getattr(settings, 'SENDGRID_API_KEY', None)
        if api_key and SENDGRID_AVAILABLE:
            return SendGridAPIClient(api_key)
        return None

    @staticmethod
    def send_email_sendgrid(
            subject: str,
            recipient_list: List[str],
            html_content: str = None,
            text_content: str = None,
            from_email: str = None,
    ) -> bool:
        """Send email using SendGrid API"""
        try:
            sg = EmailService.get_sendgrid_client()
            if not sg:
                return False

            from_email = from_email or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@surveyearn.com')

            # Parse from email if it contains name
            if '<' in from_email and '>' in from_email:
                name = from_email.split('<')[0].strip()
                email = from_email.split('<')[1].replace('>', '').strip()
                from_email_obj = From(email, name)
            else:
                from_email_obj = From(from_email, "SurveyEarn")

            # Send to each recipient
            success_count = 0
            for recipient in recipient_list:
                try:
                    message = Mail(
                        from_email=from_email_obj,
                        to_emails=To(recipient),
                        subject=Subject(subject),
                        html_content=Content("text/html", html_content) if html_content else None,
                        plain_text_content=Content("text/plain", text_content) if text_content else None
                    )

                    response = sg.send(message)

                    if response.status_code in [200, 202]:
                        success_count += 1
                        logger.info(f"SendGrid email sent to {recipient}: {subject}")
                    else:
                        logger.error(f"SendGrid failed to send to {recipient}: {response.status_code}")

                except Exception as e:
                    logger.error(f"SendGrid error sending to {recipient}: {e}")

            return success_count == len(recipient_list)

        except Exception as e:
            logger.error(f"SendGrid service error: {e}")
            return False

    @staticmethod
    def send_email(
            subject: str,
            recipient_list: List[str],
            html_content: str = None,
            text_content: str = None,
            from_email: str = None,
            fail_silently: bool = False,
            **kwargs
    ) -> bool:
        """
        Send email with HTML and text content
        Tries SendGrid first, falls back to Django SMTP
        """
        try:
            # Try SendGrid first if available
            if EmailService.get_sendgrid_client():
                logger.info(f"Attempting to send via SendGrid to {recipient_list}")
                if EmailService.send_email_sendgrid(
                        subject=subject,
                        recipient_list=recipient_list,
                        html_content=html_content,
                        text_content=text_content,
                        from_email=from_email
                ):
                    return True
                else:
                    logger.warning("SendGrid failed, falling back to SMTP")

            # Fall back to Django SMTP
            from_email = from_email or settings.DEFAULT_FROM_EMAIL

            if html_content and not text_content:
                text_content = strip_tags(html_content)

            if html_content:
                # Send HTML email
                email = EmailMultiAlternatives(
                    subject=subject,
                    body=text_content,
                    from_email=from_email,
                    to=recipient_list,
                )
                email.attach_alternative(html_content, "text/html")
                email.send(fail_silently=fail_silently)
            else:
                # Send plain text email
                send_mail(
                    subject=subject,
                    message=text_content,
                    from_email=from_email,
                    recipient_list=recipient_list,
                    fail_silently=fail_silently,
                )

            logger.info(f"SMTP email sent successfully to {recipient_list}: {subject}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {recipient_list}: {e}")
            if not fail_silently:
                raise
            return False

    @staticmethod
    def send_template_email(
            template_name: str,
            subject: str,
            recipient_list: List[str],
            context: Dict[str, Any] = None,
            from_email: str = None,
            fail_silently: bool = True
    ) -> bool:
        """
        Send email using Django templates
        """
        try:
            context = context or {}
            context.update({
                'site_name': 'SurveyEarn',
                'site_url': getattr(settings, 'SITE_URL', 'http://localhost:8000'),
            })

            # Render HTML template
            html_content = render_to_string(f'emails/{template_name}.html', context)

            # Try to render text template, fallback to HTML stripped
            try:
                text_content = render_to_string(f'emails/{template_name}.txt', context)
            except:
                text_content = strip_tags(html_content)

            return EmailService.send_email(
                subject=subject,
                recipient_list=recipient_list,
                html_content=html_content,
                text_content=text_content,
                from_email=from_email,
                fail_silently=fail_silently
            )

        except Exception as e:
            logger.error(f"Failed to send template email {template_name} to {recipient_list}: {e}")
            if not fail_silently:
                raise
            return False

    # Keep all your existing specific email methods unchanged
    @classmethod
    def send_welcome_email(cls, user: User) -> bool:
        """Send welcome email to new registered user"""
        return cls.send_template_email(
            template_name='welcome',
            subject='Welcome to SurveyEarn! 🎉',
            recipient_list=[user.email],
            context={
                'user': user,
                'username': user.username,
                'first_name': user.first_name or user.username,
            }
        )

    @classmethod
    def send_payment_confirmation_email(cls, user: User, amount: str, receipt_number: str) -> bool:
        """Send payment confirmation email"""
        return cls.send_template_email(
            template_name='payment_confirmation',
            subject='Payment Confirmed - Account Activated! ✅',
            recipient_list=[user.email],
            context={
                'user': user,
                'username': user.username,
                'amount': amount,
                'receipt_number': receipt_number,
                'payment_date': user.registration_payment_date,
            }
        )

    @classmethod
    def send_survey_notification_email(cls, user: User, survey_title: str, survey_url: str) -> bool:
        """Send new survey notification email"""
        return cls.send_template_email(
            template_name='new_survey',
            subject=f'New Survey Available: {survey_title} 📝',
            recipient_list=[user.email],
            context={
                'user': user,
                'username': user.username,
                'survey_title': survey_title,
                'survey_url': survey_url,
            }
        )

    @classmethod
    def send_bulk_notification(cls, users: List[User], subject: str, template_name: str,
                               context: Dict[str, Any] = None) -> int:
        """Send bulk notification to multiple users"""
        sent_count = 0
        for user in users:
            user_context = context.copy() if context else {}
            user_context.update({'user': user, 'username': user.username})

            if cls.send_template_email(
                    template_name=template_name,
                    subject=subject,
                    recipient_list=[user.email],
                    context=user_context
            ):
                sent_count += 1

        logger.info(f"Bulk notification sent to {sent_count}/{len(users)} users")
        return sent_count