from accounts.services.settings_service import SettingsService


def referral_context(request):
    """Add referral settings to all template contexts using dynamic settings"""
    settings_service = SettingsService()

    registration_fee = settings_service.get_registration_fee()
    commission_rate = settings_service.get_referral_commission_rate()
    commission_amount = registration_fee * commission_rate

    return {
        'REFERRAL_COMMISSION': commission_amount,
        'REFERRAL_RATE': int(commission_rate * 100),
        'REGISTRATION_FEE': registration_fee,
        'CURRENCY_SYMBOL': 'KSh',
    }