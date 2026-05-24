"""Internet-source retrieval — PLACEHOLDER.

# TODO(later): pick a vetted web source for psychology information.
#
# Candidates to evaluate before enabling this in production:
#   - PubMed / PMC (peer-reviewed, free abstracts via E-utilities API)
#   - APA PsycNet (authoritative but paywalled — needs institutional key)
#   - WHO mental-health pages (curated, multilingual)
#   - NICE / NHS clinical guidelines (UK, freely indexable)
#   - DSM-5 / ICD-11 official references (license required)
#
# Requirements when implementing:
#   * Every fetched document MUST go through the same staging → human-review
#     → approval pipeline used for uploaded PDFs.  The agent must NEVER see
#     un-reviewed web content directly.
#   * Cache aggressively (Redis) — outside calls per query violate the
#     "no live web at answer-time" rule of this project.
#   * Respect robots.txt and rate limits.
#   * Translate Persian queries to English for the search API, then send
#     the English source through the existing FA←EN translator on display.
#
# The stub below intentionally returns nothing so the rest of the app can
# call it safely while the real source is being chosen.
"""

import logging
from typing import Any

logger = logging.getLogger("psyche.internet")


def search_internet(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return web search results for a psychology query.

    TODO: implement once a vetted source is chosen (see module docstring).
    For now returns an empty list so callers degrade gracefully.
    """
    logger.debug("internet_source.search_internet called for %r — stub, no results", query)
    return []


def is_enabled() -> bool:
    """Feature flag — flip on once the source is wired up and reviewed."""
    return False
