"""Tests for the permissive bird-like AudioSet coverage set."""

from __future__ import annotations

from orpheus_common.detection import (
    BIRD_LIKE_AUDIOSET_MIDS,
    is_bird_like_audioset_mid,
)
from orpheus_common.detection.taxonomy_bridge import _CLADE_BRIDGES


def test_known_bird_mids_are_present() -> None:
    assert "/m/04s8yn" in BIRD_LIKE_AUDIOSET_MIDS  # Crow
    assert "/m/015p6" in BIRD_LIKE_AUDIOSET_MIDS  # Bird
    assert "/m/09d5_" in BIRD_LIKE_AUDIOSET_MIDS  # Owl


def test_clade_bridge_mids_are_a_subset_of_the_coverage_set() -> None:
    # The precise identity bridge (Crow/Caw → corvids) must only use mids
    # that the permissive coverage set also recognises as bird-like.
    bridge_mids = set(_CLADE_BRIDGES.get("audioset", {}))
    assert bridge_mids <= set(BIRD_LIKE_AUDIOSET_MIDS)


def test_membership_accepts_taxonomy_id_form() -> None:
    assert is_bird_like_audioset_mid(None, "/m/04s8yn") is True
    assert is_bird_like_audioset_mid(None, "/m/02mk9") is False  # engine


def test_membership_accepts_species_code_form() -> None:
    assert is_bird_like_audioset_mid("audioset_/m/04s8yn", None) is True
    assert is_bird_like_audioset_mid("audioset_/m/02mk9", None) is False


def test_non_audioset_inputs_are_not_bird_like() -> None:
    assert is_bird_like_audioset_mid("corvus", None) is False
    assert is_bird_like_audioset_mid(None, None) is False
