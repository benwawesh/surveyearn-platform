# custom_admin/views.py
import uuid
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, Http404
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from accounts.models import User
from surveys.models import Survey, Response
from payments.models import Transaction, WithdrawalRequest
from surveys.models import Survey, Response, Answer, Question, Choice
from django.db import models
from django.views.decorators.csrf import csrf_exempt
from accounts.models import User
from django.views.decorators.http import require_http_methods
import json


# Add the admin_required decorator here
def admin_required(view_func):
    """Decorator to ensure user is admin"""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not request.user.is_staff:
            messages.error(request, 'Access denied. Admin privileges required.')
            return redirect('accounts:dashboard')
        # Set admin_verified session when user passes checks
        request.session['admin_verified'] = True
        return view_func(request, *args, **kwargs)
    return wrapper


def user_login(request):
    """User login view"""
    if request.user.is_authenticated:
        # Redirect based on user type
        if request.user.is_staff:
            return redirect('custom_admin:dashboard')
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = UserLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']

            user = authenticate(request, username=username, password=password)
            if user is not None:
                if user.is_active:
                    login(request, user)

                    # Set admin session if staff user
                    if user.is_staff:
                        request.session['admin_verified'] = True
                        messages.success(request, 'Successfully logged in to admin panel.')
                        return redirect('custom_admin:dashboard')
                    else:
                        # Regular user redirect
                        next_page = request.GET.get('next', 'accounts:dashboard')
                        messages.success(request, f'Welcome back, {user.first_name or user.username}!')
                        return redirect(next_page)
                else:
                    messages.error(request, 'Your account has been deactivated.')
            else:
                messages.error(request, 'Invalid username or password.')
    else:
        form = UserLoginForm()

    context = {
        'form': form,
        'title': 'Login'
    }
    return render(request, 'accounts/login.html', context)


@admin_required
def admin_dashboard(request):
    """Admin dashboard with platform statistics"""
    # Get platform statistics
    total_users = User.objects.count()
    total_surveys = Survey.objects.count()
    total_responses = Response.objects.count()
    total_earnings = Transaction.objects.filter(
        transaction_type='survey_payment'
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Recent activity
    recent_users = User.objects.order_by('-date_joined')[:5]
    recent_surveys = Survey.objects.order_by('-created_at')[:5]
    recent_transactions = Transaction.objects.order_by('-created_at')[:5]
    pending_withdrawals = WithdrawalRequest.objects.filter(status='pending').count()

    context = {
        'total_users': total_users,
        'total_surveys': total_surveys,
        'total_responses': total_responses,
        'total_earnings': total_earnings,
        'recent_users': recent_users,
        'recent_surveys': recent_surveys,
        'recent_transactions': recent_transactions,
        'pending_withdrawals': pending_withdrawals,
    }

    return render(request, 'admin/dashboard.html', context)


@admin_required
def admin_logout(request):
    """Admin logout"""
    if 'admin_verified' in request.session:
        del request.session['admin_verified']
    logout(request)
    messages.success(request, 'Successfully logged out.')
    return redirect('surveys:landing_page')


@admin_required
def admin_users(request):
    """User management with search and filtering"""
    users = User.objects.all()

    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)
    elif status_filter == 'staff':
        users = users.filter(is_staff=True)

    # Order by latest joined
    users = users.order_by('-date_joined')

    # Pagination
    paginator = Paginator(users, 20)
    page_number = request.GET.get('page')
    users = paginator.get_page(page_number)

    context = {
        'users': users,
        'search_query': search_query,
        'status_filter': status_filter,
    }

    return render(request, 'admin/users.html', context)


@admin_required
def admin_user_detail(request, user_id):
    """View individual user details with UUID lookup"""
    try:
        # Validate UUID format
        uuid.UUID(str(user_id))
        user = get_object_or_404(User, id=user_id)
    except (ValueError, ValidationError):
        raise Http404("Invalid user ID")

    # Handle POST requests for user actions
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'toggle_active':
            user.is_active = not user.is_active
            user.save()
            status = "activated" if user.is_active else "deactivated"
            messages.success(request, f'User {user.username} has been {status}.')

        elif action == 'adjust_balance':
            amount = request.POST.get('amount')
            reason = request.POST.get('reason', '')

            if amount and reason:
                try:
                    amount = float(amount)
                    balance_before = user.balance
                    user.balance += amount
                    user.save()

                    # Create transaction record
                    Transaction.objects.create(
                        user=user,
                        transaction_type='adjustment',
                        amount=abs(amount),
                        status='completed',
                        description=f"Admin balance adjustment: {reason}",
                        balance_before=balance_before,
                        balance_after=user.balance,
                        processed_by=request.user
                    )

                    messages.success(request, f'Balance adjusted by KSh {amount}. New balance: KSh {user.balance}')
                except ValueError:
                    messages.error(request, 'Invalid amount entered.')
            else:
                messages.error(request, 'Amount and reason are required.')

    # Get user's recent transactions
    recent_transactions = Transaction.objects.filter(user=user).order_by('-created_at')[:10]

    # Get user's survey responses
    responses = Response.objects.filter(user=user).select_related('survey').order_by('-completed_at')[:10]

    # Get user's withdrawal requests
    withdrawals = WithdrawalRequest.objects.filter(user=user).order_by('-created_at')[:5]

    context = {
        'user_obj': user,
        'recent_transactions': recent_transactions,
        'responses': responses,
        'withdrawals': withdrawals,
    }
    return render(request, 'admin/user_detail.html', context)

