# accounts/management/commands/process_referral_commissions.py

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.conf import settings
from decimal import Decimal
import logging

from accounts.models import User, ReferralCommission
from accounts.services.referral_service import ReferralService
from accounts.views import notify_referral_success
from payments.models import Transaction

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Automatically process pending referral commissions and send notifications'

    def add_arguments(self, parser):
        parser.add_argument(
            '--process-all',
            action='store_true',
            help='Process all pending commissions',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Process commissions for specific user only',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without making changes',
        )
        parser.add_argument(
            '--send-notifications',
            action='store_true',
            help='Send email notifications to users',
        )
        parser.add_argument(
            '--auto-approve',
            action='store_true',
            help='Automatically approve and add to user balance',
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('Starting referral commission processing...')
        )

        # Get pending commissions
        commissions_query = ReferralCommission.objects.filter(processed=False)

        if options['user_id']:
            commissions_query = commissions_query.filter(referrer_id=options['user_id'])

        pending_commissions = commissions_query.select_related(
            'referrer', 'referred_user'
        ).order_by('created_at')

        if not pending_commissions.exists():
            self.stdout.write(
                self.style.WARNING('No pending commissions found.')
            )
            return

        self.stdout.write(
            f'Found {pending_commissions.count()} pending commissions'
        )

        total_processed = 0
        total_amount = Decimal('0.00')

        for commission in pending_commissions:
            try:
                if options['dry_run']:
                    self.stdout.write(
                        f'[DRY RUN] Would process: {commission.referrer.username} -> '
                        f'KSh {commission.commission_amount} ({commission.commission_type})'
                    )
                else:
                    self.process_commission(commission, options)
                    total_processed += 1
                    total_amount += commission.commission_amount

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error processing commission {commission.id}: {str(e)}'
                    )
                )
                logger.error(f'Commission processing error: {e}', exc_info=True)

        if not options['dry_run']:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully processed {total_processed} commissions '
                    f'totaling KSh {total_amount}'
                )
            )

            # Generate summary report
            self.generate_summary_report(total_processed, total_amount)
        else:
            self.stdout.write(
                self.style.SUCCESS('Dry run completed.')
            )

    def process_commission(self, commission, options):
        """Process a single commission"""

        # Mark as processed
        commission.processed = True
        commission.processed_at = timezone.now()
        commission.save()

        if options['auto_approve']:
            # Add to user's balance
            commission.referrer.balance += commission.commission_amount
            commission.referrer.save()

            # Create transaction record
            Transaction.objects.create(
                user=commission.referrer,
                transaction_type='credit',
                amount=commission.commission_amount,
                description=f'Referral commission: {commission.commission_type}',
                reference_id=f'REF-{commission.id}',
                status='completed'
            )

            self.stdout.write(
                f'✅ Added KSh {commission.commission_amount} to '
                f'{commission.referrer.username}\'s balance'
            )
        else:
            self.stdout.write(
                f'✅ Marked commission as processed (pending admin approval): '
                f'{commission.referrer.username} -> KSh {commission.commission_amount}'
            )

        # Send notification if requested
        if options['send_notifications']:
            try:
                notify_referral_success(
                    commission.referrer,
                    commission.referred_user,
                    commission.commission_amount,
                    commission.commission_type
                )
                self.stdout.write(f'📧 Sent notification to {commission.referrer.email}')
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f'Failed to send notification: {e}')
                )

    def generate_summary_report(self, total_processed, total_amount):
        """Generate a summary report of processed commissions"""

        # Get statistics
        stats = ReferralCommission.objects.filter(
            processed=True,
            processed_at__date=timezone.now().date()
        ).aggregate(
            today_total=Sum('commission_amount'),
            today_count=Count('id')
        )

        # Commission breakdown by type
        breakdown = ReferralCommission.objects.filter(
            processed=True,
            processed_at__date=timezone.now().date()
        ).values('commission_type').annotate(
            type_total=Sum('commission_amount'),
            type_count=Count('id')
        )

        # Top earners today
        top_earners = ReferralCommission.objects.filter(
            processed=True,
            processed_at__date=timezone.now().date()
        ).values(
            'referrer__username'
        ).annotate(
            daily_earnings=Sum('commission_amount')
        ).order_by('-daily_earnings')[:5]

        report = f"""
=== REFERRAL COMMISSION PROCESSING SUMMARY ===
Date: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}
Total Processed Today: {stats['today_count'] or 0} commissions
Total Amount Today: KSh {stats['today_total'] or 0}

BREAKDOWN BY TYPE:
"""

        for item in breakdown:
            report += f"- {item['commission_type'].title()}: {item['type_count']} commissions, KSh {item['type_total']}\n"

        report += "\nTOP EARNERS TODAY:\n"
        for i, earner in enumerate(top_earners, 1):
            report += f"{i}. {earner['referrer__username']}: KSh {earner['daily_earnings']}\n"

        self.stdout.write(report)

        # Log the report
        logger.info(f"Referral commission processing summary: {report}")
