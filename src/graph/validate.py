"""SHACL validation of the Neo4j graph using graphlint.

Runs as a post-load check (Step 10). Domain nodes should pass all shape
checks. Chunk/MENTIONS/FROM_DOCUMENT are intentionally outside SHACL and
will appear as warnings in strict mode — that's expected.

TODO: implement
"""

# def validate(driver, shacl_path: Path) -> dict:
#     """Run graphlint SHACL validation against the Neo4j graph.
#
#     Returns a validation report dict with pass/fail per shape.
#     """
#     ...
#
# def print_report(report: dict) -> None:
#     """Pretty-print a validation report."""
#     ...
