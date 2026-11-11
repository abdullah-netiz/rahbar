"""POST /api/ask. The Ingress sends /api/* here unchanged, so the prefix stays."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import AskRequest, AskResponse
from ..services.answer import answer_question

router = APIRouter(prefix="/api")


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request) -> AskResponse:
    state = request.app.state
    provider = state.provider

    if body.provider:
        p_name = body.provider.lower().strip()
        if "groq" in p_name or "hosted" in p_name:
            from ..providers.llm.hosted import HostedProvider
            provider = HostedProvider(state.settings)
        elif "ollama" in p_name:
            import os
            from dataclasses import replace
            from ..providers.llm.ollama import OllamaProvider

            ollama_url = os.environ.get("OLLAMA_URL", state.settings.ollama_url)
            if "minikube" in ollama_url:
                ollama_url = "http://host.docker.internal:11434"
            ollama_settings = replace(
                state.settings,
                ollama_url=ollama_url,
                llm_model=os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
            )
            provider = OllamaProvider(ollama_settings)

    return answer_question(
        body.question,
        state.retriever,
        provider,
        state.settings,
        is_followup=body.is_followup,
    )
