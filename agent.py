"""The reasoning core: prompt, LLM call, and the guardrail validator that
keeps pseudo-psychology out of answers."""
import logging

import requests

from .config import settings

logger = logging.getLogger("psyche.agent")


SYSTEM_PROMPT = """You are a psychology information assistant for a Persian-language application.
You provide evidence-based psychological information drawn ONLY from the verified
clinical sources supplied to you in the CONTEXT section.

RULES:
1. Use ONLY the provided context. Do not rely on outside or remembered knowledge.
2. If the context does not contain enough information, reply with exactly:
   INSUFFICIENT_CONTEXT
3. Never give a diagnosis. Never recommend medication, dosage, or treatment plans.
4. Stay neutral, factual, and compassionate.
5. Recommend consulting a licensed psychologist or psychiatrist for personal concerns.
6. If the question suggests immediate danger or crisis, advise the person to contact
   local emergency services or a crisis line.

Answer concisely in English. Cite the source name in parentheses where relevant.
"""

# Phrases typical of pop-/pseudo-psychology. Their presence lowers confidence.
POP_PSYCH_FLAGS = [
    "guaranteed", "100%", "always works", "miracle", "cure everything",
    "energy healing", "vibration", "crystal", "manifest your", "instant fix",
]


def generate(prompt: str) -> str:
    """Call the local Ollama model and return its completion."""
    resp = requests.post(
        f"{settings.ollama_url}/api/generate",
        json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def build_prompt(question: str, passages: list[dict]) -> str:
    """Assemble the final prompt from retrieved, verified passages."""
    context = "\n\n".join(
        f"[Source: {p['source_name']} | trust={p['trust_score']}]\n{p['content']}"
        for p in passages
    )
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"=== CONTEXT ===\n{context}\n\n"
        f"=== QUESTION ===\n{question}\n\n"
        f"=== ANSWER ==="
    )


def validate(answer: str, passages: list[dict]) -> dict:
    """Score an answer before it is returned to the user.

    Confidence combines the trust of the retrieved sources with a penalty
    for pop-psychology language. An answer is only 'safe' if it is backed
    by trusted sources and free of red-flag terms.
    """
    avg_trust = (
        sum(p["trust_score"] for p in passages) / len(passages) if passages else 0.0
    )
    flags = [f for f in POP_PSYCH_FLAGS if f in answer.lower()]
    insufficient = "INSUFFICIENT_CONTEXT" in answer

    confidence = 0.0 if insufficient else round(avg_trust * (0.7 if flags else 1.0), 2)
    is_safe = (
        confidence >= settings.min_trust_score
        and not flags
        and not insufficient
    )

    return {
        "confidence": confidence,
        "flags": flags,
        "insufficient": insufficient,
        "is_safe": is_safe,
    }
