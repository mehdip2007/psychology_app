# 7. Code Walkthrough

> **A guided tour of every file. What it does, why it exists, the tricky bits.**

[← Index](./README.md) · [← API Reference](./06-api-reference.md) · [Next: Configuration →](./08-configuration.md)

---

## 🗺️ Repo layout

```
psyche-agent/
├── 📂 app/                          ← The FastAPI application (runs inside agent-api container)
│   ├── __init__.py
│   ├── main.py                      ← HTTP routes + glue code
│   ├── agent.py                     ← LLM prompts + generation + guardrails
│   ├── config.py                    ← .env loader (pydantic-settings)
│   ├── services.py                  ← Extraction, OCR, translation, embeddings, chunking, Label Studio
│   └── integrations/
│       ├── __init__.py
│       ├── obsidian_sync.py         ← Pull approved notes from an Obsidian vault
│       └── internet_source.py       ← Stub for future web-search source
├── 📂 ui/
│   ├── index.html                   ← The entire frontend (no build step)
│   └── nginx.conf                   ← Reverse-proxies /api/* to FastAPI
├── 📂 docs/                         ← You are here
├── docker-compose.yml               ← The 8-service stack
├── Dockerfile                       ← agent-api image (Python 3.11 + Tesseract + Poppler)
├── requirements.txt                 ← Python dependencies
├── init_db.sh                       ← Bootstrap MongoDB indexes + Qdrant collection
├── env.example                      ← Template for .env
├── README.md                        ← Quick-start (high-level)
└── CLAUDE.md                        ← AI assistant context (codebase guide)
```

> ⚠️ **There's also a root-level `main.py`, `agent.py`, `services.py`.** These are **legacy** — the Dockerfile copies `app/` only. Edit files inside `app/` and ignore the duplicates at the root.

---

## 📄 `app/main.py`

The HTTP layer. Wires the routes to the helpers in `agent.py` and `services.py`.

### Top-level setup

```python
app = FastAPI(title="Psyche Agent", version="0.1.0-alpha")

mongo = MongoClient(settings.mongodb_uri)
db = mongo[settings.mongo_db_name]
qdrant = QdrantClient(url=settings.qdrant_url)
cache = redis.from_url(settings.redis_url, decode_responses=True)
translator = Translator()
label_studio = LabelStudio()
```

> 💡 **Why module-level clients?** All clients are connection-pooled and thread-safe. Creating one per request would be slow.

### The routes (in order they appear)

| Function | Method | Path | What it does |
|----------|--------|------|--------------|
| `health` | GET | `/health` | Returns the version string |
| `ingest_upload` | POST | `/ingest/upload` | Accept PDF/EPUB → extract → stage → push to LS |
| `review_pending` | GET | `/review/pending` | Lists `staging_sources` with `status=pending` |
| `get_stats` | GET | `/stats` | Counts pending/approved/chunks + sources list |
| `review_sync` | POST | `/review/sync` | Pull from LS, promote approvals |
| `_parse_annotation` | helper | — | Flatten LS annotation JSON |
| `_promote_to_production` | helper | — | Chunk + embed + insert |
| `_staging_from_ls_task` | helper | — | Auto-create staging record for PDFs uploaded inside LS |
| `_looks_like_smalltalk` | helper | — | Greeting / short-message detector |
| `agent_ask` | POST | `/agent/ask` | The main agent flow (see [Agent & Chat](./05-agent-and-chat.md)) |
| `obsidian_sync` | POST | `/obsidian/sync` | Sync approved Obsidian notes |
| `_append_chat_message` | helper | — | Append Q&A turn to a chat, auto-set title |
| `chat_create` | POST | `/chats` | Insert blank chat |
| `chat_list` | GET | `/chats` | Aggregate pipeline: title + message_count |
| `chat_get` | GET | `/chats/{id}` | Full chat with messages |
| `chat_delete` | DELETE | `/chats/{id}` | Remove a chat |

### The trickiest function: `agent_ask`

It does **a lot**. Read it top-down:

1. **Validate** — empty question? 400.
2. **Detect language** of the question.
3. **English+no answer_lang** → return `language_choice_required` and stop.
4. **Resolve `answer_lang`** (default: same as detected).
5. **Cache check** — Redis lookup keyed by `f"{answer_lang}:{question}"`.
6. **Small-talk pre-filter** — if greeting/short, skip Qdrant.
7. **Otherwise: Qdrant search** for top-3 verified passages.
8. **Threshold check** — if best score < 0.40, fall back to small-talk.
9. **Small-talk branch** — call `smalltalk_generate`, translate, persist, return.
10. **RAG branch** — translate question to EN, call `generate(build_prompt(...))`, validate.
11. **If unsafe** — replace with the "I don't have enough info" fallback.
12. **Translate** answer to `answer_lang`.
13. **Persist** to `conversations` + `chat_sessions` (via `_append_chat_message`).
14. **Cache** only confident, sufficient answers.
15. Return JSON.

