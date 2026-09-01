"""Entity-type state-space taxonomy — the registry, loader, and derivation.

[ARCH] Generalize the EntityEvent State Space Taxonomy (Epic 1). The canonical
``entity_type`` is a dotted string ("Animal.Bird.Crow") validated against a tree
loaded from ``data/entity_taxonomy.yaml`` — string-with-registry, not an Enum,
so the taxonomy extends by editing data, not code (and so it survives Python
3.9, which has no ``match``). Mirrors the ``KNOWN_NAMESPACES`` frozenset-registry
precedent in ``namespaces.py``.

``entity_type`` is ADDITIVE and DERIVED: a pure function of the EXISTING
cross-classifier identity seams — ``species.is_corvidae`` and
``taxonomy_bridge._CLADE_BRIDGES`` (the single source of the AudioSet mid list).
It is never authoritative over the per-evidence ``TaxonomyRef``; it's a coarse
projection for routing + the cognitive state space.

Python 3.9: ``from __future__ import annotations`` + ``Optional`` (no ``X | None``
at runtime), dict-lookup dispatch (no ``match``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from .models import TaxonomyRef
from .species import is_corvidae
from .taxonomy_bridge import _CLADE_BRIDGES

# Fixed predicate dispatch: YAML names a predicate, we resolve it HERE (no eval,
# no import-by-string). A YAML predicate not in this table fails fast at load.
_PREDICATE_DISPATCH: Dict[str, Callable[[str], bool]] = {
    "is_corvidae": is_corvidae,
}

_ENTITY_TOPIC_ROOT = "orpheus/entities"

_cache: Optional[EntityTaxonomy] = None


class EntityTaxonomy:
    """Loaded, validated entity_type registry + derivation. Read-only."""

    def __init__(
        self,
        valid_types: frozenset,
        predicate_leaves: Dict[str, str],
        legacy_species_codes: Dict[str, str],
        detection_type_defaults: Dict[str, Optional[str]],
    ) -> None:
        self._valid_types = valid_types
        self._predicate_leaves = predicate_leaves
        self._legacy_species_codes = legacy_species_codes
        self._detection_type_defaults = detection_type_defaults
        # function -> leaf, so the AudioSet path can map a mid's predicate
        # (looked up in _CLADE_BRIDGES) to a leaf without re-listing mids.
        self._func_leaves: Dict[Callable[[str], bool], str] = {
            _PREDICATE_DISPATCH[name]: leaf for name, leaf in predicate_leaves.items()
        }

    def is_known(self, entity_type: str) -> bool:
        return entity_type in self._valid_types

    def all_types(self) -> List[str]:
        return sorted(self._valid_types)

    def topic_for(self, entity_type: str) -> str:
        """``"Animal.Bird.Crow"`` -> ``"orpheus/entities/animal/bird/crow"``.

        Injective over declared types (there is no ``_self`` sentinel; coarse
        birds resolve to the real node ``Animal.Bird``)."""
        return _ENTITY_TOPIC_ROOT + "/" + entity_type.lower().replace(".", "/")

    def entity_type_for(
        self,
        *,
        taxonomy: Any = None,
        species_code: str = "",
        common_name: str = "",
        detection_type: str = "",
    ) -> Optional[str]:
        """Derive a single observation's entity_type, reusing the existing
        identity seams. Returns None when nothing resolves (the caller leaves
        entity_type NULL). ``taxonomy`` accepts a ``TaxonomyRef`` (live path) OR
        a serialised dict (backfill reads evidence JSON) OR None.
        """
        namespace, identifier = _normalize_taxonomy(taxonomy)

        # 1. Predicate path (most specific, authoritative).
        if namespace == "ioc" and identifier:
            for name, leaf in self._predicate_leaves.items():
                if _PREDICATE_DISPATCH[name](identifier):
                    return leaf
        elif namespace == "audioset" and identifier:
            predicate = _CLADE_BRIDGES.get("audioset", {}).get(identifier)
            if predicate is not None:
                leaf = self._func_leaves.get(predicate)
                if leaf is not None:
                    return leaf

        # 2. Specific legacy species_code (before the coarse default, so a known
        #    crow code never coarsens to Animal.Bird).
        leaf = self._legacy_species_codes.get((species_code or "").lower())
        if leaf is not None:
            return leaf

        # 3. Coarse default by detection_type (last resort; null => no claim).
        return self._detection_type_defaults.get(detection_type) or None


def _normalize_taxonomy(taxonomy: Any) -> tuple:
    """``(namespace, id)`` from a TaxonomyRef, a serialised dict, or None."""
    if taxonomy is None:
        return (None, None)
    if isinstance(taxonomy, TaxonomyRef):
        return (taxonomy.namespace, taxonomy.id)
    if isinstance(taxonomy, dict):
        return (taxonomy.get("namespace"), taxonomy.get("id"))
    return (None, None)


def _flatten_types(tree: Any, prefix: str, out: set) -> None:
    """Collect every dotted path in the tree (internal nodes AND leaves)."""
    if not isinstance(tree, dict):
        return
    for name, child in tree.items():
        path = f"{prefix}.{name}" if prefix else str(name)
        out.add(path)
        _flatten_types(child, path, out)


def _data_path() -> Path:
    return Path(__file__).parent / "data" / "entity_taxonomy.yaml"


def load_taxonomy(path: Optional[Path] = None) -> EntityTaxonomy:
    """Load + validate the taxonomy. Memoised when using the default path."""
    global _cache  # noqa: PLW0603 - intentional module-level cache (audioset_ontology precedent)
    if path is None and _cache is not None:
        return _cache

    yaml_path = path if path is not None else _data_path()
    if not yaml_path.exists():
        raise FileNotFoundError(f"Entity taxonomy YAML missing at {yaml_path}.")

    with yaml_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    valid_types: set = set()
    _flatten_types(data.get("types") or {}, "", valid_types)
    if not valid_types:
        raise ValueError(f"Entity taxonomy at {yaml_path} has no 'types' tree.")

    bindings = data.get("bindings") or {}
    predicate_leaves: Dict[str, str] = dict(bindings.get("predicate_leaves") or {})
    legacy_species_codes: Dict[str, str] = {
        str(code).lower(): str(leaf)
        for code, leaf in (bindings.get("legacy_species_codes") or {}).items()
    }
    detection_type_defaults: Dict[str, Optional[str]] = dict(
        bindings.get("detection_type_defaults") or {}
    )

    # Fail fast (audioset_ontology validation precedent): every predicate name
    # must be in the dispatch table, and every binding target must be a declared
    # type, so a typo can't silently produce an unroutable entity_type.
    for name, leaf in predicate_leaves.items():
        if name not in _PREDICATE_DISPATCH:
            raise ValueError(
                f"predicate_leaves references unknown predicate '{name}' "
                f"(known: {sorted(_PREDICATE_DISPATCH)})"
            )
        _require_known(leaf, valid_types, f"predicate_leaves.{name}")
    for code, leaf in legacy_species_codes.items():
        _require_known(leaf, valid_types, f"legacy_species_codes.{code}")
    for dtype, leaf in detection_type_defaults.items():
        if leaf is not None:
            _require_known(leaf, valid_types, f"detection_type_defaults.{dtype}")

    taxonomy = EntityTaxonomy(
        valid_types=frozenset(valid_types),
        predicate_leaves=predicate_leaves,
        legacy_species_codes=legacy_species_codes,
        detection_type_defaults=detection_type_defaults,
    )
    if path is None:
        _cache = taxonomy
    return taxonomy


def _require_known(leaf: str, valid_types: set, where: str) -> None:
    if leaf not in valid_types:
        raise ValueError(f"{where} maps to undeclared entity_type '{leaf}'")


def reset_cache() -> None:
    """Clear the memoised taxonomy (test isolation)."""
    global _cache  # noqa: PLW0603
    _cache = None


def derive_entity_type(
    *,
    taxonomy: Any = None,
    species_code: str = "",
    common_name: str = "",
    detection_type: str = "",
    taxo: Optional[EntityTaxonomy] = None,
) -> Optional[str]:
    """Convenience: derive against the default (or a provided) taxonomy."""
    table = taxo if taxo is not None else load_taxonomy()
    return table.entity_type_for(
        taxonomy=taxonomy,
        species_code=species_code,
        common_name=common_name,
        detection_type=detection_type,
    )
