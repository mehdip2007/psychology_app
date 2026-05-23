# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Psyche Agent** is a Persian-language psychology information assistant built as a Retrieval-Augmented Generation (RAG) application. The system enforces a strict human-review gate: no document reaches users without being explicitly approved by a human reviewer in Label Studio.

**Status:** v0.1.0-alpha — early development.

### Core Philosophy

- **Evidence-based only**: Answers are derived strictly from retrieved, approved passages. If context is insufficient, the agent says so rather than improvising.
- **Human-reviewed sources**: Every uploaded document sits in staging and must be approved in Label Studio before the agent can see it.
- **No pseudo-psychology**: A guardrail validator scores each answer and flags pop-psychology language.
- **Persian-first**: Multilingual embeddings + LibreTranslate handle Farsi natively.
- **Fully open-source & self-hosted**: Ollama, Qdrant, MongoDB, Redis, LibreTranslate, Label Studio — all local, all containerized.
- **Auditable**: Staging records, review decisions, and conversations are retained in MongoDB.

## Architecture

```
PDF Upload
    ↓
Text Extraction (PyMuPDF + Tesseract OCR for Persian)
    ↓
MongoDB staging_sources (status: PENDING, invisible to agent)
    ↓
Label Studio (HUMAN REVIEW)
    ↓
    ├─ APPROVED → chunk → embed → MongoDB psychology_docs + Qdrant vectors
    └─ REJECTED → recorded for audit, never ingested
    
Agent Query Path:
Persian Question → Multilingual Embedding → Qdrant Search (verified only)
    ↓
Retrieved Passages + System Prompt → Ollama LLM
    ↓
Guardrail Validator (trust score, pop-psych flags) → LibreTranslate EN→FA
    ↓
Persian Answer + Sources + Confidence Score
```

### Key Data Flow

1. **Ingestion** (`POST /ingest/upload`):
   - Accept PDF → extract text (text-layer or OCR fallback)
   - Detect language (Persian or English)
   - Store in `staging_sources` with `status: "pending"`
   - Push to Label Studio review queue

2. **Review Sync** (`POST /review/sync`):
   - Pull annotation decisions from Label Studio
   - For APPROVED: chunk text (800-word windows, 120-word overlap), embed, insert into `psychology_docs` + Qdrant
   - For REJECTED: mark as rejected in MongoDB (audit trail only)

3. **Agent Query** (`POST /agent/ask`):
   - Embed question (multilingual)
   - Search Qdrant (filter `is_verified=true` only)
   - If no verified sources found: return safe fallback
   - Translate question to English
   - Generate answer via Ollama (system prompt + retrieved context)
   - Validate answer (trust score, pop-psychology flags)
   - Translate answer back to Persian
   - Cache response (1-hour TTL in Redis)
   - Log conversation to MongoDB

## Tech Stack

| Layer | Component | Role |
|-------|-----------|------|
| LLM inference | **Ollama** | Local open-source model (default: mistral) |
| Vector search | **Qdrant** | Semantic retrieval; 384-dim multilingual embeddings |
| Document store | **MongoDB** | staging_sources, psychology_docs, conversations collections |
| Cache | **Redis** | 1-hour TTL on query responses |
| Translation | **LibreTranslate** | Persian ↔ English |
| Embeddings | **sentence-transformers** | paraphrase-multilingual-MiniLM-L12-v2 |
| Review UI | **Label Studio** | External human annotation tool |
| OCR | **Tesseract** (fas pack) | Scanned Persian PDFs |
| API | **FastAPI** | Ingestion, review-sync, agent endpoints |
| Metrics | **prometheus-client** | /metrics endpoint |

## Project Structure

```
psyche-agent/
├── docker-compose.yml          # Complete service stack (7 services)
├── Dockerfile                  # Python 3.11 + Tesseract + Poppler
├── requirements.txt            # Python dependencies
├── .env                        # Configuration (credentials, URLs, model names)
├── README.md                   # Comprehensive user guide
├── init_db.sh                  # MongoDB indexes + Qdrant collection bootstrap
├── main.py                     # FastAPI app (336 lines)
│   ├── Health check
│   ├── /ingest/upload
│   ├── /review/pending
│   ├── /review/sync
│   └── /agent/ask
├── config.py                   # Settings from .env (pydantic-settings)
├── agent.py                    # Ollama LLM core + guardrail validator
├── services.py                 # Text extraction, OCR, translation, embeddings, chunking, Label Studio API
└── app/
    └── __init__.py             # Empty (package marker)
```

### MongoDB Collections

