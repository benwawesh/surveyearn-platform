with open('accounts/views.py', 'r') as f:
    lines = f.readlines()

# Fix the specific indentation issues
for i, line in enumerate(lines):
    line_num = i + 1
    
    # Fix line 137: else block content needs proper indentation
    if line_num == 139 and line.strip() == "# Prepare M-Pesa STK Push":
        lines[i] = "                # Prepare M-Pesa STK Push\n"
    
    # Fix lines 140-143: these should be indented under the else block
    elif line_num in [140, 141, 142, 143] and line.strip() and not line.strip().startswith("if referral_established"):
        if not line.startswith("                "):
            lines[i] = "                " + line.lstrip() + "\n"
    
    # Fix the if referral_established line
    elif line_num == 144 and "if referral_established:" in line:
        lines[i] = "                if referral_established:\n"
    
    # Fix lines after if referral_established (should be indented further)
    elif line_num >= 145 and line.strip() and not line.startswith("                    "):
        if any(keyword in line for keyword in ["formatted_phone", "if not MPesaService", "user.delete", "messages.error", "return render"]):
            lines[i] = "                    " + line.lstrip() + "\n"

with open('accounts/views.py', 'w') as f:
    f.writelines(lines)

print("Fixed indentation issues")
