"""SHACL-derived constants for the Virginia archaeology knowledge graph.

All types, relationships, display labels, and constraints are derived from
shacl/virginia-archaeology.shacl.ttl and kept here as pure data — no logic,
no imports needed. Other modules import these constants rather than
hard-coding schema knowledge.
"""

# ---------------------------------------------------------------------------
# Entity types — Neo4j label → human-readable name
# ---------------------------------------------------------------------------

ENTITY_TYPES: dict[str, str] = {
    "E27_Site": "Archaeological Site",
    "E74_Group": "Cultural Group",
    "E21_Person": "Person",
    "E22_Man-Made_Object": "Artifact",
    "E5_Event": "Event",
    "E53_Place": "Place",
    "E52_Time-Span": "Time Period",
    "E31_Document": "Document",
    "S19_Encounter_Event": "Discovery Event",
}

# ---------------------------------------------------------------------------
# Entity categories — UI sidebar groupings
# Maps display name → list of Neo4j labels in that category
# ---------------------------------------------------------------------------

ENTITY_CATEGORIES: dict[str, list[str]] = {
    "Peoples & Cultures": ["E74_Group"],
    "Persons": ["E21_Person"],
    "Sites": ["E27_Site"],
    "Places": ["E53_Place"],
    "Events": ["E5_Event", "S19_Encounter_Event"],
    "Time Periods": ["E52_Time-Span"],
    "Artifacts": ["E22_Man-Made_Object"],
}

# ---------------------------------------------------------------------------
# Relationship types — valid relationship type strings from the SHACL schema
# ---------------------------------------------------------------------------

RELATIONSHIP_TYPES: list[str] = [
    "P53_HAS_FORMER_OR_CURRENT_LOCATION",
    "HAS_CULTURAL_AFFILIATION",
    "P107I_IS_CURRENT_OR_FORMER_MEMBER_OF",
    "P4_HAS_TIME-SPAN",
    "P8_TOOK_PLACE_ON_OR_WITHIN",
    "P11_HAD_PARTICIPANT",
    "O19_HAS_FOUND_OBJECT",
    "P14_CARRIED_OUT_BY",
    "P70I_IS_DOCUMENTED_IN",
    "P89_FALLS_WITHIN",
    "P45_CONSISTS_OF",
    "P101_HAD_AS_GENERAL_USE",
    "MENTIONS",
    "FROM_DOCUMENT",
]

# ---------------------------------------------------------------------------
# Relationship display labels — CIDOC-CRM type → human-readable label for UI
# Used when rendering evidence triples, e.g. "Cactus Hill — located in — …"
# ---------------------------------------------------------------------------

RELATIONSHIP_DISPLAY_LABELS: dict[str, str] = {
    "P53_HAS_FORMER_OR_CURRENT_LOCATION": "located in",
    "HAS_CULTURAL_AFFILIATION": "affiliated with",
    "P107I_IS_CURRENT_OR_FORMER_MEMBER_OF": "member of",
    "P4_HAS_TIME-SPAN": "dated to",
    "P8_TOOK_PLACE_ON_OR_WITHIN": "took place in",
    "P11_HAD_PARTICIPANT": "involved",
    "O19_HAS_FOUND_OBJECT": "found",
    "P14_CARRIED_OUT_BY": "carried out by",
    "P70I_IS_DOCUMENTED_IN": "documented in",
    "P89_FALLS_WITHIN": "within",
    "P45_CONSISTS_OF": "made of",
    "P101_HAD_AS_GENERAL_USE": "used as",
    "MENTIONS": "mentions",
    "FROM_DOCUMENT": "from document",
}

# ---------------------------------------------------------------------------
# Relationship constraints — derived from SHACL sh:property declarations
# Maps each relationship type to the valid source and target node labels.
# Used to validate extraction output before graph loading.
# ---------------------------------------------------------------------------

RELATIONSHIP_CONSTRAINTS: dict[str, dict[str, list[str]]] = {
    # Site/Group/Artifact → Place or Site
    # Site.P53 → E53_Place, Group.P53 → E53_Place, Artifact.P53 → E27_Site
    "P53_HAS_FORMER_OR_CURRENT_LOCATION": {
        "source": ["E27_Site", "E74_Group", "E22_Man-Made_Object"],
        "target": ["E53_Place", "E27_Site"],
    },
    # Site → Group
    "HAS_CULTURAL_AFFILIATION": {
        "source": ["E27_Site"],
        "target": ["E74_Group"],
    },
    # Person → Group, Group → Group (parent)
    "P107I_IS_CURRENT_OR_FORMER_MEMBER_OF": {
        "source": ["E21_Person", "E74_Group"],
        "target": ["E74_Group"],
    },
    # Site/Group/Artifact/Event/DiscoveryEvent/Document → TimePeriod
    "P4_HAS_TIME-SPAN": {
        "source": [
            "E27_Site",
            "E74_Group",
            "E22_Man-Made_Object",
            "E5_Event",
            "S19_Encounter_Event",
            "E31_Document",
        ],
        "target": ["E52_Time-Span"],
    },
    # Event/DiscoveryEvent → Place or Site
    # Event.P8 target is untyped (Place or Site), DiscoveryEvent.P8 → E27_Site
    "P8_TOOK_PLACE_ON_OR_WITHIN": {
        "source": ["E5_Event", "S19_Encounter_Event"],
        "target": ["E53_Place", "E27_Site"],
    },
    # Event → Person or Group (SHACL target is untyped IRI)
    "P11_HAD_PARTICIPANT": {
        "source": ["E5_Event"],
        "target": ["E21_Person", "E74_Group"],
    },
    # DiscoveryEvent → Artifact
    "O19_HAS_FOUND_OBJECT": {
        "source": ["S19_Encounter_Event"],
        "target": ["E22_Man-Made_Object"],
    },
    # DiscoveryEvent/Document → Person
    "P14_CARRIED_OUT_BY": {
        "source": ["S19_Encounter_Event", "E31_Document"],
        "target": ["E21_Person"],
    },
    # Any domain node → Document
    "P70I_IS_DOCUMENTED_IN": {
        "source": [
            "E27_Site",
            "E74_Group",
            "E21_Person",
            "E22_Man-Made_Object",
            "E5_Event",
            "S19_Encounter_Event",
        ],
        "target": ["E31_Document"],
    },
    # Place → Place (containment hierarchy)
    "P89_FALLS_WITHIN": {
        "source": ["E53_Place"],
        "target": ["E53_Place"],
    },
    # Artifact material — stored as property in SHACL, but modeled as
    # relationship type in extraction for flexibility
    "P45_CONSISTS_OF": {
        "source": ["E22_Man-Made_Object"],
        "target": [],  # string property, no target node type
    },
    # Artifact function — same as above
    "P101_HAD_AS_GENERAL_USE": {
        "source": ["E22_Man-Made_Object"],
        "target": [],  # string property, no target node type
    },
    # RAG infrastructure (outside SHACL)
    "MENTIONS": {
        "source": ["Chunk"],
        "target": list(ENTITY_TYPES.keys()),
    },
    "FROM_DOCUMENT": {
        "source": ["Chunk"],
        "target": ["E31_Document"],
    },
}