@admin_required
def adjust_user_balance(request, user_id):
    """Adjust user balance (AJAX endpoint)"""
    if request.method == 'POST':
        try:
            # Validate UUID format
            uuid.UUID(str(user_id))
            user = get_object_or_404(User, id=user_id)

            adjustment_type = request.POST.get('type')  # 'add' or 'subtract'
            amount = float(request.POST.get('amount', 0))
            reason = request.POST.get('reason', '')

            if amount <= 0:
                return JsonResponse({'success': False, 'error': 'Amount must be positive'})

            balance_before = user.balance

            if adjustment_type == 'add':
                user.balance += amount
                transaction_type = 'adjustment'
                description = f"Admin balance addition: {reason}"
            elif adjustment_type == 'subtract':
                if user.balance < amount:
                    return JsonResponse({'success': False, 'error': 'Insufficient balance'})
                user.balance -= amount
                transaction_type = 'adjustment'
                description = f"Admin balance deduction: {reason}"
            else:
                return JsonResponse({'success': False, 'error': 'Invalid adjustment type'})

            user.save()

            # Create transaction record
            Transaction.objects.create(
                user=user,
                transaction_type=transaction_type,
                amount=amount,
                status='completed',
                description=description,
                balance_before=balance_before,
                balance_after=user.balance,
                processed_by=request.user,
                notes=f"Manual adjustment by {request.user.username}"
            )

            return JsonResponse({
                'success': True,
                'new_balance': float(user.balance),
                'message': f'Balance adjusted successfully. New balance: ${user.balance}'
            })

        except (ValueError, ValidationError):
            return JsonResponse({'success': False, 'error': 'Invalid user ID'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@admin_required
def admin_surveys(request):
    """Survey management with search and filtering"""
    surveys = Survey.objects.all()

    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        surveys = surveys.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        surveys = surveys.filter(status=status_filter)

    # Filter by payout range
    payout_filter = request.GET.get('payout', '')
    if payout_filter == '0-5':
        surveys = surveys.filter(payout__gte=0, payout__lt=5)
    elif payout_filter == '5-10':
        surveys = surveys.filter(payout__gte=5, payout__lt=10)
    elif payout_filter == '10-20':
        surveys = surveys.filter(payout__gte=10, payout__lt=20)
    elif payout_filter == '20+':
        surveys = surveys.filter(payout__gte=20)

    # Order by latest created
    surveys = surveys.order_by('-created_at')

    # Pagination
    paginator = Paginator(surveys, 15)
    page_number = request.GET.get('page')
    surveys = paginator.get_page(page_number)

    context = {
        'surveys': surveys,
        'search_query': search_query,
        'status_filter': status_filter,
        'payout_filter': payout_filter,
    }

    return render(request, 'admin/surveys.html', context)


@admin_required
def admin_survey_detail(request, survey_id):
    """View individual survey details with UUID lookup"""
    try:
        # Validate UUID format
        uuid.UUID(str(survey_id))
        survey = get_object_or_404(Survey, id=survey_id)
    except (ValueError, ValidationError):
        raise Http404("Invalid survey ID")

    # Get recent responses
    recent_responses = Response.objects.filter(survey=survey).select_related('user').order_by('-completed_at')[:10]

    context = {
        'survey': survey,
        'recent_responses': recent_responses,
    }
    return render(request, 'admin/survey_detail.html', context)


@admin_required
def admin_withdrawals(request):
    """Withdrawal management with filtering"""
    withdrawals = WithdrawalRequest.objects.all()

    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        withdrawals = withdrawals.filter(
            Q(user__username__icontains=search_query) |
            Q(user__email__icontains=search_query)
        )

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        withdrawals = withdrawals.filter(status=status_filter)

    # Filter by payment method
    method_filter = request.GET.get('method', '')
    if method_filter:
        withdrawals = withdrawals.filter(payment_method=method_filter)

    # Order by latest created
    withdrawals = withdrawals.order_by('-created_at')

    # Get statistics
    stats = {
        'pending_count': WithdrawalRequest.objects.filter(status='pending').count(),
        'processed_today': WithdrawalRequest.objects.filter(
            status='completed',
            completed_at__date=timezone.now().date()
        ).count(),
        'total_month': WithdrawalRequest.objects.filter(
            status='completed',
            completed_at__month=timezone.now().month
        ).aggregate(total=Sum('amount'))['total'] or 0,
        'rejected_count': WithdrawalRequest.objects.filter(status='rejected').count(),
    }

    # Pagination
    paginator = Paginator(withdrawals, 20)
    page_number = request.GET.get('page')
    withdrawals = paginator.get_page(page_number)

    context = {
        'withdrawals': withdrawals,
        'stats': stats,
        'search_query': search_query,
        'status_filter': status_filter,
        'method_filter': method_filter,
    }

    return render(request, 'admin/withdrawals.html', context)


@admin_required
def admin_withdrawal_detail(request, withdrawal_id):
    """View individual withdrawal details with UUID lookup"""
    try:
        # Validate UUID format
        uuid.UUID(str(withdrawal_id))
        withdrawal = get_object_or_404(WithdrawalRequest, id=withdrawal_id)
    except (ValueError, ValidationError):
        raise Http404("Invalid withdrawal ID")

    context = {
        'withdrawal': withdrawal,
    }
    return render(request, 'admin/withdrawal_detail.html', context)


@admin_required
def approve_withdrawal(request, withdrawal_id):
    """Approve withdrawal request"""
    try:
        # Validate UUID format
        uuid.UUID(str(withdrawal_id))
        withdrawal = get_object_or_404(WithdrawalRequest, id=withdrawal_id)

        if withdrawal.can_be_approved():
            notes = request.POST.get('notes', '')
            if withdrawal.approve(request.user, notes):
                messages.success(request, f'Withdrawal of ${withdrawal.amount} approved successfully.')
            else:
                messages.error(request, 'Failed to approve withdrawal.')
        else:
            messages.error(request, 'Withdrawal cannot be approved in its current state.')

    except (ValueError, ValidationError):
        messages.error(request, 'Invalid withdrawal ID.')

    return redirect('custom_admin:withdrawals')


@admin_required
def reject_withdrawal(request, withdrawal_id):
    """Reject withdrawal request"""
    try:
        # Validate UUID format
        uuid.UUID(str(withdrawal_id))
        withdrawal = get_object_or_404(WithdrawalRequest, id=withdrawal_id)

        if withdrawal.can_be_rejected():
            reason = request.POST.get('reason', 'No reason provided')
            notes = request.POST.get('notes', '')
            if withdrawal.reject(request.user, reason, notes):
                messages.success(request, f'Withdrawal of ${withdrawal.amount} rejected and balance restored.')
            else:
                messages.error(request, 'Failed to reject withdrawal.')
        else:
            messages.error(request, 'Withdrawal cannot be rejected in its current state.')

    except (ValueError, ValidationError):
        messages.error(request, 'Invalid withdrawal ID.')

    return redirect('custom_admin:withdrawals')


@admin_required
def admin_transactions(request):
    """Transaction management with filtering"""
    transactions = Transaction.objects.all()

    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        transactions = transactions.filter(
            Q(user__username__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    # Filter by transaction type
    type_filter = request.GET.get('type', '')
    if type_filter:
        transactions = transactions.filter(transaction_type=type_filter)

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        transactions = transactions.filter(status=status_filter)

    # Filter by date range
    date_filter = request.GET.get('date', '')
    if date_filter == 'today':
        transactions = transactions.filter(created_at__date=timezone.now().date())
    elif date_filter == 'week':
        week_ago = timezone.now() - timezone.timedelta(days=7)
        transactions = transactions.filter(created_at__gte=week_ago)
    elif date_filter == 'month':
        transactions = transactions.filter(created_at__month=timezone.now().month)

    # Order by latest created
    transactions = transactions.order_by('-created_at')

    # Get statistics
    stats = {
        'total_revenue': transactions.filter(
            transaction_type='survey_payment'
        ).aggregate(total=Sum('amount'))['total'] or 0,
        'survey_payments': transactions.filter(
            transaction_type='survey_payment'
        ).aggregate(total=Sum('amount'))['total'] or 0,
        'withdrawals': transactions.filter(
            transaction_type='withdrawal'
        ).aggregate(total=Sum('amount'))['total'] or 0,
        'today_volume': transactions.filter(
            created_at__date=timezone.now().date()
        ).aggregate(total=Sum('amount'))['total'] or 0,
    }

    # Pagination
    paginator = Paginator(transactions, 25)
    page_number = request.GET.get('page')
    transactions = paginator.get_page(page_number)

    context = {
        'transactions': transactions,
        'stats': stats,
        'search_query': search_query,
        'type_filter': type_filter,
        'status_filter': status_filter,
        'date_filter': date_filter,
    }

    return render(request, 'admin/transactions.html', context)


@admin_required
def admin_transaction_detail(request, transaction_id):
    """View individual transaction details with UUID lookup"""
    try:
        # Validate UUID format
        uuid.UUID(str(transaction_id))
        transaction = get_object_or_404(Transaction, id=transaction_id)
    except (ValueError, ValidationError):
        raise Http404("Invalid transaction ID")

    context = {
        'transaction': transaction,
    }
    return render(request, 'admin/transaction_detail.html', context)


@admin_required
def admin_reports(request):
    """Reports and analytics dashboard"""
    # Get key metrics
    metrics = {
        'total_revenue': Transaction.objects.filter(
            transaction_type='survey_payment'
        ).aggregate(total=Sum('amount'))['total'] or 0,
        'survey_completions': Response.objects.count(),
        'active_users': User.objects.filter(
            last_login__gte=timezone.now() - timezone.timedelta(days=30)
        ).count(),
        'avg_payout': Survey.objects.aggregate(avg=models.Avg('payout'))['avg'] or 0,
    }

    # Get top performing surveys
    top_surveys = Survey.objects.annotate(
        response_count=Count('responses')
    ).order_by('-response_count')[:5]

    # Get top earners
    top_earners = User.objects.order_by('-total_earnings')[:5]

    # Platform summary
    summary = {
        'total_users': User.objects.count(),
        'total_surveys': Survey.objects.count(),
        'total_paid': Transaction.objects.filter(
            transaction_type='survey_payment'
        ).aggregate(total=Sum('amount'))['total'] or 0,
        'completion_rate': 85,  # This would be calculated based on actual data
    }

    context = {
        'metrics': metrics,
        'top_surveys': top_surveys,
        'top_earners': top_earners,
        'summary': summary,
    }

    return render(request, 'admin/reports.html', context)


# Additional view functions to add to custom_admin/views.py

@admin_required
def admin_survey_edit(request, survey_id):
    """Edit survey details - simplified without demographics"""
    try:
        uuid.UUID(str(survey_id))
        survey = get_object_or_404(Survey, id=survey_id)
    except (ValueError, ValidationError):
        raise Http404("Invalid survey ID")

    if request.method == 'POST':
        # Update survey fields
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        payout = request.POST.get('payout')
        status = request.POST.get('status', survey.status)
        max_responses = request.POST.get('max_responses')

        # Validation
        if not title:
            messages.error(request, 'Please provide a survey title.')
            return render(request, 'admin/survey_edit.html', {'survey': survey})

        if not description:
            messages.error(request, 'Please provide a survey description.')
            return render(request, 'admin/survey_edit.html', {'survey': survey})

        try:
            payout = float(payout)
            if payout <= 0:
                messages.error(request, 'Payout amount must be greater than 0.')
                return render(request, 'admin/survey_edit.html', {'survey': survey})
        except (ValueError, TypeError):
            messages.error(request, 'Please provide a valid payout amount.')
            return render(request, 'admin/survey_edit.html', {'survey': survey})

        # Handle max_responses
        max_responses_value = None
        if max_responses:
            try:
                max_responses_value = int(max_responses)
                if max_responses_value <= 0:
                    max_responses_value = None
            except (ValueError, TypeError):
                max_responses_value = None

        # Update survey
        try:
            survey.title = title
            survey.description = description
            survey.payout = payout
            survey.status = status
            survey.max_responses = max_responses_value
            survey.save()

            messages.success(request, 'Survey updated successfully!')
            return redirect('custom_admin:survey_detail', survey_id=survey.id)
        except Exception as e:
            messages.error(request, f'Error updating survey: {str(e)}')

    context = {
        'survey': survey,
    }
    return render(request, 'admin/survey_edit.html', context)


@admin_required
def admin_survey_delete(request, survey_id):
    """Delete survey (with confirmation)"""
    try:
        # Validate UUID format
        uuid.UUID(str(survey_id))
        survey = get_object_or_404(Survey, id=survey_id)
    except (ValueError, ValidationError):
        raise Http404("Invalid survey ID")

    if request.method == 'POST':
        if request.POST.get('confirm') == 'yes':
            survey_title = survey.title
            survey.delete()
            messages.success(request, f'Survey "{survey_title}" deleted successfully.')
            return redirect('custom_admin:surveys')
        else:
            messages.error(request, 'Survey deletion cancelled.')
            return redirect('custom_admin:survey_detail', survey_id=survey.id)

    context = {
        'survey': survey,
    }
    return render(request, 'admin/survey_delete_confirm.html', context)


@admin_required
def admin_survey_create(request):
    """Create new survey - simplified without demographics"""
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        payout = request.POST.get('payout')
        status = request.POST.get('status', 'draft')
        max_responses = request.POST.get('max_responses')

        # Validation
        if not title:
            messages.error(request, 'Please provide a survey title.')
            return render(request, 'admin/survey_create.html')

        if not description:
            messages.error(request, 'Please provide a survey description.')
            return render(request, 'admin/survey_create.html')

        try:
            payout = float(payout)
            if payout <= 0:
                messages.error(request, 'Payout amount must be greater than 0.')
                return render(request, 'admin/survey_create.html')
        except (ValueError, TypeError):
            messages.error(request, 'Please provide a valid payout amount.')
            return render(request, 'admin/survey_create.html')

        # Handle max_responses
        max_responses_value = None
        if max_responses:
            try:
                max_responses_value = int(max_responses)
                if max_responses_value <= 0:
                    max_responses_value = None
            except (ValueError, TypeError):
                max_responses_value = None

        # Create survey
        try:
            survey = Survey.objects.create(
                title=title,
                description=description,
                payout=payout,
                status=status,
                max_responses=max_responses_value,
                created_by=request.user
            )
            messages.success(request, f'Survey "{title}" created successfully!')
            return redirect('custom_admin:survey_detail', survey_id=survey.id)
        except Exception as e:
            messages.error(request, f'Error creating survey: {str(e)}')

    return render(request, 'admin/survey_create.html')


@admin_required
def activate_survey(request, survey_id):
    """Activate a survey"""
    try:
        # Validate UUID format
        uuid.UUID(str(survey_id))
        survey = get_object_or_404(Survey, id=survey_id)

        if survey.status == 'draft' or survey.status == 'paused':
            survey.status = 'active'
            survey.save()
            messages.success(request, f'Survey "{survey.title}" activated successfully.')
        else:
            messages.error(request, 'Survey cannot be activated in its current state.')

    except (ValueError, ValidationError):
        messages.error(request, 'Invalid survey ID.')

    return redirect('custom_admin:survey_detail', survey_id=survey_id)


@admin_required
def pause_survey(request, survey_id):
    """Pause a survey"""
    try:
        # Validate UUID format
        uuid.UUID(str(survey_id))
        survey = get_object_or_404(Survey, id=survey_id)

        if survey.status == 'active':
            survey.status = 'paused'
            survey.save()
            messages.success(request, f'Survey "{survey.title}" paused successfully.')
        else:
            messages.error(request, 'Survey cannot be paused in its current state.')

    except (ValueError, ValidationError):
        messages.error(request, 'Invalid survey ID.')

    return redirect('custom_admin:survey_detail', survey_id=survey_id)


@admin_required
def process_withdrawal(request, withdrawal_id):
    """Process withdrawal by sending M-Pesa B2C payment"""
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('custom_admin:withdrawals')

    try:
        # Validate UUID format
        uuid.UUID(str(withdrawal_id))
        withdrawal = get_object_or_404(WithdrawalRequest, id=withdrawal_id)

        if withdrawal.status != 'approved':
            messages.error(request, 'Withdrawal must be approved before processing.')
            return redirect('custom_admin:withdrawals')

        # Change status to processing
        withdrawal.status = 'processing'
        withdrawal.save()

        # Import your M-Pesa service
        from payments.services import WithdrawalService

        # Initialize withdrawal service
        withdrawal_service = WithdrawalService()

        try:
            # Process the M-Pesa B2C payment
            result = withdrawal_service.process_mpesa_withdrawal(withdrawal)

            if result.get('success', False):
                # Payment initiated successfully
                mpesa_receipt = result.get('receipt_number', '')
                withdrawal.status = 'processed'
                withdrawal.external_transaction_id = mpesa_receipt
                withdrawal.processed_at = timezone.now()
                withdrawal.processed_by = request.user
                withdrawal.save()

                # Create transaction record
                from payments.models import Transaction
                Transaction.objects.create(
                    user=withdrawal.user,
                    transaction_type='withdrawal',
                    amount=-withdrawal.amount,
                    status='completed',
                    description=f'Withdrawal processed - M-Pesa: {mpesa_receipt}',
                    balance_before=withdrawal.user.balance,
                    balance_after=withdrawal.user.balance,
                    processed_by=request.user
                )

                messages.success(request,
                                 f'M-Pesa payment of KSh {withdrawal.net_amount} sent successfully! Receipt: {mpesa_receipt}')

            else:
                # Payment failed
                error_message = result.get('error', 'M-Pesa payment failed')
                withdrawal.status = 'failed'
                withdrawal.failure_reason = error_message
                withdrawal.save()

                # Return money to user balance
                withdrawal.user.balance += withdrawal.amount
                withdrawal.user.save()

                messages.error(request, f'M-Pesa payment failed: {error_message}')

        except Exception as mpesa_error:
            # M-Pesa API error
            withdrawal.status = 'failed'
            withdrawal.failure_reason = str(mpesa_error)
            withdrawal.save()

            # Return money to user balance
            withdrawal.user.balance += withdrawal.amount
            withdrawal.user.save()

            messages.error(request, f'M-Pesa processing error: {str(mpesa_error)}')

    except (ValueError, ValidationError):
        messages.error(request, 'Invalid withdrawal ID.')
    except Exception as e:
        messages.error(request, f'Error processing withdrawal: {str(e)}')

    return redirect('custom_admin:withdrawals')


@admin_required
def export_reports(request):
    """Export reports data"""
    import csv
    from django.http import HttpResponse

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="platform_report.csv"'

    writer = csv.writer(response)

    # Export type based on request parameter
    export_type = request.GET.get('type', 'transactions')

    if export_type == 'transactions':
        writer.writerow(['Date', 'User', 'Type', 'Amount', 'Status', 'Description'])

        transactions = Transaction.objects.all().order_by('-created_at')[:1000]  # Limit to 1000 recent
        for transaction in transactions:
            writer.writerow([
                transaction.created_at.strftime('%Y-%m-%d %H:%M'),
                transaction.user.username,
                transaction.get_transaction_type_display(),
                transaction.amount,
                transaction.get_status_display(),
                transaction.description
            ])

    elif export_type == 'surveys':
        writer.writerow(['Title', 'Payout', 'Status', 'Responses', 'Total Cost', 'Created'])

        surveys = Survey.objects.all().order_by('-created_at')
        for survey in surveys:
            writer.writerow([
                survey.title,
                survey.payout,
                survey.get_status_display(),
                survey.total_responses,
                survey.total_payout_cost,
                survey.created_at.strftime('%Y-%m-%d')
            ])

    elif export_type == 'users':
        writer.writerow(['Username', 'Email', 'Balance', 'Total Earnings', 'Surveys Completed', 'Joined'])

        users = User.objects.all().order_by('-date_joined')
        for user in users:
            writer.writerow([
                user.username,
                user.email,
                user.balance,
                user.total_earnings,
                user.total_surveys_completed,
                user.date_joined.strftime('%Y-%m-%d')
            ])

    elif export_type == 'withdrawals':
        writer.writerow(['User', 'Amount', 'Payment Method', 'Status', 'Requested', 'Processed'])

        withdrawals = WithdrawalRequest.objects.all().order_by('-created_at')
        for withdrawal in withdrawals:
            writer.writerow([
                withdrawal.user.username,
                withdrawal.amount,
                withdrawal.get_payment_method_display(),
                withdrawal.get_status_display(),
                withdrawal.created_at.strftime('%Y-%m-%d %H:%M'),
                withdrawal.completed_at.strftime('%Y-%m-%d %H:%M') if withdrawal.completed_at else 'N/A'
            ])

    return response


# Add these views to your custom_admin/views.py file
@admin_required
def admin_survey_questions(request, survey_id):
    """Manage questions for a specific survey"""
    try:
        uuid.UUID(str(survey_id))
        survey = get_object_or_404(Survey, id=survey_id)
    except (ValueError, ValidationError):
        raise Http404("Invalid survey ID")

    questions = survey.questions.prefetch_related('choices').order_by('order')

    context = {
        'survey': survey,
        'questions': questions,
    }
    return render(request, 'admin/survey_questions.html', context)


@admin_required
def admin_question_create(request, survey_id):
    """Create a new question for a survey with choices and correct answers"""
    try:
        uuid.UUID(str(survey_id))
        survey = get_object_or_404(Survey, id=survey_id)
    except (ValueError, ValidationError):
        raise Http404("Invalid survey ID")

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Get basic question data
                question_text = request.POST.get('question_text', '').strip()
                question_type = request.POST.get('question_type')
                is_required = request.POST.get('is_required') == 'on'
                order = request.POST.get('order')

                # Validate required fields
                if not question_text:
                    messages.error(request, 'Question text is required.')
                    return render(request, 'admin/question_create.html', {'survey': survey})

                if not question_type:
                    messages.error(request, 'Please select a question type.')
                    return render(request, 'admin/question_create.html', {'survey': survey})

                # Handle order
                if order:
                    try:
                        order = int(order)
                    except (ValueError, TypeError):
                        order = survey.questions.count() + 1
                else:
                    order = survey.questions.count() + 1

                # Create the question
                question = Question.objects.create(
                    survey=survey,
                    question_text=question_text,
                    question_type=question_type,
                    is_required=is_required,
                    order=order
                )

                # Handle different question types
                if question_type == 'mcq':
                    # Handle Multiple Choice Question
                    choices = request.POST.getlist('mcq_choices[]')
                    correct_answer = request.POST.get('correct_mcq_answer')

                    if not choices or not any(choice.strip() for choice in choices):
                        question.delete()
                        messages.error(request, 'Please add at least one choice for multiple choice question.')
                        return render(request, 'admin/question_create.html', {'survey': survey})

                    if not correct_answer:
                        question.delete()
                        messages.error(request, 'Please select the correct answer for multiple choice question.')
                        return render(request, 'admin/question_create.html', {'survey': survey})

                    # Create choices
                    for i, choice_text in enumerate(choices, 1):
                        if choice_text.strip():
                            is_correct = str(i) == correct_answer
                            Choice.objects.create(
                                question=question,
                                choice_text=choice_text.strip(),
                                order=i,
                                is_correct=is_correct
                            )

                elif question_type == 'checkbox':
                    # Handle Checkbox Question
                    choices = request.POST.getlist('checkbox_choices[]')
                    correct_answers = request.POST.getlist('correct_checkbox_answers')

                    if not choices or not any(choice.strip() for choice in choices):
                        question.delete()
                        messages.error(request, 'Please add at least one choice for checkbox question.')
                        return render(request, 'admin/question_create.html', {'survey': survey})

                    if not correct_answers:
                        question.delete()
                        messages.error(request, 'Please select at least one correct answer for checkbox question.')
                        return render(request, 'admin/question_create.html', {'survey': survey})

                    # Create choices
                    for i, choice_text in enumerate(choices, 1):
                        if choice_text.strip():
                            is_correct = str(i) in correct_answers
                            Choice.objects.create(
                                question=question,
                                choice_text=choice_text.strip(),
                                order=i,
                                is_correct=is_correct
                            )

                elif question_type == 'rating':
                    # Handle Rating Question
                    rating_min = request.POST.get('rating_min', 1)
                    rating_max = request.POST.get('rating_max', 5)
                    rating_min_label = request.POST.get('rating_min_label', '')
                    rating_max_label = request.POST.get('rating_max_label', '')

                    try:
                        rating_min = int(rating_min)
                        rating_max = int(rating_max)
                    except (ValueError, TypeError):
                        rating_min, rating_max = 1, 5

                    question.rating_min = rating_min
                    question.rating_max = rating_max
                    question.save()

                    # Create label choices if provided
                    if rating_min_label:
                        Choice.objects.create(
                            question=question,
                            choice_text=rating_min_label,
                            order=rating_min,
                            is_correct=False
                        )
                    if rating_max_label:
                        Choice.objects.create(
                            question=question,
                            choice_text=rating_max_label,
                            order=rating_max,
                            is_correct=False
                        )

                elif question_type == 'yes_no':
                    # Handle Yes/No Question
                    correct_answer = request.POST.get('correct_answer', 'both')

                    # Create Yes/No choices
                    Choice.objects.create(
                        question=question,
                        choice_text='Yes',
                        order=1,
                        is_correct=(correct_answer in ['yes', 'both'])
                    )
                    Choice.objects.create(
                        question=question,
                        choice_text='No',
                        order=2,
                        is_correct=(correct_answer in ['no', 'both'])
                    )

                # For text and textarea questions, no additional setup needed

                messages.success(request, f'Question "{question_text[:50]}..." created successfully!')
                return redirect('custom_admin:survey_questions', survey_id=survey.id)

        except Exception as e:
            messages.error(request, f'Error creating question: {str(e)}')
            return render(request, 'admin/question_create.html', {'survey': survey})

    context = {
        'survey': survey,
    }
    return render(request, 'admin/question_create.html', context)


@admin_required
def admin_question_edit(request, survey_id, question_id):
    """Edit a question"""
    try:
        uuid.UUID(str(survey_id))
        uuid.UUID(str(question_id))
        survey = get_object_or_404(Survey, id=survey_id)
        question = get_object_or_404(Question, id=question_id, survey=survey)
    except (ValueError, ValidationError):
        raise Http404("Invalid survey or question ID")

    if request.method == 'POST':
        question.question_text = request.POST.get('question_text')
        question.question_type = request.POST.get('question_type')
        question.is_required = request.POST.get('is_required') == 'on'
        question.order = int(request.POST.get('order', question.order))

        # Rating specific fields
        rating_min = request.POST.get('rating_min')
        rating_max = request.POST.get('rating_max')
        question.rating_min = int(rating_min) if rating_min else None
        question.rating_max = int(rating_max) if rating_max else None

        question.save()

        # Update choices if MCQ
        if question.question_type == 'mcq':
            # Delete existing choices and create new ones
            question.choices.all().delete()
            choices = request.POST.getlist('choices[]')
            for i, choice_text in enumerate(choices):
                if choice_text.strip():
                    Choice.objects.create(
                        question=question,
                        choice_text=choice_text.strip(),
                        order=i + 1
                    )

        messages.success(request, 'Question updated successfully.')
        return redirect('custom_admin:survey_questions', survey_id=survey.id)

    context = {
        'survey': survey,
        'question': question,
    }
    return render(request, 'admin/question_edit.html', context)


@admin_required
def admin_question_delete(request, survey_id, question_id):
    """Delete a question"""
    try:
        uuid.UUID(str(survey_id))
        uuid.UUID(str(question_id))
        survey = get_object_or_404(Survey, id=survey_id)
        question = get_object_or_404(Question, id=question_id, survey=survey)
    except (ValueError, ValidationError):
        raise Http404("Invalid survey or question ID")

    if request.method == 'POST':
        if request.POST.get('confirm') == 'yes':
            question_text = question.question_text
            question.delete()
            messages.success(request, f'Question "{question_text}" deleted successfully.')
        else:
            messages.error(request, 'Question deletion cancelled.')

        return redirect('custom_admin:survey_questions', survey_id=survey.id)

    context = {
        'survey': survey,
        'question': question,
    }
    return render(request, 'admin/question_delete.html', context)


@admin_required
def admin_reports_advanced(request):
    """Advanced reports with comprehensive analytics"""

    # Get date range from request
    date_range = int(request.GET.get('days', 30))
    report_type = request.GET.get('type', 'overview')

    context = {
        'date_range': date_range,
        'report_type': report_type,
    }

    if report_type == 'overview':
        # Executive summary
        summary = ReportsService.generate_executive_summary(date_range)
        chart_data = ReportsService.export_data_for_charts(date_range)

        context.update({
            'summary': summary,
            'chart_data': json.dumps(chart_data),
        })

    elif report_type == 'users':
        # Detailed user analytics
        user_analytics = ReportsService.get_user_analytics(date_range)
        context['user_analytics'] = user_analytics

    elif report_type == 'surveys':
        # Detailed survey analytics
        survey_analytics = ReportsService.get_survey_analytics(date_range)
        context['survey_analytics'] = survey_analytics

    elif report_type == 'financial':
        # Detailed financial analytics
        financial_analytics = ReportsService.get_financial_analytics(date_range)
        context['financial_analytics'] = financial_analytics

    elif report_type == 'health':
        # Platform health metrics
        health_metrics = ReportsService.get_platform_health_metrics()
        context['health_metrics'] = health_metrics

    return render(request, 'admin/reports_advanced.html', context)


@admin_required
def survey_detailed_analytics(request, survey_id):
    """Detailed analytics for a specific survey"""

    analytics = ReportsService.get_survey_response_analytics(survey_id)

    if not analytics:
        messages.error(request, 'Survey not found')
        return redirect('custom_admin:surveys')

    context = {
        'analytics': analytics,
        'survey_id': survey_id
    }

    return render(request, 'admin/survey_analytics.html', context)


@admin_required
def export_analytics_data(request):
    """Export analytics data as JSON or CSV"""

    export_format = request.GET.get('format', 'json')
    report_type = request.GET.get('type', 'overview')
    date_range = int(request.GET.get('days', 30))

    if report_type == 'overview':
        data = ReportsService.generate_executive_summary(date_range)
    elif report_type == 'users':
        data = ReportsService.get_user_analytics(date_range)
    elif report_type == 'surveys':
        data = ReportsService.get_survey_analytics(date_range)
    elif report_type == 'financial':
        data = ReportsService.get_financial_analytics(date_range)
    else:
        data = {'error': 'Invalid report type'}

    if export_format == 'json':
        response = HttpResponse(
            json.dumps(data, default=str, indent=2),
            content_type='application/json'
        )
        response['Content-Disposition'] = f'attachment; filename="{report_type}_analytics.json"'
        return response

    elif export_format == 'csv':
        # For CSV, we'll export a flattened version of key metrics
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{report_type}_analytics.csv"'

        writer = csv.writer(response)

        if report_type == 'overview':
            writer.writerow(['Metric', 'Value'])
            metrics = data['key_metrics']
            for key, value in metrics.items():
                writer.writerow([key.replace('_', ' ').title(), value])

        return response

    return JsonResponse({'error': 'Invalid export format'})


@admin_required
def process_mpesa_withdrawal(request, withdrawal_id):
    """Process M-Pesa withdrawal specifically"""
    try:
        withdrawal = WithdrawalRequest.objects.get(id=withdrawal_id)
    except WithdrawalRequest.DoesNotExist:
        messages.error(request, "Withdrawal request not found.")
        return redirect('custom_admin:withdrawals')

    if request.method == 'POST':
        if withdrawal.payment_method != 'mpesa':
            messages.error(request, "This withdrawal is not for M-Pesa.")
            return redirect('custom_admin:withdrawals')

        try:
            # Import M-Pesa service when it's available
            from payments.services import MPesaService

            # Process M-Pesa withdrawal
            result = MPesaService.process_withdrawal(withdrawal)

            if result['success']:
                messages.success(request,
                                 f"M-Pesa withdrawal processed successfully. Transaction ID: {result.get('transaction_id', 'N/A')}")

                # Update withdrawal status
                withdrawal.status = 'processing'
                withdrawal.processed_by = request.user
                withdrawal.processed_at = timezone.now()
                withdrawal.external_reference = result.get('transaction_id', '')
                withdrawal.save()

            else:
                messages.error(request, f"M-Pesa processing failed: {result.get('error', 'Unknown error')}")

        except ImportError:
            # M-Pesa service not implemented yet - simulate processing
            messages.info(request, "M-Pesa service not fully implemented yet. Marking as processing for testing.")
            withdrawal.status = 'processing'
            withdrawal.processed_by = request.user
            withdrawal.processed_at = timezone.now()
            withdrawal.save()

        except Exception as e:
            messages.error(request, f"Error processing M-Pesa withdrawal: {str(e)}")

    return redirect('custom_admin:withdrawals')


@admin_required
def admin_mpesa_transactions(request):
    """View M-Pesa transactions"""
    from payments.models import MPesaTransaction

    # Get filter parameters
    status_filter = request.GET.get('status', '')
    transaction_type_filter = request.GET.get('type', '')
    search_query = request.GET.get('search', '')

    # Build queryset
    transactions = MPesaTransaction.objects.select_related('user', 'withdrawal_request').all()

    if status_filter:
        transactions = transactions.filter(status=status_filter)
    if transaction_type_filter:
        transactions = transactions.filter(transaction_type=transaction_type_filter)
    if search_query:
        transactions = transactions.filter(
            models.Q(user__username__icontains=search_query) |
            models.Q(phone_number__icontains=search_query) |
            models.Q(mpesa_receipt_number__icontains=search_query)
        )

    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(transactions, 25)
    page_number = request.GET.get('page')
    page_transactions = paginator.get_page(page_number)

    # Get statistics
    stats = {
        'total_transactions': MPesaTransaction.objects.count(),
        'completed_transactions': MPesaTransaction.objects.filter(status='completed').count(),
        'failed_transactions': MPesaTransaction.objects.filter(status='failed').count(),
        'total_amount': MPesaTransaction.objects.filter(status='completed').aggregate(
            total=models.Sum('amount'))['total'] or 0,
    }

    context = {
        'transactions': page_transactions,
        'stats': stats,
        'status_choices': MPesaTransaction.STATUS_CHOICES,
        'type_choices': MPesaTransaction.TRANSACTION_TYPES,
        'current_status': status_filter,
        'current_type': transaction_type_filter,
        'search_query': search_query,
    }

    return render(request, 'admin/mpesa_transactions.html', context)


@admin_required
def delete_user(request, user_id):
    """Delete a user permanently (for testing/development)"""
    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        username = user.username

        try:
            # Delete related data first (if any)
            if hasattr(user, 'transactions'):
                user.transactions.all().delete()
            if hasattr(user, 'survey_responses'):
                user.survey_responses.all().delete()

            # Delete the user
            user.delete()

            messages.success(request, f'User "{username}" has been permanently deleted.')
            # CORRECT: Use 'users' not 'admin_users'
            return redirect('custom_admin:users')

        except Exception as e:
            messages.error(request, f'Error deleting user: {str(e)}')
            # CORRECT: Use 'user_detail' not 'admin_user_detail'
            return redirect('custom_admin:user_detail', user_id=user_id)

    # GET request - show confirmation page
    context = {
        'user': user,
        'title': f'Delete User: {user.username}',
        'related_data': {
            'transactions': getattr(user, 'transactions', User.objects.none()).count(),
            'survey_responses': getattr(user, 'survey_responses', User.objects.none()).count(),
        }
    }

    return render(request, 'admin/delete_user_confirm.html', context)


@admin_required
@require_http_methods(["POST"])
@csrf_exempt
def bulk_delete_users(request):
    """Bulk delete multiple users (AJAX endpoint)"""
    try:
        data = json.loads(request.body.decode('utf-8'))
        user_ids = data.get('user_ids', [])

        if not user_ids:
            return JsonResponse({'status': 'error', 'message': 'No users selected'})

        deleted_count = 0
        errors = []

        for user_id in user_ids:
            try:
                user = User.objects.get(id=user_id)

                # Skip superusers and staff for safety
                if user.is_superuser or user.is_staff:
                    errors.append(f'Cannot delete admin user: {user.username}')
                    continue

                # Delete related data
                user.transactions.all().delete()
                user.survey_responses.all().delete()

                # Delete user
                user.delete()
                deleted_count += 1

            except User.DoesNotExist:
                errors.append(f'User with ID {user_id} not found')
            except Exception as e:
                errors.append(f'Error deleting user {user_id}: {str(e)}')

        return JsonResponse({
            'status': 'success',
            'deleted_count': deleted_count,
            'errors': errors
        })

    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})


@admin_required
def delete_test_users(request):
    """Delete all test users (usernames starting with 'test' or 'opo')"""
    if request.method == 'POST':
        try:
            # Find test users
            test_users = User.objects.filter(
                username__istartswith='test'
            ) | User.objects.filter(
                username__istartswith='opo'
            ) | User.objects.filter(
                email__icontains='test'
            )

            # Exclude admin users
            test_users = test_users.exclude(is_superuser=True).exclude(is_staff=True)

            deleted_count = 0
            for user in test_users:
                # Delete related data safely
                if hasattr(user, 'transactions'):
                    user.transactions.all().delete()
                if hasattr(user, 'survey_responses'):
                    user.survey_responses.all().delete()
                user.delete()
                deleted_count += 1

            messages.success(request, f'Deleted {deleted_count} test users successfully.')

        except Exception as e:
            messages.error(request, f'Error deleting test users: {str(e)}')

        # CORRECT: Use 'users' not 'admin_users'
        return redirect('custom_admin:users')

    # GET request - show confirmation
    test_users = User.objects.filter(
        username__istartswith='test'
    ) | User.objects.filter(
        username__istartswith='opo'
    ) | User.objects.filter(
        email__icontains='test'
    )
    test_users = test_users.exclude(is_superuser=True).exclude(is_staff=True)

    context = {
        'test_users': test_users,
        'title': 'Delete All Test Users'
    }

    return render(request, 'admin/delete_test_users.html', context)


# Add these imports to the top of your custom_admin/views.py file
from accounts.models import SystemSettings, SettingsAuditLog
from accounts.services.settings_service import SettingsService
from decimal import Decimal, InvalidOperation


# Add these settings views to your custom_admin/views.py file
# (Add them after your existing views)

@admin_required
def settings_dashboard(request):
    """Main settings dashboard"""
    # Get all settings grouped by type
    settings_by_type = {}
    for setting in SystemSettings.objects.filter(is_active=True).order_by('setting_type', 'setting_name'):
        if setting.setting_type not in settings_by_type:
            settings_by_type[setting.setting_type] = []
        settings_by_type[setting.setting_type].append(setting)

    # Get recent audit logs
    recent_changes = SettingsAuditLog.objects.select_related('setting', 'changed_by').order_by('-changed_at')[:10]

    context = {
        'settings_by_type': settings_by_type,
        'recent_changes': recent_changes,
        'total_settings': SystemSettings.objects.filter(is_active=True).count(),
    }

    return render(request, 'admin/settings/settings.html', context)


@admin_required
def edit_setting(request, setting_id):
    """Edit a specific setting"""
    setting = get_object_or_404(SystemSettings, id=setting_id)

    if request.method == 'POST':
        try:
            new_value = request.POST.get('value', '').strip()
            change_reason = request.POST.get('reason', '').strip()

            if not new_value:
                messages.error(request, "Value cannot be empty.")
                return redirect('custom_admin:edit_setting', setting_id=setting_id)

            # Convert value based on current setting type
            old_value = setting.get_value()

            if setting.decimal_value is not None or setting.setting_type in ['fee', 'rate']:
                try:
                    converted_value = Decimal(new_value)
                except InvalidOperation:
                    messages.error(request, "Invalid decimal value.")
                    return redirect('custom_admin:edit_setting', setting_id=setting_id)
            elif setting.integer_value is not None or setting.setting_type == 'limit':
                try:
                    converted_value = int(new_value)
                except ValueError:
                    messages.error(request, "Invalid integer value.")
                    return redirect('custom_admin:edit_setting', setting_id=setting_id)
            elif setting.boolean_value is not None:
                converted_value = new_value.lower() in ['true', '1', 'yes', 'on']
            else:
                converted_value = new_value

            # Validate constraints
            if isinstance(converted_value, (int, float, Decimal)):
                if setting.min_value is not None and converted_value < setting.min_value:
                    messages.error(request, f"Value must be at least {setting.min_value}")
                    return redirect('custom_admin:edit_setting', setting_id=setting_id)

                if setting.max_value is not None and converted_value > setting.max_value:
                    messages.error(request, f"Value must not exceed {setting.max_value}")
                    return redirect('custom_admin:edit_setting', setting_id=setting_id)

            # Update the setting
            setting.set_value(converted_value)
            setting.updated_by = request.user
            setting.save()

            # Create audit log
            SettingsAuditLog.objects.create(
                setting=setting,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(converted_value),
                change_reason=change_reason,
                changed_by=request.user,
                ip_address=request.META.get('REMOTE_ADDR')
            )

            # Clear cache
            SettingsService.clear_cache(setting.setting_key)

            messages.success(request, f"Setting '{setting.setting_name}' updated successfully!")
            return redirect('custom_admin:settings_dashboard')

        except Exception as e:
            messages.error(request, f"Error updating setting: {str(e)}")

    context = {
        'setting': setting,
        'current_value': setting.get_value(),
    }

    return render(request, 'admin/settings/edit.html', context)


@admin_required
def quick_edit_settings(request):
    """Quick edit multiple settings via AJAX"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            setting_key = data.get('setting_key')
            new_value = data.get('value')

            if not setting_key or new_value is None:
                return JsonResponse({'success': False, 'error': 'Missing required fields'})

            # Update using SettingsService
            setting = SettingsService.set_setting(
                key=setting_key,
                value=new_value,
                user=request.user,
                reason="Quick edit via admin dashboard"
            )

            return JsonResponse({
                'success': True,
                'message': f"Updated {setting.setting_name}",
                'new_value': str(setting.get_value())
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@admin_required
def reset_to_defaults(request):
    """Reset all settings to default values"""
    if request.method == 'POST':
        try:
            # Force update all existing settings to defaults
            updated_count = 0
            for key, config in SettingsService.DEFAULT_SETTINGS.items():
                setting = SettingsService.set_setting(
                    key=key,
                    value=config['value'],
                    user=request.user,
                    reason="Reset to defaults via admin panel"
                )
                updated_count += 1

            # Clear all cache
            SettingsService.clear_cache()

            messages.success(request, f"Reset {updated_count} settings to default values!")

        except Exception as e:
            messages.error(request, f"Error resetting settings: {str(e)}")

    return redirect('custom_admin:settings_dashboard')


@admin_required
def settings_audit_log(request):
    """View settings audit log"""
    # Get filter parameters
    setting_filter = request.GET.get('setting', '')
    user_filter = request.GET.get('user', '')

    # Build queryset
    logs = SettingsAuditLog.objects.select_related('setting', 'changed_by').order_by('-changed_at')

    if setting_filter:
        logs = logs.filter(setting__setting_name__icontains=setting_filter)

    if user_filter:
        logs = logs.filter(changed_by__username__icontains=user_filter)

    # Pagination
    paginator = Paginator(logs, 25)  # Show 25 logs per page
    page = request.GET.get('page')

    try:
        logs = paginator.page(page)
    except:
        logs = paginator.page(1)

    context = {
        'logs': logs,
        'setting_filter': setting_filter,
        'user_filter': user_filter,
    }

    return render(request, 'admin/settings/audit_log.html', context)


@admin_required
def export_settings(request):
    """Export current settings as JSON"""
    from django.http import HttpResponse
    from datetime import datetime

    # Get all current settings
    settings_data = SettingsService.get_all_settings()

    # Add metadata
    export_data = {
        'exported_at': datetime.now().isoformat(),
        'exported_by': request.user.username,
        'settings': settings_data
    }

    response = HttpResponse(
        json.dumps(export_data, indent=2, default=str),
        content_type='application/json'
    )
    response[
        'Content-Disposition'] = f'attachment; filename="surveyearn_settings_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json"'

    return response


@admin_required
def current_values_api(request):
    """API endpoint to get current setting values for quick reference"""
    # Return commonly used settings for dashboard display
    current_values = {
        'registration_fee': str(SettingsService.get_registration_fee()),
        'referral_commission_rate': str(SettingsService.get_referral_commission_rate()),
        'minimum_withdrawal_amount': str(SettingsService.get_minimum_withdrawal_amount()),
        'survey_base_payment': str(SettingsService.get_survey_base_payment()),
        'auto_approve_referral_commissions': SettingsService.auto_approve_referral_commissions(),
        'max_surveys_per_day': SettingsService.get_max_surveys_per_day(),
    }

    return JsonResponse(current_values)


@admin_required
def initialize_settings(request):
    """Initialize default settings"""
    if request.method == 'POST':
        try:
            created_count = SettingsService.initialize_default_settings(request.user)
            if created_count > 0:
                messages.success(request, f"Created {created_count} new default settings!")
            else:
                messages.info(request, "All default settings already exist.")
        except Exception as e:
            messages.error(request, f"Error initializing settings: {str(e)}")

    return redirect('custom_admin:settings_dashboard')


from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDay, TruncMonth
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import json

# Imports based on your models
from accounts.models import User, SystemSettings
from payments.models import Transaction
from surveys.models import Survey, Response

# Try to import settings service
try:
    from accounts.services.settings_service import SettingsService
except ImportError:
    SettingsService = None


@staff_member_required
def financial_analytics_dashboard(request):
    """
    Professional financial analytics dashboard with revenue and expense tracking
    """
    # Date ranges
    today = timezone.now().date()
    last_30_days = today - timedelta(days=30)
    last_7_days = today - timedelta(days=7)
    current_month_start = today.replace(day=1)
    last_month_start = (current_month_start - timedelta(days=1)).replace(day=1)

    # Basic metrics
    total_users = User.objects.filter(is_staff=False).count()
    active_users_30d = User.objects.filter(
        is_staff=False,
        last_login__gte=timezone.now() - timedelta(days=30)
    ).count()
    total_transactions = Transaction.objects.count()

    # FIXED: REVENUE STREAMS - Use actual transaction data
    registration_fees_revenue = Transaction.objects.filter(
        transaction_type='registration_fee'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # Service fees from positive adjustments and negative bonuses
    positive_adjustments = Transaction.objects.filter(
        transaction_type='adjustment',
        amount__gt=0
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    negative_bonuses = Transaction.objects.filter(
        transaction_type='bonus',
        amount__lt=0
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    service_fees_revenue = positive_adjustments + abs(negative_bonuses)

    revenue_streams = {
        'registration_fees': registration_fees_revenue,
        'service_fees': service_fees_revenue,
        'total': registration_fees_revenue + service_fees_revenue
    }

    # FIXED: OPERATING EXPENSES - Use actual transaction data
    survey_compensation = Transaction.objects.filter(
        transaction_type='survey_payment'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # Referral commissions from actual transactions
    referral_commissions = Transaction.objects.filter(
        transaction_type='referral_commission'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    user_withdrawals = Transaction.objects.filter(
        transaction_type='withdrawal'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    operating_expenses = {
        'survey_compensation': survey_compensation,
        'referral_commissions': referral_commissions,
        'user_withdrawals': user_withdrawals,
        'total': survey_compensation + referral_commissions + user_withdrawals
    }

    # FINANCIAL PERFORMANCE METRICS
    total_revenue = revenue_streams['total']
    total_expenses = operating_expenses['total']
    net_profit = total_revenue - total_expenses

    if total_revenue > 0:
        profit_margin = float(net_profit / total_revenue * 100)
        expense_ratio = float(total_expenses / total_revenue * 100)
    else:
        profit_margin = 0.0
        expense_ratio = 0.0

    # Outstanding liabilities
    total_user_balances = User.objects.filter(
        is_staff=False,
        balance__isnull=False
    ).aggregate(total=Sum('balance'))['total'] or Decimal('0')

    pending_withdrawals = Transaction.objects.filter(
        transaction_type='withdrawal',
        created_at__gte=last_7_days
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    outstanding_liabilities = total_user_balances + pending_withdrawals

    # FIXED: CURRENT MONTH PERFORMANCE - Use transaction data
    current_month_registration_revenue = Transaction.objects.filter(
        transaction_type='registration_fee',
        created_at__gte=current_month_start
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    current_month_paid_users = Transaction.objects.filter(
        transaction_type='registration_fee',
        created_at__gte=current_month_start
    ).count()

    # Current month service fees
    current_month_positive_adj = Transaction.objects.filter(
        created_at__gte=current_month_start,
        transaction_type='adjustment',
        amount__gt=0
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    current_month_negative_bonus = Transaction.objects.filter(
        created_at__gte=current_month_start,
        transaction_type='bonus',
        amount__lt=0
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    current_month_service_fees = current_month_positive_adj + abs(current_month_negative_bonus)

    # Current month expenses - use transaction data
    current_month_survey_comp = Transaction.objects.filter(
        created_at__gte=current_month_start,
        transaction_type='survey_payment'
    ).aggregate(
        total=Sum('amount'),
        count=Count('id')
    )

    current_month_withdrawals = Transaction.objects.filter(
        created_at__gte=current_month_start,
        transaction_type='withdrawal'
    ).aggregate(
        total=Sum('amount'),
        count=Count('id')
    )

    current_month_referral_commissions = Transaction.objects.filter(
        created_at__gte=current_month_start,
        transaction_type='referral_commission'
    ).aggregate(
        total=Sum('amount'),
        count=Count('id')
    )

    current_month_stats = {
        'registration_revenue': current_month_registration_revenue,
        'service_fees': current_month_service_fees,
        'survey_compensation': current_month_survey_comp['total'] or Decimal('0'),
        'referral_commissions': current_month_referral_commissions['total'] or Decimal('0'),
        'user_withdrawals': current_month_withdrawals['total'] or Decimal('0'),
        'new_registrations': current_month_paid_users,
        'survey_responses': current_month_survey_comp['count'] or 0,
        'withdrawal_count': current_month_withdrawals['count'] or 0,
        'referral_count': current_month_referral_commissions['count'] or 0,
    }

    current_month_stats['total_revenue'] = (
            current_month_stats['registration_revenue'] +
            current_month_stats['service_fees']
    )
    current_month_stats['total_expenses'] = (
            current_month_stats['survey_compensation'] +
            current_month_stats['referral_commissions'] +
            current_month_stats['user_withdrawals']
    )

    # FIXED: GROWTH METRICS - Use transaction data
    current_month_revenue = current_month_stats['total_revenue']

    last_month_registration_revenue = Transaction.objects.filter(
        transaction_type='registration_fee',
        created_at__gte=last_month_start,
        created_at__lt=current_month_start
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    last_month_pos_adj = Transaction.objects.filter(
        created_at__gte=last_month_start,
        created_at__lt=current_month_start,
        transaction_type='adjustment',
        amount__gt=0
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    last_month_neg_bonus = Transaction.objects.filter(
        created_at__gte=last_month_start,
        created_at__lt=current_month_start,
        transaction_type='bonus',
        amount__lt=0
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    last_month_service_revenue = last_month_pos_adj + abs(last_month_neg_bonus)
    last_month_revenue = last_month_registration_revenue + last_month_service_revenue

    if last_month_revenue > 0:
        revenue_growth = float((current_month_revenue - last_month_revenue) / last_month_revenue * 100)
    else:
        revenue_growth = 0.0

    # FIXED: DAILY REVENUE & EXPENSE DATA - Use transaction data
    revenue_expense_data = []
    for i in range(30):
        day = today - timedelta(days=29 - i)
        day_start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
        day_end = day_start + timedelta(days=1)

        # Daily registration revenue from actual transactions
        daily_registration_revenue = Transaction.objects.filter(
            transaction_type='registration_fee',
            created_at__gte=day_start,
            created_at__lt=day_end
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # Daily service fees
        daily_pos_adj = Transaction.objects.filter(
            created_at__gte=day_start,
            created_at__lt=day_end,
            transaction_type='adjustment',
            amount__gt=0
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        daily_neg_bonus = Transaction.objects.filter(
            created_at__gte=day_start,
            created_at__lt=day_end,
            transaction_type='bonus',
            amount__lt=0
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        daily_service_revenue = daily_pos_adj + abs(daily_neg_bonus)
        daily_revenue = daily_registration_revenue + daily_service_revenue

        # Daily expenses from actual transactions
        daily_survey = Transaction.objects.filter(
            created_at__gte=day_start,
            created_at__lt=day_end,
            transaction_type='survey_payment'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        daily_withdraw = Transaction.objects.filter(
            created_at__gte=day_start,
            created_at__lt=day_end,
            transaction_type='withdrawal'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        daily_referral_commission = Transaction.objects.filter(
            created_at__gte=day_start,
            created_at__lt=day_end,
            transaction_type='referral_commission'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        daily_expenses = daily_survey + daily_withdraw + daily_referral_commission

        revenue_expense_data.append({
            'date': day.isoformat(),
            'revenue': float(daily_revenue),
            'expenses': float(daily_expenses),
            'profit': float(daily_revenue - daily_expenses)
        })

    # FIXED: CHART DATA - Use transaction data
    monthly_revenue = []
    for i in range(12):
        month_start = (current_month_start - timedelta(days=32 * i)).replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        month_registration_revenue = Transaction.objects.filter(
            transaction_type='registration_fee',
            created_at__gte=month_start,
            created_at__lte=month_end
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        month_registrations = Transaction.objects.filter(
            transaction_type='registration_fee',
            created_at__gte=month_start,
            created_at__lte=month_end
        ).count()

        month_pos_adj = Transaction.objects.filter(
            created_at__gte=month_start,
            created_at__lte=month_end,
            transaction_type='adjustment',
            amount__gt=0
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        month_neg_bonus = Transaction.objects.filter(
            created_at__gte=month_start,
            created_at__lte=month_end,
            transaction_type='bonus',
            amount__lt=0
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        month_service = month_pos_adj + abs(month_neg_bonus)
        month_revenue = month_registration_revenue + month_service

        monthly_revenue.append({
            'month': month_start,
            'total': month_revenue,
            'count': month_registrations
        })

    monthly_revenue.reverse()

    # Daily transactions
    daily_transactions = Transaction.objects.filter(
        created_at__gte=last_30_days
    ).annotate(
        day=TruncDay('created_at')
    ).values('day').annotate(
        survey_payments=Count('id', filter=Q(transaction_type='survey_payment')),
        withdrawals=Count('id', filter=Q(transaction_type='withdrawal')),
        adjustments=Count('id', filter=Q(transaction_type='adjustment')),
        bonuses=Count('id', filter=Q(transaction_type='bonus')),
        registration_fees=Count('id', filter=Q(transaction_type='registration_fee')),
        referral_commissions=Count('id', filter=Q(transaction_type='referral_commission'))
    ).order_by('day')

    # Survey metrics
    survey_metrics = {
        'total_responses': Response.objects.filter(completed_at__gte=last_30_days).count(),
        'total_payout': Response.objects.filter(
            completed_at__gte=last_30_days
        ).aggregate(total=Sum('payout_amount'))['total'] or Decimal('0')
    }

    # Top surveys
    top_surveys = Survey.objects.annotate(
        response_count=Count('responses'),
        total_paid=Sum('responses__payout_amount')
    ).order_by('-response_count')[:5]

    # Dynamic balance distribution based on system settings
    try:
        if SettingsService:
            settings_service = SettingsService()
            min_withdrawal = settings_service.get_setting('minimum_withdrawal_amount') or 100
        else:
            min_withdrawal = SystemSettings.get_setting('minimum_withdrawal_amount', 100)
    except:
        min_withdrawal = 100

    user_balances = User.objects.filter(is_staff=False).values_list('balance', flat=True)
    user_balances_filtered = [b for b in user_balances if b is not None]

    # Create dynamic balance ranges based on minimum withdrawal
    range_1 = min_withdrawal // 2  # Half of minimum withdrawal
    range_2 = min_withdrawal  # Minimum withdrawal amount
    range_3 = min_withdrawal * 2  # Double minimum withdrawal

    balance_ranges = {
        f'KES 0-{range_1}': len([b for b in user_balances_filtered if 0 <= b <= range_1]),
        f'KES {range_1+1}-{range_2}': len([b for b in user_balances_filtered if range_1 < b <= range_2]),
        f'KES {range_2+1}-{range_3}': len([b for b in user_balances_filtered if range_2 < b <= range_3]),
        f'KES {range_3+1}+': len([b for b in user_balances_filtered if b > range_3])
    }

    # High-value transactions
    high_value_transactions = Transaction.objects.filter(
        created_at__gte=last_7_days,
        amount__gte=100
    ).select_related('user').order_by('-amount')[:10]

    # System settings - get actual values from your system
    try:
        if SettingsService:
            settings_service = SettingsService()
            system_settings = {
                'registration_fee': settings_service.get_registration_fee(),
                'survey_base_payment': settings_service.get_setting('survey_base_payment'),
                'referral_commission_rate': float(settings_service.get_referral_commission_rate() * 100),  # Convert to percentage
                'minimum_withdrawal_amount': settings_service.get_setting('minimum_withdrawal_amount')
            }
        else:
            system_settings = {
                'registration_fee': SystemSettings.get_setting('registration_fee'),
                'survey_base_payment': SystemSettings.get_setting('survey_base_payment'),
                'referral_commission_rate': float(SystemSettings.get_setting('referral_commission_rate', 0.5) * 100),
                'minimum_withdrawal_amount': SystemSettings.get_setting('minimum_withdrawal_amount')
            }
    except Exception:
        # Only fallback if settings can't be loaded at all
        system_settings = {
            'registration_fee': 'Not configured',
            'survey_base_payment': 'Not configured',
            'referral_commission_rate': 'Not configured',
            'minimum_withdrawal_amount': 'Not configured'
        }

    context = {
        # Financial metrics
        'revenue_streams': revenue_streams,
        'operating_expenses': operating_expenses,
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        'expense_ratio': expense_ratio,
        'outstanding_liabilities': outstanding_liabilities,

        # Growth metrics
        'revenue_growth': revenue_growth,
        'current_month_revenue': current_month_revenue,
        'last_month_revenue': last_month_revenue,

        # Current month stats
        'current_month_stats': current_month_stats,
        'current_month': current_month_start.strftime('%B %Y'),

        # Chart data
        'revenue_expense_data': json.dumps(revenue_expense_data),
        'monthly_revenue_data': json.dumps(monthly_revenue, default=str),
        'daily_transactions_data': json.dumps(list(daily_transactions), default=str),

        # Basic metrics
        'total_users': total_users,
        'active_users_30d': active_users_30d,
        'total_transactions': total_transactions,
        'total_user_balances': total_user_balances,
        'pending_withdrawals': pending_withdrawals,

        'survey_metrics': survey_metrics,
        'top_surveys': top_surveys,
        'balance_ranges': balance_ranges,
        'high_value_transactions': high_value_transactions,
        'system_settings': system_settings,

        'date_ranges': {
            'today': today,
            'last_30_days': last_30_days,
            'last_7_days': last_7_days,
            'current_month_start': current_month_start
        }
    }

    return render(request, 'admin/financial_analytics.html', context)


@staff_member_required
def financial_analytics_api(request):
    """
    API endpoint for financial data updates - fully dynamic, no hardcoded values
    """
    metric = request.GET.get('metric', 'overview')

    if metric == 'overview':
        try:
            # FIXED: Revenue calculation using actual transactions (no hardcoded values)
            registration_revenue = Transaction.objects.filter(
                transaction_type='registration_fee'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            # Service fees from positive adjustments and negative bonuses
            positive_adj = Transaction.objects.filter(
                transaction_type='adjustment',
                amount__gt=0
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            negative_bonus = Transaction.objects.filter(
                transaction_type='bonus',
                amount__lt=0
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            service_fees = positive_adj + abs(negative_bonus)
            total_revenue = registration_revenue + service_fees

            # FIXED: Expenses using actual transactions (no hardcoded calculations)
            survey_compensation = Transaction.objects.filter(
                transaction_type='survey_payment'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            # Use actual referral commission transactions
            referral_commissions = Transaction.objects.filter(
                transaction_type='referral_commission'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            user_withdrawals = Transaction.objects.filter(
                transaction_type='withdrawal'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            total_expenses = survey_compensation + referral_commissions + user_withdrawals
            net_profit = total_revenue - total_expenses

            profit_margin = float(net_profit / total_revenue * 100) if total_revenue > 0 else 0.0

            # Outstanding liabilities
            total_user_balances = User.objects.filter(
                is_staff=False,
                balance__isnull=False
            ).aggregate(total=Sum('balance'))['total'] or Decimal('0')

            active_users = User.objects.filter(
                is_staff=False,
                last_login__gte=timezone.now() - timedelta(days=30)
            ).count()

            return JsonResponse({
                'revenue_streams': {
                    'registration_fees': float(registration_revenue),
                    'service_fees': float(service_fees),
                    'total': float(total_revenue)
                },
                'operating_expenses': {
                    'survey_compensation': float(survey_compensation),
                    'referral_commissions': float(referral_commissions),
                    'user_withdrawals': float(user_withdrawals),
                    'total': float(total_expenses)
                },
                'total_revenue': float(total_revenue),
                'total_expenses': float(total_expenses),
                'net_profit': float(net_profit),
                'profit_margin': profit_margin,
                'outstanding_liabilities': float(total_user_balances),
                'active_users': active_users,
                'last_updated': timezone.now().isoformat()
            })

        except Exception as e:
            return JsonResponse({
                'error': f'Error: {str(e)}',
                'total_revenue': 0.0,
                'total_expenses': 0.0,
                'net_profit': 0.0,
                'profit_margin': 0.0,
                'last_updated': timezone.now().isoformat()
            }, status=500)

    elif metric == 'daily_trend':
        try:
            last_7_days = timezone.now().date() - timedelta(days=7)

            # Get detailed daily breakdown by transaction type
            daily_data = Transaction.objects.filter(
                created_at__gte=last_7_days
            ).annotate(
                day=TruncDay('created_at')
            ).values('day').annotate(
                # Revenue streams
                registration_revenue=Sum('amount', filter=Q(transaction_type='registration_fee')),
                service_fees=Sum('amount', filter=Q(transaction_type='adjustment', amount__gt=0)) +
                             Sum('amount', filter=Q(transaction_type='bonus', amount__lt=0)),

                # Expense streams
                survey_payments=Sum('amount', filter=Q(transaction_type='survey_payment')),
                referral_commissions=Sum('amount', filter=Q(transaction_type='referral_commission')),
                withdrawals=Sum('amount', filter=Q(transaction_type='withdrawal')),

                # Transaction counts
                total_transactions=Count('id'),
                registration_count=Count('id', filter=Q(transaction_type='registration_fee')),
                survey_count=Count('id', filter=Q(transaction_type='survey_payment')),
                withdrawal_count=Count('id', filter=Q(transaction_type='withdrawal')),
                commission_count=Count('id', filter=Q(transaction_type='referral_commission'))
            ).order_by('day')

            daily_data_list = []
            for item in daily_data:
                daily_revenue = (item['registration_revenue'] or Decimal('0')) + (item['service_fees'] or Decimal('0'))
                daily_expenses = (
                        (item['survey_payments'] or Decimal('0')) +
                        (item['referral_commissions'] or Decimal('0')) +
                        (item['withdrawals'] or Decimal('0'))
                )

                daily_data_list.append({
                    'day': item['day'],
                    'revenue': {
                        'registration': float(item['registration_revenue'] or Decimal('0')),
                        'service_fees': float(item['service_fees'] or Decimal('0')),
                        'total': float(daily_revenue)
                    },
                    'expenses': {
                        'surveys': float(item['survey_payments'] or Decimal('0')),
                        'commissions': float(item['referral_commissions'] or Decimal('0')),
                        'withdrawals': float(item['withdrawals'] or Decimal('0')),
                        'total': float(daily_expenses)
                    },
                    'net_profit': float(daily_revenue - daily_expenses),
                    'transaction_counts': {
                        'total': item['total_transactions'] or 0,
                        'registrations': item['registration_count'] or 0,
                        'surveys': item['survey_count'] or 0,
                        'withdrawals': item['withdrawal_count'] or 0,
                        'commissions': item['commission_count'] or 0
                    }
                })

            return JsonResponse({
                'daily_data': daily_data_list,
                'last_updated': timezone.now().isoformat()
            }, default=str)

        except Exception as e:
            return JsonResponse({
                'error': f'Error: {str(e)}',
                'daily_data': [],
                'last_updated': timezone.now().isoformat()
            }, status=500)

    elif metric == 'real_time':
        try:
            # Get current system settings dynamically
            try:
                if SettingsService:
                    settings_service = SettingsService()
                    current_settings = {
                        'registration_fee': float(settings_service.get_registration_fee()),
                        'commission_rate': float(settings_service.get_referral_commission_rate() * 100),
                        'min_withdrawal': float(settings_service.get_setting('minimum_withdrawal_amount') or 100)
                    }
                else:
                    current_settings = {
                        'registration_fee': float(SystemSettings.get_setting('registration_fee') or 0),
                        'commission_rate': float(SystemSettings.get_setting('referral_commission_rate', 0) * 100),
                        'min_withdrawal': float(SystemSettings.get_setting('minimum_withdrawal_amount') or 100)
                    }
            except:
                current_settings = {
                    'registration_fee': 0,
                    'commission_rate': 0,
                    'min_withdrawal': 0
                }

            # Get recent activity (last hour)
            last_hour = timezone.now() - timedelta(hours=1)
            recent_activity = Transaction.objects.filter(
                created_at__gte=last_hour
            ).values('transaction_type').annotate(
                count=Count('id'),
                total_amount=Sum('amount')
            )

            return JsonResponse({
                'current_settings': current_settings,
                'recent_activity': list(recent_activity),
                'active_users_now': User.objects.filter(
                    last_login__gte=timezone.now() - timedelta(minutes=30)
                ).count(),
                'last_updated': timezone.now().isoformat()
            }, default=str)

        except Exception as e:
            return JsonResponse({
                'error': f'Error: {str(e)}',
                'last_updated': timezone.now().isoformat()
            }, status=500)

    return JsonResponse({'error': 'Invalid metric'}, status=400)

# Add these imports to your views.py
from django.shortcuts import redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from decimal import Decimal, InvalidOperation
import csv
from django.http import HttpResponse


@staff_member_required
def manual_transaction(request):
    """
    Create manual transactions (adjustments, bonuses, corrections)
    """
    if request.method == 'POST':
        try:
            # Get form data
            user_id = request.POST.get('user_id')
            transaction_type = request.POST.get('transaction_type')
            amount = request.POST.get('amount')
            description = request.POST.get('description', '')

            # Validation
            if not all([user_id, transaction_type, amount]):
                messages.error(request, 'All fields are required.')
                return redirect('custom_admin:manual_transaction')

            # Get user
            try:
                user = User.objects.get(id=user_id, is_staff=False)
            except User.DoesNotExist:
                messages.error(request, 'User not found.')
                return redirect('custom_admin:manual_transaction')

            # Parse amount
            try:
                amount = Decimal(str(amount))
            except (InvalidOperation, ValueError):
                messages.error(request, 'Invalid amount format.')
                return redirect('custom_admin:manual_transaction')

            # Validate transaction type
            valid_types = ['adjustment', 'bonus', 'correction']
            if transaction_type not in valid_types:
                messages.error(request, 'Invalid transaction type.')
                return redirect('custom_admin:manual_transaction')

            # Create transaction
            transaction = Transaction.objects.create(
                user=user,
                transaction_type=transaction_type,
                amount=amount,
                description=f"Manual {transaction_type}: {description}" if description else f"Manual {transaction_type}",
                # Add any other required fields based on your Transaction model
            )

            # Update user balance if it's a positive adjustment or bonus
            if amount > 0 and transaction_type in ['adjustment', 'bonus']:
                user.balance = (user.balance or Decimal('0')) + amount
                user.save()
            elif amount < 0 and transaction_type == 'adjustment':
                # Negative adjustment - deduct from balance
                current_balance = user.balance or Decimal('0')
                if current_balance + amount >= 0:  # amount is negative
                    user.balance = current_balance + amount
                    user.save()
                else:
                    messages.warning(request,
                                     f'Transaction created but user balance would go negative. Current balance: KES {current_balance}')

            messages.success(
                request,
                f'Manual {transaction_type} of KES {amount} created for {user.username}. Transaction ID: {transaction.id}'
            )

        except Exception as e:
            messages.error(request, f'Error creating transaction: {str(e)}')

        return redirect('custom_admin:manual_transaction')

    # GET request - show form
    context = {
        'page_title': 'Manual Transactions',
        'page_description': 'Create manual financial adjustments, bonuses, and corrections',
    }

    return render(request, 'admin/manual_transaction.html', context)


@staff_member_required
def transaction_search_users(request):
    """
    AJAX endpoint for user search in manual transaction form
    """
    query = request.GET.get('q', '').strip()

    if len(query) < 2:
        return JsonResponse({'users': []})

    # Search users by username, email, or phone
    users = User.objects.filter(
        is_staff=False
    ).filter(
        Q(username__icontains=query) |
        Q(email__icontains=query) |
        Q(phone_number__icontains=query)
    )[:10]  # Limit to 10 results

    user_data = []
    for user in users:
        user_data.append({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'phone_number': user.phone_number or 'N/A',
            'balance': float(user.balance or Decimal('0')),
            'display': f"{user.username} ({user.email}) - Balance: KES {user.balance or 0}"
        })

    return JsonResponse({'users': user_data})


@staff_member_required
def export_transactions_csv(request):
    """
    Export transactions to CSV with filters
    """
    # Get filter parameters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    transaction_type = request.GET.get('transaction_type')
    user_id = request.GET.get('user_id')
    min_amount = request.GET.get('min_amount')
    max_amount = request.GET.get('max_amount')

    # Build query
    transactions = Transaction.objects.select_related('user').all()

    # Apply filters
    if start_date:
        try:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            transactions = transactions.filter(created_at__date__gte=start_date)
        except ValueError:
            pass

    if end_date:
        try:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            transactions = transactions.filter(created_at__date__lte=end_date)
        except ValueError:
            pass

    if transaction_type and transaction_type != 'all':
        transactions = transactions.filter(transaction_type=transaction_type)

    if user_id:
        try:
            user_id = int(user_id)
            transactions = transactions.filter(user_id=user_id)
        except (ValueError, TypeError):
            pass

    if min_amount:
        try:
            min_amount = Decimal(str(min_amount))
            transactions = transactions.filter(amount__gte=min_amount)
        except (InvalidOperation, ValueError):
            pass

    if max_amount:
        try:
            max_amount = Decimal(str(max_amount))
            transactions = transactions.filter(amount__lte=max_amount)
        except (InvalidOperation, ValueError):
            pass

    # Order by most recent first
    transactions = transactions.order_by('-created_at')

    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    filename = f'transactions_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    # Write header
    writer.writerow([
        'Transaction ID',
        'User ID',
        'Username',
        'Email',
        'Phone Number',
        'Transaction Type',
        'Amount (KES)',
        'Description',
        'Created At',
        'Status'
    ])

    # Write data
    for transaction in transactions:
        writer.writerow([
            transaction.id,
            transaction.user.id if transaction.user else 'N/A',
            transaction.user.username if transaction.user else 'N/A',
            transaction.user.email if transaction.user else 'N/A',
            transaction.user.phone_number if transaction.user and transaction.user.phone_number else 'N/A',
            transaction.transaction_type,
            float(transaction.amount),
            transaction.description or 'N/A',
            transaction.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            getattr(transaction, 'status', 'completed')  # Add status field if it exists
        ])

    return response


@staff_member_required
def transaction_detail_modal(request, transaction_id):
    """
    AJAX endpoint for transaction detail modal
    """
    try:
        transaction = get_object_or_404(Transaction.objects.select_related('user'), id=transaction_id)

        # Get related transactions for this user (last 5)
        related_transactions = Transaction.objects.filter(
            user=transaction.user
        ).exclude(id=transaction_id).order_by('-created_at')[:5]

        data = {
            'transaction': {
                'id': transaction.id,
                'user': {
                    'id': transaction.user.id if transaction.user else None,
                    'username': transaction.user.username if transaction.user else 'N/A',
                    'email': transaction.user.email if transaction.user else 'N/A',
                    'phone_number': transaction.user.phone_number if transaction.user else 'N/A',
                    'balance': float(transaction.user.balance or Decimal('0')) if transaction.user else 0,
                    'registration_paid': transaction.user.registration_paid if transaction.user else False,
                },
                'transaction_type': transaction.transaction_type,
                'amount': float(transaction.amount),
                'description': transaction.description or 'N/A',
                'created_at': transaction.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'status': getattr(transaction, 'status', 'completed'),
            },
            'related_transactions': [
                {
                    'id': t.id,
                    'transaction_type': t.transaction_type,
                    'amount': float(t.amount),
                    'created_at': t.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'description': t.description or 'N/A'
                }
                for t in related_transactions
            ]
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# Enhanced transactions view to replace your existing one

@staff_member_required
def transactions(request):
    """
    Enhanced transaction management with filtering, search, and statistics
    ALIGNED: Now uses same calculation logic as financial analytics dashboard
    """
    # Get filter parameters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    transaction_type = request.GET.get('transaction_type')
    user_search = request.GET.get('user_search')
    min_amount = request.GET.get('min_amount')
    max_amount = request.GET.get('max_amount')
    sort = request.GET.get('sort', '-created_at')

    # Base queryset
    transactions_qs = Transaction.objects.select_related('user').all()

    # Apply filters
    if start_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            transactions_qs = transactions_qs.filter(created_at__date__gte=start_date_obj)
        except ValueError:
            pass

    if end_date:
        try:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            transactions_qs = transactions_qs.filter(created_at__date__lte=end_date_obj)
        except ValueError:
            pass

    if transaction_type and transaction_type != 'all':
        transactions_qs = transactions_qs.filter(transaction_type=transaction_type)

    if user_search:
        transactions_qs = transactions_qs.filter(
            Q(user__username__icontains=user_search) |
            Q(user__email__icontains=user_search) |
            Q(user__phone_number__icontains=user_search)
        )

    if min_amount:
        try:
            min_amount_val = Decimal(str(min_amount))
            transactions_qs = transactions_qs.filter(amount__gte=min_amount_val)
        except (InvalidOperation, ValueError):
            pass

    if max_amount:
        try:
            max_amount_val = Decimal(str(max_amount))
            transactions_qs = transactions_qs.filter(amount__lte=max_amount_val)
        except (InvalidOperation, ValueError):
            pass

    # Apply sorting
    valid_sorts = ['id', '-id', 'amount', '-amount', 'created_at', '-created_at']
    if sort in valid_sorts:
        transactions_qs = transactions_qs.order_by(sort)
    else:
        transactions_qs = transactions_qs.order_by('-created_at')

    # ALIGNED: Calculate statistics using same logic as financial analytics dashboard

    # REVENUE CALCULATION - Same as financial analytics
    # Registration fees: paid users × registration fee setting
    paid_users = User.objects.filter(registration_paid=True).count()
    try:
        from accounts.services.settings_service import SettingsService
        settings_service = SettingsService()
        avg_registration_fee = settings_service.get_registration_fee()
    except:
        avg_registration_fee = SystemSettings.get_setting('registration_fee', 500)

    registration_fees_revenue = paid_users * Decimal(str(avg_registration_fee))

    # Service fees from transactions (same as financial analytics)
    positive_adjustments = Transaction.objects.filter(
        transaction_type='adjustment',
        amount__gt=0
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    negative_bonuses = Transaction.objects.filter(
        transaction_type='bonus',
        amount__lt=0
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    service_fees_revenue = positive_adjustments + abs(negative_bonuses)

    # Total inflow
    total_inflow = registration_fees_revenue + service_fees_revenue

    # EXPENSE CALCULATION - Same as financial analytics
    # Survey compensation
    survey_compensation = Transaction.objects.filter(
        transaction_type='survey_payment'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # FIXED: Referral commissions from actual referral_commission transactions
    referral_commissions = Transaction.objects.filter(
        transaction_type='referral_commission'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # User withdrawals
    user_withdrawals = Transaction.objects.filter(
        transaction_type='withdrawal'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # Total outflow
    total_outflow = abs(survey_compensation) + abs(referral_commissions) + abs(user_withdrawals)

    # Net flow = revenue - expenses
    net_flow = total_inflow - total_outflow

    # Total transaction count
    total_transactions = transactions_qs.count()

    # Transaction type breakdown for insights
    transaction_breakdown = transactions_qs.values('transaction_type').annotate(
        count=Count('id'),
        total_amount=Sum('amount')
    ).order_by('-total_amount')

    # Pagination
    paginator = Paginator(transactions_qs, 50)
    page_number = request.GET.get('page')
    transactions_page = paginator.get_page(page_number)

    context = {
        'transactions': transactions_page,
        'total_transactions': total_transactions,
        'total_inflow': total_inflow,
        'total_outflow': total_outflow,
        'net_flow': net_flow,
        'transaction_breakdown': transaction_breakdown,
        'page_title': 'Transaction Management',
        'page_description': 'Comprehensive transaction history with advanced filtering and export capabilities',

        # Additional context for detailed breakdown
        'revenue_breakdown': {
            'registration_fees': registration_fees_revenue,
            'service_fees': service_fees_revenue,
            'paid_users_count': paid_users,
            'avg_registration_fee': avg_registration_fee,
        },
        'expense_breakdown': {
            'survey_compensation': abs(survey_compensation),
            'referral_commissions': abs(referral_commissions),
            'user_withdrawals': abs(user_withdrawals),
        },

        # For maintaining filter state in pagination links
        'current_filters': {
            'start_date': start_date,
            'end_date': end_date,
            'transaction_type': transaction_type,
            'user_search': user_search,
            'min_amount': min_amount,
            'max_amount': max_amount,
            'sort': sort,
        }
    }

    return render(request, 'admin/transactions.html', context)


# custom_admin/views.py (add these functions - FINAL FINAL CORRECTED VERSION)
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Count, Avg, Sum, Q
from django.core.paginator import Paginator
from django.utils import timezone

from django.views.decorators.csrf import csrf_exempt
from datetime import datetime, timedelta
from django.db import transaction
from django.views.decorators.http import require_http_methods
from django.urls import reverse
import json
import subprocess
import json as json_lib
import requests
import os

# Import tutorial models
from tutorials.models import (
    TutorialCategory, Tutorial, QuizQuestion, QuizAnswer,
    UserTutorialProgress, UserQuizAttempt, UserQuizAnswer
)


def is_admin(user):
    """Check if user is admin - adjust this to match your existing admin check"""
    return user.is_staff or user.is_superuser


def get_video_duration_from_file(video_file):
    """Get duration from uploaded video file using ffprobe"""
    try:
        # Save the uploaded file temporarily to get its path
        temp_path = video_file.temporary_file_path()

        # Use ffprobe to get video duration
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', temp_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            data = json_lib.loads(result.stdout)
            if 'format' in data and 'duration' in data['format']:
                duration = float(data['format']['duration'])
                return timedelta(seconds=int(duration))
    except Exception as e:
        pass  # Or add logging: logger.error(f"Error getting video duration: {e}")

    return None


def get_youtube_duration(video_url):
    """Get duration from YouTube URL - basic implementation"""
    try:
        # This is a simplified version - for full implementation you'd need YouTube Data API
        # For now, we'll return None and let the user set duration manually
        return None
    except Exception as e:
        pass  # Handle any exceptions gracefully

    return None

# Tutorial Management Views
@user_passes_test(is_admin)
def tutorials_dashboard(request):
    """Tutorial management dashboard"""
    # Basic statistics - ALL FIELD NAMES CORRECTED
    stats = {
        'total_tutorials': Tutorial.objects.count(),
        'active_tutorials': Tutorial.objects.filter(is_published=True).count(),
        'total_categories': TutorialCategory.objects.count(),
        'active_categories': TutorialCategory.objects.filter(is_active=True).count(),
        'total_learners': UserTutorialProgress.objects.values('user').distinct().count(),
        'completed_tutorials': UserTutorialProgress.objects.filter(is_completed=True).count(),
        'total_quiz_attempts': UserQuizAttempt.objects.count(),
        'passed_quizzes': UserQuizAttempt.objects.filter(is_passed=True).count(),
    }

    # Calculate rates
    if stats['total_learners'] > 0:
        stats['completion_rate'] = round((stats['completed_tutorials'] / stats['total_learners']) * 100, 1)
    else:
        stats['completion_rate'] = 0

    if stats['total_quiz_attempts'] > 0:
        stats['quiz_pass_rate'] = round((stats['passed_quizzes'] / stats['total_quiz_attempts']) * 100, 1)
    else:
        stats['quiz_pass_rate'] = 0

    # Recent activity (last 7 days)
    week_ago = timezone.now() - timedelta(days=7)
    recent_completions = UserTutorialProgress.objects.filter(
        is_completed=True,
        updated_at__gte=week_ago
    ).select_related('user', 'tutorial').order_by('-updated_at')[:10]

    # Popular tutorials
    popular_tutorials = Tutorial.objects.annotate(
        completion_count=Count('user_progress', filter=Q(user_progress__is_completed=True))
    ).order_by('-completion_count')[:5]

    # Category performance
    category_stats = TutorialCategory.objects.annotate(
        tutorial_count=Count('tutorials'),
        completion_count=Count('tutorials__user_progress', filter=Q(tutorials__user_progress__is_completed=True))
    ).filter(is_active=True)

    context = {
        'stats': stats,
        'recent_completions': recent_completions,
        'popular_tutorials': popular_tutorials,
        'category_stats': category_stats,
        'page_title': 'Tutorial Management Dashboard'
    }

    return render(request, 'admin/tutorials_dashboard.html', context)


@user_passes_test(is_admin)
def tutorials_list(request):
    """List all tutorials with filtering"""
    tutorials = Tutorial.objects.select_related('category').annotate(
        completion_count=Count('user_progress', filter=Q(user_progress__is_completed=True)),
        avg_quiz_score=Avg('quiz_attempts__score_percentage')
    ).order_by('-created_at')

    # Filtering
    category_id = request.GET.get('category')
    if category_id:
        tutorials = tutorials.filter(category_id=category_id)

    status = request.GET.get('status')
    if status == 'active':
        tutorials = tutorials.filter(is_published=True)
    elif status == 'inactive':
        tutorials = tutorials.filter(is_published=False)

    search = request.GET.get('search')
    if search:
        tutorials = tutorials.filter(
            Q(title__icontains=search) |
            Q(description__icontains=search)
        )

    # Pagination
    paginator = Paginator(tutorials, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    categories = TutorialCategory.objects.filter(is_active=True)

    context = {
        'page_obj': page_obj,
        'categories': categories,
        'current_category': category_id,
        'current_status': status,
        'current_search': search,
        'page_title': 'Manage Tutorials'
    }

    return render(request, 'admin/tutorials_list.html', context)


@user_passes_test(is_admin)
def tutorial_detail(request, tutorial_id):
    """View tutorial details and analytics"""
    tutorial = get_object_or_404(Tutorial, id=tutorial_id)

    # Analytics
    total_started = tutorial.user_progress.count()
    total_completed = tutorial.user_progress.filter(is_completed=True).count()
    completion_rate = (total_completed / total_started * 100) if total_started > 0 else 0

    quiz_attempts = tutorial.quiz_attempts.count()
    quiz_passed = tutorial.quiz_attempts.filter(is_passed=True).count()
    quiz_pass_rate = (quiz_passed / quiz_attempts * 100) if quiz_attempts > 0 else 0
    avg_score = tutorial.quiz_attempts.aggregate(avg=Avg('score_percentage'))['avg'] or 0

    # Recent learners
    recent_progress = tutorial.user_progress.select_related('user').order_by('-updated_at')[:10]

    # Quiz questions
    questions = tutorial.quiz_questions.prefetch_related('answers').order_by('order')

    context = {
        'tutorial': tutorial,
        'stats': {
            'total_started': total_started,
            'total_completed': total_completed,
            'completion_rate': round(completion_rate, 1),
            'quiz_attempts': quiz_attempts,
            'quiz_passed': quiz_passed,
            'quiz_pass_rate': round(quiz_pass_rate, 1),
            'avg_score': round(avg_score, 1),
        },
        'recent_progress': recent_progress,
        'questions': questions,
        'page_title': f'Tutorial: {tutorial.title}'
    }

    return render(request, 'admin/tutorial_detail.html', context)


@user_passes_test(is_admin)
def tutorial_toggle_status(request, tutorial_id):
    """Toggle tutorial published status"""
    if request.method == 'POST':
        tutorial = get_object_or_404(Tutorial, id=tutorial_id)
        tutorial.is_published = not tutorial.is_published
        tutorial.save()

        status = 'published' if tutorial.is_published else 'unpublished'
        messages.success(request, f'Tutorial "{tutorial.title}" {status}!')

    return redirect('custom_admin:tutorials_list')


@user_passes_test(is_admin)
def categories_list(request):
    """List tutorial categories with enhanced statistics"""
    categories = TutorialCategory.objects.annotate(
        tutorial_count=Count('tutorials'),
        active_tutorial_count=Count('tutorials', filter=Q(tutorials__is_published=True))
    ).order_by('order', 'name')

    # Enhanced statistics
    total_categories = categories.count()
    active_categories = categories.filter(is_active=True).count()
    inactive_categories = total_categories - active_categories

    context = {
        'categories': categories,
        'total_categories': total_categories,
        'active_categories': active_categories,
        'inactive_categories': inactive_categories,
        'page_title': 'Tutorial Categories'
    }
    return render(request, 'admin/tutorial_categories.html', context)


@user_passes_test(is_admin)
def user_progress(request):
    """View user tutorial progress"""
    progress_list = UserTutorialProgress.objects.select_related(
        'user', 'tutorial'
    ).order_by('-updated_at')

    # Filters
    tutorial_id = request.GET.get('tutorial')
    if tutorial_id:
        progress_list = progress_list.filter(tutorial_id=tutorial_id)

    status = request.GET.get('status')
    if status == 'completed':
        progress_list = progress_list.filter(is_completed=True)
    elif status == 'in_progress':
        progress_list = progress_list.filter(is_completed=False, video_watch_percentage__gt=0)
    elif status == 'not_started':
        progress_list = progress_list.filter(video_watch_percentage=0)

    user_search = request.GET.get('user_search')
    if user_search:
        progress_list = progress_list.filter(
            Q(user__username__icontains=user_search) |
            Q(user__email__icontains=user_search)
        )

    # Pagination
    paginator = Paginator(progress_list, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    tutorials = Tutorial.objects.filter(is_published=True).order_by('title')

    context = {
        'page_obj': page_obj,
        'tutorials': tutorials,
        'current_tutorial': tutorial_id,
        'current_status': status,
        'current_user_search': user_search,
        'page_title': 'User Progress'
    }

    return render(request, 'admin/user_progress.html', context)


@user_passes_test(is_admin)
def tutorial_analytics_api(request):
    """API for charts and analytics"""
    # Daily completions for last 30 days
    thirty_days_ago = timezone.now() - timedelta(days=30)
    daily_data = []

    for i in range(30):
        date = (timezone.now() - timedelta(days=29 - i)).date()
        completions = UserTutorialProgress.objects.filter(
            is_completed=True,
            updated_at__date=date
        ).count()

        attempts = UserQuizAttempt.objects.filter(
            completed_at__date=date
        ).count()

        daily_data.append({
            'date': date.strftime('%Y-%m-%d'),
            'completions': completions,
            'quiz_attempts': attempts
        })

    # Category performance
    category_data = list(TutorialCategory.objects.annotate(
        completions=Count('tutorials__user_progress', filter=Q(tutorials__user_progress__is_completed=True))
    ).values('name', 'completions'))

    return JsonResponse({
        'daily_completions': daily_data,
        'category_performance': category_data,
    })


@user_passes_test(is_admin)
@csrf_exempt
def bulk_tutorial_actions(request):
    """Handle bulk actions on tutorials"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            action = data.get('action')
            tutorial_ids = data.get('tutorial_ids', [])

            tutorials = Tutorial.objects.filter(id__in=tutorial_ids)

            if action == 'activate':
                tutorials.update(is_published=True)
                message = f'{tutorials.count()} tutorials published'
            elif action == 'deactivate':
                tutorials.update(is_published=False)
                message = f'{tutorials.count()} tutorials unpublished'
            elif action == 'delete':
                count = tutorials.count()
                tutorials.delete()
                message = f'{count} tutorials deleted'
            else:
                return JsonResponse({'success': False, 'message': 'Invalid action'})

            return JsonResponse({'success': True, 'message': message})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})

    return JsonResponse({'success': False, 'message': 'Invalid request method'})


