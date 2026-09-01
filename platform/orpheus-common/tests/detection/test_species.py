"""Tests for shared corvid taxonomy constants and helpers."""

import pytest

from orpheus_common.detection.species import (
    CORVID_SPECIES,
    CORVIDAE_GENERA,
    CROW_UI_CODES,
    is_corvid,
    is_corvid_species_code,
    is_corvidae,
)


class TestCorvidSpecies:
    """Tests for the slug-based CORVID_SPECIES set (back-compat path)."""

    def test_is_set(self) -> None:
        assert isinstance(CORVID_SPECIES, set)

    def test_not_empty(self) -> None:
        assert len(CORVID_SPECIES) > 0

    def test_all_lowercase(self) -> None:
        for code in CORVID_SPECIES:
            assert code == code.lower(), f"Code {code!r} is not lowercase"

    def test_max_six_chars(self) -> None:
        for code in CORVID_SPECIES:
            assert len(code) <= 6, f"Code {code!r} exceeds 6 characters"

    def test_contains_expected_genera(self) -> None:
        """The most common Michigan-relevant corvid slugs are present."""
        expected = {
            "corvus",  # American Crow, Common Raven, Fish Crow, …
            "cyanoc",  # Blue Jay (Cyanocitta) + Mexican Jay (Cyanocorax)
            "periso",  # Canada Jay (Perisoreus canadensis)
            "picahu",  # Black-billed Magpie (Pica hudsonia)
            "nucifr",  # Clark's Nutcracker
            "garrul",  # Eurasian Jay
        }
        assert expected.issubset(CORVID_SPECIES)

    def test_michigan_corvids_covered_by_slug(self) -> None:
        """Every Michigan-resident corvid's slug must be in the set —
        guards against the historical 'picahu' miss."""
        michigan_corvids = {
            "corvus",  # American Crow / Common Raven / Fish Crow / etc.
            "cyanoc",  # Blue Jay
            "periso",  # Canada Jay
            "picahu",  # Black-billed Magpie (occasional)
        }
        for slug in michigan_corvids:
            assert slug in CORVID_SPECIES, (
                f"Michigan-resident corvid slug {slug!r} missing from CORVID_SPECIES"
            )

    def test_no_ebird_codes(self) -> None:
        """Should not contain eBird alpha codes (old, unreachable values)."""
        ebird_codes = {"amecro", "comrav", "blujay", "eurmag", "blkbma", "stecro"}
        assert CORVID_SPECIES.isdisjoint(ebird_codes)


class TestCorvidaeGenera:
    """Tests for the authoritative scientific-name-based set."""

    def test_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            CORVIDAE_GENERA.add("Rogue")  # type: ignore[attr-defined]

    def test_contains_michigan_residents(self) -> None:
        for genus in ("Corvus", "Cyanocitta", "Perisoreus", "Pica"):
            assert genus in CORVIDAE_GENERA, f"{genus} should be in CORVIDAE_GENERA"

    def test_capitalised_not_lowercased(self) -> None:
        """Scientific genus names are capitalised in IOC convention."""
        for genus in CORVIDAE_GENERA:
            assert genus[0].isupper(), f"{genus!r} should start with uppercase"


