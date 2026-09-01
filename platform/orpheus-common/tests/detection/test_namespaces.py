"""Tests for the well-known taxonomy namespace registry."""

from __future__ import annotations

import pytest

from orpheus_common.detection import KNOWN_NAMESPACES, TaxonomyRef, validate_namespace


class TestKnownNamespaces:
    """Sanity checks on the registry itself."""

    def test_includes_day_one_authorities(self) -> None:
        assert "ebird" in KNOWN_NAMESPACES
        assert "ioc" in KNOWN_NAMESPACES
        assert "audioset" in KNOWN_NAMESPACES

    def test_includes_escape_hatch(self) -> None:
        """orpheus.custom lets local deployments add labels without
        having to update KNOWN_NAMESPACES first."""
        assert "orpheus.custom" in KNOWN_NAMESPACES

    def test_is_frozen(self) -> None:
        """frozenset prevents accidental mutation at runtime."""
        with pytest.raises(AttributeError):
            KNOWN_NAMESPACES.add("rogue")  # type: ignore[attr-defined]


class TestValidateNamespace:
    """Tests for ``validate_namespace()`` directly."""

    def test_accepts_known(self) -> None:
        assert validate_namespace("ebird") == "ebird"
        assert validate_namespace("audioset") == "audioset"

    def test_rejects_unknown(self) -> None:
        with pytest.raises(ValueError, match="Unknown TaxonomyRef namespace"):
            validate_namespace("not_a_real_namespace")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="Unknown TaxonomyRef namespace"):
            validate_namespace("")

    def test_error_message_lists_known(self) -> None:
        """The error message must hint at what the caller should use."""
        try:
            validate_namespace("birdnet_codes")
        except ValueError as exc:
            assert "ebird" in str(exc)
            assert "audioset" in str(exc)


class TestTaxonomyRefValidation:
    """End-to-end: TaxonomyRef rejects unknown namespaces at construction."""

    def test_accepts_known_namespace(self) -> None:
        ref = TaxonomyRef(namespace="audioset", id="/m/04rlf")
        assert ref.namespace == "audioset"

    def test_rejects_unknown_namespace(self) -> None:
        # Pydantic wraps validator errors in ValidationError.
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TaxonomyRef(namespace="not_in_registry", id="whatever")

    def test_accepts_ebird(self) -> None:
        ref = TaxonomyRef(namespace="ebird", id="amecro", common_name="American Crow")
        assert ref.id == "amecro"

    def test_accepts_ioc(self) -> None:
        ref = TaxonomyRef(
            namespace="ioc", id="Corvus brachyrhynchos", common_name="American Crow"
        )
        assert ref.namespace == "ioc"

    def test_accepts_orpheus_custom(self) -> None:
        ref = TaxonomyRef(namespace="orpheus.custom", id="local.crow_alarm")
        assert ref.id == "local.crow_alarm"