@user_passes_test(is_admin)
def tutorial_create(request):
    """Create a new tutorial with automatic duration detection"""
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Get form data
                video_source = request.POST.get('video_source', 'url')

                # Handle video duration - start with manual input as fallback
                video_duration_seconds = request.POST.get('video_duration', '0')
                if not video_duration_seconds or video_duration_seconds == '':
                    video_duration_seconds = '0'

                initial_duration = timedelta(seconds=int(video_duration_seconds))

                # Create tutorial with initial duration
                tutorial = Tutorial.objects.create(
                    title=request.POST.get('title'),
                    description=request.POST.get('description', ''),
                    video_source=video_source,
                    video_duration=initial_duration,
                    completion_reward=0,
                    category_id=request.POST.get('category') if request.POST.get('category') else None,
                    is_published=request.POST.get('is_published') == 'on',
                    quiz_required=request.POST.get('quiz_required') == 'on',
                    quiz_passing_score=int(request.POST.get('quiz_passing_score', 70)) if request.POST.get(
                        'quiz_passing_score') else 70,
                    max_quiz_attempts=int(request.POST.get('max_quiz_attempts', 999999)) if request.POST.get(
                        'max_quiz_attempts') else 999999
                )

                # Handle video source and try to detect duration
                detected_duration = None

                if video_source == 'url':
                    video_url = request.POST.get('video_url', '')
                    tutorial.video_url = video_url

                    # Try to detect duration from URL
                    if video_url and ('youtube.com' in video_url or 'youtu.be' in video_url):
                        detected_duration = get_youtube_duration(video_url)

                elif video_source == 'upload':
                    video_file = request.FILES.get('video_file')
                    if video_file:
                        # Validate file size (max 500MB)
                        if video_file.size > 500 * 1024 * 1024:
                            raise ValueError("Video file size cannot exceed 500MB")

                        tutorial.video_file = video_file

                        # Try to detect duration from uploaded file
                        detected_duration = get_video_duration_from_file(video_file)

                # Update duration if we detected it automatically
                if detected_duration and detected_duration.total_seconds() > 0:
                    tutorial.video_duration = detected_duration

                tutorial.save()

                # Process quiz questions if any
                questions_data = request.POST.get('questions_json')
                if questions_data:
                    questions = json.loads(questions_data)
                    for i, question_data in enumerate(questions):
                        if question_data.get('question'):
                            question = QuizQuestion.objects.create(
                                tutorial=tutorial,
                                question=question_data.get('question'),
                                question_type=question_data.get('type', 'multiple_choice'),
                                order=i + 1
                            )

                            for j, answer_data in enumerate(question_data.get('answers', [])):
                                if answer_data.get('text'):
                                    QuizAnswer.objects.create(
                                        question=question,
                                        answer=answer_data.get('text'),
                                        is_correct=answer_data.get('correct', False),
                                        order=j + 1
                                    )

                # Create success message with duration info
                duration_info = ""
                if tutorial.video_duration.total_seconds() > 0:
                    total_seconds = int(tutorial.video_duration.total_seconds())
                    minutes = total_seconds // 60
                    seconds = total_seconds % 60
                    duration_info = f" (Duration: {minutes}m {seconds}s)"

                messages.success(request, f'Tutorial "{tutorial.title}" created successfully!{duration_info}')
                return redirect('custom_admin:tutorial_detail', tutorial_id=tutorial.id)

        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Error creating tutorial: {str(e)}')

    categories = TutorialCategory.objects.filter(is_active=True).order_by('name')
    context = {
        'page_title': 'Create Tutorial',
        'categories': categories,
        'is_edit': False,
    }
    return render(request, 'admin/tutorial_form.html', context)


