# accounts/apps.py
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    verbose_name = 'User Accounts'

    def ready(self):
        """
        Called when the app is ready.
        Import signal handlers here if needed.
        """
        # Import signals if you have any
        # from . import signals
        pass