from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.db import transaction
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from decimal import Decimal
import json
from .models import Survey, Question, Choice, Response, Answer
from payments.services import SurveyPaymentService


def survey_list(request):
    """
    Display available surveys for users to take with filtering
    """
    # Get all active surveys - FIXED: Changed back to 'active' (lowercase)
    surveys = Survey.objects.filter(status='active').prefetch_related('questions')

    # If user is authenticated, filter out completed surveys
    if request.user.is_authenticated:
        completed_survey_ids = Response.objects.filter(user=request.user).values_list('survey_id', flat=True)
        surveys = surveys.exclude(id__in=completed_survey_ids)

    # Apply filters from GET parameters
    # Note: Category filter removed since Survey model doesn't have category field

    reward_min = request.GET.get('reward_min')
    if reward_min:
        try:
            reward_min = float(reward_min)
            surveys = surveys.filter(payout__gte=reward_min)
        except (ValueError, TypeError):
            pass  # Invalid input, ignore filter

    # Apply sorting
    sort_option = request.GET.get('sort', 'newest')
    if sort_option == 'highest_reward':
        surveys = surveys.order_by('-payout')
    elif sort_option == 'ending_soon':
        # Assuming you have an end_date field, otherwise use created_at
        surveys = surveys.order_by('end_date') if hasattr(Survey, 'end_date') else surveys.order_by('-created_at')
    else:  # newest (default)
        surveys = surveys.order_by('-created_at')

    # Check availability for each survey
    available_surveys = []
    for survey in surveys:
        if survey.is_available:
            # Add extra info for display
            survey.question_count = survey.questions.count()
            survey.estimated_minutes = max(1, survey.question_count // 2)  # Rough estimate
            available_surveys.append(survey)

    context = {
        'surveys': available_surveys,
        'total_surveys': len(available_surveys),
    }

    return render(request, 'surveys/survey_list.html', context)


@login_required
def survey_detail(request, survey_id):
    """
    Display survey detail and handle survey submission
    """
    survey = get_object_or_404(Survey, id=survey_id, status='active')

    # Check if user has already taken this survey
    existing_response = Response.objects.filter(user=request.user, survey=survey).first()
    if existing_response:
        messages.info(request, 'You have already completed this survey.')
        return redirect('surveys:survey_list')

    # Check if survey has reached max responses
    if survey.max_responses and survey.responses.count() >= survey.max_responses:
        messages.warning(request, 'This survey has reached its maximum number of responses.')
        return redirect('surveys:survey_list')

    # Get all questions ordered by their order field
    questions = survey.questions.all().order_by('order')

    if request.method == 'POST':
        return handle_survey_submission(request, survey, questions)

    # GET request - show survey form
    context = {
        'survey': survey,
        'questions': questions,
    }
    return render(request, 'surveys/survey_detail.html', context)


@login_required
def handle_survey_submission(request, survey, questions):
    """
    Process survey form submission
    """
    errors = []

    # Validate all questions
    for question in questions:
        field_name = f'question_{question.id}'

        if question.is_required:
            if question.question_type in ['mcq', 'yes_no', 'rating']:
                # Radio button fields
                if field_name not in request.POST or not request.POST[field_name]:
                    errors.append(f'Please answer question: {question.question_text}')
            elif question.question_type == 'checkbox':
                # Checkbox fields (can have multiple values)
                values = request.POST.getlist(field_name)
                if not values:
                    errors.append(f'Please select at least one option for: {question.question_text}')
            else:
                # Text and textarea fields
                value = request.POST.get(field_name, '').strip()
                if not value:
                    errors.append(f'Please answer question: {question.question_text}')

    if errors:
        for error in errors:
            messages.error(request, error)
        context = {
            'survey': survey,
            'questions': questions,
            'form_data': request.POST,  # Preserve user input
        }
        return render(request, 'surveys/survey_detail.html', context)

    # Save the survey response
    try:
        with transaction.atomic():
            # Create the main response record
            response = Response.objects.create(
                user=request.user,
                survey=survey,
                payout_amount=survey.payout
            )

            # Save individual answers
            for question in questions:
                field_name = f'question_{question.id}'

                if question.question_type == 'text':
                    text_answer = request.POST.get(field_name, '').strip()
                    if text_answer:
                        Answer.objects.create(
                            response=response,
                            question=question,
                            text_answer=text_answer
                        )

                elif question.question_type == 'textarea':
                    text_answer = request.POST.get(field_name, '').strip()
                    if text_answer:
                        Answer.objects.create(
                            response=response,
                            question=question,
                            text_answer=text_answer
                        )

                elif question.question_type == 'mcq':
                    choice_id = request.POST.get(field_name)
                    if choice_id:
                        try:
                            choice = Choice.objects.get(id=choice_id, question=question)
                            Answer.objects.create(
                                response=response,
                                question=question,
                                choice=choice
                            )
                        except Choice.DoesNotExist:
                            pass

                elif question.question_type == 'checkbox':
                    choice_ids = request.POST.getlist(field_name)
                    for choice_id in choice_ids:
                        try:
                            choice = Choice.objects.get(id=choice_id, question=question)
                            Answer.objects.create(
                                response=response,
                                question=question,
                                choice=choice
                            )
                        except Choice.DoesNotExist:
                            pass

                elif question.question_type == 'rating':
                    rating_value = request.POST.get(field_name)
                    if rating_value:
                        try:
                            rating = int(rating_value)
                            # Validate rating is within bounds
                            min_rating = question.rating_min or 1
                            max_rating = question.rating_max or 10
                            if min_rating <= rating <= max_rating:
                                Answer.objects.create(
                                    response=response,
                                    question=question,
                                    rating_answer=rating
                                )
                        except (ValueError, TypeError):
                            pass

                elif question.question_type == 'yes_no':
                    yes_no_value = request.POST.get(field_name)
                    if yes_no_value in ['yes', 'no']:
                        Answer.objects.create(
                            response=response,
                            question=question,
                            boolean_answer=(yes_no_value == 'yes')
                        )

            # Process payment using the payment service
            try:
                from payments.services import SurveyPaymentService

                # Mark response as completed first
                response.completed = True
                response.completed_at = timezone.now()
                response.save()

                # Process payment
                payment_result = SurveyPaymentService.process_survey_completion_payment(response)

                if payment_result['success']:
                    transaction_obj = payment_result['transaction']
                    # Refresh user balance from database
                    request.user.refresh_from_db()
                    messages.success(request,
                                     f'Survey completed successfully! KSh {transaction_obj.amount} has been added to your account. '
                                     f'New balance: KSh {request.user.balance}')
                else:
                    messages.warning(request,
                                     f'Survey completed but payment processing failed: {payment_result["message"]}. '
                                     'Please contact support if this issue persists.')

            except ImportError:
                # Fallback to basic payment if service not available
                current_balance = getattr(request.user, 'balance', None)
                if current_balance is not None:
                    request.user.balance = (current_balance or Decimal('0.00')) + survey.payout
                    request.user.save()
                    messages.success(request, f'Survey completed! KSh {survey.payout} added to your account.')
                else:
                    messages.warning(request, "Payment processing not configured properly.")

            except Exception as payment_error:
                import traceback
                traceback.print_exc()
                messages.error(request, 'Survey submitted but payment processing failed. Please contact support.')

            return redirect('surveys:survey_success', survey_id=survey.id)

    except Exception as e:
        # Debug information
        import traceback
        traceback.print_exc()

        # Show the actual error message for debugging
        messages.error(request, f'Error: {str(e)}')
        context = {
            'survey': survey,
            'questions': questions,
            'form_data': request.POST,
        }
        return render(request, 'surveys/survey_detail.html', context)

@login_required
@csrf_protect
def take_survey(request, survey_id):
    """
    Handle survey taking process
    """
    # FIXED: Changed back to 'active' (lowercase)
    survey = get_object_or_404(Survey, id=survey_id, status='active')

    # Check if user can take this survey
    can_take, message = survey.can_user_take_survey(request.user)

    if not can_take:
        messages.error(request, message)
        return redirect('surveys:survey_list') # Fixed redirect

    questions = survey.questions.prefetch_related('choices').order_by('order')

    if request.method == 'POST':
        return handle_survey_submission(request, survey, questions)

    # GET request - display survey form
    context = {
        'survey': survey,
        'questions': questions,
    }

    return render(request, 'surveys/take_survey.html', context)


@login_required
def survey_complete(request, survey_id, response_id):
    """
    Display survey completion confirmation
    """
    survey = get_object_or_404(Survey, id=survey_id)
    response = get_object_or_404(Response, id=response_id, user=request.user, survey=survey)

    # Get user's updated balance
    user_balance = request.user.balance

    context = {
        'response': response,
        'survey': response.survey,
        'payout_amount': response.payout_amount,
        'user_balance': user_balance,
    }

    return render(request, 'surveys/survey_complete.html', context)


@login_required
def my_survey_history(request):
    """
    Display user's survey completion history
    """
    responses = Response.objects.filter(user=request.user).select_related('survey').order_by('-completed_at')

    # Calculate statistics
    total_surveys = responses.count()
    total_earned = sum(response.payout_amount for response in responses)

    context = {
        'responses': responses,
        'total_surveys': total_surveys,
        'total_earned': total_earned,
    }

    return render(request, 'surveys/my_surveys.html', context)


@login_required
@require_http_methods(["GET"])
def survey_preview(request, survey_id):
    """
    AJAX endpoint to preview survey questions
    """
    # FIXED: Changed back to 'active' (lowercase)
    survey = get_object_or_404(Survey, id=survey_id, status='active')
    questions = survey.questions.prefetch_related('choices').order_by('order')

    questions_data = []
    for question in questions:
        question_data = {
            'id': str(question.id),
            'text': question.question_text,
            'type': question.question_type,
            'required': question.is_required,
            'order': question.order,
        }

        if question.question_type == 'mcq':
            question_data['choices'] = [
                {'id': str(choice.id), 'text': choice.choice_text}
                for choice in question.choices.order_by('order')
            ]
        elif question.question_type == 'rating':
            question_data['rating_min'] = question.rating_min
            question_data['rating_max'] = question.rating_max

        questions_data.append(question_data)

    return JsonResponse({
        'survey': {
            'id': str(survey.id),
            'title': survey.title,
            'description': survey.description,
            'payout': str(survey.payout),
        },
        'questions': questions_data,
    })


def get_client_ip(request):
    """
    Get the client's IP address from request
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


# Public views (no login required)
def survey_stats(request):
    """
    Public statistics page
    """
    stats = {
        # FIXED: Changed back to 'active' (lowercase)
        'total_surveys': Survey.objects.filter(status='active').count(),
        'total_responses': Response.objects.count(),
        'total_payout': sum(r.payout_amount for r in Response.objects.all()),
        'active_users': Response.objects.values('user').distinct().count(),
    }

    context = {'stats': stats}
    return render(request, 'surveys/surveys.html', context)  # Using surveys.html template


def landing_page(request):
    """
    Landing page for all visitors - marketing/homepage at root URL
    Smart redirect based on user authentication and role
    """
    # Check if there's a referral code in the URL
    referral_code = request.GET.get('ref')

    # Smart redirect based on user authentication and role
    if request.user.is_authenticated:
        if request.user.is_staff:
            # Admin users go to admin dashboard
            return redirect('custom_admin:dashboard')
        else:
            # Regular users go to surveys page to start earning
            return redirect('surveys:survey_list')

    # If there's a referral code, redirect new users directly to registration
    if referral_code:
        return redirect(f'/accounts/register/?ref={referral_code}')

    # Stats for landing page (for anonymous visitors without referral codes)
    stats = {
        'total_surveys': Survey.objects.filter(status='active').count(),
        'total_responses': Response.objects.count(),
        'total_payout': sum(r.payout_amount for r in Response.objects.all()) if Response.objects.exists() else 0,
        'active_users': Response.objects.values('user').distinct().count(),
    }

    context = {'stats': stats}
    return render(request, 'surveys/landing_page.html', context)


@login_required
def survey_dashboard(request):
    """
    Main dashboard for logged-in users showing available surveys
    """
    # Get all active surveys - FIXED: Changed back to 'active' (lowercase)
    surveys = Survey.objects.filter(status='active').prefetch_related('questions')

    # Filter out completed surveys for this user
    completed_survey_ids = Response.objects.filter(user=request.user).values_list('survey_id', flat=True)
    surveys = surveys.exclude(id__in=completed_survey_ids)

    # Check availability for each survey
    available_surveys = []
    for survey in surveys:
        if survey.is_available:
            # Add extra info for display
            survey.question_count = survey.questions.count()
            survey.estimated_minutes = max(1, survey.question_count // 2)  # Rough estimate
            available_surveys.append(survey)

    # User stats
    user_responses = Response.objects.filter(user=request.user)
    user_stats = {
        'total_completed': user_responses.count(),
        'total_earned': sum(r.payout_amount for r in user_responses),
        'current_balance': request.user.balance,
    }

    context = {
        'surveys': available_surveys,
        'total_surveys': len(available_surveys),
        'user_stats': user_stats,
    }

    return render(request, 'surveys/survey_dashboard.html', context)


@login_required
def survey_success(request, survey_id):
    """
    Show survey completion success page
    """
    survey = get_object_or_404(Survey, id=survey_id)
    response = get_object_or_404(Response, user=request.user, survey=survey)

    context = {
        'survey': survey,
        'response': response,
        'payout': response.payout_amount,
    }
    return render(request, 'surveys/survey_success.html', context)


@login_required
def survey_response_detail(request, response_id):
    """
    Display detailed view of a user's survey response with questions and answers
    """
    response = get_object_or_404(Response, id=response_id, user=request.user)

    # Get all questions with their answers
    questions_with_answers = []
    for question in response.survey.questions.all().order_by('order'):
        # Get the answer(s) for this question
        answers = response.answers.filter(question=question)

        # Store answer data with more detail
        answer_data = {
            'question': question,
            'answers': [],
            'selected_choices': [],  # For multiple choice/checkbox
            'text_answer': None,
            'rating_answer': None,
            'boolean_answer': None,
            'answer_count': answers.count()
        }

        for answer in answers:
            if answer.choice:
                # Multiple choice or checkbox
                answer_data['answers'].append(answer.choice.choice_text)
                answer_data['selected_choices'].append(answer.choice)
            elif answer.text_answer:
                # Text or textarea
                answer_data['answers'].append(answer.text_answer)
                answer_data['text_answer'] = answer.text_answer
            elif answer.rating_answer is not None:
                # Rating
                answer_data['answers'].append(str(answer.rating_answer))
                answer_data['rating_answer'] = answer.rating_answer
            elif answer.boolean_answer is not None:
                # Yes/No
                answer_text = "Yes" if answer.boolean_answer else "No"
                answer_data['answers'].append(answer_text)
                answer_data['boolean_answer'] = answer.boolean_answer

        # If no answer provided
        if not answer_data['answers']:
            answer_data['answers'] = ["No answer provided"]

        questions_with_answers.append(answer_data)

    context = {
        'response': response,
        'survey': response.survey,
        'questions_with_answers': questions_with_answers,
    }

    return render(request, 'surveys/response_detail.html', context)