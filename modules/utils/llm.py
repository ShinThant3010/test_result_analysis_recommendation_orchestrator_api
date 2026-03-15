from __future__ import annotations

import time

from modules.utils.genai_client import get_genai_client
from modules.utils.run_logging import extract_token_counts, log_llm_call


def generate_content_with_logging(
    *,
    model: str,
    prompt: str,
    log_name: str,
) -> str:
    """Generate content using the GenAI client while logging input/output tokens and runtime."""
    
    client = get_genai_client()
    start = time.time()
    response = client.models.generate_content(
        model=model,
        contents=[{"parts": [{"text": prompt}]}],
    )
    raw_text = (response.text or "").strip()
    input_tokens, output_tokens = extract_token_counts(response)
    log_llm_call(
        name=log_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        llm_runtime=time.time() - start,
    )
    return raw_text
