"""Build a knowledge graph from archaeology PDFs using neo4j-graphrag SimpleKGPipeline.

Uses the CIDOC-CRM-derived schema from this project to extract entities and
relationships from Virginia archaeology source PDFs and load them into Neo4j.

Usage:
    uv run python src/neo4j_kg_pipeline.py
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Optional, Union

# Allow importing sibling modules from src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import neo4j
from neo4j_graphrag.embeddings import SentenceTransformerEmbeddings
from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline
from neo4j_graphrag.llm import AnthropicLLM, OllamaLLM, OpenAILLM
from neo4j_graphrag.llm.types import LLMResponse
from neo4j_graphrag.message_history import MessageHistory
from neo4j_graphrag.types import LLMMessage

from config import (
    ANTHROPIC_API_KEY,
    EMBEDDING_MODEL,
    LLM_PROVIDER,
    NEO4J_DATABASE,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USERNAME,
    NER_MODEL,
    OPENAI_API_KEY,
    PDF_DIR,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("kg_pipeline")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("neo4j").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("anthropic").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Throttled LLM wrapper — prevents 429s on tight rate limits
# ---------------------------------------------------------------------------

# Haiku free tier: 10K input tokens/min, 50 requests/min
MAX_REQUESTS_PER_MINUTE = 3  # conservative: ~3K tokens/request × 3 = 9K tokens/min


class ThrottledAnthropicLLM(AnthropicLLM):
    """AnthropicLLM with a token-bucket throttle to stay under rate limits."""

    _semaphore: asyncio.Semaphore = asyncio.Semaphore(1)
    _min_interval: float = 60.0 / MAX_REQUESTS_PER_MINUTE
    _last_request: float = 0.0

    async def ainvoke(
        self,
        input: str,
        message_history: Optional[Union[list[LLMMessage], MessageHistory]] = None,
        system_instruction: Optional[str] = None,
    ) -> LLMResponse:
        async with self._semaphore:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request)
            if wait > 0:
                logger.debug("Throttling: waiting %.1fs before next LLM call", wait)
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()
            return await super().ainvoke(input, message_history, system_instruction)


# ---------------------------------------------------------------------------
# Schema — CIDOC-CRM ontology mapped for SimpleKGPipeline
# ---------------------------------------------------------------------------

NODE_TYPES: list[dict[str, Any]] = [
    {
        "label": "E27_Site",
        "description": "An archaeological site (e.g., Cactus Hill, Werowocomoco, Thunderbird)",
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "note", "type": "STRING"},
        ],
    },
    {
        "label": "E74_Group",
        "description": "A tribe, nation, confederacy, or cultural group (e.g., Powhatan, Monacan, Nottoway)",
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "note", "type": "STRING"},
            {"name": "group_type", "type": "STRING"},
        ],
    },
    {
        "label": "E21_Person",
        "description": "A historical person referenced in the source material (e.g., Wahunsenacah, John Smith)",
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "note", "type": "STRING"},
        ],
    },
    {
        "label": "E22_Man-Made_Object",
        "description": "An artifact found at a site (e.g., Clovis point, ceramic sherd, shell gorget)",
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "note", "type": "STRING"},
            {"name": "material", "type": "STRING"},
            {"name": "use", "type": "STRING"},
        ],
    },
    {
        "label": "E5_Event",
        "description": "A historical or archaeological event (e.g., English contact, migration, battle)",
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "note", "type": "STRING"},
            {"name": "event_type", "type": "STRING"},
        ],
    },
    {
        "label": "E53_Place",
        "description": "A geographic location or region (e.g., Shenandoah Valley, James River, Tidewater)",
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "note", "type": "STRING"},
            {"name": "place_type", "type": "STRING"},
        ],
    },
    {
        "label": "E52_Time-Span",
        "description": "A cultural or chronological period (e.g., Late Woodland, Paleo-Indian, 15000 BP)",
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "begin_date", "type": "STRING"},
            {"name": "end_date", "type": "STRING"},
        ],
    },
    {
        "label": "E31_Document",
        "description": "A source document or publication",
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "doc_type", "type": "STRING"},
        ],
    },
    {
        "label": "S19_Encounter_Event",
        "description": "An archaeological discovery or encounter event",
        "properties": [
            {"name": "name", "type": "STRING"},
            {"name": "discovery_type", "type": "STRING"},
        ],
    },
]

RELATIONSHIP_TYPES: list[dict[str, str]] = [
    {
        "label": "P53_HAS_FORMER_OR_CURRENT_LOCATION",
        "description": "Where something is/was located",
    },
    {
        "label": "HAS_CULTURAL_AFFILIATION",
        "description": "Cultural group associated with a site",
    },
    {
        "label": "P107I_IS_CURRENT_OR_FORMER_MEMBER_OF",
        "description": "Membership in a group",
    },
    {"label": "P4_HAS_TIME-SPAN", "description": "Associated time period"},
    {"label": "P8_TOOK_PLACE_ON_OR_WITHIN", "description": "Where an event took place"},
    {"label": "P11_HAD_PARTICIPANT", "description": "Who participated in an event"},
    {"label": "O19_HAS_FOUND_OBJECT", "description": "Object found during discovery"},
    {"label": "P14_CARRIED_OUT_BY", "description": "Who carried out an action"},
    {"label": "P70I_IS_DOCUMENTED_IN", "description": "Source documentation"},
    {"label": "P89_FALLS_WITHIN", "description": "Place containment hierarchy"},
    {"label": "P45_CONSISTS_OF", "description": "Material composition of artifact"},
    {"label": "P101_HAD_AS_GENERAL_USE", "description": "Functional use of artifact"},
]

PATTERNS: list[tuple[str, str, str]] = [
    ("E27_Site", "P53_HAS_FORMER_OR_CURRENT_LOCATION", "E53_Place"),
    ("E74_Group", "P53_HAS_FORMER_OR_CURRENT_LOCATION", "E53_Place"),
    ("E22_Man-Made_Object", "P53_HAS_FORMER_OR_CURRENT_LOCATION", "E27_Site"),
    ("E27_Site", "HAS_CULTURAL_AFFILIATION", "E74_Group"),
    ("E21_Person", "P107I_IS_CURRENT_OR_FORMER_MEMBER_OF", "E74_Group"),
    ("E74_Group", "P107I_IS_CURRENT_OR_FORMER_MEMBER_OF", "E74_Group"),
    ("E27_Site", "P4_HAS_TIME-SPAN", "E52_Time-Span"),
    ("E74_Group", "P4_HAS_TIME-SPAN", "E52_Time-Span"),
    ("E22_Man-Made_Object", "P4_HAS_TIME-SPAN", "E52_Time-Span"),
    ("E5_Event", "P4_HAS_TIME-SPAN", "E52_Time-Span"),
    ("S19_Encounter_Event", "P4_HAS_TIME-SPAN", "E52_Time-Span"),
    ("E31_Document", "P4_HAS_TIME-SPAN", "E52_Time-Span"),
    ("E5_Event", "P8_TOOK_PLACE_ON_OR_WITHIN", "E53_Place"),
    ("E5_Event", "P8_TOOK_PLACE_ON_OR_WITHIN", "E27_Site"),
    ("S19_Encounter_Event", "P8_TOOK_PLACE_ON_OR_WITHIN", "E27_Site"),
    ("E5_Event", "P11_HAD_PARTICIPANT", "E21_Person"),
    ("E5_Event", "P11_HAD_PARTICIPANT", "E74_Group"),
    ("S19_Encounter_Event", "O19_HAS_FOUND_OBJECT", "E22_Man-Made_Object"),
    ("S19_Encounter_Event", "P14_CARRIED_OUT_BY", "E21_Person"),
    ("E31_Document", "P14_CARRIED_OUT_BY", "E21_Person"),
    ("E27_Site", "P70I_IS_DOCUMENTED_IN", "E31_Document"),
    ("E74_Group", "P70I_IS_DOCUMENTED_IN", "E31_Document"),
    ("E21_Person", "P70I_IS_DOCUMENTED_IN", "E31_Document"),
    ("E22_Man-Made_Object", "P70I_IS_DOCUMENTED_IN", "E31_Document"),
    ("E5_Event", "P70I_IS_DOCUMENTED_IN", "E31_Document"),
    ("S19_Encounter_Event", "P70I_IS_DOCUMENTED_IN", "E31_Document"),
    ("E53_Place", "P89_FALLS_WITHIN", "E53_Place"),
    ("E22_Man-Made_Object", "P45_CONSISTS_OF", "E22_Man-Made_Object"),
    ("E22_Man-Made_Object", "P101_HAD_AS_GENERAL_USE", "E22_Man-Made_Object"),
]

# ---------------------------------------------------------------------------
# PDF paths (relative to project root)
# ---------------------------------------------------------------------------

PDF_FILES: list[Path] = [
    PDF_DIR / "sample.pdf",
    PDF_DIR / "259 ASV Newsletter Dec 2025.pdf",
]

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _build_pipeline() -> tuple[SimpleKGPipeline, neo4j.Driver]:
    """Construct the SimpleKGPipeline with the configured LLM and local embeddings."""
    logger.info("Initializing Neo4j driver at %s (db=%s)", NEO4J_URI, NEO4J_DATABASE)
    driver = neo4j.GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
    )
    driver.verify_connectivity()
    logger.info("Neo4j connection verified")

    logger.info("Initializing LLM (%s): %s", LLM_PROVIDER, NER_MODEL)
    llm_params = {"max_tokens": 4096, "temperature": 0}
    if LLM_PROVIDER == "ollama":
        llm = OllamaLLM(
            model_name=NER_MODEL,
            model_params={"format": "json", "options": {"temperature": 0}},
        )
    elif LLM_PROVIDER == "openai":
        llm = OpenAILLM(
            model_name=NER_MODEL, model_params=llm_params, api_key=OPENAI_API_KEY
        )
    else:
        llm = ThrottledAnthropicLLM(
            model_name=NER_MODEL, model_params=llm_params, api_key=ANTHROPIC_API_KEY
        )

    logger.info("Initializing embedder: %s", EMBEDDING_MODEL)
    embedder = SentenceTransformerEmbeddings(
        model=EMBEDDING_MODEL,
        trust_remote_code=True,
    )

    logger.info(
        "Building SimpleKGPipeline with %d node types, %d rel types, %d patterns",
        len(NODE_TYPES),
        len(RELATIONSHIP_TYPES),
        len(PATTERNS),
    )

    pipeline = SimpleKGPipeline(
        llm=llm,
        driver=driver,
        embedder=embedder,
        schema={
            "node_types": NODE_TYPES,
            "relationship_types": RELATIONSHIP_TYPES,
            "patterns": PATTERNS,
            "additional_node_types": False,
        },
        from_pdf=True,
        perform_entity_resolution=True,
        on_error="IGNORE",
        neo4j_database="neo4j",
    )

    return pipeline, driver


async def process_pdfs(pipeline: SimpleKGPipeline, pdf_files: list[Path]) -> None:
    """Process each PDF through the pipeline sequentially."""
    for i, pdf_path in enumerate(pdf_files, 1):
        if not pdf_path.exists():
            logger.warning("PDF not found, skipping: %s", pdf_path)
            continue

        logger.info(
            "[%d/%d] Processing: %s (%.1f MB)",
            i,
            len(pdf_files),
            pdf_path.name,
            pdf_path.stat().st_size / (1024 * 1024),
        )

        t0 = time.perf_counter()
        try:
            result = await pipeline.run_async(file_path=str(pdf_path))
            elapsed = time.perf_counter() - t0
            logger.info(
                "[%d/%d] Finished %s in %.1fs — result: %s",
                i,
                len(pdf_files),
                pdf_path.name,
                elapsed,
                result,
            )
        except Exception:
            elapsed = time.perf_counter() - t0
            logger.exception(
                "[%d/%d] Failed processing %s after %.1fs",
                i,
                len(pdf_files),
                pdf_path.name,
                elapsed,
            )


async def main() -> None:
    """Entry point: load config, build pipeline, process PDFs."""
    pipeline, driver = _build_pipeline()
    try:
        await process_pdfs(pipeline, PDF_FILES)
    finally:
        logger.info("Closing Neo4j driver")
        driver.close()

    logger.info("Pipeline complete")


if __name__ == "__main__":
    asyncio.run(main())
