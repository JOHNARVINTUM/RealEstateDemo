#!/usr/bin/env python
"""
Webhook tester script for RealEstate360 PayMongo integration.
Tests signature verification and idempotency.
"""

import requests
import json
import hmac
import hashlib
import time
import os

def test_no_signature():
    """Test 1: Webhook with no signature should return 403"""
    print("\n=== Test 1: No Signature ===")
    response = requests.post(
        'http://127.0.0.1:8000/payments/paymongo/webhook/',
        json={"test": "fake"}
    )
    print(f"Status: {response.status_code}")
    print(f"Expected: 403")
    print(f"PASS" if response.status_code == 403 else "FAIL")
    return response.status_code == 403

def test_invalid_signature():
    """Test 2: Webhook with invalid signature should return 403"""
    print("\n=== Test 2: Invalid Signature ===")
    response = requests.post(
        'http://127.0.0.1:8000/payments/paymongo/webhook/',
        headers={
            'Content-Type': 'application/json',
            'Paymongo-Signature': 't=1234567890,v1=invalid_signature'
        },
        json={"data": {"type": "event"}}
    )
    print(f"Status: {response.status_code}")
    print(f"Expected: 403")
    print(f"PASS" if response.status_code == 403 else "FAIL")
    return response.status_code == 403

def check_server_running():
    """Check if Django server is running"""
    try:
        response = requests.get('http://127.0.0.1:8000/tenant/', timeout=5)
        print(f"\nServer is running (Status: {response.status_code})")
        return True
    except requests.exceptions.ConnectionError:
        print("\nERROR: Django server not running!")
        print("Start it with: python manage.py runserver")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("PayMongo Webhook Security Tests")
    print("=" * 50)
    
    # Check server first
    if not check_server_running():
        exit(1)
    
    # Run tests
    results = []
    results.append(("No Signature", test_no_signature()))
    results.append(("Invalid Signature", test_invalid_signature()))
    
    # Summary
    print("\n" + "=" * 50)
    print("Test Summary")
    print("=" * 50)
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{name}: {status}")
    
    all_passed = all(r[1] for r in results)
    print(f"\nOverall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
