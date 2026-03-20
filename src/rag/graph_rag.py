"""Entity-first retrieval: filters → subgraph → chunks → Claude.

Three retrieval paths depending on user input:
  - Path A (filters only): graph traversal via MENTIONS edges, no vector search
  - Path B (text only): vector search, no graph traversal
  - Path C (filters + text): both, merged with relevance boosting

TODO: implement
"""

# async def query(
#     filters: list[str] | None = None,
#     question: str | None = None,
#     k: int = 10,
# ) -> dict:
#     """Run an entity-first graph retrieval query.
#
#     Args:
#         filters: List of entity_ids selected by the user.
#         question: Optional text query.
#         k: Number of chunks to retrieve.
#
#     Returns:
#         Dict with answer, sources, evidence_triples, stats, connection_status.
#     """
#     ...
