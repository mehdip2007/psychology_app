# 2. Architecture

> **The big picture: every box, every arrow, every container.**

[← Index](./README.md) · [← Overview](./01-overview.md) · [Next: Getting Started →](./03-getting-started.md)

---

## 🗺️ The 30-second mental model

Think of Psyche-Agent as a small **office** with several specialized rooms:

| Room | What happens there | Container |
|------|--------------------|-----------|
| 🚪 **Reception** | Visitors arrive (HTTP requests), get routed to the right room | `chat-ui` (nginx) |
| 🧑‍💼 **Manager's office** | Decides which question goes where, handles chats | `agent-api` (FastAPI) |
| 🗄️ **Filing cabinet** | Stores every document, chat, decision | `mongodb` |
| 🔍 **Index card box** | Finds passages by meaning, not just words | `qdrant` |
| 📌 **Sticky-note board** | Cached answers to recent questions | `redis` |
| 🧠 **The thinker** | Local LLM that writes the actual answer text | `ollama` |
| 🌍 **Translator** | Translates Persian ↔ English | `libretranslate` |
| 🏷️ **Review desk** | Where humans approve/reject sources | `label-studio` |

All 8 rooms (containers) talk to each other over a private docker network. Only the **reception** (`chat-ui`) is reachable from outside — that's how your browser connects.

---

## 📐 Full architecture diagram

```mermaid
flowchart TB
    subgraph "Outside world"
        Browser["🌐 Your browser"]
    end

    subgraph "Docker network: psyche-net"
        UI["chat-ui<br/>(nginx :80)"]
        API["agent-api<br/>(FastAPI :8000)"]
        Mongo[("mongodb<br/>:27017")]
        Qdrant[("qdrant<br/>:6333")]
        Redis[("redis<br/>:6379")]
        Ollama["ollama<br/>:11434"]
        Translator["libretranslate<br/>:5000"]
        Labels["label-studio<br/>:8080"]
    end

    Browser -- "http://localhost:3000" --> UI
    Browser -- "http://localhost:8080 (review UI)" --> Labels
    UI -- "/api/* proxy" --> API
    API --> Mongo
    API --> Qdrant
    API --> Redis
    API -- "generate text" --> Ollama
    API -- "FA ↔ EN" --> Translator
    API -- "push tasks / pull decisions" --> Labels
    Labels --> Mongo

    style API fill:#2D6B6B,color:#fff
    style UI fill:#3D8A8A,color:#fff
    style Browser fill:#B5873A,color:#fff
```

---

## 🚪 Port map

| Service | Inside docker network | Outside (host) port | Used for |
|---------|----------------------|---------------------|----------|
| chat-ui | `:80` | `:3000` | Web app you open in browser |
| agent-api | `:8000` | `:8000` | Direct API (also `/docs` for Swagger) |
| label-studio | `:8080` | `:8080` | Reviewer UI |
| qdrant | `:6333` | `:6333` | Vector dashboard at `/dashboard` |
| libretranslate | `:5000` | `:5000` | Translation API |
| ollama | `:11434` | `:11434` | LLM (rarely accessed directly) |
| mongodb | `:27017` | — | Not exposed to host |
| redis | `:6379` | — | Not exposed to host |

> 💡 **Why are some not exposed?** Mongo and Redis hold sensitive data (chat history, cached answers). Keeping them docker-internal-only is a small but free security win.

---

## 🔁 Two main flows

### Flow A: A reviewer adds a new source

```mermaid
sequenceDiagram
    participant R as Reviewer
    participant UI as chat-ui
    participant API as agent-api
    participant LS as label-studio
    participant M as mongodb
    participant Q as qdrant

    R->>UI: Upload PDF via sidebar
    UI->>API: POST /api/ingest/upload
    API->>API: Extract text (PyMuPDF + OCR fallback)
    API->>M: Insert into staging_sources (status=pending)
    API->>LS: Push task to review project
    Note over LS: Reviewer opens Label Studio,<br/>chooses Approve/Reject + metadata
    R->>UI: Click "Sync" in sidebar
    UI->>API: POST /api/review/sync
    API->>LS: Fetch annotated tasks
    LS-->>API: List of decisions
    loop For each approved task
        API->>M: Mark staging as approved
        API->>API: Chunk text (800-word windows)
        loop For each chunk
            API->>API: Compute embedding (384-dim)
            API->>M: Insert into psychology_docs
            API->>Q: Upsert vector with payload
        end
    end
```

