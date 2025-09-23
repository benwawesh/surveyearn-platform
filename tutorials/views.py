# tutorials/views.py
import json
from datetime import datetime, timedelta
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.db import transaction
from django.db.models import Avg, Count, Sum, Q
from django.utils import timezone
from django.core.paginator import Paginator

from .models import (
    TutorialCategory, Tutorial, QuizQuestion, QuizAnswer,
    UserTutorialProgress, UserQuizAttempt, UserQuizAnswer
)
from accounts.models import User
from payments.models import Transaction


@login_required
def tutorial_dashboard(request):
    """Main tutorial dashboard showing all published tutorials"""

    # Get all published tutorials (regardless of categories)
    tutorials = Tutorial.objects.filter(is_published=True).order_by('-created_at')

    # Get user's progress for these tutorials
    user_progress = {}
    if request.user.is_authenticated:
        progress_queryset = UserTutorialProgress.objects.filter(
            user=request.user,
            tutorial__in=tutorials
        ).select_related('tutorial')
        user_progress = {p.tutorial_id: p for p in progress_queryset}

    # Calculate basic statistics
    total_tutorials = tutorials.count()
    completed_tutorials = sum(1 for p in user_progress.values() if p.is_completed) if user_progress else 0
    in_progress_tutorials = sum(1 for p in user_progress.values() if
                                not p.is_completed and p.video_watch_percentage > 0) if user_progress else 0

    # Calculate total earned (you might need to adjust this based on your reward system)
    total_earned = 0
    if request.user.is_authenticated:
        completed_progress = [p for p in user_progress.values() if p.is_completed and p.reward_claimed]
        total_earned = sum(p.tutorial.completion_reward or 0 for p in completed_progress)

    context = {
        'tutorials': tutorials,
        'user_progress': user_progress,
        'total_tutorials': total_tutorials,
        'completed_tutorials': completed_tutorials,
        'in_progress_tutorials': in_progress_tutorials,
        'total_earned': total_earned,
    }

    return render(request, 'tutorials/dashboard.html', context)


@login_required
def category_detail(request, category_id):
    """Show tutorials in a specific category"""
    category = get_object_or_404(TutorialCategory, id=category_id, is_active=True)
    tutorials = category.tutorials.filter(is_published=True).order_by('order')

    # Get user progress for these tutorials
    user_progress = UserTutorialProgress.objects.filter(
        user=request.user, tutorial__in=tutorials
    ).select_related('tutorial')
    progress_by_tutorial = {p.tutorial_id: p for p in user_progress}

    # Check accessibility for each tutorial
    tutorial_accessibility = {}
    for tutorial in tutorials:
        tutorial_accessibility[tutorial.id] = tutorial.is_accessible_by_user(request.user)

    context = {
        'category': category,
        'tutorials': tutorials,
        'progress_by_tutorial': progress_by_tutorial,
        'tutorial_accessibility': tutorial_accessibility,
    }

    return render(request, 'tutorials/category_detail.html', context)


@login_required
def tutorial_detail(request, pk):
    """Show individual tutorial with video and quiz"""
    tutorial = get_object_or_404(Tutorial, id=pk, is_published=True)

    # Get or create user progress
    progress, created = UserTutorialProgress.objects.get_or_create(
        user=request.user,
        tutorial=tutorial,
        defaults={
            'video_watch_percentage': 0.0,
            'quiz_attempts': 0,
            'score_percentage': 0.0,
            'is_passed': False,
            'is_completed': False
        }
    )

    # Get quiz questions
    quiz_questions = tutorial.quiz_questions.filter(is_active=True).order_by('order')

    # Handle video embed URL safely
    video_embed_url = None
    if tutorial.video_url:
        video_embed_url = get_video_embed_url(tutorial.video_url)

    # Simplified can_take_quiz logic - allow quiz if questions exist
    can_take_quiz = quiz_questions.exists()

    context = {
        'tutorial': tutorial,
        'progress': progress,
        'quiz_questions': quiz_questions,
        'can_take_quiz': can_take_quiz,
        'video_embed_url': video_embed_url,
    }

    return render(request, 'tutorials/tutorial_detail.html', context)


@login_required
@require_POST
def update_video_progress(request, pk):
    """Update user's video watching progress via AJAX"""
    tutorial = get_object_or_404(Tutorial, id=pk, is_published=True)

    try:
        data = json.loads(request.body)
        watch_percentage = float(data.get('watch_percentage', 0))
        watch_percentage = max(0, min(100, watch_percentage))  # Clamp between 0-100

        progress, created = UserTutorialProgress.objects.get_or_create(
            user=request.user, tutorial=tutorial
        )

        # Update video progress
        if watch_percentage > progress.video_watch_percentage:
            progress.video_watch_percentage = watch_percentage

            # Mark video as completed if watched >= 90%
            if watch_percentage >= 90 and not progress.video_completed_at:
                progress.video_completed_at = timezone.now()

            progress.save()

        return JsonResponse({
            'success': True,
            'watch_percentage': progress.video_watch_percentage,
            'can_take_quiz': progress.can_take_quiz(),
        })

    except (json.JSONDecodeError, ValueError) as e:
        return JsonResponse({'success': False, 'error': 'Invalid data'}, status=400)


