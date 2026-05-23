# Psyche Agent

> **A Persian-language psychology information assistant — open-source, self-hosted, and built around a strict human-review gate so no unverified source ever reaches users.**

**Status:** `v0.1.0-alpha` — early development. Interfaces and schema may change.

---

## Table of Contents

1. [Disclaimer](#disclaimer)
2. [Overview](#overview)
3. [Key Principles](#key-principles)
4. [Architecture](#architecture)
5. [Tech Stack](#tech-stack)
6. [The Source Review Workflow](#the-source-review-workflow)
7. [Prerequisites](#prerequisites)
8. [Installation](#installation)
9. [Label Studio Project Setup](#label-studio-project-setup)
10. [Usage](#usage)
11. [API Reference](#api-reference)
12. [Project Structure](#project-structure)
13. [Configuration](#configuration)
14. [Content Integrity & Guardrails](#content-integrity--guardrails)
15. [Persian Language Support](#persian-language-support)
16. [Known Limitations (Alpha)](#known-limitations-alpha)
17. [Roadmap](#roadmap)
18. [Troubleshooting](#troubleshooting)
19. [License](#license)

---

## Disclaimer

**Psyche Agent provides general psychological information only.** It is **not** a
diagnostic tool, **not** a substitute for professional mental-health care, and
**not** a crisis service. The agent is explicitly instructed never to diagnose
or recommend treatment, and every answer it returns carries a disclaimer
advising the user to consult a licensed psychologist or psychiatrist.

If a user appears to be in crisis, the agent advises contacting local emergency
services. Operators deploying this software are responsible for ensuring an
appropriate crisis-referral pathway exists for their region.

---

## Overview

Psyche Agent is a **Retrieval-Augmented Generation (RAG)** application that
answers psychology questions **in Persian (Farsi)**. It is designed for one
purpose above all others: **trustworthiness**. A psychology assistant is only
as reliable as the material behind it, so the system is built so that **no
document can influence an answer until a human has reviewed and approved it.**

Everything runs locally via Docker — open-source models, open-source
translation, open-source vector search. There are no external API costs and no
data leaves your infrastructure.

---

## Key Principles

| Principle | How it is enforced |
|-----------|--------------------|
| **Evidence-based only** | The agent answers strictly from retrieved, approved passages. If context is insufficient it says so instead of improvising. |
| **Human-reviewed sources** | Every uploaded document lands in a *staging* area and must be approved in **Label Studio** before it becomes searchable. |
| **No pseudo-psychology** | A guardrail validator scores each answer for source trust and flags pop-psychology language. |
| **Persian-first** | Multilingual embeddings + LibreTranslate handle Farsi input and output natively. |
| **Fully open-source & self-hosted** | Ollama, Qdrant, MongoDB, Redis, LibreTranslate, Label Studio — all local, all containerised. |
| **Auditable** | Staging records, review decisions, and conversations are all retained in MongoDB. |

---

## Architecture

```
                          ┌──────────────────────────────┐
        PDF upload  ─────► │  Agent API  (/ingest/upload)  │
                          │  • extract text (PyMuPDF)      │
                          │  • OCR fallback (Tesseract-fas)│
                          └───────────────┬────────────────┘
                                          │
                                          ▼
                          ┌──────────────────────────────┐
                          │  MongoDB  ·  staging_sources   │  status: PENDING
                          │  (NOT visible to the agent)    │
                          └───────────────┬────────────────┘
                                          │ pushed as a task
                                          ▼
                          ┌──────────────────────────────┐
                          │  Label Studio (review tool)    │ ◄── HUMAN REVIEWS HERE
                          │  approve / reject + metadata   │
                          └───────────────┬────────────────┘
                                          │ /review/sync pulls decisions
                              ┌───────────┴───────────┐
                          APPROVED                 REJECTED
                              │                        │
                              ▼                        ▼
              ┌────────────────────────┐    recorded for audit,
              │ chunk → embed →         │    never ingested
              │ MongoDB psychology_docs │
              │ + Qdrant vectors        │
              └────────────────────────┘
                              │
   ┌──────────────────────────┴───────────────────────────┐
   │                  AGENT QUERY PATH                      │
   │                                                        │
   │  Persian question                                      │
   │      │                                                 │
   │      ▼                                                 │
   │  embed (multilingual) ──► Qdrant search (verified only) │
   │      │                                                 │
   │      ▼                                                 │
   │  LibreTranslate  FA → EN                                │
   │      │                                                 │
   │      ▼                                                 │
   │  Ollama LLM  (system prompt + retrieved context)        │
   │      │                                                 │
   │      ▼                                                 │
   │  Guardrail validator (trust score + pop-psych flags)    │
   │      │                                                 │
   │      ▼                                                 │
   │  LibreTranslate  EN → FA  ──►  Persian answer + sources │
   └────────────────────────────────────────────────────────┘
```

The agent **only ever reads `psychology_docs`**. The `staging_sources`
collection is structurally invisible to the query path — approval is the only
bridge between the two.

---

## Tech Stack

| Layer | Component | Role |
|-------|-----------|------|
| LLM inference | **Ollama** | Runs the local open-source model (default: `mistral`) |
| Vector search | **Qdrant** | Semantic retrieval over approved passages |
| Document store | **MongoDB** | `staging_sources`, `psychology_docs`, `conversations` |
| Cache | **Redis** | Caches agent answers (1-hour TTL) |
| Translation | **LibreTranslate** | Persian ↔ English |
| Embeddings | **sentence-transformers** | `paraphrase-multilingual-MiniLM-L12-v2` (384-dim, multilingual) |
| Review tool | **Label Studio** | External human-in-the-loop approval interface |
| OCR | **Tesseract** (`fas` pack) | Reads scanned Persian PDFs |
| API | **FastAPI** | Ingestion, review-sync, and agent endpoints |
| Metrics | **prometheus-client** | `/metrics` endpoint for observability |

---

## The Source Review Workflow

This is the heart of the project. **A source is never trusted automatically.**

1. **Upload** — You send a PDF to `POST /ingest/upload`.
2. **Extraction** — Text is pulled from the PDF. If it is a scanned image
   (common for Persian books), OCR runs automatically.
3. **Staging** — The extracted text is stored in MongoDB with
   `status: "pending"`. At this point it is **inert** — the agent cannot see it.
4. **Queued for review** — The same text is pushed as a task into a
   **Label Studio** project.
5. **Human review** — You open Label Studio, read the document, and record a
   decision: **approve** or **reject**, plus metadata (source name, source
   type, trust score).
6. **Sync** — You call `POST /review/sync`. The API reads the decisions:
   - **Approved** → the document is chunked, embedded, and written to the
     production store (`psychology_docs` + Qdrant). It is now searchable.
   - **Rejected** → marked `rejected` in MongoDB for audit. It is **never**
     ingested.

> **Why an external tool?** Keeping review in Label Studio means the people
> validating clinical content do not need access to your codebase or database.
> They get a clean UI, a queue, and a full annotation history.

---

## Prerequisites

- **Docker** and **Docker Compose** (v2+)
- **~8 GB RAM minimum** (the LLM and embedding model are the heavy parts;
  16 GB is comfortable)
- **~15 GB free disk** for images, models, and volumes
- A GPU is optional — Ollama runs on CPU, just slower
- `curl` and `bash` for the init script

---

## Installation

### 1. Clone and configure

```bash
git clone <your-repo-url> psyche-agent
cd psyche-agent

cp .env.example .env
# Edit .env — at minimum change MONGO_PASSWORD.
```

### 2. Start the stack

```bash
docker compose up -d
```

First start is slow: LibreTranslate downloads its language models and Label
Studio initialises. Give it a few minutes.

### 3. Pull an LLM model into Ollama

```bash
docker exec -it psyche-ollama ollama pull mistral
```

> Swap `mistral` for any model you prefer (e.g. `llama3`, `gemma2`). Update
> `OLLAMA_MODEL` in `.env` and restart `agent-api` if you change it.

### 4. Initialise the databases

```bash
chmod +x scripts/init_db.sh
./scripts/init_db.sh
```

This creates the MongoDB indexes and the Qdrant collection.

### 5. Set up Label Studio

See [Label Studio Project Setup](#label-studio-project-setup) below — this is a
one-time manual step to create the review project and get an API token.

### 6. Verify

```bash
curl http://localhost:8000/health
# {"status":"ok","service":"psyche-agent","version":"0.1.0-alpha"}
```

### Service endpoints

| Service | URL |
|---------|-----|
| Agent API (docs) | http://localhost:8000/docs |
| Label Studio | http://localhost:8080 |
| Qdrant dashboard | http://localhost:6333/dashboard |
| LibreTranslate | http://localhost:5000 |
| Metrics | http://localhost:8000/metrics |

---

## Label Studio Project Setup

This is a **one-time** setup.

1. Open **http://localhost:8080** and create an account (local, stays on your
   machine).
2. Click **Create Project**, name it e.g. *"Psyche Source Review"*.
3. Go to the project's **Settings → Labeling Interface → Code** and paste the
   configuration below.
4. Confirm the **project ID** (visible in the URL, e.g. `/projects/1/`) matches
   `LABEL_STUDIO_PROJECT_ID` in `.env`.
5. Go to **Account & Settings → Access Token**, copy the token, and set
   `LABEL_STUDIO_API_KEY` in `.env`.
6. Restart the API so it picks up the token:
   ```bash
   docker compose restart agent-api
   ```

### Labeling interface configuration

```xml
<View>
  <Header value="Source Review — Psyche Agent"/>

  <Text name="filename" value="$filename"/>
  <Text name="language" value="$language"/>
  <Text name="text" value="$text"/>

  <Choices name="decision" toName="text" required="true" choice="single-radio">
    <Choice value="approve"/>
    <Choice value="reject"/>
  </Choices>

  <Choices name="source_type" toName="text" choice="single-radio">
    <Choice value="peer_reviewed"/>
    <Choice value="clinical_guideline"/>
    <Choice value="textbook"/>
    <Choice value="educational"/>
  </Choices>

  <Choices name="trust_score" toName="text" choice="single-radio">
    <Choice value="1.0"/>
    <Choice value="0.95"/>
    <Choice value="0.85"/>
    <Choice value="0.70"/>
  </Choices>

  <TextArea name="source_name" toName="text" maxSubmissions="1"
            placeholder="Official source name (e.g. DSM-5 Persian Edition)"/>
  <TextArea name="notes" toName="text" maxSubmissions="1"
            placeholder="Reviewer notes (optional)"/>
</View>
```

The `from_name` of each field (`decision`, `source_type`, `trust_score`,
`source_name`, `notes`) is what the `/review/sync` endpoint parses — keep these
names unchanged.

---

## Usage

### 1. Upload a source

```bash
curl -X POST http://localhost:8000/ingest/upload \
  -F "file=@/path/to/persian-psychology-book.pdf"
```

Response:

```json
{
  "staging_id": "665f1a...",
  "language": "fa",
  "extraction_method": "ocr",
  "char_count": 48213,
  "status": "pending_review",
  "message": "Parked in staging. Review it in Label Studio before it reaches the agent."
}
```

### 2. Review in Label Studio

Open **http://localhost:8080**, open your project, and you will see the
document waiting in the queue. Read it, choose **approve** or **reject**, fill
in the metadata, and submit.

### 3. Sync the decisions

```bash
curl -X POST http://localhost:8000/review/sync
```

```json
{ "promoted": ["665f1a..."], "rejected": [], "skipped": 0,
  "summary": "1 approved, 0 rejected." }
```

Approved documents are now embedded and searchable.

### 4. Ask the agent

```bash
curl -X POST http://localhost:8000/agent/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "علائم اختلال اضطراب فراگیر چیست؟"}'
```

```json
{
  "answer": "...پاسخ به فارسی...",
  "disclaimer": "این اطلاعات صرفاً جنبه آموزشی دارد...",
  "confidence": 0.95,
  "sources": ["DSM-5 Persian Edition"],
  "flags": [],
  "is_safe": true,
  "language": "fa"
}
```

If no approved source covers the question, the agent says so rather than
guessing.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/health` | Service health check |
| `POST` | `/ingest/upload` | Upload a PDF → staging → Label Studio queue |
| `GET`  | `/review/pending` | List sources awaiting review |
| `POST` | `/review/sync` | Pull review decisions; promote approved sources |
| `POST` | `/agent/ask` | Ask a question (body: `{"question": "..."}`) |
| `GET`  | `/metrics` | Prometheus metrics |
| `GET`  | `/docs` | Interactive OpenAPI documentation |

---

## Project Structure

```
psyche-agent/
├── docker-compose.yml      # Full service stack
├── Dockerfile              # Agent API image (includes Tesseract)
├── requirements.txt        # Python dependencies
├── .env.example            # Configuration template
├── .gitignore
├── .dockerignore
├── README.md
├── scripts/
│   └── init_db.sh          # Creates MongoDB indexes + Qdrant collection
└── app/
    ├── __init__.py
    ├── config.py           # Settings (env-driven)
    ├── services.py         # Extraction, OCR, translation, embeddings, Label Studio
    ├── agent.py            # System prompt, LLM call, guardrail validator
    └── main.py             # FastAPI app: ingestion, review-sync, agent
```

### MongoDB collections

| Collection | Purpose |
|------------|---------|
| `staging_sources` | Uploaded documents awaiting / after review. **Agent never reads this.** |
| `psychology_docs` | Approved, chunked, verified passages. **Agent reads only this.** |
| `conversations` | Audit log of every question and answer |

---

## Configuration

All settings live in `.env` (see `.env.example`).

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_USER` / `MONGO_PASSWORD` | `admin` / `changeme` | MongoDB credentials |
| `MONGODB_URI` | `mongodb://admin:changeme@mongodb:27017` | Mongo connection string |
| `MONGO_DB_NAME` | `psyche` | Database name |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant endpoint |
| `QDRANT_COLLECTION` | `psychology_docs` | Vector collection name |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection |
| `OLLAMA_URL` | `http://ollama:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `mistral` | Model name to use |
| `LIBRETRANSLATE_URL` | `http://libretranslate:5000` | Translation service |
| `LABEL_STUDIO_URL` | `http://label-studio:8080` | Review tool |
| `LABEL_STUDIO_API_KEY` | *(empty)* | **Must be set** after first login |
| `LABEL_STUDIO_PROJECT_ID` | `1` | Review project ID |
| `EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | sentence-transformers model |
| `EMBEDDING_DIM` | `384` | Vector size — must match the model |
| `MIN_TRUST_SCORE` | `0.7` | Minimum confidence for a "safe" answer |

> **If you change `EMBEDDING_MODEL`**, update `EMBEDDING_DIM` to match the new
> model and recreate the Qdrant collection.

---

## Content Integrity & Guardrails

Trustworthiness is enforced at three points:

**1. Ingestion gate.** Nothing reaches the agent without passing through the
Label Studio review. Rejected material is recorded but never embedded.

**2. Source metadata.** Every approved passage carries a `source_name`,
`source_type`, and `trust_score` (0.70–1.0). Suggested values:

| Source type | Trust score |
|-------------|-------------|
| Peer-reviewed article (DOI) | `1.0` |
| Clinical guideline (DSM-5, ICD-11, APA) | `0.95` |
| Verified textbook | `0.85` |
| Educational material | `0.70` |

**3. Answer validation.** Before returning a response, the validator
(`app/agent.py`):
- averages the trust score of the retrieved sources;
- scans for pop-/pseudo-psychology language (e.g. *"guaranteed"*, *"miracle"*,
  *"energy healing"*) and applies a confidence penalty;
- treats `INSUFFICIENT_CONTEXT` from the model as a hard stop.

If the resulting confidence falls below `MIN_TRUST_SCORE`, the agent **replaces
its own answer** with a safe fallback that points the user to a professional.

The system prompt additionally forbids diagnosis, medication advice, and any
claim not grounded in the supplied context.

---

## Persian Language Support

Persian is handled at every stage:

- **Input** — questions are accepted directly in Farsi. A Unicode-range check
  detects the language.
- **Semantic search** — the embedding model is multilingual, so a Persian
  question retrieves relevant passages even when the underlying clinical source
  is English.
- **Reasoning** — the question is translated to English via LibreTranslate so
  the LLM reasons over context in a single consistent language.
- **Output** — the answer and its disclaimer are translated back to Persian.
- **Scanned PDFs** — Tesseract with the `fas` language pack OCRs Persian
  documents that have no text layer.

> **Translation note (alpha):** LibreTranslate is reliable for general text but
> can blur specialised clinical terminology. Reviewing approved sources and
> spot-checking answers is recommended. The roadmap includes evaluating
> Persian-native models to remove the translation hop entirely.

---

## Known Limitations (Alpha)

- **Label Studio setup is manual.** Project creation and the API token are
  one-time manual steps; there is no automated bootstrap yet.
- **`/review/sync` is poll-based.** You trigger it manually (or via cron). There
  is no webhook from Label Studio yet.
- **Translation fidelity.** Double translation (FA→EN→FA) can lose nuance in
  clinical terms.
- **No authentication on the API.** The alpha API is unauthenticated — do not
  expose it to the public internet.
- **PDF only.** Other formats (DOCX, EPUB, plain text) are not yet supported
  for ingestion.
- **No re-embedding on model change.** Changing the embedding model requires
  rebuilding the vector collection manually.
- **Single-reviewer assumption.** The sync logic reads the latest annotation;
  multi-reviewer consensus is not implemented.

---

## Roadmap

- [ ] Webhook-driven review sync (no manual polling)
- [ ] API authentication (token / OAuth)
- [ ] Automated Label Studio project bootstrap
- [ ] Evaluate Persian-native LLMs / embeddings to drop the translation hop
- [ ] Support DOCX, EPUB, and plain-text ingestion
- [ ] RAG quality evaluation harness
- [ ] Crisis-detection module with configurable regional referral resources
- [ ] Multi-reviewer consensus before promotion
- [ ] Grafana dashboards for the Prometheus metrics

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `/ingest/upload` works but nothing appears in Label Studio | `LABEL_STUDIO_API_KEY` not set, or wrong `LABEL_STUDIO_PROJECT_ID`. Set them in `.env` and `docker compose restart agent-api`. |
| Agent always says it has no information | No sources approved yet, or Qdrant collection not created. Run `scripts/init_db.sh` and approve at least one source. |
| First request is very slow | The embedding model loads lazily on first use; subsequent calls are fast. |
| Ollama errors / empty answers | Model not pulled. Run `docker exec -it psyche-ollama ollama pull mistral`. |
| OCR produces garbage for a Persian PDF | Low scan quality. The `fas` Tesseract pack needs a reasonably clean scan (~300 DPI). |
| `/review/sync` returns everything in `skipped` | The Label Studio labeling config does not match — the `decision` field must exist. Re-check the XML config. |

View logs for any service:

```bash
docker compose logs -f agent-api
```

---

## License

Released under the **MIT License**. The open-source components (Ollama models,
Qdrant, MongoDB, Redis, LibreTranslate, Label Studio) carry their own licenses —
review them before any production or commercial deployment.

---

*Psyche Agent is an alpha project. It is an information tool and does not
provide medical or psychological diagnosis or treatment.*
