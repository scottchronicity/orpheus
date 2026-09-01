"""Well-known taxonomy namespace registry.

Every ``TaxonomyRef`` in Orpheus uses a namespace from this registry. The
registry is intentionally small and frozen — adding a namespace is a
deliberate code+doc change, not an ad-hoc string.

See ``docs/designs/cross-classifier-identity.md`` §3.2 for the rationale
and the per-namespace conventions.
"""

from __future__ import annotations

#: Frozen set of namespace identifiers that may appear in ``TaxonomyRef.namespace``.
#:
#: Adding a namespace:
#:   1. Add the string to this set.
#:   2. Document the namespace's authority + id format in the design doc.
#:   3. Add a per-classifier mapping module that emits TaxonomyRefs in
#:      the new namespace, OR add equivalence-table rows mapping the new
#:      namespace to an existing one.
KNOWN_NAMESPACES: frozenset = frozenset(
    {
        "ebird",          # eBird alpha codes (Cornell Lab) — canonical bird key
        "ioc",            # IOC World Bird List Latin binomial — alternate bird key
        "audioset",       # Google AudioSet ontology machine_ids
        "inaturalist",    # iNaturalist taxon IDs (reserved for future iNatSounds)
        "itis",           # ITIS taxonomic serial numbers (reserved)
        "orpheus.custom", # Per-deployment custom labels (escape hatch)
    }
)


def validate_namespace(namespace: str) -> str:
    """Return ``namespace`` if it's in :data:`KNOWN_NAMESPACES`, else raise.

    Used by ``TaxonomyRef`` to reject typos and accidental new namespaces.
    Adding a namespace is a registry update + doc PR, not a free-form
    string at the call site.

    Raises:
        ValueError: If ``namespace`` is not in the registry.
    """
    if namespace not in KNOWN_NAMESPACES:
        raise ValueError(
            f"Unknown TaxonomyRef namespace {namespace!r}. "
            f"Known namespaces: {sorted(KNOWN_NAMESPACES)}. "
            "To add a new namespace, update KNOWN_NAMESPACES in "
            "orpheus_common.detection.namespaces and the cross-classifier-"
            "identity design doc."
        )
    return namespace
