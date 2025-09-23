# custom_admin/apps.py
from django.apps import AppConfig


class CustomAdminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'custom_admin'
    verbose_name = 'Custom Admin Panel'

    def ready(self):
        """
        Called when the app is ready. 
        Can be used for app initialization tasks.
        """
        pass