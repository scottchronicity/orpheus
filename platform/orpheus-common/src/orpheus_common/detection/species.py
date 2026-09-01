"""Shared taxonomy constants for corvid species detection.

Two ways to identify a corvid:

  1. **By IOC scientific name (preferred).** ``is_corvidae(scientific)``
     does a first-word-match against ``CORVIDAE_GENERA`` — a hand-
     maintained list of all genera in the Corvidae family. This is the
     authoritative path now that BirdNET emits IOC scientific names via
     Layer 1 of the cross-classifier-identity work (see
     ``docs/designs/cross-classifier-identity.md`` §3).

  2. **By 6-char Latin slug (back-compat fallback).** ``CORVID_SPECIES``
     contains the 6-character lowercase scientific-name prefixes that
     BirdNET's parser produces. Use only when the scientific name isn't
     available (legacy code paths). Maintained as defense-in-depth.

The slug approach is intentionally fragile: BirdNET's 6-char-slug scheme
collides heavily (87% of species share a slug with at least one other).
``"corvus"`` covers ~32 crow/raven species so coarse "is this a corvid?"
checks survive the collision, but ``"picapi"`` (Pica pica, Eurasian
magpie) doesn't cover ``"picahu"`` (Pica hudsonia, Black-billed Magpie),
which is the magpie Michigan would actually see. Hence the dual-path
approach — slug for back-compat, scientific name for accuracy.

``CROW_UI_CODES`` is the union of codes the frontend should use when
filtering for "crow" entities (includes the generic ``crow`` code
emitted by the dedicated Crow Classifier agent).
"""

from __future__ import annotations

from typing import Optional

# Authoritative path: full IOC genus names from the Corvidae family.
# Source: IOC World Bird List + Cornell Lab Birds of the World.
# When BirdNET emits TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos"),
# the first word is the genus — match against this set.
CORVIDAE_GENERA: frozenset = frozenset(
    {
        # Crows, ravens, rooks
        "Corvus",
        # Jackdaws (split from Corvus in some treatments)
        "Coloeus",
        # Magpies (Old World)
        "Pica",
        # Azure-winged magpies
        "Cyanopica",
        # Blue magpies
        "Urocissa",
        # Green magpies
        "Cissa",
        # Mexican / Brazilian / Green jays
        "Cyanocorax",
        # Magpie-jays
        "Calocitta",
        # Scrub jays (Aphelocoma)
        "Aphelocoma",
        # Blue jay, Stellar's jay
        "Cyanocitta",
        # Pinyon jay
        "Gymnorhinus",
        # Gray / Canada jays
        "Perisoreus",
        # Eurasian jay
        "Garrulus",
        # Nutcrackers
        "Nucifraga",
        # Choughs
        "Pyrrhocorax",
        # American "true" jays
        "Cyanolyca",
        # Brown jay
        "Psilorhinus",
        # Crested jay
        "Platylophus",
        # Black magpies
        "Platysmurus",
        # Treepies (subfamily Crypsirininae)
        "Crypsirina",
        "Dendrocitta",
        "Temnurus",
        # Ground jays
        "Podoces",
        # Piapiac
        "Ptilostomus",
        # Stresemann's bushcrow
        "Zavattariornis",
    }
)


def is_corvidae(scientific_name: Optional[str]) -> bool:
    """Return True if ``scientific_name`` is a member of family Corvidae.

    Does a first-word-match against :data:`CORVIDAE_GENERA`. Robust to
    sub-species suffixes (``"Corvus brachyrhynchos hesperis"`` matches).
    Returns False for None, empty string, or anything outside the family.

    Args:
        scientific_name: Full or partial IOC scientific name (binomial,
            trinomial, or just the genus). May be None.
    """
    if not scientific_name:
        return False
    genus = scientific_name.strip().split(" ", 1)[0]
    return genus in CORVIDAE_GENERA


