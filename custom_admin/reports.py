# custom_admin/reports.py - Advanced reports data processing

from django.db.models import Sum, Count, Avg, Q, F
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import json

from accounts.models import User
from surveys.models import Survey, SurveyResponse, Question, Answer
from payments.models import Transaction, WithdrawalRequest, MPesaTransaction


class ReportsService:
    """Service class for generating comprehensive platform reports"""

    @staticmethod
    def get_dashboard_metrics(date_range=30):
        """Get key dashboard metrics for the last N days"""

        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=date_range)

        # User metrics
        total_users = User.objects.count()
        new_users = User.objects.filter(
            date_joined__date__range=[start_date, end_date]
        ).count()
        active_users = User.objects.filter(
            last_login__date__range=[start_date, end_date]
        ).count()
        verified_users = User.objects.filter(
            email_verified=True
        ).count()

        # Survey metrics
        total_surveys = Survey.objects.count()
        active_surveys = Survey.objects.filter(status='active').count()
        completed_responses = SurveyResponse.objects.filter(
            completed_at__date__range=[start_date, end_date],
            status='completed'
        ).count()

        # Financial metrics
        period_payouts = Transaction.objects.filter(
            created_at__date__range=[start_date, end_date],
            transaction_type='survey_payment',
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        period_withdrawals = WithdrawalRequest.objects.filter(
            created_at__date__range=[start_date, end_date],
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        total_platform_balance = User.objects.aggregate(
            total=Sum('balance')
        )['total'] or Decimal('0')

        # Growth metrics
        previous_period_users = User.objects.filter(
            date_joined__date__range=[start_date - timedelta(days=date_range), start_date]
        ).count()

        user_growth_rate = 0
        if previous_period_users > 0:
            user_growth_rate = ((new_users - previous_period_users) / previous_period_users) * 100

        return {
            'user_metrics': {
                'total_users': total_users,
                'new_users': new_users,
                'active_users': active_users,
                'verified_users': verified_users,
                'user_growth_rate': round(user_growth_rate, 2),
                'verification_rate': round((verified_users / total_users * 100), 2) if total_users > 0 else 0
            },
            'survey_metrics': {
                'total_surveys': total_surveys,
                'active_surveys': active_surveys,
                'completed_responses': completed_responses,
                'avg_responses_per_survey': round(completed_responses / active_surveys, 2) if active_surveys > 0 else 0
            },
            'financial_metrics': {
                'period_payouts': float(period_payouts),
                'period_withdrawals': float(period_withdrawals),
                'total_platform_balance': float(total_platform_balance),
                'net_flow': float(period_payouts - period_withdrawals)
            },
            'date_range': {
                'start_date': start_date,
                'end_date': end_date,
                'days': date_range
            }
        }

    @staticmethod
    def get_user_analytics(date_range=30):
        """Get detailed user analytics"""

        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=date_range)

        # User registration trends
        daily_registrations = User.objects.filter(
            date_joined__date__range=[start_date, end_date]
        ).extra(
            select={'day': 'date(date_joined)'}
        ).values('day').annotate(
            count=Count('id')
        ).order_by('day')

        # User engagement metrics
        engagement_stats = {
            'highly_active': User.objects.filter(total_surveys_completed__gte=10).count(),
            'moderately_active': User.objects.filter(
                total_surveys_completed__gte=3,
                total_surveys_completed__lt=10
            ).count(),
            'low_activity': User.objects.filter(
                total_surveys_completed__gte=1,
                total_surveys_completed__lt=3
            ).count(),
            'inactive': User.objects.filter(total_surveys_completed=0).count()
        }

        # Top earners
        top_earners = User.objects.order_by('-total_earnings')[:10].values(
            'username', 'total_earnings', 'total_surveys_completed', 'balance'
        )

        # User location distribution (if you collect this data)
        location_stats = User.objects.exclude(
            location__isnull=True
        ).exclude(
            location__exact=''
        ).values('location').annotate(
            count=Count('id')
        ).order_by('-count')[:10]

        # Age group distribution (if you collect birth dates)
        age_groups = {
            '18-24': 0, '25-34': 0, '35-44': 0, '45-54': 0, '55+': 0
        }

        users_with_age = User.objects.exclude(date_of_birth__isnull=True)
        for user in users_with_age:
            age = ReportsService._calculate_age(user.date_of_birth)
            if 18 <= age <= 24:
                age_groups['18-24'] += 1
            elif 25 <= age <= 34:
                age_groups['25-34'] += 1
            elif 35 <= age <= 44:
                age_groups['35-44'] += 1
            elif 45 <= age <= 54:
                age_groups['45-54'] += 1
            elif age >= 55:
                age_groups['55+'] += 1

        return {
            'registration_trends': list(daily_registrations),
            'engagement_stats': engagement_stats,
            'top_earners': list(top_earners),
            'location_stats': list(location_stats),
            'age_groups': age_groups
        }

    @staticmethod
    def get_survey_analytics(date_range=30):
        """Get detailed survey analytics"""

        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=date_range)

        # Survey performance metrics
        survey_stats = Survey.objects.annotate(
            response_count=Count('responses'),
            completion_rate=Count('responses', filter=Q(responses__status='completed')) * 100.0 / Count('responses'),
            total_cost=Sum('responses__survey__payout', filter=Q(responses__status='completed'))
        ).values(
            'id', 'title', 'status', 'payout', 'max_responses', 'created_at',
            'response_count', 'completion_rate', 'total_cost'
        ).order_by('-response_count')

        # Question type distribution
        question_types = Question.objects.values('question_type').annotate(
            count=Count('id')
        ).order_by('-count')

        # Daily response trends
        daily_responses = SurveyResponse.objects.filter(
            completed_at__date__range=[start_date, end_date],
            status='completed'
        ).extra(
            select={'day': 'date(completed_at)'}
        ).values('day').annotate(
            count=Count('id'),
            total_payout=Sum('survey__payout')
        ).order_by('day')

        # Most popular surveys
        popular_surveys = Survey.objects.filter(
            status='active'
        ).annotate(
            recent_responses=Count('responses', filter=Q(
                responses__completed_at__date__range=[start_date, end_date],
                responses__status='completed'
            ))
        ).order_by('-recent_responses')[:10].values(
            'title', 'payout', 'recent_responses', 'status'
        )

        # Survey completion rates by payout range
        payout_performance = []
        payout_ranges = [
            (0, 5, '0-5 KSh'),
            (5, 10, '5-10 KSh'),
            (10, 20, '10-20 KSh'),
            (20, 50, '20-50 KSh'),
            (50, 1000, '50+ KSh')
        ]

        for min_payout, max_payout, label in payout_ranges:
            surveys_in_range = Survey.objects.filter(
                payout__gte=min_payout,
                payout__lt=max_payout
            )

            if surveys_in_range.exists():
                avg_completion = surveys_in_range.annotate(
                    completion_rate=Count('responses', filter=Q(responses__status='completed')) * 100.0 / Count(
                        'responses')
                ).aggregate(avg_rate=Avg('completion_rate'))['avg_rate'] or 0

                payout_performance.append({
                    'range': label,
                    'survey_count': surveys_in_range.count(),
                    'avg_completion_rate': round(avg_completion, 2)
                })

        return {
            'survey_stats': list(survey_stats),
            'question_types': list(question_types),
            'daily_responses': list(daily_responses),
            'popular_surveys': list(popular_surveys),
            'payout_performance': payout_performance
        }

    @staticmethod
    def get_financial_analytics(date_range=30):
        """Get detailed financial analytics"""

        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=date_range)

        # Revenue and cost analysis
        total_payouts = Transaction.objects.filter(
            transaction_type='survey_payment',
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        period_payouts = Transaction.objects.filter(
            created_at__date__range=[start_date, end_date],
            transaction_type='survey_payment',
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # Withdrawal analysis
        withdrawal_stats = {
            'total_requested': WithdrawalRequest.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0'),
            'total_completed': WithdrawalRequest.objects.filter(
                status='completed'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0'),
            'pending_amount': WithdrawalRequest.objects.filter(
                status='pending'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0'),
            'average_withdrawal': WithdrawalRequest.objects.filter(
                status='completed'
            ).aggregate(avg=Avg('amount'))['avg'] or Decimal('0')
        }

        # Payment method distribution
        payment_method_stats = WithdrawalRequest.objects.values(
            'payment_method'
        ).annotate(
            count=Count('id'),
            total_amount=Sum('amount')
        ).order_by('-count')

        # Daily financial trends
        daily_financial = Transaction.objects.filter(
            created_at__date__range=[start_date, end_date]
        ).extra(
            select={'day': 'date(created_at)'}
        ).values('day', 'transaction_type').annotate(
            count=Count('id'),
            total_amount=Sum('amount')
        ).order_by('day')

        # M-Pesa transaction analysis (if implemented)
        try:
            mpesa_stats = {
                'total_b2c': MPesaTransaction.objects.filter(transaction_type='b2c').count(),
                'successful_b2c': MPesaTransaction.objects.filter(
                    transaction_type='b2c',
                    status='completed'
                ).count(),
                'failed_b2c': MPesaTransaction.objects.filter(
                    transaction_type='b2c',
                    status='failed'
                ).count(),
                'success_rate': 0
            }

            if mpesa_stats['total_b2c'] > 0:
                mpesa_stats['success_rate'] = round(
                    (mpesa_stats['successful_b2c'] / mpesa_stats['total_b2c']) * 100, 2
                )
        except:
            mpesa_stats = {}

        # User balance distribution
        balance_ranges = [
            (0, 100, '0-100 KSh'),
            (100, 500, '100-500 KSh'),
            (500, 1000, '500-1000 KSh'),
            (1000, 5000, '1000-5000 KSh'),
            (5000, 100000, '5000+ KSh')
        ]

        balance_distribution = []
        for min_balance, max_balance, label in balance_ranges:
            count = User.objects.filter(
                balance__gte=min_balance,
                balance__lt=max_balance
            ).count()

            balance_distribution.append({
                'range': label,
                'user_count': count
            })

        return {
            'revenue_metrics': {
                'total_payouts': float(total_payouts),
                'period_payouts': float(period_payouts),
                'average_daily_payout': float(period_payouts / date_range) if date_range > 0 else 0
            },
            'withdrawal_stats': {k: float(v) for k, v in withdrawal_stats.items()},
            'payment_method_stats': list(payment_method_stats),
            'daily_financial': list(daily_financial),
            'mpesa_stats': mpesa_stats,
            'balance_distribution': balance_distribution
        }

    @staticmethod
    def get_platform_health_metrics():
        """Get platform health and performance metrics"""

        # System health indicators
        total_users = User.objects.count()
        active_surveys = Survey.objects.filter(status='active').count()
        pending_withdrawals = WithdrawalRequest.objects.filter(status='pending').count()

        # Data quality metrics
        users_with_complete_profiles = User.objects.exclude(
            Q(phone_number__isnull=True) | Q(phone_number__exact='') |
            Q(date_of_birth__isnull=True) |
            Q(location__isnull=True) | Q(location__exact='')
        ).count()

        profile_completion_rate = (users_with_complete_profiles / total_users * 100) if total_users > 0 else 0

        # Error rates
        failed_transactions = Transaction.objects.filter(status='failed').count()
        total_transactions = Transaction.objects.count()
        transaction_failure_rate = (failed_transactions / total_transactions * 100) if total_transactions > 0 else 0

        # User engagement health
        recent_logins = User.objects.filter(
            last_login__gte=timezone.now() - timedelta(days=7)
        ).count()
        user_retention_rate = (recent_logins / total_users * 100) if total_users > 0 else 0

        return {
            'system_health': {
                'total_users': total_users,
                'active_surveys': active_surveys,
                'pending_withdrawals': pending_withdrawals
            },
            'data_quality': {
                'profile_completion_rate': round(profile_completion_rate, 2),
                'users_with_complete_profiles': users_with_complete_profiles
            },
            'performance_metrics': {
                'transaction_failure_rate': round(transaction_failure_rate, 2),
                'user_retention_rate': round(user_retention_rate, 2)
            }
        }

    @staticmethod
    def generate_executive_summary(date_range=30):
        """Generate executive summary report"""

        dashboard_metrics = ReportsService.get_dashboard_metrics(date_range)
        user_analytics = ReportsService.get_user_analytics(date_range)
        survey_analytics = ReportsService.get_survey_analytics(date_range)
        financial_analytics = ReportsService.get_financial_analytics(date_range)
        health_metrics = ReportsService.get_platform_health_metrics()

        # Key insights
        insights = []

        # User growth insight
        if dashboard_metrics['user_metrics']['user_growth_rate'] > 10:
            insights.append({
                'type': 'positive',
                'title': 'Strong User Growth',
                'description': f"User registration grew by {dashboard_metrics['user_metrics']['user_growth_rate']}% in the last {date_range} days"
            })
        elif dashboard_metrics['user_metrics']['user_growth_rate'] < -5:
            insights.append({
                'type': 'warning',
                'title': 'Declining User Growth',
                'description': f"User registration declined by {abs(dashboard_metrics['user_metrics']['user_growth_rate'])}% in the last {date_range} days"
            })

        # Financial health insight
        net_flow = financial_analytics['revenue_metrics']['period_payouts'] - financial_analytics['withdrawal_stats'][
            'total_completed']
        if net_flow < 0:
            insights.append({
                'type': 'warning',
                'title': 'Negative Cash Flow',
                'description': f"Withdrawals exceeded payouts by KSh {abs(net_flow):,.2f} in the last {date_range} days"
            })

        # Survey performance insight
        if len(survey_analytics['popular_surveys']) > 0:
            top_survey = survey_analytics['popular_surveys'][0]
            insights.append({
                'type': 'info',
                'title': 'Top Performing Survey',
                'description': f"'{top_survey['title']}' had {top_survey['recent_responses']} completions"
            })

        return {
            'period': f"Last {date_range} days",
            'generated_at': timezone.now(),
            'key_metrics': {
                'total_users': dashboard_metrics['user_metrics']['total_users'],
                'new_users': dashboard_metrics['user_metrics']['new_users'],
                'active_surveys': dashboard_metrics['survey_metrics']['active_surveys'],
                'total_responses': dashboard_metrics['survey_metrics']['completed_responses'],
                'total_payouts': financial_analytics['revenue_metrics']['period_payouts'],
                'pending_withdrawals': financial_analytics['withdrawal_stats']['pending_amount']
            },
            'insights': insights,
            'detailed_data': {
                'dashboard_metrics': dashboard_metrics,
                'user_analytics': user_analytics,
                'survey_analytics': survey_analytics,
                'financial_analytics': financial_analytics,
                'health_metrics': health_metrics
            }
        }

    @staticmethod
    def export_data_for_charts(date_range=30):
        """Export data formatted for Chart.js"""

        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=date_range)

        # Generate daily data
        chart_data = {
            'labels': [],
            'user_registrations': [],
            'survey_completions': [],
            'daily_payouts': [],
            'withdrawal_requests': []
        }

        current_date = start_date
        while current_date <= end_date:
            chart_data['labels'].append(current_date.strftime('%m/%d'))

            # Daily registrations
            daily_users = User.objects.filter(date_joined__date=current_date).count()
            chart_data['user_registrations'].append(daily_users)

            # Daily survey completions
            daily_responses = SurveyResponse.objects.filter(
                completed_at__date=current_date,
                status='completed'
            ).count()
            chart_data['survey_completions'].append(daily_responses)

            # Daily payouts
            daily_payout = Transaction.objects.filter(
                created_at__date=current_date,
                transaction_type='survey_payment',
                status='completed'
            ).aggregate(total=Sum('amount'))['total'] or 0
            chart_data['daily_payouts'].append(float(daily_payout))

            # Daily withdrawal requests
            daily_withdrawals = WithdrawalRequest.objects.filter(
                created_at__date=current_date
            ).count()
            chart_data['withdrawal_requests'].append(daily_withdrawals)

            current_date += timedelta(days=1)

        return chart_data

    @staticmethod
    def _calculate_age(birth_date):
        """Calculate age from birth date"""
        today = timezone.now().date()
        return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

    @staticmethod
    def get_survey_response_analytics(survey_id):
        """Get detailed analytics for a specific survey"""

        try:
            survey = Survey.objects.get(id=survey_id)
        except Survey.DoesNotExist:
            return None

        responses = SurveyResponse.objects.filter(survey=survey, status='completed')
        questions = Question.objects.filter(survey=survey).order_by('order')

        analytics = {
            'survey_info': {
                'title': survey.title,
                'description': survey.description,
                'payout': float(survey.payout),
                'status': survey.status,
                'created_at': survey.created_at,
                'total_responses': responses.count(),
                'total_cost': float(responses.count() * survey.payout)
            },
            'response_trends': [],
            'question_analytics': []
        }

        # Response trends over time
        daily_responses = responses.extra(
            select={'day': 'date(completed_at)'}
        ).values('day').annotate(
            count=Count('id')
        ).order_by('day')

        analytics['response_trends'] = list(daily_responses)

        # Question-by-question analytics
        for question in questions:
            question_data = {
                'question_id': str(question.id),
                'question_text': question.question_text,
                'question_type': question.question_type,
                'is_required': question.is_required,
                'order': question.order,
                'analytics': {}
            }

            answers = Answer.objects.filter(
                response__in=responses,
                question=question
            )

            if question.question_type in ['mcq', 'yes_no']:
                # Multiple choice analytics
                choice_counts = {}
                for answer in answers:
                    if answer.choice_answer:
                        choice_text = answer.choice_answer.choice_text
                        choice_counts[choice_text] = choice_counts.get(choice_text, 0) + 1

                question_data['analytics'] = {
                    'type': 'choice_distribution',
                    'data': choice_counts,
                    'total_responses': len(answers)
                }

            elif question.question_type == 'checkbox':
                # Checkbox analytics (multiple selections)
                choice_counts = {}
                for answer in answers:
                    if answer.choice_answer:
                        choice_text = answer.choice_answer.choice_text
                        choice_counts[choice_text] = choice_counts.get(choice_text, 0) + 1

                question_data['analytics'] = {
                    'type': 'checkbox_distribution',
                    'data': choice_counts,
                    'total_responses': len(answers)
                }

            elif question.question_type == 'rating':
                # Rating analytics
                ratings = []
                for answer in answers:
                    if answer.text_answer and answer.text_answer.isdigit():
                        ratings.append(int(answer.text_answer))

                if ratings:
                    question_data['analytics'] = {
                        'type': 'rating_stats',
                        'data': {
                            'average': round(sum(ratings) / len(ratings), 2),
                            'min': min(ratings),
                            'max': max(ratings),
                            'total_responses': len(ratings),
                            'distribution': {str(i): ratings.count(i) for i in
                                             range(question.rating_min or 1, (question.rating_max or 5) + 1)}
                        }
                    }

            elif question.question_type in ['text', 'textarea']:
                # Text analytics
                text_responses = [answer.text_answer for answer in answers if answer.text_answer]

                question_data['analytics'] = {
                    'type': 'text_stats',
                    'data': {
                        'total_responses': len(text_responses),
                        'average_length': round(sum(len(text) for text in text_responses) / len(text_responses),
                                                2) if text_responses else 0,
                        'sample_responses': text_responses[:5]  # First 5 responses as samples
                    }
                }

            analytics['question_analytics'].append(question_data)

        return analytics