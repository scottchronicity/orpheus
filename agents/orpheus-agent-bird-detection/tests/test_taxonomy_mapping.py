"""Tests for the BirdNET → TaxonomyRef mapping."""

from __future__ import annotations

import pytest
from orpheus_common.detection import TaxonomyRef
from pydantic import ValidationError

from orpheus_agent_bird_detection.taxonomy_mapping import (
    label_to_taxonomy_ref,
    parts_to_taxonomy_ref,
)


class TestLabelToTaxonomyRef:
    """``label_to_taxonomy_ref(label)`` — full BirdNET label string."""

    def test_well_formed_label(self) -> None:
        ref = label_to_taxonomy_ref("Corvus brachyrhynchos_American Crow")
        assert ref is not None
        assert ref.namespace == "ioc"
        assert ref.id == "Corvus brachyrhynchos"
        assert ref.common_name == "American Crow"

    def test_label_with_subspecies(self) -> None:
        """BirdNET labels with subspecies still parse — the scientific
        binomial+subspecies stays intact as the id."""
        ref = label_to_taxonomy_ref(
            "Junco hyemalis hyemalis_Dark-eyed Junco (Slate-colored)"
        )
        assert ref is not None
        assert ref.id == "Junco hyemalis hyemalis"

    def test_empty_label_returns_none(self) -> None:
        assert label_to_taxonomy_ref("") is None

    def test_label_without_underscore_returns_none(self) -> None:
        """A malformed label (no `_` separator) is unparseable."""
        assert label_to_taxonomy_ref("CorvusBrachyrhynchos") is None

    def test_label_with_empty_scientific_returns_none(self) -> None:
        assert label_to_taxonomy_ref("_American Crow") is None

    def test_label_with_empty_common_still_emits_ref(self) -> None:
        """A label like 'Corvus brachyrhynchos_' has no common name —
        emit the ref with common_name=None."""
        ref = label_to_taxonomy_ref("Corvus brachyrhynchos_")
        assert ref is not None
        assert ref.id == "Corvus brachyrhynchos"
        assert ref.common_name is None

    def test_label_trims_whitespace(self) -> None:
        ref = label_to_taxonomy_ref("  Corvus brachyrhynchos  _  American Crow  ")
        assert ref is not None
        assert ref.id == "Corvus brachyrhynchos"
        assert ref.common_name == "American Crow"


class TestPartsToTaxonomyRef:
    """``parts_to_taxonomy_ref()`` — when the agent already has the parts."""

    def test_both_parts(self) -> None:
        ref = parts_to_taxonomy_ref("Corvus brachyrhynchos", "American Crow")
        assert ref is not None
        assert ref.namespace == "ioc"
        assert ref.id == "Corvus brachyrhynchos"
        assert ref.common_name == "American Crow"

    def test_scientific_only(self) -> None:
        ref = parts_to_taxonomy_ref("Corvus brachyrhynchos")
        assert ref is not None
        assert ref.common_name is None

    def test_no_scientific_returns_none(self) -> None:
        assert parts_to_taxonomy_ref(None) is None
        assert parts_to_taxonomy_ref("") is None
        assert parts_to_taxonomy_ref("   ") is None

    def test_empty_common_treated_as_none(self) -> None:
        ref = parts_to_taxonomy_ref("Corvus corax", "")
        assert ref is not None
        assert ref.common_name is None

    def test_namespace_is_validated(self) -> None:
        """Sanity: the emitted namespace must pass the registry check —
        proves we're not accidentally using an unknown namespace."""
        # Construction with a valid namespace must not raise (registry
        # validation is implicit in TaxonomyRef construction; see
        # platform/orpheus-common/tests/detection/test_namespaces.py).
        ref = parts_to_taxonomy_ref("Corvus corax", "Common Raven")
        assert ref is not None
        assert ref.namespace == "ioc"

    def test_construction_with_unknown_namespace_would_fail(self) -> None:
        """Demonstrates the registry guardrail that protects us from
        emitting an unknown namespace by accident."""
        with pytest.raises(ValidationError):
            TaxonomyRef(namespace="rogue_ns", id="x")
