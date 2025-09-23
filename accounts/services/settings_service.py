# accounts/services/settings_service.py

from django.core.cache import cache
from django.conf import settings
from decimal import Decimal
import logging
from typing import Any, Optional, Union

logger = logging.getLogger('django')


class SettingsService:
    """
    Service for managing system settings with caching and fallbacks
    """

    # Cache timeout in seconds (5 minutes)
    CACHE_TIMEOUT = 300
    CACHE_PREFIX = "system_setting_"

    # Default settings that will be created if they don't exist
    DEFAULT_SETTINGS = {
        'registration_fee': {
            'value': Decimal('500.00'),
            'name': 'Registration Fee',
            'type': 'fee',
            'description': 'Fee charged for user registration in KSh',
            'min_value': Decimal('1.00'),
            'max_value': Decimal('10000.00')
        },
        'referral_commission_rate': {
            'value': Decimal('0.25'),
            'name': 'Referral Commission Rate',
            'type': 'rate',
            'description': 'Commission rate for referrals (0.25 = 25%)',
            'min_value': Decimal('0.01'),
            'max_value': Decimal('0.50')
        },
        'auto_approve_referral_commissions': {
            'value': True,
            'name': 'Auto-approve Referral Commissions',
            'type': 'config',
            'description': 'Whether to automatically approve referral commissions'
        },
        'minimum_withdrawal_amount': {
            'value': Decimal('100.00'),
            'name': 'Minimum Withdrawal Amount',
            'type': 'limit',
            'description': 'Minimum amount users can withdraw in KSh',
            'min_value': Decimal('10.00'),
            'max_value': Decimal('1000.00')
        },
        'survey_base_payment': {
            'value': Decimal('50.00'),
            'name': 'Survey Base Payment',
            'type': 'fee',
            'description': 'Base payment for completing a survey in KSh',
            'min_value': Decimal('1.00'),
            'max_value': Decimal('500.00')
        },
        'max_surveys_per_day': {
            'value': 5,
            'name': 'Maximum Surveys Per Day',
            'type': 'limit',
            'description': 'Maximum number of surveys a user can complete per day',
            'min_value': Decimal('1'),
            'max_value': Decimal('20')
        }
    }

    @classmethod
    def get_setting(cls, key: str, default: Any = None) -> Any:
        """
        Get a setting value with caching and fallbacks

        Priority:
        1. Database (cached)
        2. Django settings
        3. Default value
        4. Provided default
        """
        # Try cache first
        cache_key = f"{cls.CACHE_PREFIX}{key}"
        cached_value = cache.get(cache_key)

        if cached_value is not None:
            logger.debug(f"Settings cache hit for {key}: {cached_value}")
            return cached_value

        # Try database
        try:
            from ..models import SystemSettings
            setting = SystemSettings.objects.get(setting_key=key, is_active=True)
            value = setting.get_value()

            # Cache the value
            cache.set(cache_key, value, cls.CACHE_TIMEOUT)
            logger.debug(f"Settings database hit for {key}: {value}")
            return value

        except:
            # Try Django settings with fallback
            django_setting_name = key.upper()
            if hasattr(settings, django_setting_name):
                value = getattr(settings, django_setting_name)
                logger.debug(f"Settings Django fallback for {key}: {value}")
                return value

            # Try default settings
            if key in cls.DEFAULT_SETTINGS:
                value = cls.DEFAULT_SETTINGS[key]['value']
                logger.debug(f"Settings default fallback for {key}: {value}")
                return value

            # Return provided default
            logger.warning(f"Setting {key} not found, using provided default: {default}")
            return default

    @classmethod
    def set_setting(cls, key: str, value: Any, user=None, reason: str = ""):
        """
        Set a setting value and log the change
        """
        try:
            from ..models import SystemSettings, SettingsAuditLog

            # Get or create the setting
            setting, created = SystemSettings.objects.get_or_create(
                setting_key=key,
                defaults={
                    'setting_name': cls._get_setting_name(key),
                    'setting_type': cls._get_setting_type(key),
                    'description': cls._get_setting_description(key),
                    'min_value': cls._get_setting_min_value(key),
                    'max_value': cls._get_setting_max_value(key),
                }
            )

            # Store old value for audit
            old_value = setting.get_value() if not created else None

            # Set new value
            setting.set_value(value)
            if user:
                setting.updated_by = user

            # Validate and save
            setting.full_clean()
            setting.save()

            # Log the change
            SettingsAuditLog.objects.create(
                setting=setting,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(value),
                change_reason=reason,
                changed_by=user
            )

            # Clear cache
            cache_key = f"{cls.CACHE_PREFIX}{key}"
            cache.delete(cache_key)

            logger.info(f"Setting {key} updated from {old_value} to {value} by {user}")
            return setting

        except Exception as e:
            logger.error(f"Error setting {key} to {value}: {str(e)}")
            raise

    @classmethod
    def get_registration_fee(cls) -> Decimal:
        """Get the current registration fee"""
        return Decimal(str(cls.get_setting('registration_fee', 500)))

    @classmethod
    def get_referral_commission_rate(cls) -> Decimal:
        """Get the current referral commission rate"""
        return Decimal(str(cls.get_setting('referral_commission_rate', 0.25)))

    @classmethod
    def get_minimum_withdrawal_amount(cls) -> Decimal:
        """Get the minimum withdrawal amount"""
        return Decimal(str(cls.get_setting('minimum_withdrawal_amount', 100)))

    @classmethod
    def get_survey_base_payment(cls) -> Decimal:
        """Get the base payment for surveys"""
        return Decimal(str(cls.get_setting('survey_base_payment', 50)))

    @classmethod
    def auto_approve_referral_commissions(cls) -> bool:
        """Check if referral commissions should be auto-approved"""
        return bool(cls.get_setting('auto_approve_referral_commissions', True))

    @classmethod
    def get_max_surveys_per_day(cls) -> int:
        """Get maximum surveys per day limit"""
        return int(cls.get_setting('max_surveys_per_day', 5))

    @classmethod
    def initialize_default_settings(cls, user=None):
        """
        Initialize default settings in the database
        This should be called during deployment or data migration
        """
        created_count = 0

        try:
            from ..models import SystemSettings

            for key, config in cls.DEFAULT_SETTINGS.items():
                setting, created = SystemSettings.objects.get_or_create(
                    setting_key=key,
                    defaults={
                        'setting_name': config['name'],
                        'setting_type': config['type'],
                        'description': config['description'],
                        'min_value': config.get('min_value'),
                        'max_value': config.get('max_value'),
                        'updated_by': user
                    }
                )

                if created:
                    setting.set_value(config['value'])
                    setting.save()
                    created_count += 1
                    logger.info(f"Created default setting: {key} = {config['value']}")
        except ImportError:
            logger.error("SystemSettings model not found - make sure migrations are run")
            return 0

        return created_count

    @classmethod
    def _get_setting_name(cls, key: str) -> str:
        """Get display name for a setting key"""
        if key in cls.DEFAULT_SETTINGS:
            return cls.DEFAULT_SETTINGS[key]['name']
        return key.replace('_', ' ').title()

    @classmethod
    def _get_setting_type(cls, key: str) -> str:
        """Get setting type for a key"""
        if key in cls.DEFAULT_SETTINGS:
            return cls.DEFAULT_SETTINGS[key]['type']
        return 'config'

    @classmethod
    def _get_setting_description(cls, key: str) -> str:
        """Get description for a setting key"""
        if key in cls.DEFAULT_SETTINGS:
            return cls.DEFAULT_SETTINGS[key]['description']
        return f"Setting for {key.replace('_', ' ')}"

    @classmethod
    def _get_setting_min_value(cls, key: str) -> Optional[Decimal]:
        """Get minimum value constraint for a setting key"""
        if key in cls.DEFAULT_SETTINGS:
            return cls.DEFAULT_SETTINGS[key].get('min_value')
        return None

    @classmethod
    def _get_setting_max_value(cls, key: str) -> Optional[Decimal]:
        """Get maximum value constraint for a setting key"""
        if key in cls.DEFAULT_SETTINGS:
            return cls.DEFAULT_SETTINGS[key].get('max_value')
        return None

    @classmethod
    def clear_cache(cls, key: str = None):
        """Clear settings cache for a specific key or all settings"""
        if key:
            cache_key = f"{cls.CACHE_PREFIX}{key}"
            cache.delete(cache_key)
        else:
            # Clear all settings cache
            for setting_key in cls.DEFAULT_SETTINGS.keys():
                cache_key = f"{cls.CACHE_PREFIX}{setting_key}"
                cache.delete(cache_key)

    @classmethod
    def get_all_settings(cls) -> dict:
        """Get all current settings as a dictionary"""
        settings_dict = {}

        try:
            from ..models import SystemSettings

            # Get all active settings from database
            for setting in SystemSettings.objects.filter(is_active=True):
                settings_dict[setting.setting_key] = {
                    'value': setting.get_value(),
                    'name': setting.setting_name,
                    'type': setting.setting_type,
                    'description': setting.description,
                    'updated_at': setting.updated_at,
                    'updated_by': setting.updated_by.username if setting.updated_by else None
                }
        except ImportError:
            logger.error("SystemSettings model not found")

        return settings_dict