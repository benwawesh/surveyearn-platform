import re

with open('accounts/views.py', 'r') as f:
    content = f.read()

# Fix the main structural issue: ensure else block is properly indented
# Replace the broken else block structure
old_pattern = r'''            else:

            # Prepare M-Pesa STK Push
                phone_number = form\.cleaned_data\['phone_number'\]
                username = form\.cleaned_data\['username'\]
                # UPDATED: Use dynamic fee from settings
                amount = settings_service\.get_registration_fee\(\)

            if referral_established:'''

new_pattern = '''            else:
                # Prepare M-Pesa STK Push
                phone_number = form.cleaned_data['phone_number']
                username = form.cleaned_data['username']
                # UPDATED: Use dynamic fee from settings
                amount = settings_service.get_registration_fee()

                if referral_established:'''

content = content.replace(old_pattern, new_pattern)

# Fix any remaining indentation issues with the block that follows
content = re.sub(
    r'(\n            if referral_established:\n\n            # Format phone number properly)',
    r'\n                if referral_established:\n                    # Format phone number properly',
    content
)

with open('accounts/views.py', 'w') as f:
    f.write(content)

print("Applied structural fix to accounts/views.py")