@user_passes_test(is_admin)
def tutorial_edit(request, tutorial_id):
    """Edit an existing tutorial with automatic duration detection"""
    tutorial = get_object_or_404(Tutorial, id=tutorial_id)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Get form data
                video_source = request.POST.get('video_source', 'url')

                # Update tutorial basic info
                tutorial.title = request.POST.get('title')
                tutorial.description = request.POST.get('description', '')
                tutorial.video_source = video_source
                tutorial.completion_reward = float(request.POST.get('completion_reward', 0)) if request.POST.get(
                    'completion_reward') else 0
                tutorial.category_id = request.POST.get('category') if request.POST.get('category') else None
                tutorial.is_published = request.POST.get('is_published') == 'on'
                tutorial.quiz_required = request.POST.get('quiz_required') == 'on'
                tutorial.quiz_passing_score = int(request.POST.get('quiz_passing_score', 70)) if request.POST.get(
                    'quiz_passing_score') else 70
                max_quiz_attempts=int(request.POST.get('max_quiz_attempts', 999999)) if request.POST.get('max_quiz_attempts') else 999999

                # Handle video duration - start with manual input as fallback
                video_duration_seconds = request.POST.get('video_duration', '0')
                if not video_duration_seconds or video_duration_seconds == '':
                    video_duration_seconds = '0'
                tutorial.video_duration = timedelta(seconds=int(video_duration_seconds))

                # Handle video source changes and try to detect duration
                detected_duration = None

                if video_source == 'url':
                    video_url = request.POST.get('video_url', '')
                    tutorial.video_url = video_url
                    # Clear video file if switching to URL
                    if tutorial.video_file:
                        tutorial.video_file.delete()
                        tutorial.video_file = None

                    # Try to detect duration from URL
                    if video_url and ('youtube.com' in video_url or 'youtu.be' in video_url):
                        detected_duration = get_youtube_duration(video_url)

                elif video_source == 'upload':
                    tutorial.video_url = ''  # Clear URL if switching to upload
                    video_file = request.FILES.get('video_file')
                    if video_file:
                        # Validate file size (max 500MB)
                        if video_file.size > 500 * 1024 * 1024:
                            raise ValueError("Video file size cannot exceed 500MB")
                        # Delete old video file if exists
                        if tutorial.video_file:
                            tutorial.video_file.delete()
                        tutorial.video_file = video_file

                        # Try to detect duration from uploaded file
                        detected_duration = get_video_duration_from_file(video_file)

                # Update duration if we detected it automatically
                if detected_duration and detected_duration.total_seconds() > 0:
                    tutorial.video_duration = detected_duration

                tutorial.save()

                # Handle quiz questions update
                questions_data = request.POST.get('questions_json')
                if questions_data:
                    # Delete existing questions and answers
                    tutorial.quiz_questions.all().delete()

                    # Create new questions
                    questions = json.loads(questions_data)
                    for i, question_data in enumerate(questions):
                        if question_data.get('question'):
                            question = QuizQuestion.objects.create(
                                tutorial=tutorial,
                                question=question_data.get('question'),
                                question_type=question_data.get('type', 'multiple_choice'),
                                order=i + 1
                            )

                            for j, answer_data in enumerate(question_data.get('answers', [])):
                                if answer_data.get('text'):
                                    QuizAnswer.objects.create(
                                        question=question,
                                        answer=answer_data.get('text'),
                                        is_correct=answer_data.get('correct', False),
                                        order=j + 1
                                    )

                # Create success message with duration info
                duration_info = ""
                if tutorial.video_duration.total_seconds() > 0:
                    total_seconds = int(tutorial.video_duration.total_seconds())
                    minutes = total_seconds // 60
                    seconds = total_seconds % 60
                    duration_info = f" (Duration: {minutes}m {seconds}s)"

                messages.success(request, f'Tutorial "{tutorial.title}" updated successfully!{duration_info}')
                return redirect('custom_admin:tutorial_detail', tutorial_id=tutorial.id)

        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Error updating tutorial: {str(e)}')

    # Get existing quiz questions and answers for editing
    quiz_questions = []
    for question in tutorial.quiz_questions.all().order_by('order'):
        question_data = {
            'question': question.question,
            'type': question.question_type,
            'answers': []
        }
        for answer in question.answers.all().order_by('order'):
            question_data['answers'].append({
                'text': answer.answer,
                'correct': answer.is_correct
            })
        quiz_questions.append(question_data)

    categories = TutorialCategory.objects.filter(is_active=True).order_by('name')
    context = {
        'page_title': f'Edit Tutorial: {tutorial.title}',
        'tutorial': tutorial,
        'categories': categories,
        'quiz_questions_json': json.dumps(quiz_questions),
        'is_edit': True,
    }
    return render(request, 'admin/tutorial_form.html', context)


