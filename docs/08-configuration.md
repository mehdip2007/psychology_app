# 8. Configuration

> **Every `.env` variable explained — defaults, valid values, what changes when you tune it.**

[← Index](./README.md) · [← Code Walkthrough](./07-code-walkthrough.md) · [Next: Troubleshooting →](./09-troubleshooting.md)

---

## 🗂️ Where settings live

All configuration is loaded from `.env` at the project root by `app/config.py`. Every value has a sensible default — you can boot with an empty `.env`, but a few values **should** be set for any non-toy deployment.

```python
# app/config.py
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
```

> 💡 The `extra="ignore"` means unknown variables in your `.env` are silently ignored. Typos won't crash the app — but they also won't error. Double-check spelling.

---

## 🔑 Variables by category

### 🗄️ MongoDB

| Variable | Default | Notes |
|----------|---------|-------|
| `MONGODB_URI` | `mongodb://admin:changeme@mongodb:27017` | Full connection string. Internal docker DNS hostname `mongodb`. |
| `MONGO_DB_NAME` | `psyche` | Database name (collections live inside) |
| `MONGO_USER` | `admin` | Used by `docker-compose.yml` to set up the container |
| `MONGO_PASSWORD` | `admin` | **CHANGE THIS** before non-local use |

> ⚠️ **The default `admin:admin` is fine for development on your laptop. Never deploy with it.**

---

### 🔍 Qdrant (vector store)

| Variable | Default | Notes |
|----------|---------|-------|
| `QDRANT_URL` | `http://qdrant:6333` | Internal HTTP URL. From the host: `localhost:6333`. |
| `QDRANT_COLLECTION` | `psychology_docs` | Collection name. Must match what `init_db.sh` creates. |

> 🛑 **If you change `QDRANT_COLLECTION`, you must re-run `init_db.sh`** to create the new collection with the right vector size.

---

### 🧠 Ollama (LLM)

| Variable | Default | Notes |
|----------|---------|-------|
| `OLLAMA_URL` | `http://ollama:11434` | Internal. From the host: `localhost:11434`. |
| `OLLAMA_MODEL` | `mistral` | Must match a model you've pulled into the Ollama container. |

### Switching the LLM

```bash
# Pull a new model
docker exec -it psyche-ollama ollama pull llama3:8b

# Update .env
OLLAMA_MODEL=llama3:8b

# Restart the API so it reads the new env
docker compose restart agent-api
```

| Model | Approx VRAM/RAM | Speed (CPU) | Notes |
|-------|----------------|-------------|-------|
| `mistral` | 4 GB | Medium | Solid default, multilingual-ish |
| `llama3:8b` | 5 GB | Medium | Often higher answer quality |
| `phi3` | 2 GB | Fast | Best for low-RAM machines |
| `qwen2:7b` | 4 GB | Medium | Strong on Chinese/Asian languages |

---

### 🌐 LibreTranslate

| Variable | Default | Notes |
|----------|---------|-------|
| `LIBRETRANSLATE_URL` | `http://libretranslate:5000` | Internal. From host: `localhost:5000` |

LibreTranslate auto-downloads its FA/EN language packs on first start. The volume `libretranslate_models` caches them.

---

### 🏷️ Label Studio

