#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Initialise MongoDB indexes and the Qdrant collection.
# Run AFTER `docker compose up -d`, from the project root.
# ---------------------------------------------------------------------------
set -euo pipefail

# Load .env if present
[ -f .env ] && set -a && source .env && set +a

MONGO_USER="${MONGO_USER:-admin}"
MONGO_PASSWORD="${MONGO_PASSWORD:-changeme}"
MONGO_DB="${MONGO_DB_NAME:-psyche}"
QDRANT_URL_LOCAL="http://localhost:6333"
QDRANT_COLLECTION="${QDRANT_COLLECTION:-psychology_docs}"
EMBEDDING_DIM="${EMBEDDING_DIM:-384}"

echo "==> Creating MongoDB indexes..."
docker exec -i psyche-mongodb mongosh -u "$MONGO_USER" -p "$MONGO_PASSWORD" --quiet <<EOF
use ${MONGO_DB}
db.staging_sources.createIndex({ status: 1 })
db.staging_sources.createIndex({ uploaded_at: -1 })
db.psychology_docs.createIndex({ is_verified: 1 })
db.psychology_docs.createIndex({ source_name: 1 })
db.conversations.createIndex({ created_at: -1 })
print("  MongoDB indexes created.")
EOF

echo "==> Creating Qdrant collection '${QDRANT_COLLECTION}' (dim=${EMBEDDING_DIM})..."
curl -s -X PUT "${QDRANT_URL_LOCAL}/collections/${QDRANT_COLLECTION}" \
  -H "Content-Type: application/json" \
  -d "{\"vectors\": {\"size\": ${EMBEDDING_DIM}, \"distance\": \"Cosine\"}}" >/dev/null \
  && echo "  Qdrant collection ready."

echo "==> Done. The database layer is initialised."
