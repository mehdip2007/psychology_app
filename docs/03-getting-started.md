# 3. Getting Started

> **From `git clone` to your first answered question — step by step.**

[← Index](./README.md) · [← Architecture](./02-architecture.md) · [Next: Knowledge Pipeline →](./04-knowledge-pipeline.md)

---

## ✅ Prerequisites

Before you start, make sure you have:

| Tool | Why | How to check |
|------|-----|--------------|
| **Docker Desktop** (v4.x+) or **Docker Engine + Compose v2+** | Runs every service | `docker --version` |
| **8 GB RAM minimum** (16 GB recommended) | Ollama + embeddings need memory | `free -h` (Linux) / Activity Monitor (Mac) |
| **~15 GB free disk** | Containers + downloaded LLM model | `df -h .` |
| **A terminal** | You'll be typing commands | Just open Terminal / iTerm / PowerShell |

> 💡 **GPU optional.** Ollama auto-detects an NVIDIA GPU and uses it; without one it falls back to CPU (slower but works fine for a small user base).

---

## 🚀 Step 1: Clone and configure

```bash
# Grab the code
git clone <repo-url> psyche-agent
cd psyche-agent

# Copy the example env file
cp env.example .env
```

Now open `.env` in your editor. **You only need to change one thing right now**:

```bash
MONGO_PASSWORD=admin              # ← change this to something unique
```

Everything else has sensible defaults. You can revisit [Configuration](./08-configuration.md) later.

> ⚠️ **Don't commit your `.env`** — it's already in `.gitignore`.

---

## 🐳 Step 2: Start every service

```bash
docker compose up -d
```

This pulls and starts **8 containers**. First run downloads several GB of images — be patient (5–15 min on a normal connection).

Check that they're all running:

```bash
docker compose ps
```

You should see 8 services with status `running` or `healthy`. If any is `exited`, jump to [Troubleshooting](./09-troubleshooting.md).

---

## 🧠 Step 3: Pull an LLM model

Ollama starts empty — no models yet. Pick one and pull it:

```bash
# The default that .env expects
docker exec -it psyche-ollama ollama pull mistral
```

Other good choices:

| Model | Size | Speed (CPU) | Quality |
|-------|------|-------------|---------|
| `mistral` (default) | ~4 GB | medium | ⭐⭐⭐⭐ |
| `llama3:8b` | ~5 GB | medium | ⭐⭐⭐⭐ |
| `phi3` | ~2 GB | fast | ⭐⭐⭐ |
| `qwen2:7b` | ~4 GB | medium | ⭐⭐⭐⭐ |

If you pick a different model, update `OLLAMA_MODEL=` in `.env` and restart:

```bash
docker compose restart agent-api
```

---

## 🗄️ Step 4: Initialise the databases

```bash
chmod +x init_db.sh
./init_db.sh
```

This:
- Creates MongoDB indexes on `staging_sources`, `psychology_docs`, `conversations`
- Creates the Qdrant collection `psychology_docs` with vector size 384

You only need to run it **once** (or again if you wipe volumes).

---

## 🏷️ Step 5: Set up Label Studio (one-time)

Label Studio is where you (or your reviewer) approve PDFs. It needs a tiny bit of manual setup the first time.

### 5a. Open it in your browser

[http://localhost:8080](http://localhost:8080)

Create an account (any email works — it's local).

### 5b. Create the review project

1. Click **Create Project**
2. Name it anything (e.g. *Psyche Review*)
3. Go to **Settings → Labeling Interface → Code**
4. Paste this XML config:

```xml
<View>
  <Header value="Source under review"/>
  <Text name="text" value="$text" granularity="paragraph"/>

  <Choices name="decision" toName="text" choice="single" showInLine="true">
    <Choice value="Approve"/>
    <Choice value="Reject"/>
  </Choices>

  <TextArea name="source_name" toName="text" placeholder="Source name (e.g. DSM-5)" maxSubmissions="1"/>
  <Choices name="source_type" toName="text" choice="single">
    <Choice value="clinical"/>
    <Choice value="textbook"/>
    <Choice value="article"/>
    <Choice value="unverified"/>
  </Choices>
  <TextArea name="trust_score" toName="text" placeholder="Trust score 0.0–1.0" maxSubmissions="1"/>
  <TextArea name="notes" toName="text" placeholder="Reviewer notes (optional)"/>
</View>
```

5. Save.

### 5c. Get your API token

- Click your avatar → **Account & Settings → Access Token**
- Copy the token

### 5d. Wire the token into the API

Open `.env` and set:

```bash
LABEL_STUDIO_API_KEY=<paste-token-here>
LABEL_STUDIO_PROJECT_ID=1    # check the number in the URL after /projects/
```

Restart the API so it picks up the new env:

```bash
docker compose restart agent-api
```

---

## ✔️ Step 6: Verify everything is healthy

```bash
curl http://localhost:8000/health
```

Expected:

```json
{"status":"ok","service":"psyche-agent","version":"0.1.0-alpha"}
```

---

## 📤 Step 7: Upload your first source

Open the chat UI: [http://localhost:3000](http://localhost:3000)

1. In the **sidebar** (right side, in RTL mode), find the **Upload** card.
2. Drag a psychology PDF onto it, or click to choose.
3. You'll see "✅ File uploaded — queued for review".

Now switch to Label Studio ([http://localhost:8080](http://localhost:8080)), open your project, click the queued task, and:
- Pick **Approve** (or Reject)
- Fill in source name, type, trust score
- Click **Submit**

Back in the chat UI, click **🔁 Sync Now** in the sidebar.

You should see "✅ Sync successful — 1 new source added". The Knowledge Base Status will update.

---

## 💬 Step 8: Ask your first question

Type into the chat input:

```
علائم اختلال اضطراب فراگیر چیست؟
```

(or in English, in which case the agent will first ask which language you want the answer in).

You should see:
- A **thinking dots** animation
- Then a Persian answer with **source tags** and a **confidence percentage**

🎉 Congratulations — you have a working private psychology assistant!

---

## 🧪 Step 9: Try the API directly

The UI is just a thin wrapper. Anything it does, you can curl:

```bash
# Upload
curl -X POST http://localhost:8000/ingest/upload -F "file=@/path/to/file.pdf"

# List pending
curl http://localhost:8000/review/pending

# Sync after reviewing
curl -X POST http://localhost:8000/review/sync

# Ask
curl -X POST http://localhost:8000/agent/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is CBT?"}'
```

Full reference: [API Reference](./06-api-reference.md).
Auto-generated Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs).

---

## 🔄 Day-to-day commands

| Want to... | Command |
|---|---|
| See logs (one service) | `docker compose logs -f agent-api` |
| See logs (everything) | `docker compose logs -f` |
| Restart after editing UI | `docker compose restart chat-ui` |
| Restart after editing Python | `docker compose up -d --build agent-api` |
| Stop everything | `docker compose stop` |
| Stop & remove containers (keep data) | `docker compose down` |
| Nuclear: wipe everything including data | `docker compose down -v` |

> 🛑 **`down -v` deletes Mongo + Qdrant data.** Don't run it unless you mean it.

---

## 🆘 If something is broken

Jump to [Troubleshooting](./09-troubleshooting.md). The most common gotcha (and one we've hit several times) is that **editing files doesn't take effect until you restart the right container** — see the "Docker Restart Rule" there.

---

[← Index](./README.md) · [Next: Knowledge Pipeline →](./04-knowledge-pipeline.md)
