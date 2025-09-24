# tutorials/urls.py
from django.urls import path
from . import views

app_name = 'tutorials'

urlpatterns = [
    # Main tutorial views
    path('', views.tutorial_dashboard, name='tutorial_dashboard'),
    path('category/<uuid:category_id>/', views.category_detail, name='category_detail'),
    path('tutorial/<uuid:pk>/', views.tutorial_detail, name='tutorial_detail'),

    # Video progress tracking
    path('tutorial/<uuid:pk>/progress/', views.update_video_progress, name='update_progress'),

    # Quiz system
    path('tutorial/<uuid:pk>/quiz/start/', views.start_quiz, name='start_quiz'),
    path('tutorial/<uuid:pk>/quiz/<uuid:attempt_id>/', views.take_quiz, name='take_quiz'),
    path('tutorial/<uuid:pk>/quiz/<uuid:attempt_id>/results/', views.quiz_results, name='quiz_results'),

    # Admin views
    path('admin/analytics/', views.admin_tutorial_analytics, name='admin_analytics'),
]

# Add to main urls.py:
# from django.urls import path, include
#
# urlpatterns = [
#     # ... existing patterns
#     path('tutorials/', include('tutorials.urls')),
# ]