"""
Stage 3: Send PDF batches to Claude API for offer extraction.
Supports prompt caching (system prompt cached after first call).
Returns parsed JSON offer arrays with usage stats.
"""

import json
import os
import time

import httpx

from .config import API_URL, MAX_OUTPUT_TOKENS


class APIError(Exception):
    pass


class ClassificationResult:
    def __init__(self):
        self.all_offers = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_calls = 0
        self.total_time = 0.0
        self.errors = []


def get_api_key():
    """Get API key from environment or .env file."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        # Try loading from .env in current directory
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ANTHROPIC_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    return key


def call_claude(model, system_prompt, user_message, api_key, use_cache=False):
    """
    Make a single Claude API call.
    Returns (offers_list, usage_dict, elapsed_seconds).
    """
    # Build system content with optional cache control
    if use_cache:
        system_content = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    else:
        system_content = system_prompt

    payload = {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": system_content,
        "messages": [{"role": "user", "content": user_message}],
    }

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    if use_cache:
        headers["anthropic-beta"] = "prompt-caching-2024-07-31"

    start = time.time()
    resp = httpx.post(API_URL, json=payload, headers=headers, timeout=180)
    elapsed = time.time() - start

    if resp.status_code != 200:
        raise APIError(f"API returned {resp.status_code}: {resp.text}")

    data = resp.json()
    usage = data.get("usage", {})

    # Extract text content
    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block["text"]

    # Parse JSON response
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()

    try:
        offers = json.loads(text)
    except json.JSONDecodeError as e:
        raise APIError(f"Failed to parse JSON response: {e}\nRaw (first 500): {text[:500]}")

    if not isinstance(offers, list):
        raise APIError(f"Expected JSON array, got {type(offers).__name__}")

    return offers, usage, elapsed


def classify_batches(batches, model_id, system_prompt, api_key, progress_callback=None):
    """
    Run classification across all batches.
    progress_callback(batch_idx, total_batches, batch_offers, usage, elapsed) called after each.
    Returns ClassificationResult.
    """
    result = ClassificationResult()

    for i, (user_message, doc_count) in enumerate(batches):
        use_cache = True  # always enable caching; API handles cache hits on call 2+

        try:
            offers, usage, elapsed = call_claude(
                model_id, system_prompt, user_message, api_key, use_cache=use_cache
            )
            result.all_offers.extend(offers)
            result.total_input_tokens += usage.get("input_tokens", 0)
            result.total_output_tokens += usage.get("output_tokens", 0)
            result.total_calls += 1
            result.total_time += elapsed

            if progress_callback:
                progress_callback(i, len(batches), offers, usage, elapsed)

        except APIError as e:
            result.errors.append(f"Batch {i + 1}: {e}")
            if progress_callback:
                progress_callback(i, len(batches), [], {}, 0)

    return result
