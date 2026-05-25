"""
PayMongo Checkout Session API helper.
Docs: https://developers.paymongo.com/reference/create-a-checkout
"""
import base64
import hashlib
import hmac
import json
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PAYMONGO_API_BASE = "https://api.paymongo.com/v1"
WEBHOOK_TOLERANCE_SECONDS = 300  # 5 minute tolerance for timestamp


def verify_webhook_signature(payload_body: bytes, signature_header: str, webhook_secret: str) -> bool:
    """
    Verify PayMongo webhook signature.
    
    PayMongo uses a tolerance token scheme:
    Signature format: t=<timestamp>,v1=<signature>
    Signed payload: t=<timestamp>.<json_payload>
    
    Args:
        payload_body: Raw request body bytes
        signature_header: The 'Paymongo-Signature' header value
        webhook_secret: The webhook secret from PayMongo dashboard
        
    Returns:
        bool: True if signature is valid, False otherwise
    """
    if not signature_header or not webhook_secret:
        logger.warning("Missing signature header or webhook secret")
        return False
    
    try:
        # Parse signature header: t=<timestamp>,v1=<signature>
        signatures = {}
        for item in signature_header.split(','):
            if '=' in item:
                key, value = item.split('=', 1)
                signatures[key.strip()] = value.strip()
        
        timestamp_str = signatures.get('t')
        signature = signatures.get('v1')
        
        if not timestamp_str or not signature:
            logger.warning(f"Invalid signature format: {signature_header}")
            return False
        
        # Check timestamp tolerance (prevent replay attacks)
        try:
            timestamp = int(timestamp_str)
            current_time = int(time.time())
            if abs(current_time - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
                logger.warning(f"Webhook timestamp too old: {timestamp}, current: {current_time}")
                return False
        except ValueError:
            logger.warning(f"Invalid timestamp in signature: {timestamp_str}")
            return False
        
        # Compute expected signature
        # Signed payload format: "t=<timestamp>.<json_payload>"
        signed_payload = f"t={timestamp_str}.{payload_body.decode('utf-8')}"
        
        mac = hmac.new(
            webhook_secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        )
        expected_signature = mac.hexdigest()
        
        # Use constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(signature, expected_signature)
        
        if not is_valid:
            logger.warning(f"Signature mismatch. Expected: {expected_signature[:16]}..., Got: {signature[:16]}...")
        
        return is_valid
        
    except Exception as e:
        logger.exception(f"Error verifying webhook signature: {e}")
        return False


def _auth_header():
    """Basic auth header using the secret key."""
    key = settings.PAYMONGO_SECRET_KEY
    
    # Validate that API key is configured
    if not key:
        logger.error("PAYMONGO_SECRET_KEY is not configured! Check your .env file.")
        raise ValueError("PayMongo API key not configured. Please set PAYMONGO_SECRET_KEY in your .env file.")
    
    # Validate key format (PayMongo keys start with 'sk_' or 'pk_')
    if not (key.startswith('sk_') or key.startswith('pk_')):
        logger.warning(f"PAYMONGO_SECRET_KEY appears invalid (should start with 'sk_' or 'pk_'). Current value starts with: {key[:10] if key else 'EMPTY'}...")
    
    encoded = base64.b64encode(f"{key}:".encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


def is_paymongo_configured():
    """Check if PayMongo is properly configured."""
    return bool(settings.PAYMONGO_SECRET_KEY and settings.PAYMONGO_SECRET_KEY.startswith('sk_'))


def create_checkout_session(
    amount_cents: int,
    description: str,
    metadata: dict,
    success_url: str,
    cancel_url: str,
):
    """
    Create a PayMongo Checkout Session.

    Args:
        amount_cents: Amount in centavos (e.g. 1700000 for ₱17,000.00)
        description: Line item description shown on checkout page
        metadata: Dict with bill_ids, user_id, payment_type etc.
        success_url: Where to redirect after successful payment
        cancel_url: Where to redirect if tenant cancels

    Returns:
        dict with 'checkout_session_id' and 'checkout_url' on success,
        or None on failure.
    """
    payload = {
        "data": {
            "attributes": {
                "send_email_receipt": True,
                "show_description": True,
                "show_line_items": True,
                "description": description,
                "line_items": [
                    {
                        "currency": "PHP",
                        "amount": amount_cents,
                        "name": description,
                        "quantity": 1,
                    }
                ],
                "payment_method_types": [
                    "gcash",
                    "grab_pay",
                    "card",
                ],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata,
            }
        }
    }

    # Check if PayMongo is configured before attempting API call
    if not is_paymongo_configured():
        logger.error("PayMongo checkout attempted but API key not configured!")
        return {"error": "PayMongo not configured", "checkout_session_id": None, "checkout_url": None}
    
    try:
        resp = requests.post(
            f"{PAYMONGO_API_BASE}/checkout_sessions",
            headers=_auth_header(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return {
            "checkout_session_id": data["id"],
            "checkout_url": data["attributes"]["checkout_url"],
        }
    except requests.exceptions.HTTPError as e:
        error_detail = e.response.text[:500] if e.response else 'no response'
        status_code = e.response.status_code if e.response else 'unknown'
        logger.error(f"PayMongo HTTP {status_code} error: {error_detail}")
        
        # Provide more specific error messages
        if e.response and e.response.status_code == 401:
            logger.error("PayMongo authentication failed! Check that PAYMONGO_SECRET_KEY is correct.")
        return None
    except ValueError as e:
        logger.error(f"PayMongo configuration error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logger.exception(f"PayMongo create_checkout_session failed: {e}")
        return None


def retrieve_checkout_session(session_id: str):
    """
    Retrieve a checkout session to check its payment status.

    Returns the full session data dict, or None on failure.
    """
    try:
        resp = requests.get(
            f"{PAYMONGO_API_BASE}/checkout_sessions/{session_id}",
            headers=_auth_header(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"]
    except requests.exceptions.RequestException as e:
        logger.exception(f"PayMongo retrieve_checkout_session failed: {e}")
        return None
