"""Central configuration for the archaeology knowledge graph project.

Loads environment variables from .env (if python-dotenv is installed),
then exposes module-level constants for paths, model names, Neo4j
credentials, and chunking parameters.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional .env loading — python-dotenv is a soft dependency
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env(
    key: str, default: str | None = None, *, fallback_key: str | None = None
) -> str:
    """Return an env var, optionally trying a fallback key before the default."""
    value = os.getenv(key)
    if value:
        return value
    if fallback_key:
        value = os.getenv(fallback_key)
        if value:
            return value
    if default is not None:
        return default
    raise EnvironmentError(f"Required env var {key!r} is not set")


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY: str = _env(
    "ANTHROPIC_API_KEY",
    default="",
    fallback_key="ANTHROPIC_API_KEY_SF_PM",
)
OPENAI_API_KEY: str = _env("OPENAI_API_KEY", default="")


# ---------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------
NEO4J_URI: str = _env("NEO4J_URI", default="bolt://localhost:7687")
NEO4J_USERNAME: str = _env("NEO4J_USERNAME", default="neo4j")
NEO4J_PASSWORD: str = _env("NEO4J_PASSWORD", default="Password1")
NEO4J_DATABASE: str = _env("NEO4J_DATABASE", default="neo4j")

# ---------------------------------------------------------------------------
# LLM provider — "anthropic", "openai", "ollama"
# ---------------------------------------------------------------------------
LLM_PROVIDER: str = _env("LLM_PROVIDER", default="anthropic")

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
ANTHROPIC_NER_MODEL: str = _env(
    "ANTHROPIC_NER_MODEL", default="claude-haiku-4-5-20251001"
)
OPENAI_NER_MODEL: str = _env("OPENAI_NER_MODEL", default="gpt-4o")
OLLAMA_NER_MODEL: str = _env("OLLAMA_NER_MODEL", default="qwen3:8b")
_DEFAULT_NER_MODELS = {
    "anthropic": ANTHROPIC_NER_MODEL,
    "openai": OPENAI_NER_MODEL,
    "ollama": OLLAMA_NER_MODEL,
}
NER_MODEL: str = _env(
    "NER_MODEL",
    default=_DEFAULT_NER_MODELS.get(LLM_PROVIDER, ANTHROPIC_NER_MODEL),
)
CLEANUP_MODEL: str = _env("CLEANUP_MODEL", default="qwen3:8b")
EMBEDDING_MODEL: str = _env(
    "EMBEDDING_MODEL", default="nomic-ai/nomic-embed-text-v2-moe"
)
EMBEDDING_DIM: int = int(_env("EMBEDDING_DIM", default="768"))

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
CHUNK_SIZE: int = int(_env("CHUNK_SIZE", default="1500"))
CHUNK_OVERLAP: int = int(_env("CHUNK_OVERLAP", default="200"))

# ---------------------------------------------------------------------------
# Paths (relative to project root)
# ---------------------------------------------------------------------------
DATA_DIR: Path = Path(_env("DATA_DIR", default="data"))
PDF_DIR: Path = Path(_env("PDF_DIR", default="data/pdf"))
MD_DIR: Path = Path(_env("MD_DIR", default="data/md"))
SHACL_PATH: Path = Path(
    _env("SHACL_PATH", default="shacl/virginia-archaeology.shacl.ttl")
)
