"""Prompt template assembly for RAG queries.

Shared across naive and graph retrieval paths. Assembles the final
prompt from: user query, selected entities, retrieved triples/connections,
ranked chunks, and connection status.

TODO: implement
"""

# SYSTEM_PROMPT = """You are a research assistant for Virginia archaeology.
# Answer based ONLY on the provided knowledge graph context and source text.
# ..."""
#
# def assemble_prompt(
#     query: str,
#     selected_entities: list[dict] | None = None,
#     triples: list[tuple] | None = None,
#     chunks: list[dict] | None = None,
#     connection_status: str | None = None,
# ) -> list[dict]:
#     """Build the messages list for Claude.
#
#     Returns a list of message dicts ready for the Anthropic API.
#     """
#     ...