| Collection | Purpose | Visibility to Agent |
|------------|---------|---------------------|
| `staging_sources` | Uploaded documents + review decisions | ❌ Invisible |
| `psychology_docs` | Approved, chunked, verified passages | ✅ Agent reads only this |
| `conversations` | Audit log of Q&A | ❌ Invisible |

### API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/health` | Service health |
| POST | `/ingest/upload` | Upload PDF → staging |
| GET | `/review/pending` | List sources awaiting review |
| POST | `/review/sync` | Sync Label Studio decisions; promote approved |
| POST | `/agent/ask` | Ask a question (body: `{"question": "..."}`) |
| GET | `/metrics` | Prometheus metrics |
| GET | `/docs` | Interactive OpenAPI docs |

## Setup & Development

### Prerequisites

- Docker & Docker Compose (v2+)
- ~8 GB RAM minimum; 16 GB recommended
- ~15 GB disk for images, models, volumes
- GPU optional (Ollama runs on CPU, slower)

### Quick Start

```bash
# 1. Clone and configure
git clone <repo> psyche-agent
cd psyche-agent
cp .env.example .env  # Edit .env to change MONGO_PASSWORD, Label Studio API key
# (Note: .env already exists in the project; review and update if needed)

# 2. Start all services
docker compose up -d

# 3. Pull an LLM model into Ollama
docker exec -it psyche-ollama ollama pull mistral
# (Swap mistral for another model if preferred; update OLLAMA_MODEL in .env)

# 4. Initialise databases
chmod +x init_db.sh
./init_db.sh
# Creates MongoDB indexes and Qdrant collection (psychology_docs, dim=384)

# 5. Configure Label Studio (one-time, manual)
# Open http://localhost:8080 → create account → create project
# In project Settings → Labeling Interface → Code, paste the XML config from README.md
# Verify project ID matches LABEL_STUDIO_PROJECT_ID in .env
# Get API token from Account & Settings → Access Token
# Set LABEL_STUDIO_API_KEY in .env and restart agent-api
docker compose restart agent-api

# 6. Verify health
curl http://localhost:8000/health
```

### Service Endpoints (Local)

- **Agent API docs**: http://localhost:8000/docs
- **Label Studio**: http://localhost:8080
- **Qdrant dashboard**: http://localhost:6333/dashboard
- **LibreTranslate**: http://localhost:5000
- **Metrics**: http://localhost:8000/metrics
- **Agent API**: http://localhost:8000

### Development Workflow

1. **Upload a source**:
   ```bash
   curl -X POST http://localhost:8000/ingest/upload -F "file=@/path/to/file.pdf"
   ```

2. **Review in Label Studio**:
   - Open http://localhost:8080
   - Click your project and review the queued document
   - Choose approve/reject + metadata (source name, type, trust score)

3. **Sync decisions**:
   ```bash
   curl -X POST http://localhost:8000/review/sync
   ```

4. **Test the agent**:
   ```bash
   curl -X POST http://localhost:8000/agent/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "علائم اختلال اضطراب فراگیر چیست؟"}'
   ```

### Key Configuration Variables (.env)

| Variable | Default | Notes |
|----------|---------|-------|
| `MONGO_USER` / `MONGO_PASSWORD` | admin / admin | Change for production |
| `MONGODB_URI` | mongodb://admin:admin@mongodb:27017 | Internal docker network |
| `MONGO_DB_NAME` | psyche | Database name |
| `QDRANT_URL` | http://qdrant:6333 | Internal; localhost:6333 from host |
| `QDRANT_COLLECTION` | psychology_docs | Vector collection name |
| `OLLAMA_MODEL` | mistral | Model to use (pull via docker) |
| `OLLAMA_URL` | http://ollama:11434 | Internal; localhost:11434 from host |
| `EMBEDDING_MODEL` | paraphrase-multilingual-MiniLM-L12-v2 | sentence-transformers; 384-dim |
| `EMBEDDING_DIM` | 384 | Must match embedding model |
| `MIN_TRUST_SCORE` | 0.7 | Minimum confidence for "safe" answers |
| `LABEL_STUDIO_API_KEY` | (empty) | **Must be set after first login** |
| `LABEL_STUDIO_PROJECT_ID` | 1 | Review project ID (visible in URL) |

### Docker Compose Services

- **mongodb** (mongo:7.0): Document store + audit trail
- **qdrant** (qdrant:latest): Vector search engine
- **redis** (redis:7-alpine): Response cache
- **ollama** (ollama:latest): LLM inference
- **libretranslate** (libretranslate:latest): Persian ↔ English translation
- **label-studio** (heartexlabs/label-studio:latest): Human review UI
- **agent-api** (built from Dockerfile): FastAPI application

## Code Patterns & Key Functions

### main.py (FastAPI app)

