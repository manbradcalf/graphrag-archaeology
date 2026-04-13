"""Prompt template assembly for RAG queries.

Shared across naive and graph retrieval paths. Assembles the final
prompt from: user query, selected entities, retrieved triples/connections,
ranked chunks, and connection status.
"""

from __future__ import annotations

from src.schema import RELATIONSHIP_DISPLAY_LABELS

SYSTEM_PROMPT = """You are a research assistant for Virginia archaeology. \
Answer based ONLY on the provided knowledge graph context and source text.

When entities are connected, explain the relationship using the graph paths \
as evidence. When no connection exists, say so directly — do not infer or \
fabricate relationships not supported by the graph. If the query cannot be \
answered from the available context, say so.

Cite sources using [1], [2] notation matching the numbered source chunks."""


def _format_entity_section(entity: dict) -> str:
    """Format a single entity's graph context for the prompt."""
    name = entity.get("name", "Unknown")
    etype = entity.get("type", "Entity")
    lines = [f"### Entity: {name} ({etype})"]

    triples = entity.get("triples", [])
    if triples:
        lines.append("Graph connections:")
        for subj, rel, obj in triples:
            display_rel = RELATIONSHIP_DISPLAY_LABELS.get(rel, rel.lower().replace("_", " "))
            lines.append(f"  - {subj} — {display_rel} — {obj}")
    else:
        lines.append("Graph connections: (none retrieved)")

    return "\n".join(lines)


def _format_chunks(chunks: list[dict]) -> str:
    """Format ranked chunks as numbered source references."""
    if not chunks:
        return "(no source chunks retrieved)"
    lines = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk.get("source", "unknown")
        text = chunk.get("text", "").strip()
        score_info = ""
        if "score" in chunk:
            score_info = f" (relevance: {chunk['score']:.3f})"
        lines.append(f"[{i}] Source: {source}{score_info}\n{text}")
    return "\n\n".join(lines)


def assemble_prompt(
    query: str | None = None,
    selected_entities: list[dict] | None = None,
    triples: list[tuple] | None = None,
    chunks: list[dict] | None = None,
    connection_status: str | None = None,
) -> list[dict]:
    """Build the messages list for Claude.

    Args:
        query: User's text question (may be None for filter-only queries).
        selected_entities: List of entity dicts with name, type, triples.
        triples: Flat list of (subject, relationship, object) tuples from
            graph traversal — used when entity-level grouping isn't available.
        chunks: Ranked source chunks with text, source, and optional score.
        connection_status: Summary of path-finding results between entities.

    Returns:
        A list of message dicts ready for the Anthropic API.
    """
    sections = []

    # User query
    if query:
        sections.append(f"## User Query\n{query}")
    else:
        sections.append("## User Query\n(No text query — browsing selected entities)")

    # Selected entities with their graph context
    if selected_entities:
        entity_parts = [
            f"## Selected Entities ({len(selected_entities)})",
        ]
        for entity in selected_entities:
            entity_parts.append(_format_entity_section(entity))
        sections.append("\n\n".join(entity_parts))

    # Flat triples (when not grouped by entity)
    if triples and not selected_entities:
        triple_lines = ["## Graph Connections"]
        for subj, rel, obj in triples:
            display_rel = RELATIONSHIP_DISPLAY_LABELS.get(rel, rel.lower().replace("_", " "))
            triple_lines.append(f"  - {subj} — {display_rel} — {obj}")
        sections.append("\n".join(triple_lines))

    # Source chunks
    sections.append(f"## Retrieved Context\n{_format_chunks(chunks or [])}")

    # Connection status
    if connection_status:
        sections.append(f"## Connection Status\n{connection_status}")

    user_content = "\n\n".join(sections)

    return [
        {"role": "user", "content": user_content},
    ]