| Variable | Default | Notes |
|----------|---------|-------|
| `LABEL_STUDIO_URL` | `http://label-studio:8080` | Internal URL |
| `LABEL_STUDIO_API_KEY` | *(empty)* | **MUST be set after first login** ([how](./03-getting-started.md#5c-get-your-api-token)) |
| `LABEL_STUDIO_PROJECT_ID` | `1` | Numeric project ID visible in the LS URL |

> 🛑 **If `LABEL_STUDIO_API_KEY` is empty, `/ingest/upload` succeeds but the task never appears in Label Studio.** Logs will show `Label Studio push failed: 401 Unauthorized`.

---

### 🧮 Embeddings

| Variable | Default | Notes |
|----------|---------|-------|
| `EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | Any sentence-transformers model. |
| `EMBEDDING_DIM` | `384` | **MUST match** the model's output dimension. |

> ⚠️ **Changing the embedding model is destructive.** Existing Qdrant vectors are in the old space. You'd need to:
> 1. Drop the Qdrant collection (`curl -X DELETE http://localhost:6333/collections/psychology_docs`)
> 2. Update `EMBEDDING_MODEL` and `EMBEDDING_DIM` in `.env`
> 3. Re-run `init_db.sh`
> 4. Re-embed every chunk in `psychology_docs` (no automatic tool yet — see [Roadmap](./10-roadmap.md))

### Compatible alternatives

| Model | Dim | Languages | Notes |
|-------|-----|-----------|-------|
| `paraphrase-multilingual-MiniLM-L12-v2` *(default)* | 384 | 50+ | Fast, good baseline |
| `paraphrase-multilingual-mpnet-base-v2` | 768 | 50+ | Better quality, slower, 2× memory |
| `LaBSE` | 768 | 109 | Best multilingual coverage, large |

---

### 🛡️ Guardrails

| Variable | Default | Notes |
|----------|---------|-------|
| `MIN_TRUST_SCORE` | `0.7` | Min `confidence` to mark `is_safe=true`. Lower = more permissive, higher = stricter |
| `SMALLTALK_SCORE_THRESHOLD` | `0.40` | Below this Qdrant top-score → small-talk path |

### Tuning `MIN_TRUST_SCORE`

| Value | Effect |
|-------|--------|
| `0.5` | Very permissive — most answers shown even with weakly-trusted sources |
| `0.7` *(default)* | Balanced |
| `0.85` | Strict — only the most authoritative sources produce visible answers |

### Tuning `SMALLTALK_SCORE_THRESHOLD`

| Value | Effect |
|-------|--------|
| `0.30` | More aggressive RAG — even weak matches trigger a sourced answer |
| `0.40` *(default)* | Balance — clear off-topic → small-talk, real questions → RAG |
| `0.55` | More aggressive small-talk — more questions fall through to chit-chat |

> 💡 **Tune `SMALLTALK_SCORE_THRESHOLD` after you have ≥20 sources.** With a tiny corpus, almost everything will score low and end up in small-talk.

---

### ⚡ Redis (cache)

| Variable | Default | Notes |
|----------|---------|-------|
| `REDIS_URL` | `redis://redis:6379/0` | Internal docker URL. Cache TTL is hard-coded at 1 hour. |

To change cache TTL, edit `cache.setex(cache_key, 3600, ...)` in `app/main.py` (search for `3600`).

---

## 📋 Complete `.env` template

```bash
# ---- MongoDB --------------------------------------------------------------
MONGO_USER=admin
MONGO_PASSWORD=changeme               # ← CHANGE THIS
MONGODB_URI=mongodb://admin:changeme@mongodb:27017
MONGO_DB_NAME=psyche

# ---- Qdrant ---------------------------------------------------------------
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=psychology_docs

# ---- Redis ----------------------------------------------------------------
REDIS_URL=redis://redis:6379/0

# ---- Ollama ---------------------------------------------------------------
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=mistral

# ---- LibreTranslate -------------------------------------------------------
LIBRETRANSLATE_URL=http://libretranslate:5000

# ---- Label Studio ---------------------------------------------------------
LABEL_STUDIO_URL=http://label-studio:8080
LABEL_STUDIO_API_KEY=                 # ← SET AFTER FIRST LS LOGIN
LABEL_STUDIO_PROJECT_ID=1

# ---- Embeddings -----------------------------------------------------------
EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
EMBEDDING_DIM=384

# ---- Guardrails -----------------------------------------------------------
MIN_TRUST_SCORE=0.7
SMALLTALK_SCORE_THRESHOLD=0.40
```

---

## 🔄 When changes take effect

| If you change... | You need to... |
|------------------|----------------|
| Any `.env` value | `docker compose restart agent-api` |
| `MONGO_PASSWORD` (for the first time) | `docker compose down -v && docker compose up -d` *(this wipes data)* |
| `OLLAMA_MODEL` | Pull the new model + restart agent-api |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | See destructive-change note above |
| Python code under `app/` | `docker compose up -d --build agent-api` |
| `ui/index.html` | `docker compose restart chat-ui` *(see [Troubleshooting](./09-troubleshooting.md))* |
| `docker-compose.yml` | `docker compose up -d` (recreates only changed services) |

---

[← Index](./README.md) · [Next: Troubleshooting →](./09-troubleshooting.md)