# Back-compat fallback: 6-character lowercase scientific-name prefixes
# that match BirdNET's parser output. Used when the scientific name
# isn't available — e.g. legacy detections, or schemas where only the
# species_code field is present.
#
# IMPORTANT: this list is incomplete by design — it can't cover every
# corvid genus because of slug collisions (Pica pica → picapi, but
# Pica hudsonia → picahu). Use ``is_corvidae(scientific_name)`` when
# you have the scientific name.
CORVID_SPECIES: set[str] = {
    # Crows & Ravens (Corvus sp.) — covers ~32 species via slug collision
    "corvus",
    # Jackdaws (Coloeus sp.)
    "coloeu",
    # Eurasian Jays (Garrulus sp.)
    "garrul",
    # Magpies — multiple slugs covering different Pica species
    "picapi",  # Pica pica (Eurasian magpie)
    "picahu",  # Pica hudsonia (Black-billed magpie) — Michigan-relevant
    "pinutt",  # Pica nuttalli (Yellow-billed magpie)
    # Azure-winged magpies (Cyanopica sp.)
    "cyanop",
    # Blue & Steller's Jays (Cyanocitta sp.) AND
    # Mexican/Green jays (Cyanocorax sp.) — both collide at "cyanoc"
    "cyanoc",
    # American jays (Cyanolyca sp.)
    "cyanol",
    # Scrub-Jays (Aphelocoma sp.)
    "aphelo",
    # Nutcrackers (Nucifraga sp.)
    "nucifr",
    # Gray Jays (Perisoreus sp.)
    "periso",
    # Pinyon Jay (Gymnorhinus sp.)
    "gymnor",
    # Choughs (Pyrrhocorax sp.)
    "pyrrho",
    # Blue Magpies (Urocissa sp.)
    "urocis",
    # Green Magpies (Cissa sp.) — Cissa has only 5 chars so BirdNET's
    # 6-char slug pulls in the first letter of the species epithet.
    # The most common Cissa label in BirdNET v2.4 is C. thalassina;
    # add the other slugs if you see them in production.
    "cissat",  # Cissa thalassina (Javan Green Magpie)
    "cissac",  # Cissa chinensis (Common Green Magpie)
    "cissah",  # Cissa hypoleuca (Indochinese Green Magpie)
    "cissaj",  # Cissa jefferyi (Bornean Green Magpie)
    # Treepies (Dendrocitta sp.)
    "dendro",
    # Magpie-jays (Calocitta sp.) — Calocitta is 9 chars so all species
    # collide to "caloci" via slug.
    "caloci",
    # Brown jay (Psilorhinus sp.)
    "psilor",
}


def is_corvid_species_code(species_code: Optional[str]) -> bool:
    """Slug-based corvid check (back-compat fallback).

    Returns True if ``species_code`` is in :data:`CORVID_SPECIES`. Use
    :func:`is_corvidae` instead when you have the scientific name —
    this slug approach misses corvids whose 6-char-slug isn't in the
    set (e.g. Pica hudsonia).
    """
    if not species_code:
        return False
    return species_code in CORVID_SPECIES


def is_corvid(
    *,
    scientific_name: Optional[str] = None,
    species_code: Optional[str] = None,
) -> bool:
    """Combined corvid check: prefer scientific name, fall back to slug.

    The recommended way to ask "is this detection a corvid?" — works
    for both Layer 1 (TaxonomyRef-bearing) and legacy detections.

    Args:
        scientific_name: IOC scientific name from
            ``Detection.taxonomy.id`` (when namespace=="ioc") or from
            ``Detection.metadata["species_scientific"]``.
        species_code: BirdNET's 6-char slug, as a back-compat fallback.

    Returns True if EITHER path identifies the detection as a corvid.
    """
    if is_corvidae(scientific_name):
        return True
    return is_corvid_species_code(species_code)


# Codes the UI should use when querying for crow/corvid entities.
# Includes the generic "crow" code emitted by the Crow Classifier agent.
CROW_UI_CODES: set[str] = {"corvus", "crow"}
