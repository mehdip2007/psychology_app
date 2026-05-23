"""Sync approved Obsidian notes into the production vector store."""
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from bson import ObjectId
from qdrant_client import models

from ..config import settings
from ..services import chunk_text, embed

logger = logging.getLogger("psyche.obsidian_sync")


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body. Returns ({}, content) if none."""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, parts[2].strip()


def sync_vault(vault_path: str, mongo_client, qdrant_client) -> dict:
    """Scan *vault_path* for markdown notes with ``status: approved`` in their
    YAML frontmatter and promote them into the production store.

    Returns a summary dict with keys synced / updated / skipped / errors.
    """
    path = Path(vault_path)
    if not path.exists():
        return {"error": f"Vault path does not exist: {vault_path}"}

    db = mongo_client[settings.mongo_db_name]
    synced, updated, skipped, errors = [], [], [], []

    for md_file in sorted(path.rglob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("Cannot read %s: %s", md_file, exc)
            errors.append(md_file.name)
            continue

        meta, body = _parse_frontmatter(content)
        if str(meta.get("status", "")).lower() != "approved":
            skipped.append(md_file.name)
            continue

        content_hash = hashlib.sha256(body.encode()).hexdigest()
        source_name = str(meta.get("title") or md_file.stem)
        trust_score = float(meta.get("trust_score", 0.8))
        source_type = str(meta.get("source_type", "obsidian_note"))

        # Already synced with identical content — nothing to do.
        if db.staging_sources.find_one(
            {"obsidian_path": str(md_file), "content_hash": content_hash}
        ):
            skipped.append(md_file.name)
            continue

        # Updated note — remove stale chunks first.
        old = db.staging_sources.find_one({"obsidian_path": str(md_file)})
        if old:
            old_qdrant_ids = [
                doc["qdrant_id"]
                for doc in db.psychology_docs.find({"origin_staging_id": old["_id"]})
            ]
            if old_qdrant_ids:
                qdrant_client.delete(
                    collection_name=settings.qdrant_collection,
                    points_selector=models.PointIdsList(points=old_qdrant_ids),
                )
            db.psychology_docs.delete_many({"origin_staging_id": old["_id"]})
            db.staging_sources.delete_one({"_id": old["_id"]})

        staging_id = db.staging_sources.insert_one(
            {
                "original_filename": md_file.name,
                "obsidian_path": str(md_file),
                "content_hash": content_hash,
                "extracted_text": body,
                "extraction_method": "obsidian",
                "language": "en",
                "status": "approved",
                "source_name": source_name,
                "source_type": source_type,
                "trust_score": trust_score,
                "label_studio_task": None,
                "uploaded_at": datetime.now(timezone.utc),
            }
        ).inserted_id

        points = []
        for chunk in chunk_text(body):
            mongo_id = ObjectId()
            point_id = str(uuid.uuid4())
            db.psychology_docs.insert_one(
                {
                    "_id": mongo_id,
                    "qdrant_id": point_id,
                    "content": chunk,
                    "source_name": source_name,
                    "source_type": source_type,
                    "trust_score": trust_score,
                    "language": "en",
                    "is_verified": True,
                    "origin_staging_id": staging_id,
                    "ingested_at": datetime.now(timezone.utc),
                }
            )
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=embed(chunk),
                    payload={
                        "mongo_id": str(mongo_id),
                        "source_name": source_name,
                        "trust_score": trust_score,
                        "is_verified": True,
                    },
                )
            )

        if points:
            qdrant_client.upsert(
                collection_name=settings.qdrant_collection, points=points
            )

        (updated if old else synced).append(md_file.name)
        logger.info(
            "%s '%s' (%d chunks)", "Updated" if old else "Synced", source_name, len(points)
        )

    return {
        "synced": synced,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "summary": f"{len(synced)} new, {len(updated)} updated, {len(skipped)} skipped.",
    }
