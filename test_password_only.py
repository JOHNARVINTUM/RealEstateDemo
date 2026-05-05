import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Test password generation without Django setup
def generate_password_test(first_name, last_name):
    """Test version of password generation"""
    if not first_name or not last_name:
        raise ValueError("Both first_name and last_name are required")
    
    # Split first name into parts to handle middle names
    name_parts = first_name.strip().split()
    
    # Get first letter of each part of the first name (including middle names)
    initials = ''.join([part[0].upper() for part in name_parts if part])
    
    # Combine with last name (preserve original casing, but strip whitespace)
    password = initials + last_name.strip()
    
    return password

# Test cases
test_cases = [
    ("mary-jane", "o'connor", "MJo'connor"),
    ("John", "Doe", "JDoe"),
    ("John Michael", "Smith", "JMSmith"),
]

print("Testing password generation:")
for first, last, expected in test_cases:
    result = generate_password_test(first, last)
    status = "PASS" if result == expected else "FAIL"
    print(f"{status}: '{first}' '{last}' -> '{result}' (expected: '{expected}')")
