# Create accounts/routing.py

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/payment/(?P<user_id>[0-9a-f-]+)/$', consumers.PaymentStatusConsumer.as_asgi()),
]