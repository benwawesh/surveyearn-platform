# Read the current file
with open('accounts/views.py', 'r') as f:
    content = f.read()

# Find the start and end of user_register function
start_marker = 'def user_register(request):'
end_marker = 'def user_login(request):'

start_pos = content.find(start_marker)
end_pos = content.find(end_marker)

if start_pos == -1 or end_pos == -1:
    print("Could not find function boundaries")
    exit(1)

# Extract parts before and after the function
before_function = content[:start_pos]
after_function = content[end_pos:]

# Create a corrected user_register function
corrected_function = '''def user_register(request):
    """Paid user registration with M-Pesa STK push and referral processing"""
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    # UPDATED: Use SettingsService for dynamic configuration
    settings_service = SettingsService()

    # ADDED: Check for referral info in session
    referral_info = None
    referral_code = request.session.get('referral_code')

    if referral_code:
        try:
            referrer = User.objects.get(referral_code=referral_code)
            # UPDATED: Use dynamic fee and commission rate
            amount = settings_service.get_registration_fee()
            commission_rate = settings_service.get_referral_commission_rate()

            # FIXED: Only show commission info for non-admin/staff referrers
            if referrer.is_staff or referrer.is_superuser:
                commission_amount = Decimal('0.00')  # No commission for admin/staff
                logger.info(
                    f"Registration with admin/staff referral from {referrer.username} - no commission will be paid")
            else:
                commission_amount = Decimal(str(amount)) * commission_rate
                logger.info(f"Registration with referral from {referrer.username}")

            referral_info = {
                'referrer_name': referrer.get_full_name() or referrer.username,
                'referrer_username': referrer.username,
                'referral_code': referral_code,
                'commission_amount': commission_amount,
                'registration_fee': amount,
                'is_admin_staff': referrer.is_staff or referrer.is_superuser  # ADDED: Flag for template
            }

        except User.DoesNotExist:
            logger.warning(f"Invalid referral code in session: {referral_code}")
            # Clean up invalid referral code
            del request.session['referral_code']
            if 'referrer_username' in request.session:
                del request.session['referrer_username']

    if request.method == 'POST':
        form = PaidUserRegistrationForm(request.POST)

        if form.is_valid():
            # Create user account (inactive until payment)
            user = form.save()

            # ENHANCED: Process referral relationship with atomic transaction and verification
            referral_code = request.session.get('referral_code')
            referral_established = False

            if referral_code:
                try:
                    # Use atomic transaction to ensure consistency
                    with transaction.atomic():
                        referrer = User.objects.get(referral_code=referral_code)

                        # Set the referral relationship
                        user.referred_by = referrer
                        user.save()

                        # Update referrer's total count (even for admin/staff for tracking purposes)
                        referrer.total_referrals += 1
                        referrer.save()

                        # Verify the relationship was saved correctly
                        user.refresh_from_db()
                        if user.referred_by == referrer:
                            referral_established = True

                            # UPDATED: Different logging for admin/staff vs regular referrers
                            if referrer.is_staff or referrer.is_superuser:
                                logger.info(
                                    f"User {user.username} referred by admin/staff {referrer.username} (no commission)")
                            else:
                                logger.info(f"User {user.username} successfully referred by {referrer.username}")
                        else:
                            logger.error(f"Failed to establish referral relationship for {user.username}")

                        # Only clear session if relationship was successfully established
                        if referral_established:
                            if 'referral_code' in request.session:
                                del request.session['referral_code']
                            if 'referrer_username' in request.session:
                                del request.session['referrer_username']
                            if 'referral_message' in request.session:
                                del request.session['referral_message']

                except User.DoesNotExist:
                    logger.error(f"Referral code {referral_code} not found during registration")
                except Exception as e:
                    logger.error(f"Error processing referral for {user.username}: {str(e)}")
                    import traceback
                    traceback.print_exc()

            # Prepare M-Pesa STK Push
            phone_number = form.cleaned_data['phone_number']
            username = form.cleaned_data['username']
            # UPDATED: Use dynamic fee from settings
            amount = settings_service.get_registration_fee()

            # Format phone number properly
            formatted_phone = MPesaService.format_phone_number(phone_number)

            # Validate phone number
            if not MPesaService.validate_phone_number(formatted_phone):
                user.delete()
                messages.error(request, "Please enter a valid Kenyan phone number (07XX XXX XXX or 01XX XXX XXX)")
                return render(request, 'accounts/register.html', {
                    'form': form,
                    'title': 'Register for SurveyEarn',
                    'registration_fee': amount,
                    'referral_info': referral_info  # ADDED: Pass referral info to template
                })

            # Trigger M-Pesa STK Push
            stk_response = initiate_stk_push(
                phone_number=formatted_phone,
                amount=amount,
                account_reference=username,
                transaction_desc=f"SurveyEarn registration fee for {username}"
            )

            if stk_response.get('success'):
                # Store the checkout request ID for verification
                user.mpesa_checkout_request_id = stk_response.get('checkout_request_id')
                user.registration_amount = amount
                user.phone_number = formatted_phone
                user.save()

                # Send welcome email
                try:
                    EmailService.send_welcome_email(user)
                    logger.info(f"Welcome email sent to {user.email}")
                except Exception as e:
                    logger.error(f"Failed to send welcome email to {user.email}: {e}")

                # FIXED: Success message with proper admin/staff handling
                if user.referred_by:
                    if user.referred_by.is_staff or user.referred_by.is_superuser:
                        # Admin/staff referral - mention referrer but no commission
                        messages.success(request,
                                         f"Registration initiated! You were referred by {user.referred_by.get_full_name() or user.referred_by.username}. "
                                         f"Please complete payment of KSh {amount} on your phone ({formatted_phone}) to activate your account."
                                         )
                    else:
                        # Regular referral - mention commission
                        messages.success(request,
                                         f"Registration initiated! You were referred by {user.referred_by.get_full_name() or user.referred_by.username}. "
                                         f"Please complete payment of KSh {amount} on your phone ({formatted_phone}) to activate your account."
                                         )
                else:
                    messages.success(request,
                                     f"Registration initiated! Please complete payment of KSh {amount} "
                                     f"on your phone ({formatted_phone}) to activate your account."
                                     )

                return redirect('accounts:payment_confirmation', user_id=user.id)
            else:
                user.delete()
                error_msg = stk_response.get('error', 'Payment system temporarily unavailable')
                messages.error(request, f"Payment initiation failed: {error_msg}")

        else:
            messages.error(request, "Please correct the errors below.")

    else:
        form = PaidUserRegistrationForm()

    # UPDATED: Use SettingsService for dynamic context values
    context = {
        'form': form,
        'title': 'Register for SurveyEarn',
        'registration_fee': settings_service.get_registration_fee(),
        'referral_info': referral_info,  # ADDED: Pass referral info to template
        'commission_rate': int(settings_service.get_referral_commission_rate() * 100)  # UPDATED: Dynamic rate
    }
    return render(request, 'accounts/register.html', context)


'''

# Reconstruct the file
new_content = before_function + corrected_function + after_function

# Write back to file
with open('accounts/views.py', 'w') as f:
    f.write(new_content)

print("Fixed user_register function structure and indentation")
