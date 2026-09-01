"""Map BirdNET's native label format to a canonical TaxonomyRef.

BirdNET labels in ``labels.json`` are ``"Scientific Name_Common Name"``
pairs. The scientific name is the IOC World Bird List binomial — globally
unique, and what we use as the canonical id for cross-classifier
identity (see ``docs/designs/cross-classifier-identity.md`` §3, Layer 1).

The mapping is trivial here because BirdNET emits the IOC form directly.
The module exists as a named, unit-testable contract so that:
  1. The intent is explicit at every emission site.
  2. Future BirdNET label-format changes are caught by mapping tests
     rather than silently producing weird TaxonomyRefs.
  3. The pattern matches the other classifier agents (crow-tools,
     audio-events) — every classifier has a taxonomy_mapping module.
"""

from __future__ import annotations

from typing import Optional

from orpheus_common.detection import TaxonomyRef


def label_to_taxonomy_ref(label: str) -> Optional[TaxonomyRef]:
    """Map a BirdNET label to a TaxonomyRef in the ``ioc`` namespace.

    Args:
        label: A BirdNET label, expected in ``"Scientific Name_Common Name"``
            form (e.g. ``"Corvus brachyrhynchos_American Crow"``).

    Returns:
        ``TaxonomyRef(namespace="ioc", id=<scientific>, common_name=<common>)``
        when the label parses cleanly. ``None`` if the label is empty or
        doesn't contain a ``_`` separator — caller treats ``None`` as
        "no canonical taxonomy available; downstream consumers fall back
        to the legacy free-form species_code/species_common fields."
    """
    if not label or "_" not in label:
        return None
    scientific, common = label.split("_", 1)
    scientific = scientific.strip()
    common = common.strip()
    if not scientific:
        return None
    return TaxonomyRef(
        namespace="ioc",
        id=scientific,
        common_name=common or None,
    )


def parts_to_taxonomy_ref(
    scientific: Optional[str], common: Optional[str] = None
) -> Optional[TaxonomyRef]:
    """Construct a TaxonomyRef from already-parsed parts.

    Used by the agent's emission code, which has ``species_scientific``
    and ``species_common`` already separated in the detection dict from
    BirdNET's predict() output.

    Returns ``None`` if no scientific name is available.
    """
    if not scientific:
        return None
    scientific = scientific.strip()
    if not scientific:
        return None
    return TaxonomyRef(
        namespace="ioc",
        id=scientific,
        common_name=(common or "").strip() or None,
    )
