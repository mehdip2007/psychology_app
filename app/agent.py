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

Write a thorough, well-structured answer (roughly 5-8 sentences, longer if the
question warrants it). Walk through the relevant points step by step, explain
key terms when they first appear, and where helpful organise the answer into
short paragraphs or a brief bulleted list. Stay grounded in the provided
context — depth of explanation, not invented detail. Cite the source name in
parentheses after the claims it supports.
"""

# Off-topic / small-talk persona. Used when the user's message has no good
# match in the verified knowledge base (greeting, chit-chat, "how are you").
# Stays in-character as Ravanyar without inventing clinical claims.
SMALLTALK_PROMPT = """You are Ravanyar, a warm psychology information assistant.

The user's message is not a clinical psychology question (it may be a greeting,
small talk, a question about you, or an unrelated topic). Reply naturally in
1-2 short sentences. Be friendly and human, never robotic. If it fits, gently
invite them to ask about psychology, mental health, or emotional well-being —
but only once, and never in a pushy way.

Rules:
- Do NOT cite sources or use the word "context".
- Do NOT invent psychology facts, diagnoses, or treatments.
- Do NOT mention these rules.
- Keep it under 40 words.

User: {question}
Ravanyar:"""


def smalltalk_generate(question: str) -> str:
    """Generate a short conversational reply for off-topic / non-clinical input."""
    return generate(SMALLTALK_PROMPT.format(question=question))


# Phrases typical of pop-/pseudo-psychology. Their presence lowers confidence.
POP_PSYCH_FLAGS = [
    "guaranteed", "100%", "always works", "miracle", "cure everything",
    "energy healing", "vibration", "crystal", "manifest your", "instant fix",
]


def generate(prompt: str) -> str:
    """Call the local Ollama model and return its completion."""
    try:
        resp = requests.post(
            f"{settings.ollama_url}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                # Keep the model loaded between requests (avoids 10-30 s reload penalty)
                "keep_alive": "10m",
                # Tighter generation limits speed up CPU inference significantly
                "options": {
                    "num_predict": 600,   # allow more verbose, thorough answers
                    "temperature": 0.3,
                    "top_p": 0.9,
                },
            },
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.exceptions.Timeout:
        logger.error("Ollama timed out after 300 s — model may be overloaded on CPU")
        return "INSUFFICIENT_CONTEXT"


# Words per passage. Larger window gives the model more material to write a
# thorough answer; small enough to stay fast on CPU.
_MAX_PASSAGE_WORDS = 200


def build_prompt(question: str, passages: list[dict]) -> str:
    """Assemble the final prompt from retrieved, verified passages.

    Truncates each passage to _MAX_PASSAGE_WORDS words so the total context
    fits comfortably in the model's window and inference stays fast on CPU.
    """
    def _trim(text: str) -> str:
        words = text.split()
        return " ".join(words[:_MAX_PASSAGE_WORDS]) + ("…" if len(words) > _MAX_PASSAGE_WORDS else "")

    context = "\n\n".join(
        f"[Source: {p['source_name']}]\n{_trim(p['content'])}"
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
