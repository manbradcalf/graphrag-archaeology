"""Full pipeline: PDF extraction → NER → relationships → graph loading → embeddings.

Usage:
    # Run everything (skips steps with cached output)
    uv run python main.py

    # Individual steps
    uv run python main.py extract        # PDFs → markdown
    uv run python main.py chunk          # markdown → chunks (preview only)
    uv run python main.py ner            # NER extraction (costs money)
    uv run python main.py relations      # relationship extraction (costs money)
    uv run python main.py resolve        # entity resolution
    uv run python main.py load           # load into Neo4j
    uv run python main.py embed          # generate embeddings + vector indexes

    # Options
    uv run python main.py --force        # re-run even if cached output exists
    uv run python main.py --llm-cleanup  # use Claude for OCR cleanup (costs money)
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


def step_extract(args):
    """Step 1: Extract PDFs to cleaned markdown."""
    from src.extract.pipeline import extract_all

    print("=" * 60)
    print("STEP 1: PDF Extraction")
    print("=" * 60)
    extract_all(
        Path(args.pdf_dir),
        Path(args.output_dir),
        skip_existing=not args.force,
        cleanup=args.cleanup,
    )


def step_chunk(args):
    """Step 2: Chunk markdown files (preview — chunks are generated on-the-fly for loading)."""
    from src.extract.chunker import chunk_file

    print("=" * 60)
    print("STEP 2: Text Chunking (preview)")
    print("=" * 60)
    md_dir = Path(args.output_dir)
    for md_path in sorted(md_dir.glob("*.md")):
        chunks = chunk_file(md_path)
        sizes = [len(c.text) for c in chunks]
        print(f"  {md_path.name}: {len(chunks)} chunks, avg {sum(sizes)//len(sizes)} chars")


def step_ner(args):
    """Step 3: Extract entities using Claude NER."""
    from src.extract.ner import extract_all_entities

    print("=" * 60)
    print("STEP 3: Entity Extraction (NER)")
    print("=" * 60)
    all_entities = extract_all_entities(
        md_dir=Path(args.output_dir),
        force=args.force,
    )
    for doc_name, entities in all_entities.items():
        print(f"  {doc_name}: {len(entities)} entities")
    return all_entities


def step_relations(args):
    """Step 4: Extract relationships using Claude."""
    from src.extract.ner import _load_entities
    from src.extract.relations import extract_all_relations

    print("=" * 60)
    print("STEP 4: Relationship Extraction")
    print("=" * 60)

    # Load entities from cached NER output
    entities_dir = Path("data/entities")
    all_entities = {}
    for f in sorted(entities_dir.glob("*.json")):
        all_entities[f.stem] = _load_entities(f)

    if not all_entities:
        print("ERROR: No entity files found. Run 'ner' step first.")
        sys.exit(1)

    all_relations = extract_all_relations(
        md_dir=Path(args.output_dir),
        all_entities=all_entities,
        force=args.force,
    )
    for doc_name, relations in all_relations.items():
        print(f"  {doc_name}: {len(relations)} relationships")
    return all_relations


def step_resolve(args):
    """Step 5: Entity resolution / deduplication."""
    from src.extract.ner import _load_entities
    from src.extract.resolve import resolve_entities, save_entity_registry

    print("=" * 60)
    print("STEP 5: Entity Resolution")
    print("=" * 60)

    # Load raw entities
    entities_dir = Path("data/entities")
    all_entities = {}
    for f in sorted(entities_dir.glob("*.json")):
        doc_entities = _load_entities(f)
        # Convert to dicts for resolve_entities
        all_entities[f.stem] = [
            {
                "name": e.name,
                "entity_type": e.entity_type,
                "aliases": e.aliases,
                "description": e.description,
                "confidence": e.confidence,
            }
            for e in doc_entities
        ]

    if not all_entities:
        print("ERROR: No entity files found. Run 'ner' step first.")
        sys.exit(1)

    canonical, ambiguous = resolve_entities(all_entities)
    output_path = Path("data/entity_registry.json")
    save_entity_registry(canonical, output_path, ambiguous)

    print(f"  {len(canonical)} canonical entities")
    if ambiguous:
        print(f"  {len(ambiguous)} ambiguous pairs flagged for review")
    print(f"  Saved to {output_path}")
    return canonical


def step_load(args):
    """Step 6: Load everything into Neo4j."""
    from src.extract.chunker import chunk_file
    from src.extract.relations import load_relations
    from src.extract.resolve import build_alias_map, load_entity_registry
    from src.graph.load import load_all

    print("=" * 60)
    print("STEP 6: Neo4j Graph Loading")
    print("=" * 60)

    # Load canonical entities
    registry_path = Path("data/entity_registry.json")
    if not registry_path.exists():
        print("ERROR: No entity registry found. Run 'resolve' step first.")
        sys.exit(1)
    entities = load_entity_registry(registry_path)
    print(f"  Loaded {len(entities)} canonical entities")

    # Load relations
    relations_dir = Path("data/relations")
    all_relations = []
    if relations_dir.exists():
        for f in sorted(relations_dir.glob("*.json")):
            all_relations.extend(load_relations(f))
    print(f"  Loaded {len(all_relations)} relationships")

    # Generate chunks
    md_dir = Path(args.output_dir)
    all_chunks = []
    for md_path in sorted(md_dir.glob("*.md")):
        all_chunks.extend(chunk_file(md_path))
    print(f"  Generated {len(all_chunks)} chunks")

    # Build alias map
    alias_map = build_alias_map(entities)
    print(f"  Built alias map with {len(alias_map)} entries")

    # Load into Neo4j
    load_all(entities, all_relations, all_chunks, alias_map)


def step_embed(args):
    """Step 7: Generate embeddings and create vector indexes."""
    from src.graph.embed import embed_all
    from src.graph.load import get_driver

    print("=" * 60)
    print("STEP 7: Embeddings & Vector Indexes")
    print("=" * 60)

    driver = get_driver()
    try:
        embed_all(driver)
    finally:
        driver.close()


def run_all(args):
    """Run the full pipeline."""
    print("Running full pipeline...")
    print()

    step_extract(args)
    print()

    step_ner(args)
    print()

    step_relations(args)
    print()

    step_resolve(args)
    print()

    step_load(args)
    print()

    step_embed(args)
    print()

    print("=" * 60)
    print("Pipeline complete!")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Virginia Archaeology Knowledge Graph Pipeline"
    )
    parser.add_argument(
        "step",
        nargs="?",
        default="all",
        choices=["all", "extract", "chunk", "ner", "relations", "resolve", "load", "embed"],
        help="Which pipeline step to run (default: all)",
    )
    parser.add_argument("--pdf-dir", default="data/pdf")
    parser.add_argument("--output-dir", default="data/md")
    parser.add_argument(
        "--force", action="store_true", help="Re-run even if cached output exists"
    )
    parser.add_argument(
        "--llm-cleanup", action="store_true", help="Use Claude for OCR cleanup (costs money)"
    )
    args = parser.parse_args()

    step_map = {
        "all": run_all,
        "extract": step_extract,
        "chunk": step_chunk,
        "ner": step_ner,
        "relations": step_relations,
        "resolve": step_resolve,
        "load": step_load,
        "embed": step_embed,
    }

    step_map[args.step](args)
