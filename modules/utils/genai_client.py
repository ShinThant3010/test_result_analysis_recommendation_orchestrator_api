from __future__ import annotations

import os

from google import genai


def get_genai_client() -> genai.Client:
    """Initialize and return a GenAI client using the GOOGLE_API_KEY environment variable."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is missing")
    return genai.Client(api_key=api_key)
