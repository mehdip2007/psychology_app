"""Central configuration. All values are read from environment variables / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- MongoDB ----
    mongodb_uri: str = "mongodb://admin:changeme@mongodb:27017"
    mongo_db_name: str = "psyche"

    # ---- Qdrant (vector store) ----
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "psychology_docs"

    # ---- Redis (response cache) ----
    redis_url: str = "redis://redis:6379/0"

    # ---- Ollama (local LLM) ----
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "mistral"

    # ---- LibreTranslate (FA <-> EN) ----
    libretranslate_url: str = "http://libretranslate:5000"

    # ---- Label Studio (human review tool) ----
    label_studio_url: str = "http://label-studio:8080"
    label_studio_api_key: str = ""
    label_studio_project_id: int = 1

    # ---- Embeddings ----
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384

    # ---- Guardrails ----
    min_trust_score: float = 0.7


settings = Settings()
