# accounts/management/commands/referral_analytics.py

from django.core.management.base import BaseCommand
from django.db.models import Sum, Count, Avg, F
from django.utils import timezone
from datetime import timedelta, datetime
import csv
import os

from accounts.models import User, ReferralCommission


class Command(BaseCommand):
    help = 'Generate referral analytics reports'

    def add_arguments(self, parser):
        parser.add_argument(
            '--period',
            type=str,
            choices=['daily', 'weekly', 'monthly'],
            default='monthly',
            help='Report period',
        )
        parser.add_argument(
            '--export-csv',
            action='store_true',
            help='Export results to CSV file',
        )
        parser.add_argument(
            '--user-details',
            action='store_true',
            help='Include detailed user statistics',
        )

    def handle(self, *args, **options):
        period = options['period']

        self.stdout.write(
            self.style.SUCCESS(f'Generating {period} referral analytics...')
        )

        # Calculate date range
        end_date = timezone.now()
        if period == 'daily':
            start_date = end_date - timedelta(days=1)
        elif period == 'weekly':
            start_date = end_date - timedelta(days=7)
        else:  # monthly
            start_date = end_date - timedelta(days=30)

        # Generate analytics
        analytics = self.generate_analytics(start_date, end_date)

        # Display results
        self.display_analytics(analytics, period)

        # Export to CSV if requested
        if options['export_csv']:
            self.export_to_csv(analytics, period)

        # User details if requested
        if options['user_details']:
            self.display_user_details(start_date, end_date)

    def generate_analytics(self, start_date, end_date):
        """Generate comprehensive referral analytics"""

        # Basic stats
        total_commissions = ReferralCommission.objects.filter(
            created_at__range=[start_date, end_date]
        )

        basic_stats = total_commissions.aggregate(
            total_amount=Sum('commission_amount'),
            total_count=Count('id'),
            avg_commission=Avg('commission_amount')
        )

        # Commission by type
        by_type = total_commissions.values('commission_type').annotate(
            type_amount=Sum('commission_amount'),
            type_count=Count('id')
        )

        # Top referrers
        top_referrers = total_commissions.values(
            'referrer__username',
            'referrer__referral_code'
        ).annotate(
            total_earned=Sum('commission_amount'),
            total_referrals=Count('referred_user', distinct=True)
        ).order_by('-total_earned')[:10]

        # Conversion rates
        total_users = User.objects.filter(
            date_joined__range=[start_date, end_date]
        ).count()

        referred_users = User.objects.filter(
            date_joined__range=[start_date, end_date],
            referred_by__isnull=False
        ).count()

        conversion_rate = (referred_users / total_users * 100) if total_users > 0 else 0

        # Daily breakdown
        daily_stats = []
        current_date = start_date.date()
        end_date_only = end_date.date()

        while current_date <= end_date_only:
            day_commissions = ReferralCommission.objects.filter(
                created_at__date=current_date
            ).aggregate(
                day_amount=Sum('commission_amount'),
                day_count=Count('id')
            )

            daily_stats.append({
                'date': current_date,
                'amount': day_commissions['day_amount'] or 0,
                'count': day_commissions['day_count'] or 0
            })

            current_date += timedelta(days=1)

        return {
            'basic_stats': basic_stats,
            'by_type': by_type,
            'top_referrers': top_referrers,
            'conversion_rate': conversion_rate,
            'daily_stats': daily_stats,
            'total_users': total_users,
            'referred_users': referred_users
        }

    def display_analytics(self, analytics, period):
        """Display analytics in a formatted way"""

        self.stdout.write(f"\n=== REFERRAL ANALYTICS ({period.upper()}) ===")

        basic = analytics['basic_stats']
        self.stdout.write(f"Total Commissions: {basic['total_count'] or 0}")
        self.stdout.write(f"Total Amount: KSh {basic['total_amount'] or 0}")
        self.stdout.write(f"Average Commission: KSh {basic['avg_commission'] or 0:.2f}")
        self.stdout.write(f"Conversion Rate: {analytics['conversion_rate']:.1f}%")

        self.stdout.write(f"\nCOMMISSIONS BY TYPE:")
        for item in analytics['by_type']:
            self.stdout.write(
                f"- {item['commission_type'].title()}: "
                f"{item['type_count']} commissions, KSh {item['type_amount']}"
            )

        self.stdout.write(f"\nTOP 10 REFERRERS:")
        for i, referrer in enumerate(analytics['top_referrers'], 1):
            self.stdout.write(
                f"{i:2d}. {referrer['referrer__username'][:20]:20s} | "
                f"KSh {referrer['total_earned']:8.2f} | "
                f"{referrer['total_referrals']:3d} referrals"
            )

    def display_user_details(self, start_date, end_date):
        """Display detailed user statistics"""

        self.stdout.write(f"\n=== USER DETAILS ===")

        # Users with most referrals in period
        top_users = User.objects.filter(
            referrer_commissions__created_at__range=[start_date, end_date]
        ).annotate(
            period_referrals=Count('referrer_commissions'),
            period_earnings=Sum('referrer_commissions__commission_amount')
        ).order_by('-period_referrals')[:5]

        for user in top_users:
            self.stdout.write(
                f"- {user.username}: {user.period_referrals} referrals, "
                f"KSh {user.period_earnings or 0} earned"
            )

    def export_to_csv(self, analytics, period):
        """Export analytics to CSV file"""

        filename = f"referral_analytics_{period}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"

        with open(filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)

            # Write summary
            writer.writerow(['=== REFERRAL ANALYTICS SUMMARY ==='])
            writer.writerow(['Period', period])
            writer.writerow(['Generated', timezone.now().strftime('%Y-%m-%d %H:%M:%S')])
            writer.writerow([])

            # Write basic stats
            basic = analytics['basic_stats']
            writer.writerow(['Metric', 'Value'])
            writer.writerow(['Total Commissions', basic['total_count'] or 0])
            writer.writerow(['Total Amount (KSh)', basic['total_amount'] or 0])
            writer.writerow(['Average Commission (KSh)', f"{basic['avg_commission'] or 0:.2f}"])
            writer.writerow(['Conversion Rate (%)', f"{analytics['conversion_rate']:.1f}"])
            writer.writerow([])

            # Write daily breakdown
            writer.writerow(['=== DAILY BREAKDOWN ==='])
            writer.writerow(['Date', 'Commissions', 'Amount (KSh)'])
            for day in analytics['daily_stats']:
                writer.writerow([day['date'], day['count'], day['amount']])
            writer.writerow([])

            # Write top referrers
            writer.writerow(['=== TOP REFERRERS ==='])
            writer.writerow(['Rank', 'Username', 'Total Earned (KSh)', 'Total Referrals'])
            for i, referrer in enumerate(analytics['top_referrers'], 1):
                writer.writerow([
                    i,
                    referrer['referrer__username'],
                    referrer['total_earned'],
                    referrer['total_referrals']
                ])

        self.stdout.write(
            self.style.SUCCESS(f'Analytics exported to {filename}')
        )