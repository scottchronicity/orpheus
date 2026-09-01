"""Tests for the public portal projection — the privacy chokepoint."""

import json
from datetime import datetime, timezone

import pytest

from orpheus_common.config import OrpheusConfig, PublicProjectionConfig
from orpheus_common.detection.models import Entity, EntityEvidence
from orpheus_common.portal import (
    PUBLIC_ALLOWED_KEYS,
    SENSITIVE_FIELDS,
    PublicEntityRecord,
    PublicProjection,
    ReadModel,
    coarsen_location,
    coarsen_time,
    export_public_site,
)


def _sensitive_entity() -> Entity:
    """An entity carrying every kind of private data the projection must drop."""
    return Entity(
        entity_id="ent-1",
        timestamp=datetime(2026, 1, 2, 13, 45, 7, tzinfo=timezone.utc),
        species="amecro",
        common_name="American Crow",
        confidence=0.93,
        entity_type="Animal.Bird.Crow",
        evidence=[
            EntityEvidence(
                event_id="e1",
                sensor_id="mic-3",
                clip_path="/data/orpheus/clips/clip.wav",
                confidence=0.93,
            )
        ],
        context={"lat": 47.6062, "lon": -122.3321, "sensor_id": "mic-3"},
        event_signature={"mics": ["mic-3"]},
    )


class TestPublicEntityRecord:
    def test_has_only_allowed_fields(self) -> None:
        assert set(PublicEntityRecord.model_fields) == PUBLIC_ALLOWED_KEYS

    def test_is_frozen(self) -> None:
        rec = PublicEntityRecord(
            species_code="x", date_bucket="2026-01-02", region_label="Site A"
        )
        with pytest.raises(Exception):  # noqa: B017,PT011 - frozen -> any mutation error
            rec.species_code = "y"


class TestPublicProjection:
    def test_drops_every_sensitive_field(self) -> None:
        rec = PublicProjection(
            PublicProjectionConfig(site_label="Site A")
        ).project_entity(_sensitive_entity())
        keys = set(rec.model_dump().keys())
        assert keys <= PUBLIC_ALLOWED_KEYS
        assert not (keys & SENSITIVE_FIELDS)
        # safe values, coarsened
        assert rec.species_code == "amecro"
        assert rec.entity_type == "Animal.Bird.Crow"
        assert rec.date_bucket == "2026-01-02"  # day bucket — no seconds
        assert rec.region_label == "Site A"
        # planted sentinels never appear in the emitted record
        blob = rec.model_dump_json()
        for sentinel in ("47.6062", "-122.3321", "mic-3", "clip.wav", "13:45"):
            assert sentinel not in blob

    def test_location_fails_closed_without_site_label(self) -> None:
        rec = PublicProjection(PublicProjectionConfig()).project_entity(
            _sensitive_entity()
        )
        assert rec.region_label == "undisclosed"  # never a coordinate

    def test_confidence_band_omitted_unless_configured(self) -> None:
        assert (
            PublicProjection(PublicProjectionConfig())
            .project_entity(_sensitive_entity())
            .confidence_band
            is None
        )
        cfg = PublicProjectionConfig(confidence_bands={"high": 0.9, "medium": 0.6})
        assert (
            PublicProjection(cfg).project_entity(_sensitive_entity()).confidence_band
            == "high"
        )


class TestCoarsen:
    def test_time(self) -> None:
        ts = datetime(2026, 1, 2, 13, 45, 7, tzinfo=timezone.utc)
        assert coarsen_time(ts) == "2026-01-02"
        assert coarsen_time(ts, "hour") == "2026-01-02T13:00"
        assert coarsen_time(ts, "bogus") == "2026-01-02"  # falls closed to day

    def test_location(self) -> None:
        assert coarsen_location(site_label="Site A") == "Site A"
        assert coarsen_location() == "undisclosed"
        # grid mode isn't shipped in v1 -> placeholder, never a coordinate
        assert coarsen_location(mode="grid", site_label="Site A") == "undisclosed"


class _FakeDB:
    def __init__(self, entities: list) -> None:
        self._entities = entities

    def get_entities(self, limit: int = 500, **_filters: object) -> list:
        # Honour limit like the real DetectionDB (default 500) so the tests can
        # prove the export passes a deliberate, larger cap.
        return list(self._entities)[:limit]


def _self_generated_entity() -> Entity:
    ent = _sensitive_entity()
    return ent.model_copy(update={"entity_id": "ent-echo", "is_self_generated": True})


class TestReadModel:
    def test_yields_only_public_records(self) -> None:
        rm = ReadModel(
            _FakeDB([_sensitive_entity()]), PublicProjectionConfig(site_label="Site A")
        )
        out = list(rm.public_entities())
        assert len(out) == 1
        assert isinstance(out[0], PublicEntityRecord)
        assert out[0].species_code == "amecro"

    def test_drops_self_generated_entities(self) -> None:
        # A playback echo tagged is_self_generated must never ship as a wildlife
        # observation — and the allow-list record has no slot for the flag, so
        # dropping (not tagging) is the only safe public projection.
        rm = ReadModel(
            _FakeDB([_sensitive_entity(), _self_generated_entity()]),
            PublicProjectionConfig(site_label="Site A"),
        )
        assert len(list(rm.public_entities())) == 1

    def test_explicit_limit_hit_logs_truncation_warning(self, monkeypatch) -> None:
        from unittest.mock import Mock

        from orpheus_common.portal import read_model as read_model_mod

        warn_logger = Mock()
        monkeypatch.setattr(read_model_mod, "logger", warn_logger)
        rm = ReadModel(
            _FakeDB([_sensitive_entity()] * 3), PublicProjectionConfig(site_label="A")
        )
        assert len(list(rm.public_entities(limit=2))) == 2
        warn_logger.warning.assert_called_once()  # truncation is loud, not silent
        warn_logger.reset_mock()
        assert len(list(rm.public_entities(limit=50))) == 3
        warn_logger.warning.assert_not_called()  # under the cap -> quiet


