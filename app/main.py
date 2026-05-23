"""Psyche Agent - FastAPI application.

Three responsibilities:
  1. /ingest  - accept a PDF, extract text, park it in MongoDB staging,
                and push it to the Label Studio review queue.
  2. /review  - pull reviewer decisions from Label Studio; APPROVED sources
                are chunked, embedded and promoted to the production store.
  3. /agent   - answer Persian questions using ONLY the production store.
"""
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

import requests
import redis
from bson import ObjectId
from fastapi import FastAPI, File, HTTPException, UploadFile
from prometheus_client import Counter, make_asgi_app
from pydantic import BaseModel
from pymongo import MongoClient
from qdrant_client import QdrantClient, models

from .agent import build_prompt, generate, validate
from .config import settings
from .services import (
    LabelStudio,
    Translator,
    chunk_text,
    detect_language,
    embed,
    extract_epub,
    extract_text,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("psyche")

app = FastAPI(title="Psyche Agent", version="0.1.0-alpha")

# ---- clients -------------------------------------------------------------
mongo = MongoClient(settings.mongodb_uri)
db = mongo[settings.mongo_db_name]
qdrant = QdrantClient(url=settings.qdrant_url)
cache = redis.from_url(settings.redis_url, decode_responses=True)
translator = Translator()
label_studio = LabelStudio()

# ---- metrics -------------------------------------------------------------
INGEST_COUNT = Counter("psyche_ingest_total", "PDFs uploaded to staging")
APPROVE_COUNT = Counter("psyche_approved_total", "Sources promoted to production")
ASK_COUNT = Counter("psyche_ask_total", "Agent questions answered")
app.mount("/metrics", make_asgi_app())


# ==========================================================================
# Health
# ==========================================================================
@app.get("/health")
def health():
    return {"status": "ok", "service": "psyche-agent", "version": "0.1.0-alpha"}


# ==========================================================================
# 1. Ingestion  -  PDF -> staging -> Label Studio review queue
# ==========================================================================
@app.post("/ingest/upload")
async def ingest_upload(file: UploadFile = File(...)):
    """Upload a PDF. It is parked in staging and queued for human review.
    It is NOT visible to the agent until a reviewer approves it."""
    fname = file.filename.lower()
    if not (fname.endswith(".pdf") or fname.endswith(".epub")):
        raise HTTPException(400, "Only PDF and EPUB files are supported.")

    raw_bytes = await file.read()
    result = extract_epub(raw_bytes) if fname.endswith(".epub") else extract_text(raw_bytes)
    if not result["text"]:
        raise HTTPException(422, "No text could be extracted from this PDF.")

    language = detect_language(result["text"])
    staging_id = db.staging_sources.insert_one(
        {
            "original_filename": file.filename,
            "extracted_text": result["text"],
            "extraction_method": result["method"],
            "language": language,
            "status": "pending",
            "uploaded_at": datetime.now(timezone.utc),
            "label_studio_task": None,
        }
    ).inserted_id

    # push into the Label Studio review project
    try:
        ls_resp = label_studio.push_task(
            str(staging_id), file.filename, result["text"], language
        )
        db.staging_sources.update_one(
            {"_id": staging_id}, {"$set": {"label_studio_task": ls_resp}}
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Label Studio push failed: %s", exc)

    INGEST_COUNT.inc()
    return {
        "staging_id": str(staging_id),
        "language": language,
        "extraction_method": result["method"],
        "char_count": len(result["text"]),
        "status": "pending_review",
        "message": "Parked in staging. Review it in Label Studio before it reaches the agent.",
    }


@app.get("/review/pending")
def review_pending():
    """List sources still awaiting review (text body omitted for brevity)."""
    items = db.staging_sources.find({"status": "pending"}, {"extracted_text": 0})
    return [{**i, "_id": str(i["_id"])} for i in items]


@app.get("/stats")
def get_stats():
    """Return knowledge-base counts and the list of approved source names."""
    pending = db.staging_sources.count_documents({"status": "pending"})
    approved = db.staging_sources.count_documents({"status": "approved"})
    total_chunks = db.psychology_docs.count_documents({})
    source_names = db.psychology_docs.distinct("source_name")
    sources = sorted(
        [
            {
                "name": name,
                "chunks": db.psychology_docs.count_documents({"source_name": name}),
            }
            for name in source_names
        ],
        key=lambda x: x["name"],
    )
    return {
        "pending": pending,
        "approved": approved,
        "total_chunks": total_chunks,
        "sources": sources,
    }


# ==========================================================================
# 2. Review sync  -  pull decisions from Label Studio
# ==========================================================================
def _parse_annotation(task: dict) -> dict | None:
    """Flatten the latest Label Studio annotation into a {field: value} dict."""
    annotations = task.get("annotations", [])
    if not annotations:
        return None
    fields: dict = {}
    for item in annotations[-1].get("result", []):
        name = item.get("from_name")
        value = item.get("value", {})
        if "choices" in value:
            fields[name] = value["choices"][0] if value["choices"] else None
        elif "text" in value:
            fields[name] = value["text"][0] if value["text"] else None
    return fields


def _promote_to_production(staging_doc: dict, metadata: dict) -> list[str]:
    """Chunk + embed an approved source and write it to the production store."""
    chunks = chunk_text(staging_doc["extracted_text"])
    points, chunk_ids = [], []
    for chunk in chunks:
        mongo_id = ObjectId()
        point_id = str(uuid.uuid4())  # Qdrant requires int or UUID ids
        db.psychology_docs.insert_one(
            {
                "_id": mongo_id,
                "qdrant_id": point_id,
                "content": chunk,
                "source_name": metadata["source_name"],
                "source_type": metadata["source_type"],
                "trust_score": float(metadata["trust_score"]),
                "language": staging_doc["language"],
                "is_verified": True,
                "origin_staging_id": staging_doc["_id"],
                "ingested_at": datetime.now(timezone.utc),
            }
        )
        points.append(
            models.PointStruct(
                id=point_id,
                vector=embed(chunk),
                payload={
                    "mongo_id": str(mongo_id),
                    "source_name": metadata["source_name"],
                    "trust_score": float(metadata["trust_score"]),
                    "is_verified": True,
                },
            )
        )
        chunk_ids.append(str(mongo_id))

    if points:
        qdrant.upsert(collection_name=settings.qdrant_collection, points=points)
    return chunk_ids


def _staging_from_ls_task(task: dict) -> dict | None:
    """Return (or lazily create) a staging_sources doc for a task that was
    uploaded directly to Label Studio (no staging_id in task data).

    Fetches the PDF from LS's HTTP server, extracts text, and upserts a
    staging record so the normal approve/reject flow can proceed.
    """
    filename_path = task.get("data", {}).get("filename", "")
    if not filename_path:
        return None

    # Derive a stable de-dup key from the LS file path
    dedup_key = {"label_studio_filename": filename_path}
    existing = db.staging_sources.find_one(dedup_key)
    if existing:
        return existing

    # Fetch the PDF bytes from Label Studio's media server
    ls_file_url = f"{settings.label_studio_url}{filename_path}"
    try:
        resp = requests.get(
            ls_file_url,
            headers={"Authorization": f"Token {settings.label_studio_api_key}"},
            timeout=60,
        )
        resp.raise_for_status()
        pdf_bytes = resp.content
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not fetch LS file %s: %s", ls_file_url, exc)
        return None

    result = extract_text(pdf_bytes)
    if not result["text"]:
        logger.warning("No text extracted from %s — skipping", filename_path)
        return None

    language = detect_language(result["text"])
    original_filename = filename_path.split("/")[-1]
    # Strip the random prefix (e.g. "52017855-" added by LS)
    if len(original_filename) > 9 and original_filename[8] == "-":
        original_filename = original_filename[9:]

    doc = {
        "original_filename": original_filename,
        "extracted_text": result["text"],
        "extraction_method": result["method"],
        "language": language,
        "status": "pending",
        "uploaded_at": datetime.now(timezone.utc),
        "label_studio_task": task.get("id"),
        "label_studio_filename": filename_path,   # de-dup key
    }
    doc["_id"] = db.staging_sources.insert_one(doc).inserted_id
    logger.info("Auto-created staging record for LS task %s (%s)", task["id"], original_filename)
    return doc


@app.post("/review/sync")
def review_sync():
    """Pull reviewed tasks from Label Studio. Approved sources are promoted
    to production; rejected sources are recorded for audit but never ingested."""
    try:
        tasks = label_studio.fetch_tasks()
    except requests.exceptions.HTTPError as exc:
        ls_status = exc.response.status_code if exc.response is not None else "unknown"
        raise HTTPException(
            status_code=502,
            detail=f"Label Studio returned {ls_status} — verify LABEL_STUDIO_API_KEY and LABEL_STUDIO_PROJECT_ID in .env",
        )
    promoted, rejected, skipped = [], [], 0

    for task in tasks:
        fields = _parse_annotation(task)
        if not fields or "decision" not in fields:
            skipped += 1
            continue

        # --- locate or create the staging record ---
        staging_id = task.get("data", {}).get("staging_id")
        if staging_id:
            staging_doc = db.staging_sources.find_one({"_id": ObjectId(staging_id)})
        else:
            # Task was uploaded directly into Label Studio; auto-import it.
            staging_doc = _staging_from_ls_task(task)

        if not staging_doc or staging_doc["status"] != "pending":
            skipped += 1  # already processed or unresolvable
            continue

        if str(fields["decision"]).lower().startswith("approve"):
            metadata = {
                "source_name": fields.get("source_name")
                or staging_doc["original_filename"],
                "source_type": fields.get("source_type") or "unverified",
                "trust_score": fields.get("trust_score") or 0.7,
            }
            chunk_ids = _promote_to_production(staging_doc, metadata)
            db.staging_sources.update_one(
                {"_id": staging_doc["_id"]},
                {
                    "$set": {
                        "status": "approved",
                        "reviewed_at": datetime.now(timezone.utc),
                        "approved_metadata": metadata,
                        "production_chunk_ids": chunk_ids,
                    }
                },
            )
            APPROVE_COUNT.inc()
            promoted.append(str(staging_doc["_id"]))
        else:
            db.staging_sources.update_one(
                {"_id": staging_doc["_id"]},
                {
                    "$set": {
                        "status": "rejected",
                        "reviewed_at": datetime.now(timezone.utc),
                        "review_notes": fields.get("notes", ""),
                    }
                },
            )
            rejected.append(str(staging_doc["_id"]))

    return {
        "promoted": promoted,
        "rejected": rejected,
        "skipped": skipped,
        "summary": f"{len(promoted)} approved, {len(rejected)} rejected.",
    }


# ==========================================================================
# 3. Agent  -  Persian question -> verified RAG -> Persian answer
# ==========================================================================
class AskRequest(BaseModel):
    question: str


@app.post("/agent/ask")
def agent_ask(req: AskRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "Field 'question' must not be empty.")

    # cache hit?
    cache_key = "ask:" + hashlib.sha256(question.encode()).hexdigest()
    if (cached := cache.get(cache_key)) is not None:
        return {**json.loads(cached), "cached": True}

    lang = detect_language(question)

    # The multilingual embedder lets a Persian question match English docs.
    hits = qdrant.search(
        collection_name=settings.qdrant_collection,
        query_vector=embed(question),
        limit=5,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="is_verified", match=models.MatchValue(value=True)
                )
            ]
        ),
    )
    passages = []
    for hit in hits:
        mid = hit.payload.get("mongo_id")
        doc = db.psychology_docs.find_one({"_id": ObjectId(mid)}) if mid else None
        if doc:
            passages.append(doc)

    # no verified knowledge -> say so, do not improvise
    if not passages:
        answer_fa = translator.to_persian(
            "I don't have verified clinical information on this topic yet. "
            "Please consult a licensed psychologist."
        )
        return {
            "answer": answer_fa,
            "confidence": 0.0,
            "sources": [],
            "is_safe": True,
            "language": "fa",
        }

    # reason in English, then translate the answer back to Persian
    question_en = translator.to_english(question) if lang == "fa" else question
    answer_en = generate(build_prompt(question_en, passages))
    check = validate(answer_en, passages)

    if not check["is_safe"]:
        answer_en = (
            "I can only provide verified clinical information and could not produce "
            "a reliable answer here. Please consult a licensed psychologist."
        )

    answer_fa = translator.to_persian(answer_en)
    disclaimer_fa = translator.to_persian(
        "This is informational only and is not a substitute for professional care."
    )

    response = {
        "answer": answer_fa,
        "disclaimer": disclaimer_fa,
        "confidence": check["confidence"],
        "sources": sorted({p["source_name"] for p in passages}),
        "flags": check["flags"],
        "is_safe": check["is_safe"],
        "language": "fa",
    }

    # audit log + cache
    db.conversations.insert_one(
        {
            "question": question,
            "language": lang,
            "answer_en": answer_en,
            "answer_fa": answer_fa,
            "confidence": check["confidence"],
            "flags": check["flags"],
            "sources": response["sources"],
            "created_at": datetime.now(timezone.utc),
        }
    )
    cache.setex(cache_key, 3600, json.dumps(response))
    ASK_COUNT.inc()
    return response


# ==========================================================================
# 4. Obsidian vault sync
# ==========================================================================
OBSIDIAN_SYNC_COUNT = Counter("psyche_obsidian_sync_total", "Obsidian syncs triggered")


class ObsidianSyncRequest(BaseModel):
    vault_path: str = "/vault/sources"


@app.post("/obsidian/sync")
def obsidian_sync(req: ObsidianSyncRequest):
    """Scan an Obsidian vault for notes with ``status: approved`` in their
    YAML frontmatter and promote them into the production store."""
    from .integrations.obsidian_sync import sync_vault

    result = sync_vault(req.vault_path, mongo_client=mongo, qdrant_client=qdrant)
    if "error" in result:
        raise HTTPException(400, result["error"])
    OBSIDIAN_SYNC_COUNT.inc()
    return result