@user_passes_test(is_admin)
@require_http_methods(["POST"])
def tutorial_delete(request, tutorial_id):
    """Delete a tutorial"""
    tutorial = get_object_or_404(Tutorial, id=tutorial_id)
    tutorial_title = tutorial.title

    try:
        tutorial.delete()
        messages.success(request, f'Tutorial "{tutorial_title}" deleted successfully!')
    except Exception as e:
        messages.error(request, f'Error deleting tutorial: {str(e)}')

    return redirect('custom_admin:tutorials_list')


@user_passes_test(is_admin)
def category_create(request):
    """Create a new category with enhanced form handling"""
    if request.method == 'POST':
        try:
            # Get form data
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            icon = request.POST.get('icon', '').strip()
            order = request.POST.get('order', 1)
            is_active = request.POST.get('is_active') == 'on'

            # Basic validation
            if not name:
                messages.error(request, 'Category name is required')
                return render(request, 'admin/category_form.html', {
                    'form_title': 'Create Category',
                    'cancel_url': reverse('custom_admin:categories_list'),
                })

            # Create category
            category = TutorialCategory.objects.create(
                name=name,
                description=description,
                icon=icon or 'fas fa-play',  # Default icon
                order=int(order),
                is_active=is_active
            )

            messages.success(request, f'Category "{category.name}" created successfully!')
            return redirect('custom_admin:categories_list')

        except ValueError as e:
            messages.error(request, f'Invalid order value: {order}')
        except Exception as e:
            messages.error(request, f'Error creating category: {str(e)}')

    # GET request - show empty form
    context = {
        'form_title': 'Create Category',
        'cancel_url': reverse('custom_admin:categories_list'),
        'page_title': 'Create Category'
    }
    return render(request, 'admin/category_form.html', context)


