"""Tests for the deterministic cross-classifier / cross-modal bridge.

The bridge must be pure and deterministic: same inputs → same answer on a
laptop and on the Jetson, with no DB and no learned state.
"""

from __future__ import annotations

from orpheus_common.detection import TaxonomyRef, same_source
from orpheus_common.detection.taxonomy_bridge import _synonym_match

# Canonical refs used across the cases.
AMERICAN_CROW = TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos")
COMMON_RAVEN = TaxonomyRef(namespace="ioc", id="Corvus corax")
BLUE_JAY = TaxonomyRef(namespace="ioc", id="Cyanocitta cristata")
AMERICAN_ROBIN = TaxonomyRef(namespace="ioc", id="Turdus migratorius")

AUDIOSET_CROW = TaxonomyRef(namespace="audioset", id="/m/04s8yn")  # "Crow"
AUDIOSET_CAW = TaxonomyRef(namespace="audioset", id="/m/07r5c2p")  # "Caw"
AUDIOSET_BIRD = TaxonomyRef(namespace="audioset", id="/m/015p6")  # generic "Bird"
AUDIOSET_OWL = TaxonomyRef(namespace="audioset", id="/m/09d5_")  # "Owl" (no bridge yet)
AUDIOSET_ENGINE = TaxonomyRef(namespace="audioset", id="/m/02mk9")  # non-animal


class TestMembershipBridge:
    """A coarse clade label and a specific species name the same source."""

    def test_audioset_crow_bridges_to_ioc_american_crow(self) -> None:
        assert same_source(AUDIOSET_CROW, AMERICAN_CROW) is True

    def test_is_symmetric(self) -> None:
        assert same_source(AMERICAN_CROW, AUDIOSET_CROW) is True

    def test_caw_also_bridges_to_corvids(self) -> None:
        assert same_source(AUDIOSET_CAW, COMMON_RAVEN) is True

    def test_audioset_crow_bridges_to_any_corvid(self) -> None:
        # The coarse "Crow" clade covers the whole family Corvidae, so a
        # Blue Jay (Cyanocitta) is in-clade too.
        assert same_source(AUDIOSET_CROW, BLUE_JAY) is True


class TestNoFalseMerges:
    """The bridge must not glue unrelated sources together."""

    def test_audioset_crow_does_not_bridge_to_robin(self) -> None:
        # A robin is not a corvid — co-occurrence is not identity.
        assert same_source(AUDIOSET_CROW, AMERICAN_ROBIN) is False

    def test_generic_bird_label_never_bridges(self) -> None:
        # Generic "Bird" is deliberately NOT a bridge: it fires on almost
        # every bird clip and would promiscuously glue distinct co-occurring
        # species into one Entity (the "soup" ADR 0013 killed).
        assert same_source(AUDIOSET_BIRD, AMERICAN_CROW) is False
        assert same_source(AUDIOSET_BIRD, AMERICAN_ROBIN) is False

    def test_unmapped_clade_does_not_bridge_yet(self) -> None:
        # "Owl" has no IOC predicate wired yet → no bridge (graceful).
        assert same_source(AUDIOSET_OWL, AMERICAN_CROW) is False

    def test_non_animal_audioset_does_not_bridge(self) -> None:
        assert same_source(AUDIOSET_ENGINE, AMERICAN_CROW) is False

    def test_two_ioc_species_do_not_bridge(self) -> None:
        # Same-namespace specifics are handled by exact match upstream, never
        # merged by the bridge — two different birds stay two sources.
        assert same_source(AMERICAN_CROW, AMERICAN_ROBIN) is False
        assert same_source(AMERICAN_CROW, COMMON_RAVEN) is False

    def test_two_audioset_labels_do_not_bridge(self) -> None:
        assert same_source(AUDIOSET_CROW, AUDIOSET_CAW) is False


class TestSynonymBridge:
    """Same-granularity cross-modal synonyms — the non-animal path. A truck
    heard by audio and seen by video is one source even though neither label
    is "more specific" than the other."""

    def test_registered_synonym_pair_matches_either_order(self) -> None:
        truck_audio = TaxonomyRef(namespace="audioset", id="/m/07r04")
        truck_video = TaxonomyRef(namespace="orpheus.custom", id="truck")
        registry = frozenset(
            {frozenset({("audioset", "/m/07r04"), ("orpheus.custom", "truck")})}
        )
        assert _synonym_match(truck_audio, truck_video, synonyms=registry) is True
        assert _synonym_match(truck_video, truck_audio, synonyms=registry) is True

    def test_unregistered_pair_does_not_match(self) -> None:
        truck_audio = TaxonomyRef(namespace="audioset", id="/m/07r04")
        truck_video = TaxonomyRef(namespace="orpheus.custom", id="truck")
        # No vehicle synonyms registered in the production table yet.
        assert same_source(truck_audio, truck_video) is False
