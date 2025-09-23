from django.db import migrations, models
import django.db.models.deletion
import uuid
from decimal import Decimal


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_user_country_user_mpesa_checkout_request_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='referral_code',
            field=models.CharField(blank=True, max_length=10, help_text='Unique referral code for this user'),
        ),
        migrations.AddField(
            model_name='user',
            name='referred_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='referrals', to='accounts.user',
                                    help_text='User who referred this user'),
        ),
        migrations.AddField(
            model_name='user',
            name='referral_earnings',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10,
                                      help_text='Total earnings from referral commissions'),
        ),
        migrations.AddField(
            model_name='user',
            name='total_referrals',
            field=models.PositiveIntegerField(default=0, help_text='Total number of users referred by this user'),
        ),
        migrations.CreateModel(
            name='ReferralCommission',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('commission_amount',
                 models.DecimalField(decimal_places=2, help_text='Commission amount earned', max_digits=10)),
                ('commission_type',
                 models.CharField(choices=[('registration', 'Registration'), ('survey', 'Survey Completion')],
                                  help_text='Type of activity that generated this commission', max_length=20)),
                ('source_amount', models.DecimalField(decimal_places=2,
                                                      help_text='Original transaction amount that generated this commission',
                                                      max_digits=10)),
                ('processed',
                 models.BooleanField(default=False, help_text='Whether this commission has been paid out')),
                ('processed_at',
                 models.DateTimeField(blank=True, help_text='When this commission was processed', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='When this commission was created')),
                ('referrer', models.ForeignKey(help_text='User who earned the commission',
                                               on_delete=django.db.models.deletion.CASCADE,
                                               related_name='commissions_earned', to='accounts.user')),
                ('referred_user', models.ForeignKey(help_text='User who generated the commission',
                                                    on_delete=django.db.models.deletion.CASCADE,
                                                    related_name='commissions_generated', to='accounts.user')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='referralcommission',
            index=models.Index(fields=['referrer', '-created_at'], name='accounts_re_referre_f8b9a3_idx'),
        ),
        migrations.AddIndex(
            model_name='referralcommission',
            index=models.Index(fields=['processed', '-created_at'], name='accounts_re_process_c75e9a_idx'),
        ),
    ]