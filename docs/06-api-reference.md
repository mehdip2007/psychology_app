# 6. API Reference

> **Every endpoint, every parameter, every response field — with curl examples.**

[← Index](./README.md) · [← Agent & Chat](./05-agent-and-chat.md) · [Next: Code Walkthrough →](./07-code-walkthrough.md)

---

## 🌐 Base URL

| Environment | URL |
|-------------|-----|
| Direct to FastAPI | `http://localhost:8000` |
| Via UI's nginx proxy | `http://localhost:3000/api` |

> 💡 The UI prefixes every call with `/api/` and nginx strips it before forwarding. You can curl either URL — both reach the same FastAPI.

Interactive Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 📜 Endpoint summary

| Method | Path | Purpose |
|--------|------|---------|
| GET | [`/health`](#get-health) | Liveness check |
| POST | [`/ingest/upload`](#post-ingestupload) | Upload a PDF/EPUB to staging |
| GET | [`/review/pending`](#get-reviewpending) | List documents awaiting review |
| POST | [`/review/sync`](#post-reviewsync) | Pull decisions from Label Studio |
| GET | [`/stats`](#get-stats) | Knowledge-base counts |
| POST | [`/agent/ask`](#post-agentask) | Ask a question |
| POST | [`/obsidian/sync`](#post-obsidiansync) | Sync approved Obsidian notes |
| POST | [`/chats`](#post-chats) | Create a chat session |
| GET | [`/chats`](#get-chats) | List chat sessions |
| GET | [`/chats/{id}`](#get-chatsid) | Get one chat with all messages |
| DELETE | [`/chats/{id}`](#delete-chatsid) | Delete a chat |
| GET | `/metrics` | Prometheus metrics (text format) |
| GET | `/docs` | OpenAPI Swagger UI |

---

## `GET /health`

Used for liveness/readiness probes.

```bash
curl http://localhost:8000/health
```

```json
{ "status": "ok", "service": "psyche-agent", "version": "0.1.0-alpha" }
```

---

## `POST /ingest/upload`

Upload a PDF or EPUB. The file is parked in staging and queued for review. **The agent CANNOT see it until approved.**

### Request
- `Content-Type: multipart/form-data`
- `file`: the PDF or EPUB file

```bash
curl -X POST http://localhost:8000/ingest/upload \
  -F "file=@/path/to/dsm5.pdf"
```

### Response (201)

```json
{
  "staging_id": "65f8...",
  "language": "en",
  "extraction_method": "text-layer",
  "char_count": 124300,
  "status": "pending_review",
  "message": "Parked in staging. Review it in Label Studio before it reaches the agent."
}
```

### Errors
| Code | Reason |
|------|--------|
| 400 | File isn't a PDF or EPUB |
| 422 | Couldn't extract any text |

---

## `GET /review/pending`

Lists documents still awaiting human review (text body omitted to keep response small).

```bash
curl http://localhost:8000/review/pending
```

```json
[
  {
    "_id": "65f8...",
    "original_filename": "anxiety_handbook.pdf",
    "language": "en",
    "extraction_method": "text-layer",
    "status": "pending",
    "uploaded_at": "2026-05-24T10:23:00Z"
  }
]
```

---

## `POST /review/sync`

Pulls every annotated task from Label Studio and applies the decisions.

- **Approved** → chunked, embedded, inserted into `psychology_docs` + Qdrant
- **Rejected** → marked rejected (audit only)
- **No decision yet** → skipped

```bash
curl -X POST http://localhost:8000/review/sync
```

### Response

```json
{
  "promoted": ["65f8...", "65f9..."],
  "rejected": ["65fa..."],
  "skipped": 12,
  "summary": "2 approved, 1 rejected."
}
```

### Errors
| Code | Reason |
|------|--------|
| 502 | Label Studio API key / project ID wrong (check `.env`) |

---

## `GET /stats`

Returns knowledge-base counts and the list of approved sources. Used by the UI sidebar.

```bash
curl http://localhost:8000/stats
```

```json
{
  "pending": 3,
  "approved": 13,
  "total_chunks": 181,
  "sources": [
    { "name": "Anxiety Disorders Overview", "chunks": 1 },
    { "name": "Mark Manson — Self-Discipline", "chunks": 18 }
  ]
}
```

---

## `POST /agent/ask`

The main agent endpoint. Send a question, get an answer.

### Request body

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `question` | string | ✅ | — | The user's message |
| `chat_id` | string | ❌ | `null` | If provided, append this Q&A to that chat's history |
| `answer_lang` | `"fa"` \| `"en"` | ❌ | — | Force the answer language. If omitted and the question is English, see *Two-step language flow* below |

### Two-step language flow (for English questions)

If `question` is detected as English and `answer_lang` is missing, the agent doesn't answer yet:

```json
{
  "language_choice_required": true,
  "detected_language": "en",
  "message": "Detected English question. Which language do you want the answer in?",
  "options": ["en", "fa"]
}
```

The UI resends with `answer_lang` set.

### Normal response

```json
{
  "answer": "اختلال اضطراب فراگیر (GAD) با ...",
  "disclaimer": "این فقط جنبه اطلاعاتی دارد ...",
  "confidence": 0.84,
  "sources": ["DSM-5", "Anxiety Disorders Overview"],
  "flags": [],
  "is_safe": true,
  "insufficient": false,
  "language": "fa"
}
```

### Small-talk response

When the question is a greeting / off-topic:

```json
{
  "answer": "سلام! خوشحالم که اینجایی. هر وقت دلت خواست از من سؤال روان‌شناسی بپرس.",
  "confidence": null,
  "sources": [],
  "is_safe": true,
  "smalltalk": true,
  "language": "fa"
}
```

### Insufficient-context response

When sources exist but the LLM can't produce a reliable answer:

```json
{
  "answer": "متأسفم، اطلاعات کافی در این مورد ندارم. لطفاً با روان‌شناس متخصص مشورت کنید.",
  "confidence": 0.0,
  "sources": ["..."],
  "is_safe": true,
  "insufficient": true,
  "language": "fa"
}
```

### Examples

```bash
# Persian question (auto-replies in Persian)
curl -X POST http://localhost:8000/agent/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "علائم اختلال اضطراب فراگیر چیست؟"}'

# English question, force Persian reply, attach to chat
curl -X POST http://localhost:8000/agent/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is cognitive behavioral therapy?",
    "answer_lang": "fa",
    "chat_id": "65fb..."
  }'
```

---

## `POST /obsidian/sync`

Scan an Obsidian vault for notes with `status: approved` in frontmatter and promote them to production.

### Request

```json
{ "vault_path": "/vault/sources" }
```

```bash
curl -X POST http://localhost:8000/obsidian/sync \
  -H "Content-Type: application/json" \
  -d '{"vault_path":"/vault/sources"}'
```

Notes with `status: pending` or `status: rejected` are skipped. Re-syncing a note whose content hash hasn't changed is a no-op.

---

## `POST /chats`

Create a new chat session.

### Request body (all optional)

```json
{ "title": "Initial title or omit" }
```

### Response

```json
{
  "id": "65fb...",
  "title": "New chat",
  "created_at": "2026-05-24T10:30:00Z",
  "updated_at": "2026-05-24T10:30:00Z",
  "message_count": 0
}
```

> 💡 If you omit `title`, the first user message sent in this chat will auto-set the title to its first 60 characters.

---

## `GET /chats`

List recent chats (newest first), without messages for speed.

### Query params

| Name | Type | Default | Limits |
|------|------|---------|--------|
| `limit` | int | 50 | 1–200 |

```bash
curl http://localhost:8000/chats?limit=20
```

### Response

```json
[
  {
    "id": "65fb...",
    "title": "What are the symptoms of GAD?",
    "created_at": "2026-05-24T10:30:00Z",
    "updated_at": "2026-05-24T10:32:11Z",
    "message_count": 4
  }
]
```

---

## `GET /chats/{id}`

Fetch one chat with the full message history.

```bash
curl http://localhost:8000/chats/65fb...
```

### Response

```json
{
  "id": "65fb...",
  "title": "What are the symptoms of GAD?",
  "created_at": "2026-05-24T10:30:00Z",
  "updated_at": "2026-05-24T10:32:11Z",
  "messages": [
    {
      "role": "user",
      "content": "What are the symptoms of GAD?",
      "ts": "2026-05-24T10:30:00Z"
    },
    {
      "role": "assistant",
      "content": "Generalized anxiety disorder presents with ...",
      "language": "fa",
      "confidence": 0.84,
      "sources": ["DSM-5"],
      "insufficient": false,
      "smalltalk": false,
      "ts": "2026-05-24T10:30:08Z"
    }
  ]
}
```

### Errors
| Code | Reason |
|------|--------|
| 400 | `id` isn't a valid ObjectId |
| 404 | No chat with that id |

---

## `DELETE /chats/{id}`

Permanently delete a chat and all its messages.

```bash
curl -X DELETE http://localhost:8000/chats/65fb...
```

```json
{ "deleted": "65fb..." }
```

---

## 🧪 Postman / Insomnia

Import the auto-generated OpenAPI spec:

```
http://localhost:8000/openapi.json
```

This gives you every endpoint with example bodies pre-filled.

---

[← Index](./README.md) · [Next: Code Walkthrough →](./07-code-walkthrough.md)
