from django.urls import path
from . import views

app_name = 'surveys'

urlpatterns = [

    # Dashboard for logged-in users (surveys list)
    path('', views.survey_list, name='survey_list'),  # Alternative URL

    # Other pages
    path('stats/', views.survey_stats, name='survey_stats'),

    # Survey taking flow
    path('survey/<uuid:survey_id>/', views.survey_detail, name='survey_detail'),
    path('<uuid:survey_id>/success/', views.survey_success, name='survey_success'),
    path('survey/<uuid:survey_id>/take/', views.take_survey, name='take_survey'),
    path('survey/<uuid:survey_id>/submit/', views.take_survey, name='submit_survey'),
    path('survey/<uuid:survey_id>/complete/<uuid:response_id>/', views.survey_complete, name='survey_complete'),
    path('survey/<uuid:survey_id>/preview/', views.survey_preview, name='survey_preview'),

    # User survey history
    path('my-surveys/', views.my_survey_history, name='my_surveys'),
    path('response/<uuid:response_id>/', views.survey_response_detail, name='response_detail'),
]