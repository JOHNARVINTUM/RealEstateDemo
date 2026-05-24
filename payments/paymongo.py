"""
PayMongo Checkout Session API helper.
Docs: https://developers.paymongo.com/reference/create-a-checkout
"""
import base64
import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PAYMONGO_API_BASE = "https://api.paymongo.com/v1"


def _auth_header():
    """Basic auth header using the secret key."""
    key = settings.PAYMONGO_SECRET_KEY
    encoded = base64.b64encode(f"{key}:".encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


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
        logger.error(f"PayMongo create_checkout_session HTTP error: {e} — Response: {e.response.text[:500] if e.response else 'no response'}")
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