> 🔍 **Read the file alongside [Agent & Chat](./05-agent-and-chat.md)** — the decision tree there matches this function 1:1.

---

## 📄 `app/agent.py`

The LLM core. Pure functions — no I/O state beyond the HTTP call to Ollama.

### What's in it

| Name | Type | Purpose |
|------|------|---------|
| `SYSTEM_PROMPT` | str constant | Locked-down system prompt for RAG answers |
| `SMALLTALK_PROMPT` | str template | Friendlier persona for off-topic messages |
| `POP_PSYCH_FLAGS` | list | Phrases that lower the confidence score |
| `generate(prompt)` | function | POST to Ollama, return completion |
| `smalltalk_generate(question)` | function | Specialized `generate` for chit-chat |
| `build_prompt(question, passages)` | function | Assemble system + context + question |
| `validate(answer, passages)` | function | Score confidence, detect pop-psych |

### `generate`: the Ollama call

```python
resp = requests.post(
    f"{settings.ollama_url}/api/generate",
    json={
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "10m",
        "options": {
            "num_predict": 600,
            "temperature": 0.3,
            "top_p": 0.9,
        },
    },
    timeout=300,
)
```

> 🔑 **The two settings that most affect behavior:**
> - `num_predict=600` — max tokens. Higher = more verbose. Was 180; raised when the user asked for more thorough answers.
> - `temperature=0.3` — low value → deterministic → fewer hallucinations.

### `validate`: the guardrail

```python
avg_trust = mean(p["trust_score"] for p in passages)
flags = [f for f in POP_PSYCH_FLAGS if f in answer.lower()]
insufficient = "INSUFFICIENT_CONTEXT" in answer

confidence = 0 if insufficient else avg_trust * (0.7 if flags else 1.0)
is_safe = confidence >= MIN_TRUST_SCORE and not flags and not insufficient
```

| Variable | Meaning |
|----------|---------|
| `avg_trust` | Mean of the trust scores assigned by reviewers |
| `flags` | Pop-psych phrases found in the answer |
| `insufficient` | LLM explicitly admitted defeat |
| `confidence` | Final score 0–1 |
| `is_safe` | Boolean gate — if False, the UI uses the fallback path |

---

## 📄 `app/services.py`

Reusable helpers — extraction, translation, embeddings, chunking, Label Studio API.

### `extract_text(pdf_bytes)`

Two-stage:
1. Try the embedded text layer with PyMuPDF.
2. If <100 chars, fall back to OCR.

Returns `{"text": ..., "method": "text-layer" | "ocr"}`.

### `extract_epub(epub_bytes)`

EPUBs are ZIP archives of XHTML. We:
1. Open as ZIP
2. Find every `.html`/`.xhtml` entry that isn't nav/toc/cover
3. BeautifulSoup → strip tags → join text
4. Skip near-empty pages (<50 chars)

### `ocr_pdf(pdf_bytes)`

`pdf2image` rasterizes pages at 300 DPI, `pytesseract` OCRs each with `lang="fas+eng"`.

> 💡 **Tesseract needs language packs.** The Dockerfile installs `tesseract-ocr-fas` — without it, Persian comes out garbled.

### `detect_language(text)`

Counts Unicode characters in the Persian range. Returns `"fa"` if ≥25%, else `"en"`.

### `Translator`

Thin wrapper around LibreTranslate. `to_english(text)` and `to_persian(text)`. Graceful fallback: on error, returns the input text unchanged so the pipeline doesn't crash.

### `embed(text)`

Lazy-loads `paraphrase-multilingual-MiniLM-L12-v2` via `@lru_cache(maxsize=1)`. The first call is slow (~5 s, model load); subsequent calls are sub-millisecond.

### `chunk_text(text, size=800, overlap=120)`

Sliding word-window with overlap. Keeps adjacent chunks sharing 120 words so context isn't lost at boundaries.

### `LabelStudio` class

Two methods:
- `push_task(staging_id, filename, text, language)` → `POST /api/projects/{id}/import`
- `fetch_tasks()` → `GET /api/projects/{id}/tasks?fields=all&page_size=1000`

Both use the API token from `.env`.

---

## 📄 `app/config.py`

A single `Settings` class (pydantic-settings) that reads from `.env`. Every value has a default so the app boots even with a blank `.env`.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    mongodb_uri: str = "mongodb://admin:changeme@mongodb:27017"
    qdrant_url: str = "http://qdrant:6333"
    ollama_model: str = "mistral"
    min_trust_score: float = 0.7
    smalltalk_score_threshold: float = 0.40
    # ... etc
