# 10. Roadmap

> **What's planned, what's intentionally not done, and how you could help.**

[← Index](./README.md) · [← Troubleshooting](./09-troubleshooting.md)

---

## 🎯 Current status: `v0.1.0-alpha`

The core loop works end-to-end:
- ✅ Upload → review → publish pipeline
- ✅ Multilingual RAG with verified-source enforcement
- ✅ Chat sessions with persistent history + auto-titles
- ✅ Small-talk detection (bilingual)
- ✅ English-language opt-in flow
- ✅ Guardrails (pop-psych, trust score, insufficient-context)

What follows below is everything that isn't yet here.

---

## 🚧 Active TODOs

### Internet source (TODO)

The single biggest planned feature. **Currently stubbed** at `app/integrations/internet_source.py`:

```python
def search_internet(query: str, limit: int = 5) -> list[dict]:
    """TODO: implement once a vetted source is chosen."""
    return []
```

#### Candidate sources to evaluate

| Source | Pros | Cons |
|--------|------|------|
| **PubMed / PMC** | Peer-reviewed, free, has an E-utilities API | English only, abstracts not full text |
| **APA PsycNet** | Most authoritative psychology source | Paywalled — needs institutional API key |
| **WHO mental-health pages** | Curated, multilingual, free | Limited depth, mostly overview pages |
| **NICE / NHS guidelines** | UK clinical standards, free, structured | UK-centric, English only |
| **DSM-5 / ICD-11** | Diagnostic gold standard | License required for re-use |

#### Design constraints (non-negotiable)

1. **Every fetched document MUST go through the same staging → review → approval pipeline.** The agent must never see un-reviewed web content directly.
2. **Cache aggressively in Redis.** The "no live web at answer-time" rule of this project means we never call external APIs during `/agent/ask`.
3. **Respect `robots.txt` and rate limits.** Use the source's official API where available.
4. **Translation discipline.** Translate Persian queries to English for the search API, then send the English source text through the existing FA↔EN translator on display.

---

### Webhook-driven review sync

**Current:** `/review/sync` is poll-based — you click the sidebar button (or hit the endpoint with cron).

**Wanted:** Label Studio webhook → `POST /webhook/label-studio` → auto-sync just the changed task.

**Benefit:** Reviewers see their approvals live without manually triggering sync.

---

### Multi-turn chat context

**Current:** Each `/agent/ask` is independent. The agent has no memory of prior turns in the same chat — it sees only the latest question.

**Wanted:** Pass the last N turns as additional context. Be careful about prompt-window inflation.

**Open question:** how to handle follow-up questions ("tell me more about that") without losing the verified-source citation discipline?

---

### Multi-reviewer consensus

**Current:** The sync logic reads the **latest** annotation. With multiple reviewers, the most recent click wins.

**Wanted:** "Approve" only when ≥2 reviewers approve, or when 1 reviewer approves and 0 reject.

---

### Re-embedding tool

**Problem:** Changing `EMBEDDING_MODEL` requires manually:
1. Dropping the Qdrant collection
2. Re-running `init_db.sh`
3. Iterating every `psychology_docs` chunk and inserting fresh vectors

**Wanted:** A `/admin/reembed` endpoint or CLI command that does all three in one shot.

---

### API authentication

**Current:** The alpha API is unauthenticated. Anyone with network access to `:8000` can upload, query, or delete chats.

**Wanted:** At minimum, an API-key header check via FastAPI dependency. Better: OAuth2 / OIDC.

> 🛑 **Until this lands, do not expose Psyche-Agent to the public internet.**

---

### Format expansion

| Format | Status |
|--------|--------|
| PDF | ✅ Supported |
| EPUB | ✅ Supported |
| DOCX | ❌ Not yet (python-docx is small, easy add) |
| Plain text / Markdown | ❌ Not yet |
| HTML | ❌ Not yet |
| Audio (Whisper transcription) | ❌ Bigger lift but high-impact for clinical talks |

---

### Better Persian tokenization

The current word-window chunker (`chunk_text`) splits on whitespace. Persian word boundaries are well-defined but compound words can be split awkwardly. A Hazm- or stanza-based tokenizer would chunk more naturally.

---

### Crisis detection guardrail

**Current:** The system prompt instructs the LLM to suggest emergency services for crisis hints. There's no programmatic regex / classifier.

**Wanted:** A pre-filter that scans the question for crisis keywords (in FA + EN) and prepends a banner with emergency numbers (Iran: 123) regardless of what the LLM says.

---

### Better small-talk threshold tuning

**Current:** Single global `SMALLTALK_SCORE_THRESHOLD = 0.40`.

**Wanted:** Different thresholds per language (Persian short-text scores are noisier than English), or adaptive based on top-1 vs top-2 score delta.

---

### Streaming responses

**Current:** UI shows "thinking dots" until the full answer arrives. On a slow CPU this can be 10+ seconds.

**Wanted:** Use Ollama's `stream: true` and pipe tokens to the UI via SSE or WebSocket so users see the answer building up.

---

### Multi-language UI

**Current:** UI labels are FA + EN.

**Wanted:** Add Arabic and maybe Turkish/Kurdish for the broader regional audience.

---

## ❌ Things we deliberately won't add

| Feature | Why not |
|---------|---------|
| Cloud-hosted SaaS version | Defeats the privacy-first design |
| User accounts in the alpha | Out of scope; let teams build their own auth layer |
| Live web search at answer-time | Would break the verified-only rule |
| Image generation | Not psychology-relevant; adds attack surface |
| Voice output | Could mislead users into thinking it's a therapist |
| Direct diagnosis / treatment | Explicit no-go in the system prompt; will not change |

---

## 🤝 How to contribute

(When the repo opens for contributions.)

1. Pick a TODO above, or open an issue describing what you want to change.
2. Branch: `feat/<short-name>` or `fix/<short-name>`.
3. Follow the existing patterns — read [Code Walkthrough](./07-code-walkthrough.md) first.
4. Keep the **human-review rule** intact. Any new ingestion path must go through staging.
5. Add or update the relevant docs page in `docs/`.
6. PR with a screenshot/recording for UI changes.

---

## 📅 Recent changelog (since alpha-0)

| Date | Change |
|------|--------|
| 2026-05-24 | Bilingual greeting pre-filter (Persian "سلام چطوری" now correctly small-talk) |
| 2026-05-24 | Confluence-style `docs/` folder (this!) |
| 2026-05-24 | Small-talk branch + score threshold |
| 2026-05-24 | Chat sessions (create / list / get / delete + auto-title) |
| 2026-05-24 | English language-choice prompt |
| 2026-05-24 | Verbose-answer prompt + larger context window |
| 2026-05-24 | Internet-source plugin stub |

---

[← Index](./README.md)
