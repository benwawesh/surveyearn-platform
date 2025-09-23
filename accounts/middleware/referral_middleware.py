import logging
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings

logger = logging.getLogger('referrals')

class ReferralTrackingMiddleware(MiddlewareMixin):
    def process_request(self, request):
        ref_code = request.GET.get('ref')
        if ref_code:
            try:
                from accounts.models import User
                referrer = User.objects.get(referral_code=ref_code)
                request.session['referral_code'] = ref_code
                request.session['referrer_username'] = referrer.username
                request.session.set_expiry(30 * 24 * 60 * 60)
                logger.info(f"Referral code {ref_code} stored for referrer: {referrer.username}")
            except Exception as e:
                logger.warning(f"Invalid referral code: {ref_code}")
        return None