- **`ingest_upload()`**: Extract PDF → staging → Label Studio
- **`_parse_annotation()`**: Flatten Label Studio annotation JSON
- **`_promote_to_production()`**: Chunk, embed, insert approved source
- **`review_sync()`**: Pull Label Studio decisions, apply them
- **`agent_ask()`**: Core RAG loop with caching

### config.py (Pydantic Settings)

All configuration loaded from `.env` at startup. No hardcoded credentials.

### agent.py (LLM Core)

- **`generate(prompt)`**: POST to Ollama `/api/generate` endpoint
- **`build_prompt(question, passages)`**: Assemble system prompt + context + question
- **`validate(answer, passages)`**: Score confidence (avg trust score × pop-psych penalty), detect insufficient context

**System Prompt Constraints**:
- Use ONLY provided context; no outside knowledge
- Return `INSUFFICIENT_CONTEXT` if context insufficient
- Never diagnose, recommend medication, or suggest treatment
- Stay neutral, factual, compassionate
- Recommend consulting licensed professional
- Flag if question suggests crisis; advise emergency services

**Pop-Psychology Flags**: "guaranteed", "100%", "miracle", "cure everything", "energy healing", "manifest your", etc. Trigger confidence penalty.

### services.py (Supporting Services)

- **`extract_text(pdf_bytes)`**: Text-layer (PyMuPDF) → fallback to OCR (Tesseract)
- **`ocr_pdf(bytes, lang="fas+eng")`**: Tesseract with Persian + English packs
- **`detect_language(text)`**: Unicode range check for Persian (0x0600–0x06FF)
- **`Translator`**: Thin wrapper around LibreTranslate (`to_english()`, `to_persian()`)
- **`embed(text)`**: Load embedding model once (LRU cache), normalize vectors
- **`chunk_text(text, size=800, overlap=120)`**: Word-window chunking for RAG
- **`LabelStudio`**: Push tasks via `/api/projects/{id}/import`, fetch tasks from `/api/projects/{id}/tasks`

## Testing & Troubleshooting

### Service Logs

```bash
docker compose logs -f agent-api          # API logs
docker compose logs -f mongodb            # MongoDB
docker compose logs -f qdrant             # Qdrant
docker compose logs -f ollama             # LLM inference
docker compose logs -f libretranslate      # Translation
docker compose logs -f label-studio       # Review UI
```

### Common Issues

| Symptom | Cause / Fix |
|---------|----------|
| `/ingest/upload` works but nothing in Label Studio | `LABEL_STUDIO_API_KEY` not set or wrong `PROJECT_ID`. Set in `.env` and `docker compose restart agent-api`. |
| Agent always says "no information" | No approved sources, or Qdrant collection not created. Run `init_db.sh` and approve at least one source. |
| First request very slow | Embedding model loads lazily; subsequent calls are fast. |
| Ollama errors / empty answers | Model not pulled. Run `docker exec -it psyche-ollama ollama pull mistral`. |
| OCR garbage output | Low scan quality. Tesseract needs ~300 DPI. |
| `/review/sync` skips everything | Label Studio labeling config missing `decision` field. Re-check XML config in README. |

### Manual Verification

```bash
# Check MongoDB collections
docker exec -it psyche-mongodb mongosh -u admin -p admin
> use psyche
> db.staging_sources.countDocuments()
> db.psychology_docs.countDocuments()
> db.conversations.findOne()

# Check Qdrant collection
curl http://localhost:6333/collections/psychology_docs

# Check Ollama
curl http://localhost:11434/api/tags

# Test LibreTranslate
curl -X POST http://localhost:5000/translate \
  -H "Content-Type: application/json" \
  -d '{"q": "سلام", "source": "fa", "target": "en", "format": "text"}'
```

## Known Limitations (Alpha)

- **Label Studio setup is manual** — no automated bootstrap yet
- **`/review/sync` is poll-based** — trigger manually or via cron; no webhooks yet
- **Translation fidelity** — double translation (FA→EN→FA) can lose nuance in clinical terms
- **No API authentication** — alpha API is unauthenticated; do not expose to public internet
- **PDF only** — DOCX, EPUB, plain text not yet supported
- **No re-embedding on model change** — changing embedding model requires manual Qdrant collection rebuild
- **Single-reviewer assumption** — sync logic reads latest annotation; multi-reviewer consensus not implemented

## Additional Resources

- **README.md**: Full user guide, installation steps, Label Studio XML config, troubleshooting
- **init_db.sh**: Database bootstrap script (creates indexes, Qdrant collection)
- **docker-compose.yml**: Service definitions and volumes
- **Dockerfile**: Python 3.11 + system dependencies (Tesseract, Poppler)

