"""Naive RAG: vector search → chunks → Claude.

No graph traversal. Used as a comparison baseline against graph-enhanced
retrieval to demonstrate the value of the knowledge graph.

TODO: implement
"""

# async def query(question: str, k: int = 10) -> dict:
#     """Run a naive vector-only RAG query.
#
#     1. Embed the question
#     2. Vector search on chunk_embedding index (top-k)
#     3. Assemble prompt with ranked chunks
#     4. Claude generates answer with source citations
#     """
#     ...