class TestIsCorvidae:
    """Scientific-name-based corvid check — the authoritative path."""

    def test_american_crow(self) -> None:
        assert is_corvidae("Corvus brachyrhynchos") is True

    def test_common_raven(self) -> None:
        assert is_corvidae("Corvus corax") is True

    def test_fish_crow(self) -> None:
        assert is_corvidae("Corvus ossifragus") is True

    def test_northwestern_crow(self) -> None:
        assert is_corvidae("Corvus caurinus") is True

    def test_blue_jay(self) -> None:
        assert is_corvidae("Cyanocitta cristata") is True

    def test_canada_jay(self) -> None:
        assert is_corvidae("Perisoreus canadensis") is True

    def test_black_billed_magpie(self) -> None:
        """The Pica hudsonia case that picapi-only logic misses."""
        assert is_corvidae("Pica hudsonia") is True

    def test_pinyon_jay(self) -> None:
        assert is_corvidae("Gymnorhinus cyanocephalus") is True

    def test_clarks_nutcracker(self) -> None:
        assert is_corvidae("Nucifraga columbiana") is True

    def test_subspecies_form_still_matches(self) -> None:
        """Trinomial form (genus species subspecies) still matches."""
        assert is_corvidae("Corvus brachyrhynchos hesperis") is True

    def test_genus_alone(self) -> None:
        """The genus alone (no species) still matches — useful for
        family-level claims."""
        assert is_corvidae("Corvus") is True

    def test_not_a_corvid(self) -> None:
        assert is_corvidae("Turdus migratorius") is False  # American Robin
        assert is_corvidae("Cardinalis cardinalis") is False  # Northern Cardinal
        assert is_corvidae("Antrostomus vociferus") is False  # Whip-poor-will

    def test_handles_none(self) -> None:
        assert is_corvidae(None) is False

    def test_handles_empty(self) -> None:
        assert is_corvidae("") is False
        assert is_corvidae("   ") is False

    def test_leading_whitespace_stripped(self) -> None:
        assert is_corvidae("  Corvus brachyrhynchos") is True


class TestIsCorvidSpeciesCode:
    """Slug-based check (back-compat)."""

    def test_corvus_slug(self) -> None:
        assert is_corvid_species_code("corvus") is True

    def test_picahu_slug(self) -> None:
        """Pica hudsonia (Black-billed Magpie) — historically missing."""
        assert is_corvid_species_code("picahu") is True

    def test_non_corvid(self) -> None:
        assert is_corvid_species_code("turdus") is False  # robins/thrushes
        assert is_corvid_species_code("cardin") is False  # cardinals

    def test_handles_none(self) -> None:
        assert is_corvid_species_code(None) is False

    def test_handles_empty(self) -> None:
        assert is_corvid_species_code("") is False


class TestIsCorvid:
    """Combined check — the recommended top-level entry point."""

    def test_scientific_name_wins(self) -> None:
        """Scientific name path is preferred — works even with no slug."""
        assert is_corvid(scientific_name="Corvus brachyrhynchos") is True
        assert is_corvid(scientific_name="Cyanocitta cristata") is True

    def test_slug_fallback(self) -> None:
        """Falls back to slug when scientific name is missing."""
        assert is_corvid(species_code="corvus") is True
        assert is_corvid(species_code="picahu") is True

    def test_both_provided(self) -> None:
        """Both paths agree."""
        assert is_corvid(
            scientific_name="Corvus brachyrhynchos", species_code="corvus"
        ) is True

    def test_neither_corvid(self) -> None:
        assert is_corvid(scientific_name="Turdus migratorius") is False
        assert is_corvid(species_code="turdus") is False

    def test_neither_provided(self) -> None:
        assert is_corvid() is False
        assert is_corvid(scientific_name=None, species_code=None) is False

    def test_scientific_corvid_but_slug_isnt(self) -> None:
        """Scientific name says corvid, slug isn't in the (incomplete)
        list — scientific name wins. This is the whole point of having
        the authoritative path."""
        # Imagine BirdNET emits a new corvid genus that we don't have in
        # the slug set yet. The scientific-name check still catches it.
        assert is_corvid(
            scientific_name="Zavattariornis stresemanni",  # Stresemann's bushcrow
            species_code="zavatt",  # not in CORVID_SPECIES
        ) is True


class TestCrowUICodes:
    """Tests for CROW_UI_CODES set."""

    def test_is_set(self) -> None:
        assert isinstance(CROW_UI_CODES, set)

    def test_contains_corvus_and_crow(self) -> None:
        assert "corvus" in CROW_UI_CODES
        assert "crow" in CROW_UI_CODES

    def test_size(self) -> None:
        assert len(CROW_UI_CODES) == 2