@user_passes_test(is_admin)
def category_edit(request, category_id):
    """Edit a category with enhanced form handling"""
    try:
        category = TutorialCategory.objects.get(id=category_id)
    except TutorialCategory.DoesNotExist:
        messages.error(request, 'Category not found')
        return redirect('custom_admin:categories_list')

    if request.method == 'POST':
        try:
            # Get form data
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            icon = request.POST.get('icon', '').strip()
            order = request.POST.get('order', 1)
            is_active = request.POST.get('is_active') == 'on'

            # Basic validation
            if not name:
                messages.error(request, 'Category name is required')
                return render(request, 'admin/category_form.html', {
                    'category': category,
                    'form_title': f'Edit Category: {category.name}',
                    'cancel_url': reverse('custom_admin:categories_list'),
                })

            # Update category
            category.name = name
            category.description = description
            category.icon = icon or 'fas fa-play'
            category.order = int(order)
            category.is_active = is_active
            category.save()

            messages.success(request, f'Category "{category.name}" updated successfully!')
            return redirect('custom_admin:categories_list')

        except ValueError as e:
            messages.error(request, f'Invalid order value: {order}')
        except Exception as e:
            messages.error(request, f'Error updating category: {str(e)}')

    # GET request - show form with existing data
    context = {
        'category': category,
        'form_title': f'Edit Category: {category.name}',
        'cancel_url': reverse('custom_admin:categories_list'),
        'page_title': f'Edit Category: {category.name}'
    }
    return render(request, 'admin/category_form.html', context)


