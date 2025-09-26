# accounts/management/commands/sync_user_fields.py
from django.core.management.base import BaseCommand
from django.db.models import Sum
from accounts.models import User
from payments.models import Transaction
from decimal import Decimal


class Command(BaseCommand):
    help = 'Sync user financial fields with actual transaction data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            help='Sync specific user by username'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes'
        )

    def handle(self, *args, **options):
        username = options.get('username')
        dry_run = options.get('dry_run')

        if username:
            try:
                users = [User.objects.get(username=username)]
                self.stdout.write(f"Processing user: {username}")
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"User '{username}' not found")
                )
                return
        else:
            users = User.objects.filter(is_staff=False)
            self.stdout.write(f"Processing {users.count()} users...")

        updated_count = 0

        for user in users:
            # Calculate correct values from transactions
            completed_transactions = Transaction.objects.filter(
                user=user,
                status='completed'
            )

            # Survey earnings and count
            survey_transactions = completed_transactions.filter(
                transaction_type='survey_payment'
            )
            survey_earnings = survey_transactions.aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0.00')
            survey_count = survey_transactions.count()

            # Total earnings (all positive income)
            positive_transactions = completed_transactions.filter(
                transaction_type__in=['survey_payment', 'bonus', 'referral_commission']
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

            # Withdrawals (negative from balance)
            withdrawals = completed_transactions.filter(
                transaction_type='withdrawal'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

            # Current balance = earnings - withdrawals
            current_balance = positive_transactions - abs(withdrawals)
            current_balance = max(current_balance, Decimal('0.00'))

            # Check if update is needed
            needs_update = (
                    user.balance != current_balance or
                    user.total_earnings != positive_transactions or
                    user.total_surveys_completed != survey_count
            )

            if needs_update:
                self.stdout.write(
                    f"\nUser: {user.username}"
                )
                self.stdout.write(
                    f"  Current: balance=KSh{user.balance}, earnings=KSh{user.total_earnings}, surveys={user.total_surveys_completed}"
                )
                self.stdout.write(
                    f"  Should be: balance=KSh{current_balance}, earnings=KSh{positive_transactions}, surveys={survey_count}"
                )

                if not dry_run:
                    # Update the user fields
                    user.balance = current_balance
                    user.total_earnings = positive_transactions
                    user.total_surveys_completed = survey_count
                    user.save(update_fields=['balance', 'total_earnings', 'total_surveys_completed'])
                    self.stdout.write(
                        self.style.SUCCESS(f"  ✓ Updated {user.username}")
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f"  → Would update {user.username} (dry run)")
                    )

                updated_count += 1

        if updated_count == 0:
            self.stdout.write(
                self.style.SUCCESS("All user fields are already in sync!")
            )
        else:
            action = "Would update" if dry_run else "Updated"
            self.stdout.write(
                self.style.SUCCESS(f"\n{action} {updated_count} users")
            )