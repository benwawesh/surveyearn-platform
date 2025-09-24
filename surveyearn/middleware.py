"""
Custom middleware for handling errors and security headers
Development-aware - behaves differently based on DEBUG setting
"""
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class CustomErrorMiddleware(MiddlewareMixin):
    """
    Middleware to handle custom error responses
    Only applies error templates when DEBUG=False
    """

    def process_response(self, request, response):
        """Process the response and handle custom error codes"""

        # Only apply custom error pages in production (DEBUG=False)
        if settings.DEBUG:
            return response

        # Handle specific status codes in production
        if response.status_code == 401:
            return render(request, 'errors/401.html', status=401)
        elif response.status_code == 403:
            return render(request, 'errors/403.html', status=403)
        elif response.status_code == 404:
            return render(request, 'errors/404.html', status=404)
        elif response.status_code == 405:
            return render(request, 'errors/405.html', status=405)
        elif response.status_code == 408:
            return render(request, 'errors/408.html', status=408)
        elif response.status_code == 410:
            return render(request, 'errors/410.html', status=410)
        elif response.status_code == 413:
            return render(request, 'errors/413.html', status=413)
        elif response.status_code == 422:
            return render(request, 'errors/422.html', status=422)
        elif response.status_code == 429:
            return render(request, 'errors/429.html', status=429)
        elif response.status_code == 500:
            return render(request, 'errors/500.html', status=500)
        elif response.status_code == 502:
            return render(request, 'errors/502.html', status=502)
        elif response.status_code == 503:
            return render(request, 'errors/503.html', status=503)
        elif response.status_code == 504:
            return render(request, 'errors/504.html', status=504)

        return response

    def process_exception(self, request, exception):
        """Handle specific exceptions"""

        # Log the exception
        logger.error(f"Exception in {request.path}: {str(exception)}", exc_info=True)

        # Only apply custom error handling in production
        if settings.DEBUG:
            return None  # Let Django handle it with detailed error pages

        # Handle specific exception types in production
        if isinstance(exception, PermissionError):
            return render(request, 'errors/403.html', status=403)
        elif isinstance(exception, FileNotFoundError):
            return render(request, 'errors/404.html', status=404)
        elif isinstance(exception, TimeoutError):
            return render(request, 'errors/408.html', status=408)

        # Return None to let Django handle other exceptions normally
        return None


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Add security headers - development aware
    Only applies strict security in production
    """

    def process_response(self, request, response):
        """Add security headers based on environment"""

        if settings.DEBUG:
            # Development mode - minimal security headers
            response['X-Content-Type-Options'] = 'nosniff'
            # Don't add strict security headers in development
        else:
            # Production mode - full security headers
            response['X-Content-Type-Options'] = 'nosniff'
            response['X-Frame-Options'] = 'DENY'
            response['X-XSS-Protection'] = '1; mode=block'
            response['Referrer-Policy'] = 'strict-origin-when-cross-origin'

            # Add CSP header for error pages
            if '/errors/' in request.path or response.status_code >= 400:
                response['Content-Security-Policy'] = (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
                    "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
                    "font-src 'self' https://cdnjs.cloudflare.com; "
                    "img-src 'self' data:;"
                )

        return response


# accounts/middleware/referral_middleware.py
"""
Referral tracking middleware for SurveyEarn platform
Handles referral code tracking via URL parameters and session storage
"""

import logging
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from accounts.models import User

logger = logging.getLogger('referrals')


class ReferralTrackingMiddleware(MiddlewareMixin):
    """
    Track referral codes and store them in session for registration processing
    """

    def process_request(self, request):
        """
        Process incoming requests to detect and store referral codes
        """
        # Check for referral code in URL parameters
        ref_code = request.GET.get('ref')

        if ref_code:
            try:
                # Verify referral code exists and is valid
                referrer = User.objects.get(referral_code=ref_code)

                # Store in session with 30-day expiry
                request.session['referral_code'] = ref_code
                request.session['referrer_username'] = referrer.username
                request.session.set_expiry(30 * 24 * 60 * 60)  # 30 days

                logger.info(f"✅ Referral code {ref_code} stored for referrer: {referrer.username}")

                # Add success message for debugging (remove in production)
                if settings.DEBUG:
                    request.session[
                        'referral_message'] = f"You were referred by {referrer.get_full_name() or referrer.username}"

            except User.DoesNotExist:
                logger.warning(f"❌ Invalid referral code attempted: {ref_code}")

                # Clean up any existing invalid referral data
                session_keys_to_remove = ['referral_code', 'referrer_username', 'referral_message']
                for key in session_keys_to_remove:
                    if key in request.session:
                        del request.session[key]

            except Exception as e:
                logger.error(f"❌ Error processing referral code {ref_code}: {str(e)}")

        return None

    def process_response(self, request, response):
        """
        Add debug information about referral tracking
        """
        # Debug logging in development mode
        if settings.DEBUG and hasattr(request, 'session'):
            if 'referral_code' in request.session:
                ref_code = request.session['referral_code']
                referrer = request.session.get('referrer_username', 'Unknown')
                logger.debug(f"🔍 Active referral session: {ref_code} (referrer: {referrer})")

        return response