@login_required
@require_POST
@csrf_exempt
def resume_video(request, tutorial_id):
    """Mark that user resumed watching a video"""
    try:
        tutorial = get_object_or_404(Tutorial, id=tutorial_id, is_published=True)

        progress = get_object_or_404(
            UserTutorialProgress,
            user=request.user,
            tutorial=tutorial
        )

        progress.resume_watching()

        return JsonResponse({
            'success': True,
            'resume_position': float(progress.last_watched_position),
            'preferred_speed': float(progress.preferred_playback_speed),
            'resumed_count': progress.resumed_count
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
def get_user_preferences(request, tutorial_id):
    """Get user's video preferences for this tutorial"""
    try:
        tutorial = get_object_or_404(Tutorial, id=tutorial_id, is_published=True)

        try:
            progress = UserTutorialProgress.objects.get(
                user=request.user,
                tutorial=tutorial
            )

            return JsonResponse({
                'success': True,
                'preferences': {
                    'last_position': float(progress.last_watched_position),
                    'preferred_speed': float(progress.preferred_playback_speed),
                    'total_watch_time': float(progress.total_watch_time),
                    'video_watch_percentage': float(progress.video_watch_percentage),
                    'can_resume': progress.last_watched_position > 30
                }
            })
        except UserTutorialProgress.DoesNotExist:
            return JsonResponse({
                'success': True,
                'preferences': {
                    'last_position': 0.0,
                    'preferred_speed': 1.0,
                    'total_watch_time': 0.0,
                    'video_watch_percentage': 0.0,
                    'can_resume': False
                }
            })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
def start_quiz(request, pk):
    """Start a new quiz attempt"""
    tutorial = get_object_or_404(Tutorial, id=pk, is_published=True)
    progress, created = UserTutorialProgress.objects.get_or_create(
        user=request.user, tutorial=tutorial
    )

    # Check if quiz questions exist
    if not tutorial.quiz_questions.filter(is_active=True).exists():
        messages.error(request, "No quiz questions available for this tutorial.")
        return redirect('tutorials:tutorial_detail', pk=pk)

    # Create new quiz attempt with default values
    attempt_number = progress.quiz_attempts + 1
    total_questions = tutorial.quiz_questions.filter(is_active=True).count()

    quiz_attempt = UserQuizAttempt.objects.create(
        user=request.user,
        tutorial=tutorial,
        attempt_number=attempt_number,
        total_questions=total_questions,
        correct_answers=0,  # Add this default
        score_percentage=0.0,  # Add this default
        is_passed=False  # Add this default
    )

    # Update progress
    progress.quiz_attempts = attempt_number
    progress.save()

    return redirect('tutorials:take_quiz', pk=pk, attempt_id=quiz_attempt.id)

@login_required
def take_quiz(request, pk, attempt_id):
    """Take quiz interface"""
    tutorial = get_object_or_404(Tutorial, id=pk, is_published=True)
    quiz_attempt = get_object_or_404(
        UserQuizAttempt, id=attempt_id, user=request.user, tutorial=tutorial
    )

    questions = tutorial.quiz_questions.filter(is_active=True).order_by('order')

    if request.method == 'POST':
        return submit_quiz(request, tutorial, quiz_attempt, questions)

    # Add video support
    video_embed_url = None
    if tutorial.video_url:
        video_embed_url = get_video_embed_url(tutorial.video_url)

    context = {
        'tutorial': tutorial,
        'quiz_attempt': quiz_attempt,
        'questions': questions,
        'video_embed_url': video_embed_url,  # Add this line
    }

    return render(request, 'tutorials/take_quiz.html', context)


@login_required
@require_POST
def submit_quiz(request, tutorial, quiz_attempt, questions):
    """Process quiz submission"""
    start_time = timezone.now()
    correct_answers = 0
    total_points = 0
    earned_points = 0

    with transaction.atomic():
        # Process each question
        for question in questions:
            selected_answer_id = request.POST.get(f'question_{question.id}')
            if selected_answer_id:
                try:
                    selected_answer = QuizAnswer.objects.get(
                        id=selected_answer_id, question=question
                    )
                    is_correct = selected_answer.is_correct

                    # Record the answer
                    UserQuizAnswer.objects.create(
                        quiz_attempt=quiz_attempt,
                        question=question,
                        selected_answer=selected_answer,
                        is_correct=is_correct
                    )

                    if is_correct:
                        correct_answers += 1
                        earned_points += question.points

                    total_points += question.points

                except QuizAnswer.DoesNotExist:
                    # Log missing answer for debugging
                    total_points += question.points

        # Calculate score
        score_percentage = (earned_points / total_points * 100) if total_points > 0 else 0
        is_passed = score_percentage >= tutorial.quiz_passing_score  # Fixed field name

        # Update quiz attempt
        quiz_attempt.correct_answers = correct_answers
        quiz_attempt.score_percentage = score_percentage
        quiz_attempt.is_passed = is_passed
        quiz_attempt.time_taken = timezone.now() - start_time
        quiz_attempt.save()

        # Update user progress
        progress = UserTutorialProgress.objects.get(user=request.user, tutorial=tutorial)

        # Update best score if this attempt is better
        if score_percentage > progress.score_percentage:  # Fixed field name
            progress.score_percentage = score_percentage

        # Mark quiz as passed if this attempt passed and quiz wasn't already passed
        if is_passed and not progress.is_passed:  # Fixed field name
            progress.is_passed = True  # Fixed field name
            progress.quiz_completed_at = timezone.now()

            # Check if tutorial is fully completed
            if not progress.is_completed and progress.video_watch_percentage >= 90:
                complete_tutorial(request.user, tutorial, progress)

        progress.save()

    # Provide user feedback
    if is_passed:
        messages.success(request, f"Congratulations! You passed with {score_percentage:.1f}%")

        # Add reward notification if applicable
        if tutorial.completion_reward > 0 and progress.is_completed and not progress.reward_claimed:
            messages.info(request, f"You've earned KES {tutorial.completion_reward} for completing this tutorial!")
    else:
        remaining_attempts = tutorial.max_quiz_attempts - progress.quiz_attempts
        if remaining_attempts > 0:
            messages.warning(request,
                             f"You scored {score_percentage:.1f}%. You have {remaining_attempts} attempts remaining.")
        else:
            messages.error(request, "You have used all quiz attempts for this tutorial.")

    return redirect('tutorials:quiz_results', pk=tutorial.id, attempt_id=quiz_attempt.id)


@login_required
def quiz_results(request, pk, attempt_id):
    """Show quiz results"""
    tutorial = get_object_or_404(Tutorial, id=pk, is_published=True)
    quiz_attempt = get_object_or_404(
        UserQuizAttempt, id=attempt_id, user=request.user, tutorial=tutorial
    )

    # Get detailed results
    user_answers = UserQuizAnswer.objects.filter(
        quiz_attempt=quiz_attempt
    ).select_related('question', 'selected_answer').order_by('question__order')

    progress = UserTutorialProgress.objects.get(user=request.user, tutorial=tutorial)

    context = {
        'tutorial': tutorial,
        'quiz_attempt': quiz_attempt,
        'user_answers': user_answers,
        'progress': progress,
    }

    return render(request, 'tutorials/quiz_results.html', context)


def complete_tutorial(user, tutorial, progress):
    """Complete tutorial and award rewards"""
    progress.is_completed = True
    progress.completed_at = timezone.now()

    # Award completion reward if not already claimed
    if tutorial.completion_reward > 0 and not progress.reward_claimed:
        Transaction.objects.create(
            user=user,
            transaction_type='tutorial_reward',
            amount=tutorial.completion_reward,
            description=f"Tutorial completion reward: {tutorial.title}",
            status='completed'
        )

        # Update user balance
        user.balance += tutorial.completion_reward
        user.save()

        progress.reward_claimed = True

    progress.save()


def get_video_embed_url(video_url):
    """Convert video URL to embeddable format"""
    if 'youtube.com/watch?v=' in video_url:
        video_id = video_url.split('watch?v=')[1].split('&')[0]
        return f"https://www.youtube.com/embed/{video_id}?enablejsapi=1"
    elif 'youtu.be/' in video_url:
        video_id = video_url.split('youtu.be/')[1].split('?')[0]
        return f"https://www.youtube.com/embed/{video_id}?enablejsapi=1"
    elif 'vimeo.com/' in video_url:
        video_id = video_url.split('vimeo.com/')[1].split('?')[0]
        return f"https://player.vimeo.com/video/{video_id}"
    else:
        return video_url  # Direct video file or other format


# Admin views for tutorial management
@staff_member_required
def admin_tutorial_analytics(request):
    """Admin analytics for tutorials"""
    # Overall statistics
    total_tutorials = Tutorial.objects.filter(is_published=True).count()
    total_users = User.objects.filter(is_active=True).count()
    total_attempts = UserQuizAttempt.objects.count()
    avg_score = UserQuizAttempt.objects.aggregate(avg_score=Avg('score_percentage'))['avg_score'] or 0

    # Tutorial completion rates
    tutorial_stats = Tutorial.objects.filter(is_published=True).annotate(
        total_started=Count('user_progress'),
        total_completed=Count('user_progress', filter=Q(user_progress__is_completed=True)),
        avg_score=Avg('quiz_attempts__score_percentage'),
        total_attempts=Count('quiz_attempts')
    ).order_by('-total_started')[:10]

    # Recent activity
    recent_completions = UserTutorialProgress.objects.filter(
        is_completed=True
    ).select_related('user', 'tutorial').order_by('-completed_at')[:10]

    context = {
        'stats': {
            'total_tutorials': total_tutorials,
            'total_users': total_users,
            'total_attempts': total_attempts,
            'avg_score': round(avg_score, 1),
        },
        'tutorial_stats': tutorial_stats,
        'recent_completions': recent_completions,
    }

    return render(request, 'tutorials/admin/analytics.html', context)