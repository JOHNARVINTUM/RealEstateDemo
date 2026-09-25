"""Local-only settings. Never falls back to Supabase configuration."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / '.env.local')

from .settings import *  # noqa: F403


ENVIRONMENT = "local"
IS_PRODUCTION = False
DEBUG = True

_required = (
    "LOCAL_DB_NAME",
    "LOCAL_DB_USER",
    "LOCAL_DB_PASSWORD",
)

_missing = [key for key in _required if not os.environ.get(key)]

if _missing:
    raise ImproperlyConfigured(
        "Local PostgreSQL configuration is incomplete. Set: "
        + ", ".join(_missing)
    )

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["LOCAL_DB_NAME"],
        "USER": os.environ["LOCAL_DB_USER"],
        "PASSWORD": os.environ["LOCAL_DB_PASSWORD"],
        "HOST": os.environ.get("LOCAL_DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("LOCAL_DB_PORT", "5432"),
        "TEST": {
            "NAME": os.environ.get(
                "LOCAL_TEST_DB_NAME",
                "realestatedemo_test",
            ),
        },
        "DISABLE_SERVER_SIDE_CURSORS": True,
    }
}