```

Full list: [Configuration](./08-configuration.md).

---

## 📄 `app/integrations/obsidian_sync.py`

Pulls notes from a mounted Obsidian vault. Each note's YAML frontmatter has a `status:` field:

- `approved` → chunk + embed + insert into `psychology_docs`
- `pending` / `rejected` → skip

Already-synced notes are tracked by content hash to avoid duplicate ingestion.

---

## 📄 `app/integrations/internet_source.py`

**Stub only.** Returns an empty list. The docstring explains the design constraint:

> "Every fetched document MUST go through the same staging → human-review → approval pipeline used for uploaded PDFs."

When a vetted source (PubMed, WHO, NICE, etc.) is chosen, fill in `search_internet(query)`. See [Roadmap](./10-roadmap.md#internet-source-todo).

---

## 📄 `ui/index.html`

The **entire** frontend in one file. No build step, no npm. Just HTML + CSS + vanilla JS.

### High-level structure

```
<head>          ← Vazirmatn font, all CSS variables, all styles
<body>
  <aside .sidebar>      ← Chats / Stats / Sources / Sync / Upload / Tools cards
  <main>
    <header>            ← Sidebar toggle, brand, theme button, language toggle
    <div .disclaimer>   ← The amber warning bar
    <div .messages>     ← Scrollable chat transcript
    <div .input-area>   ← Textarea + send button
<script>        ← All UI logic (i18n, state, fetch, render)
```

### Key JS pieces

| Concept | Implementation |
|---------|----------------|
| **i18n** | `T = { fa: {...}, en: {...} }` lookup tables |
| **Theme** | `data-theme="dark"` attribute on `<html>`, persisted in `localStorage` |
| **Chat state** | `currentChatId`, `chatsCache`, `pendingEnglishQuestion` globals |
| **Stats loader** | `loadStats()` → fetch `/api/stats` → populate badges |
| **Chat loader** | `loadChats()` → fetch `/api/chats` → populate sidebar list |
| **Send** | `sendMessage()` → `postAsk()` → fetch `/api/agent/ask` |
| **Lang prompt** | When response has `language_choice_required`, render inline buttons |
| **Render reply** | `appendAI(data)` switches on `data.smalltalk` / `data.insufficient` / normal |

### One thing to know about RTL

```css
.msg { direction: ltr; unicode-bidi: plaintext; }
```

This makes mixed Persian/English text render correctly regardless of which is dominant. Without it, English in a Persian bubble (or vice versa) reads backwards.

---

## 📄 `ui/nginx.conf`

Tiny config. Two important blocks:

```nginx
client_max_body_size 100m;          # let large PDFs through

location /api/ {
    rewrite ^/api/(.*) /$1 break;   # strip /api prefix
    proxy_pass http://agent-api:8000$uri$is_args$args;
    proxy_read_timeout 360s;        # Ollama can be slow on CPU
}

location / {
    try_files $uri $uri/ /index.html;  # SPA fallback
}
```

> 🛑 **Don't touch the rewrite + proxy_pass order.** Nginx requires the rewrite *before* the proxy_pass for `$uri` to be updated correctly.

---

## 📄 `Dockerfile`

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-fas poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Why `COPY app ./app` last?** Layer caching. Code changes more often than dependencies, so dependencies go in earlier layers.

---

## 📄 `docker-compose.yml`

Defines 8 services. Worth reading the file directly — it's well commented.

Key things to notice:
- All services share the `psyche-net` network.
- Volumes for persistent data (`mongo_data`, `qdrant_data`, `ollama_data`, `label_studio_data`).
- `chat-ui` bind-mounts `./ui/index.html` so edits are live (but watch the [docker file-mount gotcha](./09-troubleshooting.md)).
- `agent-api` uses `build: .` so code changes require `docker compose up -d --build agent-api`.

---

## 📄 `init_db.sh`

A one-time bootstrap:

1. Connect to MongoDB and create indexes (`uploaded_at`, `status`, `is_verified`, etc.)
2. Connect to Qdrant and create the `psychology_docs` collection with `size=384, distance=Cosine`

Idempotent — safe to re-run.

---

## 📄 `requirements.txt`

The big ones:
- `fastapi` + `uvicorn[standard]` — HTTP server
- `pymongo` — MongoDB driver
- `qdrant-client` — Qdrant SDK
- `redis` — Redis SDK
- `requests` — for Ollama, LibreTranslate, Label Studio HTTP calls
- `pydantic-settings` — `.env` loading
- `pymupdf` (`fitz`) — PDF text extraction
- `pdf2image` + `pytesseract` — OCR
- `sentence-transformers` — multilingual embeddings (~400 MB download on first run)
- `beautifulsoup4` + `lxml` — EPUB parsing
- `prometheus-client` — `/metrics`

> 💡 **The biggest install is `sentence-transformers` + its torch dependency** (~1 GB). That's why `pip install` takes a while the first time the Docker image is built.

---

[← Index](./README.md) · [Next: Configuration →](./08-configuration.md)
