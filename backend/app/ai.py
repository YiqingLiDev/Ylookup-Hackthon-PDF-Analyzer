"""Shared Gemini client + structured-output call helper.

Every pipeline stage (extract, verify, enrich) calls Gemini with forced
JSON-schema-constrained output and the same max-2-retries-then-degrade
pattern, so that logic lives here once instead of three times.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 2

T = TypeVar("T", bound=BaseModel)

_client: genai.Client | None = None
_client_init_attempted = False


def get_client() -> genai.Client | None:
    global _client, _client_init_attempted
    if _client_init_attempted:
        return _client
    _client_init_attempted = True

    if not settings.gemini_api_key:
        logger.error("GEMINI_API_KEY not set; Gemini calls will be skipped")
        return None

    try:
        _client = genai.Client(api_key=settings.gemini_api_key)
        logger.info("Gemini client constructed (model=%s)", settings.gemini_model)
    except Exception as exc:
        logger.error("could not construct Gemini client: %s", exc)
        _client = None
    return _client


def generate_structured(parts: list, response_schema: type[T], label: str = "") -> T | None:
    """Call Gemini with forced JSON-schema output, retrying up to MAX_RETRIES
    times. Returns the parsed pydantic instance, or None if every attempt
    (including retries) failed -- callers are responsible for degrading
    gracefully rather than treating None as fatal.

    `label` is just for console visibility (e.g. "extract statement.pdf",
    "verify statement.pdf p2") so it's obvious which call is running/failing.
    """
    tag = f"[{label}] " if label else ""

    client = get_client()
    if client is None:
        logger.error("%sskipping Gemini call: no client available (is GEMINI_API_KEY set?)", tag)
        return None

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            logger.info(
                "%scalling Gemini (model=%s, attempt %s/%s)",
                tag, settings.gemini_model, attempt + 1, MAX_RETRIES + 1,
            )
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=parts,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                ),
            )
            if response.parsed is not None:
                logger.info("%sGemini call succeeded", tag)
                return response.parsed
            last_error = ValueError("Gemini returned no parsed structured output")
        except Exception as exc:
            last_error = exc
            logger.warning("%sGemini call attempt %s/%s failed: %s", tag, attempt + 1, MAX_RETRIES + 1, exc)

    logger.error("%sGemini call failed after %s attempts: %s", tag, MAX_RETRIES + 1, last_error)
    return None


def pdf_part(data: bytes) -> types.Part:
    return types.Part.from_bytes(data=data, mime_type="application/pdf")


def image_part(data: bytes) -> types.Part:
    return types.Part.from_bytes(data=data, mime_type="image/png")
