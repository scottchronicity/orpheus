"""Tests for shared corvid taxonomy constants."""

from orpheus_common.detection.species import CORVID_SPECIES, CROW_UI_CODES


class TestCorvidSpecies:
    """Tests for CORVID_SPECIES set."""

    def test_is_set(self) -> None:
        """CORVID_SPECIES should be a set."""
        assert isinstance(CORVID_SPECIES, set)

    def test_not_empty(self) -> None:
        """CORVID_SPECIES should not be empty."""
        assert len(CORVID_SPECIES) > 0

    def test_all_lowercase(self) -> None:
        """All codes should be lowercase."""
        for code in CORVID_SPECIES:
            assert code == code.lower(), f"Code {code!r} is not lowercase"

    def test_max_six_chars(self) -> None:
        """All codes should be at most 6 characters (parser output format)."""
        for code in CORVID_SPECIES:
            assert len(code) <= 6, f"Code {code!r} exceeds 6 characters"

    def test_contains_expected_genera(self) -> None:
        """Should contain the most common corvid genera prefixes."""
        expected = {"corvus", "picapi", "cyanoc", "garrul", "nucifr"}
        assert expected.issubset(CORVID_SPECIES)

    def test_no_ebird_codes(self) -> None:
        """Should not contain eBird alpha codes (old, unreachable values)."""
        ebird_codes = {"amecro", "comrav", "blujay", "eurmag", "blkbma", "stecro"}
        assert CORVID_SPECIES.isdisjoint(ebird_codes)


class TestCrowUICodes:
    """Tests for CROW_UI_CODES set."""

    def test_is_set(self) -> None:
        """CROW_UI_CODES should be a set."""
        assert isinstance(CROW_UI_CODES, set)

    def test_contains_corvus_and_crow(self) -> None:
        """CROW_UI_CODES should contain both 'corvus' and 'crow'."""
        assert "corvus" in CROW_UI_CODES
        assert "crow" in CROW_UI_CODES

    def test_size(self) -> None:
        """CROW_UI_CODES should have exactly 2 members."""
        assert len(CROW_UI_CODES) == 2