### Flow B: A user asks a question

```mermaid
sequenceDiagram
    participant U as User
    participant UI as chat-ui
    participant API as agent-api
    participant R as redis
    participant T as libretranslate
    participant Q as qdrant
    participant M as mongodb
    participant O as ollama

    U->>UI: Type "علائم اضطراب چیست؟"
    UI->>API: POST /api/agent/ask {question, chat_id}
    API->>R: Check cache for this question
    alt Cache hit
        R-->>API: Cached answer
    else Cache miss
        API->>API: Detect language (FA)
        API->>API: Looks like greeting? No
        API->>API: Compute question embedding
        API->>Q: Search top-3 verified passages
        Q-->>API: Hits with similarity scores
        alt Top score < threshold (small-talk)
            API->>T: Translate question FA→EN
            API->>O: Generate small-talk reply
            O-->>API: Friendly 1-2 sentence reply
        else Good match (real question)
            API->>M: Fetch full passage texts
            API->>T: Translate question FA→EN
            API->>O: Generate answer from passages
            O-->>API: English answer
            API->>API: Validate (trust, pop-psych flags)
            API->>T: Translate answer EN→FA
        end
        API->>R: Cache result for 1h
        API->>M: Log to conversations + chat_sessions
    end
    API-->>UI: JSON response
    UI->>U: Render bubble with sources
```

---

## 🧱 MongoDB collections

```
psyche (database)
├── staging_sources       — uploaded files awaiting / after review
├── psychology_docs       — approved, chunked, embedded passages (the only thing the agent sees)
├── conversations         — append-only audit log of every Q&A
└── chat_sessions         — grouped multi-turn conversations with title + messages
```

> 🔒 **Visibility rule:** The agent **only reads `psychology_docs`**. Everything else is for auditing or workflow. If a document isn't in `psychology_docs`, the agent literally cannot quote it.

See [Code Walkthrough → main.py](./07-code-walkthrough.md#mainpy) for the exact queries.

---

## 🌍 Where data lives on disk

Docker volumes persist across container restarts. They live under `~/Library/Containers/com.docker.docker/...` on macOS or `/var/lib/docker/volumes/` on Linux.

| Volume | What's in it |
|--------|--------------|
| `mongo_data` | All MongoDB collections |
| `qdrant_data` | Vector index files |
| `ollama_data` | Downloaded LLM models (can be several GB) |
| `label_studio_data` | Annotation project state |

> ⚠️ **Backup tip:** if you only back up one thing, back up `mongo_data` — that's your source of truth. Qdrant can be rebuilt by re-embedding `psychology_docs`.

---

## 🤝 How services authenticate to each other

| From | To | Auth method |
|------|----|----|
| agent-api | mongodb | Username/password from `.env` |
| agent-api | qdrant | None (network isolation) |
| agent-api | redis | None (network isolation) |
| agent-api | ollama | None (network isolation) |
| agent-api | libretranslate | None (network isolation) |
| agent-api | label-studio | API token (`LABEL_STUDIO_API_KEY` in `.env`) |
| browser | chat-ui | None (alpha — do not expose to internet) |

> 🛑 **Security note:** This project is intended for **single-tenant local use**. The alpha API has no user authentication. Do not expose `:8000` or `:3000` to the public internet without adding auth.

---

## 🎛️ Why these specific technologies?

| Choice | Alternative | Why we picked it |
|--------|-------------|------------------|
| **Ollama** | OpenAI API, Anthropic API | Free, runs offline, no per-token billing |
| **Qdrant** | Pinecone, Weaviate, pgvector | Open source, very fast, great Docker image |
| **MongoDB** | Postgres | Flexible schema for evolving document shapes |
| **Redis** | In-memory dict | Persistent across restarts, atomic TTL |
| **LibreTranslate** | Google Translate, DeepL | Self-hosted = no API key, no data leakage |
| **Label Studio** | Custom UI | Already perfect for our annotation flow |
| **FastAPI** | Flask, Django | Async, type hints, auto Swagger `/docs` |
| **paraphrase-multilingual-MiniLM** | OpenAI embeddings | Multilingual, 384-dim, runs on CPU |

---

[← Index](./README.md) · [Next: Getting Started →](./03-getting-started.md)
