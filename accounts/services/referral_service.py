# accounts/services/referral_service.py

import logging
from accounts.services.settings_service import SettingsService
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from accounts.models import User, ReferralCommission
from payments.models import Transaction

logger = logging.getLogger('referrals')


class ReferralService:
    @staticmethod
    def create_registration_commission(user):
        """
        Create commission for referrer when referred user completes registration payment
        Called from M-Pesa callback
        FIXED: Excludes admin/staff from earning commissions
        """
        if not user.referred_by:
            logger.debug(f"User {user.username} has no referrer - skipping commission")
            return None

        # FIXED: Check if referrer is admin/staff - they shouldn't earn commissions
        if user.referred_by.is_staff or user.referred_by.is_superuser:
            logger.info(f"ℹ️ Skipping registration commission for admin/staff referrer: {user.referred_by.username} (is_staff: {user.referred_by.is_staff}, is_superuser: {user.referred_by.is_superuser})")
            return None

        try:
            commission_rate = SettingsService.get_referral_commission_rate()
            registration_fee = Decimal(str(user.registration_amount or SettingsService.get_registration_fee()))
            commission_amount = registration_fee * commission_rate

            # Check if commission already exists
            existing = ReferralCommission.objects.filter(
                referrer=user.referred_by,
                referred_user=user,
                commission_type='registration'
            ).first()

            if existing:
                logger.warning(f"Registration commission already exists for {user.username}")
                return existing

            with transaction.atomic():
                commission = ReferralCommission.objects.create(
                    referrer=user.referred_by,
                    referred_user=user,
                    commission_amount=commission_amount,
                    commission_type='registration',
                    source_amount=registration_fee,
                    processed=False
                )

                # Update referrer's earnings (but not balance until processed)
                user.referred_by.referral_earnings += commission_amount
                user.referred_by.save(update_fields=['referral_earnings'])

                logger.info(
                    f"✅ Registration commission created: {commission.referrer.username} earns KSh {commission_amount}")
                return commission

        except Exception as e:
            logger.error(f"❌ Error creating registration commission for {user.username}: {str(e)}")
            return None

    @staticmethod
    def create_survey_commission(user, survey_payout):
        """
        Process referral commission for survey completion
        FIXED: Excludes admin/staff from earning commissions
        """
        if not user.referred_by:
            return None

        # FIXED: Check if referrer is admin/staff - they shouldn't earn commissions
        if user.referred_by.is_staff or user.referred_by.is_superuser:
            logger.info(f"ℹ️ Skipping survey commission for admin/staff referrer: {user.referred_by.username}")
            return None

        try:
            commission_rate = SettingsService.get_referral_commission_rate()
            commission_amount = survey_payout * commission_rate

            with transaction.atomic():
                commission = ReferralCommission.objects.create(
                    referrer=user.referred_by,
                    referred_user=user,
                    commission_amount=commission_amount,
                    commission_type='survey',
                    source_amount=survey_payout,
                    processed=False
                )

                # Add to referrer's earnings
                user.referred_by.referral_earnings += commission_amount
                user.referred_by.save(update_fields=['referral_earnings'])

                logger.info(
                    f"✅ Survey commission created: {commission.referrer.username} earns KSh {commission_amount}")
                return commission

        except Exception as e:
            logger.error(f"❌ Error creating survey commission: {str(e)}")
            return None

    @staticmethod
    def process_pending_commissions(referrer_user=None, auto_approve=False):
        """
        Process pending commissions and add to user balances
        Can be called for specific user or all users
        """
        filters = {'processed': False}
        if referrer_user:
            filters['referrer'] = referrer_user

        pending_commissions = ReferralCommission.objects.filter(**filters)
        processed_count = 0
        total_amount = Decimal('0')

        for commission in pending_commissions:
            try:
                with transaction.atomic():
                    # Add to referrer's balance
                    commission.referrer.balance += commission.commission_amount
                    commission.referrer.total_earnings += commission.commission_amount
                    commission.referrer.save(update_fields=['balance', 'total_earnings'])

                    # Mark commission as processed
                    commission.processed = True
                    commission.processed_at = timezone.now()
                    commission.save()

                    # Create transaction record
                    Transaction.objects.create(
                        user=commission.referrer,
                        amount=commission.commission_amount,
                        transaction_type='referral_commission',
                        description=f'Referral commission from {commission.referred_user.username} ({commission.commission_type})',
                        balance_after=commission.referrer.balance
                    )

                    processed_count += 1
                    total_amount += commission.commission_amount

                    logger.info(
                        f"✅ Processed commission: KSh {commission.commission_amount} to {commission.referrer.username}")

            except Exception as e:
                logger.error(f"❌ Error processing commission {commission.id}: {str(e)}")

        return {
            'processed_count': processed_count,
            'total_amount': total_amount
        }

    @staticmethod
    def get_referral_stats(user):
        """Get referral statistics for a user"""
        try:
            stats = {
                'total_referrals': user.total_referrals,
                'referral_earnings': user.referral_earnings,
                'pending_commissions': ReferralCommission.objects.filter(
                    referrer=user, processed=False
                ).count(),
                'processed_commissions': ReferralCommission.objects.filter(
                    referrer=user, processed=True
                ).count(),
                'referral_code': user.referral_code,
                'referred_users': User.objects.filter(referred_by=user).values_list('username', flat=True)
            }
            return stats
        except Exception as e:
            logger.error(f"❌ Error getting referral stats for {user.username}: {str(e)}")
            return None

    @staticmethod
    def debug_user_referrals(username):
        """Debug helper to check user's referral status"""
        try:
            user = User.objects.get(username=username)

            debug_info = {
                'user': user.username,
                'referral_code': user.referral_code,
                'referred_by': user.referred_by.username if user.referred_by else None,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
                'total_referrals': user.total_referrals,
                'referral_earnings': user.referral_earnings,
                'balance': user.balance,
                'commissions_earned': [],
                'commissions_generated': []
            }

            # Get commissions earned (as referrer)
            for comm in user.commissions_earned.all():
                debug_info['commissions_earned'].append({
                    'amount': str(comm.commission_amount),
                    'type': comm.commission_type,
                    'from_user': comm.referred_user.username,
                    'processed': comm.processed,
                    'created': comm.created_at.strftime('%Y-%m-%d %H:%M:%S')
                })

            # Get commissions generated (as referred user)
            for comm in user.commissions_generated.all():
                debug_info['commissions_generated'].append({
                    'amount': str(comm.commission_amount),
                    'type': comm.commission_type,
                    'to_user': comm.referrer.username,
                    'processed': comm.processed,
                    'created': comm.created_at.strftime('%Y-%m-%d %H:%M:%S')
                })

            logger.info(f"🔍 Debug info for {username}: {debug_info}")
            return debug_info

        except User.DoesNotExist:
            logger.error(f"❌ User {username} not found")
            return None

    @staticmethod
    def audit_admin_commissions():
        """
        Audit function to identify any existing commissions paid to admin/staff accounts
        Returns list of problematic commissions that should be reviewed
        """
        try:
            # Find all commissions where referrer is admin/staff
            admin_commissions = ReferralCommission.objects.filter(
                referrer__is_staff=True
            ) | ReferralCommission.objects.filter(
                referrer__is_superuser=True
            )

            audit_results = []
            total_incorrect_amount = Decimal('0')

            for commission in admin_commissions:
                audit_results.append({
                    'commission_id': commission.id,
                    'referrer': commission.referrer.username,
                    'referred_user': commission.referred_user.username if commission.referred_user else 'Unknown',
                    'amount': commission.commission_amount,
                    'type': commission.commission_type,
                    'processed': commission.processed,
                    'created_at': commission.created_at,
                    'is_staff': commission.referrer.is_staff,
                    'is_superuser': commission.referrer.is_superuser
                })
                total_incorrect_amount += commission.commission_amount

            logger.info(f"🔍 Audit found {len(audit_results)} commissions paid to admin/staff totaling KSh {total_incorrect_amount}")
            return {
                'total_commissions': len(audit_results),
                'total_amount': total_incorrect_amount,
                'commissions': audit_results
            }

        except Exception as e:
            logger.error(f"❌ Error during admin commission audit: {str(e)}")
            return None

    @staticmethod
    def reverse_admin_commissions(dry_run=True):
        """
        Reverse commissions that were incorrectly paid to admin/staff accounts
        Set dry_run=False to actually execute the reversals
        """
        try:
            admin_commissions = ReferralCommission.objects.filter(
                referrer__is_staff=True,
                processed=True
            ) | ReferralCommission.objects.filter(
                referrer__is_superuser=True,
                processed=True
            )

            reversal_results = []
            total_reversed = Decimal('0')

            for commission in admin_commissions:
                if dry_run:
                    reversal_results.append({
                        'action': 'WOULD_REVERSE',
                        'commission_id': commission.id,
                        'referrer': commission.referrer.username,
                        'amount': commission.commission_amount
                    })
                else:
                    with transaction.atomic():
                        # Subtract from referrer's balance and earnings
                        commission.referrer.balance -= commission.commission_amount
                        commission.referrer.total_earnings -= commission.commission_amount
                        commission.referrer.referral_earnings -= commission.commission_amount
                        commission.referrer.save()

                        # Create reversal transaction
                        Transaction.objects.create(
                            user=commission.referrer,
                            amount=-commission.commission_amount,
                            transaction_type='correction',
                            description=f'Reversal of inappropriate admin commission from {commission.referred_user.username if commission.referred_user else "Unknown"}',
                            balance_after=commission.referrer.balance
                        )

                        # Mark commission as reversed (you might want to add a 'reversed' field to your model)
                        commission.processed = False  # or add commission.reversed = True
                        commission.save()

                        reversal_results.append({
                            'action': 'REVERSED',
                            'commission_id': commission.id,
                            'referrer': commission.referrer.username,
                            'amount': commission.commission_amount
                        })

                total_reversed += commission.commission_amount

            action_type = "DRY RUN" if dry_run else "EXECUTED"
            logger.info(f"🔄 Commission reversal {action_type}: {len(reversal_results)} commissions totaling KSh {total_reversed}")

            return {
                'dry_run': dry_run,
                'total_reversed': total_reversed,
                'reversals': reversal_results
            }

        except Exception as e:
            logger.error(f"❌ Error during commission reversal: {str(e)}")
            return None