"""Hosted free-tier provider (Groq, Google AI Studio, OpenRouter).

The key arrives as LLM_API_KEY from a Kubernetes Secret created on the command
line. It never appears in a file you commit, and never in a log line.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from ...config import Settings
from ...routes.metrics import GENERATION_LATENCY, TOKENS_IN, TOKENS_OUT
from ...schemas import Answer, Passage
from .ollama import SYSTEM_PROMPT, build_evidence_block, safe_fallback_answer

log = logging.getLogger("rahbar.llm.hosted")


class HostedProvider:
    name = "hosted"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings  # hosted_base_url, llm_model, llm_api_key, temperature, llm_timeout

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        evidence_text = build_evidence_block(passages)
        user_message = f"Retrieved Passages:\n{evidence_text}\n\nQuestion: {question}"

        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": self.settings.temperature,
            "response_format": {"type": "json_object"},  # Constrained JSON mode
        }

        est_tokens_in = (len(SYSTEM_PROMPT) + len(user_message)) // 4
        TOKENS_IN.inc(est_tokens_in)

        max_attempts = 2
        last_error = ""

        with GENERATION_LATENCY.time():
            for attempt in range(1, max_attempts + 1):
                try:
                    url = f"{self.settings.hosted_base_url.rstrip('/')}/chat/completions"
                    with httpx.Client(timeout=self.settings.llm_timeout) as client:
                        resp = client.post(url, headers=headers, json=payload)
                        resp.raise_for_status()
                        data = resp.json()

                    choices = data.get("choices", [])
                    if not choices:
                        raise ValueError("No choices in LLM completion response")
                    content = choices[0].get("message", {}).get("content", "")
                    TOKENS_OUT.inc(len(content) // 4)

                    # Validate model output with Pydantic
                    answer_obj = Answer.model_validate_json(content)
                    return answer_obj

                except (httpx.HTTPError, json.JSONDecodeError, ValidationError, ValueError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    log.warning(
                        "Hosted generation attempt %d failed: %s; retrying=%s",
                        attempt,
                        last_error,
                        attempt < max_attempts,
                    )

        log.error("All %d hosted generation attempts failed (%s); returning safe fallback", max_attempts, last_error)
        return safe_fallback_answer(last_error)
