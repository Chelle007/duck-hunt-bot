"""Gemini Flash image verification for duck claims."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from google import genai
from google.genai import types


@dataclass
class VerificationResult:
    is_duck: bool
    number_seen: Optional[int]
    match: bool
    suspicious: bool
    reason: str
    suspicion_reason: str


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def verify_duck_photo(
    api_key: str,
    model: str,
    image_bytes: bytes,
    mime_type: str,
    claimed_number: int,
) -> VerificationResult:
    """Verify that the photo shows a resin duck and the visible number matches."""
    client = genai.Client(api_key=api_key)

    prompt = f"""You are verifying submissions for a duck hunt game.

The player claims they found duck number {claimed_number}.

Look at the image and determine:
1. Is there a small resin duck toy visible in the photo? (Ducks may be any color — pink, blue, green, etc. Do not require a specific color.)
2. Is there a number written or printed under/near the duck?
3. Does the visible number match the claimed number {claimed_number}?
4. Does the image look suspicious or edited? (screenshot, downloaded image, cropped/edited number, collage, photoshopped, or not a fresh photo of a physical duck)

Respond with ONLY valid JSON in this exact shape:
{{
  "is_duck": true or false,
  "number_seen": integer or null if unreadable,
  "match": true or false,
  "suspicious": true or false,
  "suspicion_reason": "short explanation if suspicious, otherwise empty string",
  "reason": "short explanation"
}}

Rules:
- "is_duck" is true only if a small resin duck toy is clearly visible. Color does not matter.
- "number_seen" should be the number you can read from the image, or null if unreadable.
- "match" is true only if is_duck is true AND number_seen equals {claimed_number}.
- "suspicious" is true if the image might be fake, edited, a screenshot of another photo, or not a trustworthy fresh photo of a real duck.
- When in doubt about authenticity, set suspicious to true.
- If the image is blurry or the number is unclear, set number_seen to null and match to false.
"""

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            prompt,
        ],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        ),
    )

    raw_text = (response.text or "").strip()
    if not raw_text:
        return VerificationResult(
            is_duck=False,
            number_seen=None,
            match=False,
            suspicious=False,
            reason="Gemini returned an empty response.",
            suspicion_reason="",
        )

    try:
        data = _extract_json(raw_text)
    except (json.JSONDecodeError, TypeError):
        return VerificationResult(
            is_duck=False,
            number_seen=None,
            match=False,
            suspicious=False,
            reason="Could not parse verification response.",
            suspicion_reason="",
        )

    number_seen = data.get("number_seen")
    if number_seen is not None:
        try:
            number_seen = int(number_seen)
        except (TypeError, ValueError):
            number_seen = None

    is_duck = bool(data.get("is_duck", False))
    suspicious = bool(data.get("suspicious", False))
    suspicion_reason = str(data.get("suspicion_reason", "")).strip()
    reason = str(data.get("reason", "No reason provided."))

    if is_duck and number_seen == claimed_number:
        match = True
    else:
        match = False

    return VerificationResult(
        is_duck=is_duck,
        number_seen=number_seen,
        match=match,
        suspicious=suspicious,
        reason=reason,
        suspicion_reason=suspicion_reason,
    )
