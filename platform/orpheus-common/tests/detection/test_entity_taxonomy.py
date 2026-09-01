"""Tests for the entity-type taxonomy registry + derivation ([ARCH])."""

from pathlib import Path

import pytest

from orpheus_common.detection import TaxonomyRef
from orpheus_common.detection.entity_taxonomy import (
    EntityTaxonomy,
    derive_entity_type,
    load_taxonomy,
    reset_cache,
)


@pytest.fixture
def taxo() -> EntityTaxonomy:
    reset_cache()
    table = load_taxonomy()  # the bundled data/entity_taxonomy.yaml
    yield table
    reset_cache()


class TestRegistry:
    def test_internal_nodes_and_leaves_are_valid_types(self, taxo: EntityTaxonomy) -> None:
        for t in (
            "Animal",
            "Animal.Bird",  # internal node is a valid (coarse) type
            "Animal.Bird.Crow",
            "Animal.Bird.Owl",
            "Animal.Critter",
            "Human",
            "Human.Known",
            "Plant",
        ):
            assert taxo.is_known(t), t
        assert taxo.is_known("Animal.Bird.Dragon") is False

    def test_topic_for_is_injective_and_lowercased(self, taxo: EntityTaxonomy) -> None:
        assert taxo.topic_for("Animal.Bird.Crow") == "orpheus/entities/animal/bird/crow"
        assert taxo.topic_for("Animal.Bird") == "orpheus/entities/animal/bird"
        assert taxo.topic_for("Human.Known") == "orpheus/entities/human/known"


class TestDerivation:
    def test_ioc_corvid_resolves_to_crow(self, taxo: EntityTaxonomy) -> None:
        ref = TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos")
        assert taxo.entity_type_for(taxonomy=ref, detection_type="species.detected") == (
            "Animal.Bird.Crow"
        )

    def test_ioc_noncorvid_bird_coarsens_to_animal_bird(self, taxo: EntityTaxonomy) -> None:
        ref = TaxonomyRef(namespace="ioc", id="Turdus migratorius")  # American Robin
        assert taxo.entity_type_for(
            taxonomy=ref, species_code="amerob", detection_type="species.detected"
        ) == "Animal.Bird"

    def test_audioset_crow_mid_resolves_via_clade_bridges(self, taxo: EntityTaxonomy) -> None:
        ref = TaxonomyRef(namespace="audioset", id="/m/04s8yn")  # Crow
        assert taxo.entity_type_for(
            taxonomy=ref, detection_type="audio.classified"
        ) == "Animal.Bird.Crow"

    def test_audioset_unmapped_mid_is_none(self, taxo: EntityTaxonomy) -> None:
        ref = TaxonomyRef(namespace="audioset", id="/m/0jbk")  # Animal (generic)
        assert (
            taxo.entity_type_for(taxonomy=ref, detection_type="audio.classified") is None
        )

    def test_crow_agent_detection_type_default(self, taxo: EntityTaxonomy) -> None:
        assert taxo.entity_type_for(detection_type="crow.analyzed") == "Animal.Bird.Crow"

    def test_legacy_species_code_without_taxonomy(self, taxo: EntityTaxonomy) -> None:
        # A pre-feature row: species_code only, no taxonomy. Specific code wins
        # over the coarse species.detected default.
        assert taxo.entity_type_for(
            species_code="corvus", detection_type="species.detected"
        ) == "Animal.Bird.Crow"

    def test_unresolvable_is_none(self, taxo: EntityTaxonomy) -> None:
        assert taxo.entity_type_for(detection_type="audio.motion") is None
        assert taxo.entity_type_for() is None

    def test_taxonomy_as_dict_matches_ref(self, taxo: EntityTaxonomy) -> None:
        # Backfill reads evidence JSON → taxonomy is a dict, not a TaxonomyRef.
        as_dict = {"namespace": "ioc", "id": "Corvus brachyrhynchos"}
        as_ref = TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos")
        assert taxo.entity_type_for(taxonomy=as_dict) == taxo.entity_type_for(taxonomy=as_ref)
        assert taxo.entity_type_for(taxonomy=as_dict) == "Animal.Bird.Crow"

    def test_module_derive_uses_default_taxonomy(self) -> None:
        reset_cache()
        ref = TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos")
        assert derive_entity_type(taxonomy=ref) == "Animal.Bird.Crow"
        reset_cache()


class TestLoaderValidation:
    def _write(self, tmp_path: Path, text: str) -> Path:
        p = tmp_path / "tax.yaml"
        p.write_text(text)
        return p

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_taxonomy(tmp_path / "nope.yaml")

    def test_empty_types_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="no 'types'"):
            load_taxonomy(self._write(tmp_path, "version: 1\ntypes: {}\n"))

    def test_unknown_predicate_name_raises(self, tmp_path: Path) -> None:
        text = (
            "version: 1\n"
            "types:\n  Animal:\n    Bird:\n      Crow:\n"
            "bindings:\n  predicate_leaves:\n    is_made_up: Animal.Bird.Crow\n"
        )
        with pytest.raises(ValueError, match="unknown predicate"):
            load_taxonomy(self._write(tmp_path, text))

    def test_binding_to_undeclared_type_raises(self, tmp_path: Path) -> None:
        text = (
            "version: 1\n"
            "types:\n  Animal:\n    Bird:\n      Crow:\n"
            "bindings:\n  legacy_species_codes:\n    corvus: Animal.Bird.Owl\n"  # Owl not declared
        )
        with pytest.raises(ValueError, match="undeclared entity_type"):
            load_taxonomy(self._write(tmp_path, text))
