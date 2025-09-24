""" SurveyEarn Platform URL Configuration """
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts.views import ReferralClickTracker
from surveys.views import landing_page  # Import landing page directly

# Updated URL patterns
urlpatterns = [
    # Landing page at root URL
    path('', landing_page, name='landing_page'),  # Direct to landing page view

    # App URLs
    path('surveys/', include('surveys.urls')),
    path('accounts/', include('accounts.urls')),
    path('payments/', include('payments.urls')),
    path('management/', include('custom_admin.urls')),
    path('tutorials/', include('tutorials.urls')),
    path('api/track-referral/', ReferralClickTracker.as_view(), name='track_referral_click'),
]

# Rest of your configuration remains the same
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

handler400 = 'surveyearn.error_handlers.handler400'
handler403 = 'surveyearn.error_handlers.handler403'
handler404 = 'surveyearn.error_handlers.handler404'
handler500 = 'surveyearn.error_handlers.handler500'