class TestPublicProjectionConfig:
    def test_defaults_disabled_and_fail_closed(self) -> None:
        c = PublicProjectionConfig.from_dict({})
        assert c.enabled is False
        assert c.time_granularity == "day"
        assert c.location_mode == "site_label"
        assert c.site_label == ""
        assert c.confidence_bands == {}

    def test_wired_into_orpheus_config(self) -> None:
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "public": {"enabled": True, "site_label": "Site A"},
            },
            source="<test>",
        )
        assert cfg.public.enabled is True
        assert cfg.public.site_label == "Site A"
        assert cfg.to_dict()["public"]["site_label"] == "Site A"


class TestPublicExport:
    """The artifact scan: the emitted file must carry no sensitive keys or
    planted sentinels — a leak fails the build before any public byte ships."""

    def test_export_emits_only_safe_data(self, tmp_path) -> None:
        out = export_public_site(
            _FakeDB([_sensitive_entity()]),
            PublicProjectionConfig(site_label="Site A"),
            tmp_path / "public_site",
        )
        blob = out.read_text()
        data = json.loads(blob)
        assert data["entities"], "expected at least one exported entity"
        for rec in data["entities"]:
            assert set(rec) <= PUBLIC_ALLOWED_KEYS
            assert not (set(rec) & SENSITIVE_FIELDS)
        # planted sentinels (a coord, a sensor id, a clip path, a wall-clock time)
        # must not appear anywhere in the raw artifact
        for sentinel in ("47.6062", "-122.3321", "mic-3", "clip.wav", "13:45"):
            assert sentinel not in blob

    def test_export_is_atomic_full_replace(self, tmp_path) -> None:
        cfg = PublicProjectionConfig(site_label="Site A")
        export_public_site(_FakeDB([_sensitive_entity()]), cfg, tmp_path / "site")
        # re-export with no entities fully replaces (a removed species disappears)
        out = export_public_site(_FakeDB([]), cfg, tmp_path / "site")
        assert json.loads(out.read_text())["entities"] == []
        assert not (tmp_path / "site" / ".entities.json.tmp").exists()

    def test_export_is_not_capped_at_the_ui_page_size(self, tmp_path) -> None:
        # get_entities defaults to limit=500 (a UI page size). The full-replace
        # citizen-science export must pass a deliberate, much larger cap or the
        # dataset silently plateaus at the 500 newest entities.
        many = [_sensitive_entity() for _ in range(501)]
        out = export_public_site(
            _FakeDB(many), PublicProjectionConfig(site_label="Site A"), tmp_path / "site"
        )
        data = json.loads(out.read_text())
        assert data["count"] == 501
        assert len(data["entities"]) == 501

    def test_export_excludes_self_generated_entities(self, tmp_path) -> None:
        # The system's own crow-call playback (corollary discharge echo) must
        # not appear in the public dataset as a real observation.
        out = export_public_site(
            _FakeDB([_sensitive_entity(), _self_generated_entity()]),
            PublicProjectionConfig(site_label="Site A"),
            tmp_path / "site",
        )
        data = json.loads(out.read_text())
        assert data["count"] == 1
        assert len(data["entities"]) == 1

    def test_export_carries_provenance_envelope(self, tmp_path) -> None:
        out = export_public_site(
            _FakeDB([_sensitive_entity()]),
            PublicProjectionConfig(site_label="Site A"),  # default day granularity
            tmp_path / "site",
        )
        data = json.loads(out.read_text())
        assert data["count"] == len(data["entities"])
        assert data["site_label"] == "Site A"
        # generated_at is coarsened (day precision by default) — never second-precision,
        # so it can't fingerprint. Day granularity => a bare YYYY-MM-DD, no time part.
        assert "T" not in data["generated_at"]
        assert len(data["generated_at"]) == 10  # YYYY-MM-DD


class TestExportCli:
    """orpheus-public-export runs on the portal/mirror host: the replica path
    must be stated (mirror.staging_path or --db), never guessed from the
    Jetson's live-DB default."""

    def _install_config(self, **extra: object) -> None:
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "public": {"enabled": True, "site_label": "Site A"},
                **extra,
            },
            source="<test>",
        )
        OrpheusConfig._instance = cfg  # conftest resets the singleton after

    def test_fails_closed_without_replica_path(self) -> None:
        from orpheus_common.portal.export import main

        self._install_config()  # no mirror.staging_path
        assert main([]) == 2  # refuse, never fall back to the live-DB path

    def test_db_argument_names_the_replica(self, tmp_path) -> None:
        from orpheus_common.detection import DetectionDB
        from orpheus_common.portal.export import main

        replica = tmp_path / "replica.db"
        DetectionDB(db_path=replica).save_entity(_sensitive_entity())
        self._install_config()
        out_dir = tmp_path / "site"
        assert main(["--db", str(replica), "--out", str(out_dir)]) == 0
        data = json.loads((out_dir / "entities.json").read_text())
        assert data["count"] == 1

    def test_staging_path_config_still_works(self, tmp_path) -> None:
        from orpheus_common.detection import DetectionDB
        from orpheus_common.portal.export import main

        replica = tmp_path / "replica.db"
        DetectionDB(db_path=replica).save_entity(_sensitive_entity())
        self._install_config(mirror={"staging_path": str(replica)})
        out_dir = tmp_path / "site"
        assert main(["--out", str(out_dir)]) == 0
        assert (out_dir / "entities.json").exists()