@user_passes_test(is_admin)
@require_http_methods(["POST"])
def category_toggle_status(request, category_id):
    """Toggle category active status with enhanced feedback"""
    try:
        category = TutorialCategory.objects.get(id=category_id)
        category.is_active = not category.is_active
        category.save()

        status = "activated" if category.is_active else "deactivated"
        messages.success(request, f'Category "{category.name}" {status} successfully!')

    except TutorialCategory.DoesNotExist:
        messages.error(request, 'Category not found')
    except Exception as e:
        messages.error(request, f'Error updating category status: {str(e)}')

    return redirect('custom_admin:categories_list')


@user_passes_test(is_admin)
@require_http_methods(["POST"])
def category_delete(request, category_id):
    """Delete a category (only if no tutorials) with enhanced validation"""
    try:
        category = TutorialCategory.objects.get(id=category_id)

        # Check if category has tutorials
        tutorial_count = category.tutorials.count()
        if tutorial_count > 0:
            messages.error(
                request,
                f'Cannot delete category "{category.name}" - it has {tutorial_count} tutorial(s). '
                'Please move or delete the tutorials first.'
            )
        else:
            category_name = category.name
            category.delete()
            messages.success(request, f'Category "{category_name}" deleted successfully!')

    except TutorialCategory.DoesNotExist:
        messages.error(request, 'Category not found')
    except Exception as e:
        messages.error(request, f'Error deleting category: {str(e)}')

    return redirect('custom_admin:categories_list')