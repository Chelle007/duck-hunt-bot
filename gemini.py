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
    reason: str


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

    prompt = f"""You are a strict photo verifier for a duck hunt game. Players must send an unedited in-person photo of a numbered resin duck toy.

The player claims they found duck number {claimed_number}.

Examine the image carefully for signs of cheating or editing.

Respond with ONLY valid JSON in this exact shape:
{{
  "is_duck": true or false,
  "number_seen": integer or null if unreadable,
  "number_is_physical": true or false,
  "image_authentic": true or false,
  "match": true or false,
  "reason": "short explanation"
}}

Field definitions:
- "is_duck": true only if a small resin DUCK-SHAPED toy is clearly visible (not a bottle, gem, or other shape). Color does not matter.
- "number_seen": the integer you can read, or null if unreadable.
- "number_is_physical": true only if the number appears on a real physical label, sticker, tag, or handwriting on/near the duck — with natural lighting, perspective, and edges that belong in the scene. false if the number looks digitally added, pasted, photoshopped, drawn in an editor, on a flat white/colored rectangle overlay, has a drop shadow from editing, has unnaturally sharp rectangular borders, or does not follow the surface curvature/lighting of the object.
- "image_authentic": true only if this looks like a single unedited photo taken in person right now. false for screenshots, downloaded images, collages, heavy filters, or any edited/composited image.
- "match": true ONLY when ALL of these are true: is_duck, number_seen equals {claimed_number}, number_is_physical, image_authentic.

REJECT examples (set number_is_physical=false and/or image_authentic=false and match=false):
- A number on a white square pasted onto the object with perfect sharp edges
- Digital text overlay or markup added after the photo was taken
- A number floating on the image without a physical sticker/tag
- Screenshot of another photo
- Number that looks too crisp/clean compared to the rest of the photo

When unsure about editing or overlays, set number_is_physical=false, image_authentic=false, and match=false.
If blurry or number unclear, set number_seen=null and match=false.
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
            reason="Gemini returned an empty response.",
        )

    try:
        data = _extract_json(raw_text)
    except (json.JSONDecodeError, TypeError):
        return VerificationResult(
            is_duck=False,
            number_seen=None,
            match=False,
            reason="Could not parse verification response.",
        )

    number_seen = data.get("number_seen")
    if number_seen is not None:
        try:
            number_seen = int(number_seen)
        except (TypeError, ValueError):
            number_seen = None

    is_duck = bool(data.get("is_duck", False))
    number_is_physical = bool(data.get("number_is_physical", False))
    image_authentic = bool(data.get("image_authentic", False))
    reason = str(data.get("reason", "No reason provided."))

    match = bool(data.get("match", False))
    if (
        not is_duck
        or number_seen != claimed_number
        or not number_is_physical
        or not image_authentic
    ):
        match = False

    return VerificationResult(
        is_duck=is_duck,
        number_seen=number_seen,
        match=match,
        reason=reason,
    )
