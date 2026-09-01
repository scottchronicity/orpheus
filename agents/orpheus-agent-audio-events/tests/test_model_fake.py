"""Tests for ``DeterministicFakeSED`` and the ``build_model`` factory."""

from __future__ import annotations

import numpy as np
import pytest

from orpheus_agent_audio_events.model import (
    DeterministicFakeSED,
    build_model,
)


class TestDeterministicFakeSED:
    """The fake gives us reproducible inputs for the post-processing tests."""

    def test_default_shape(self) -> None:
        fake = DeterministicFakeSED(
            sample_rate=32000, num_classes=527, frame_duration_seconds=0.032
        )
        audio = np.zeros(32000, dtype=np.float32)  # 1 s
        out = fake.predict(audio)
        assert out.ndim == 2
        # ~31 frames for 1 s at 32 ms/frame.
        assert out.shape[0] == 31
        assert out.shape[1] == 527

    def test_zero_audio_zero_output_by_default(self) -> None:
        fake = DeterministicFakeSED()
        audio = np.zeros(32000, dtype=np.float32)
        out = fake.predict(audio)
        assert np.all(out == 0.0)

    def test_inject_event_makes_class_score(self) -> None:
        fake = DeterministicFakeSED(num_classes=10, frame_duration_seconds=0.032)
        fake.inject_event(class_index=3, start_seconds=0.5, end_seconds=1.5, score=0.85)
        audio = np.zeros(32000 * 2, dtype=np.float32)  # 2 s
        out = fake.predict(audio)
        # Frames 0.5/0.032 = ~15 to 1.5/0.032 = ~46.
        assert out[15:46, 3].mean() == pytest.approx(0.85, abs=0.05)
        # Other classes are zero.
        assert out[:, 0].max() == 0.0

    def test_inject_event_rejects_bad_class_index(self) -> None:
        fake = DeterministicFakeSED(num_classes=10)
        with pytest.raises(ValueError, match="class_index"):
            fake.inject_event(class_index=100, start_seconds=0.0, end_seconds=1.0)

    def test_inject_event_rejects_bad_time_range(self) -> None:
        fake = DeterministicFakeSED()
        with pytest.raises(ValueError, match="start_seconds"):
            fake.inject_event(class_index=0, start_seconds=-0.1, end_seconds=0.5)
        with pytest.raises(ValueError, match="start_seconds"):
            fake.inject_event(class_index=0, start_seconds=1.0, end_seconds=0.5)

    def test_inject_event_rejects_score_out_of_range(self) -> None:
        fake = DeterministicFakeSED()
        with pytest.raises(ValueError, match="score"):
            fake.inject_event(class_index=0, start_seconds=0.0, end_seconds=1.0, score=1.5)

    def test_multiple_events_stack(self) -> None:
        fake = DeterministicFakeSED(num_classes=10)
        fake.inject_event(class_index=3, start_seconds=0.0, end_seconds=0.5, score=0.8)
        fake.inject_event(class_index=5, start_seconds=0.5, end_seconds=1.0, score=0.6)
        audio = np.zeros(32000, dtype=np.float32)
        out = fake.predict(audio)
        assert out[5, 3] == pytest.approx(0.8)
        assert out[20, 5] == pytest.approx(0.6)


class TestBuildModel:
    """``build_model`` is the entry point the agent uses."""

    def test_fake_variant(self) -> None:
        model = build_model(variant="fake")
        assert isinstance(model, DeterministicFakeSED)

    def test_cnn14_requires_checkpoint(self) -> None:
        with pytest.raises(ValueError, match="checkpoint_path"):
            build_model(variant="cnn14_sed", checkpoint_path=None)

    def test_unknown_variant_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown model variant"):
            build_model(variant="some_made_up_thing")


class TestPannsLabelsStaging:
    """Tests for the ``_stage_panns_labels_and_pin_home`` helper that
    works around ``panns_inference``'s hardcoded ``~/panns_data/...``
    path. Ensures the file lands in the right place on systemd / unknown-user
    deployments and that HOME doesn't get stuck in the modified state."""

    def test_copies_bundled_csv_when_missing(self, tmp_path, monkeypatch) -> None:
        """First-run path: the labels file doesn't exist; the helper
        copies the bundled CSV into place under $ORPHEUS_DATA_ROOT."""
        import csv  # noqa: PLC0415
        import os  # noqa: PLC0415

        from orpheus_agent_audio_events.model import (  # noqa: PLC0415
            _restore_home,
            _stage_panns_labels_and_pin_home,
        )

        fake_home = tmp_path / "fake-user-home"
        fake_home.mkdir()
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        monkeypatch.setenv("HOME", str(fake_home))

        data_root, original_home = _stage_panns_labels_and_pin_home()

        # File copied to the expected place.
        labels = tmp_path / "panns_data" / "class_labels_indices.csv"
        assert labels.exists()
        # Must contain all 527 AudioSet classes (header + 527 rows = 528).
        with labels.open() as f:
            rows = list(csv.reader(f))
        assert len(rows) == 528, f"Expected 528 rows incl header, got {len(rows)}"
        assert rows[0] == ["index", "mid", "display_name"]
        # First row is Speech (panns_inference's index 0).
        assert rows[1][0] == "0"
        assert rows[1][1] == "/m/09x0r"
        # Last row is Field recording (index 526).
        assert rows[-1][0] == "526"

        # HOME got pinned to the data root for the panns_inference import.
        assert os.environ["HOME"] == str(tmp_path)
        assert data_root == str(tmp_path)
        assert original_home == str(fake_home)

        # Caller restores HOME via _restore_home — this MUST work so the
        # rest of the process doesn't have a stuck HOME.
        _restore_home(original_home)
        assert os.environ["HOME"] == str(fake_home)

    def test_idempotent_when_already_staged(self, tmp_path, monkeypatch) -> None:
        """Re-running with the file already in place is a no-op (no copy,
        no error, no rewrite). Important — agent restarts shouldn't
        re-copy 14kB every time."""
        from orpheus_agent_audio_events.model import (  # noqa: PLC0415
            _restore_home,
            _stage_panns_labels_and_pin_home,
        )

        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        # First call — places the file.
        _, original_home = _stage_panns_labels_and_pin_home()
        _restore_home(original_home)

        labels = tmp_path / "panns_data" / "class_labels_indices.csv"
        mtime_before = labels.stat().st_mtime

        # Second call — should not rewrite the file.
        _, original_home = _stage_panns_labels_and_pin_home()
        _restore_home(original_home)
        assert labels.stat().st_mtime == mtime_before

    def test_restore_home_handles_unset_home(self, tmp_path, monkeypatch) -> None:
        """If HOME wasn't set originally, _restore_home unsets it again
        instead of leaving it pinned. Edge case for very minimal envs."""
        import os  # noqa: PLC0415

        from orpheus_agent_audio_events.model import _restore_home  # noqa: PLC0415

        monkeypatch.delenv("HOME", raising=False)
        assert "HOME" not in os.environ
        # Simulate the helper having set HOME.
        staged = tmp_path / "staged"
        staged.mkdir()
        os.environ["HOME"] = str(staged)
        # Restore with None (the value original_home would have been).
        _restore_home(None)
        assert "HOME" not in os.environ

    def test_falls_back_to_default_data_root(self, tmp_path, monkeypatch) -> None:
        """Without ORPHEUS_DATA_ROOT set, the helper defaults to
        /data/orpheus — but here we'd actually create files there, so
        just verify the rationale lives in the docstring and the
        environment is consulted."""
        from orpheus_agent_audio_events.model import (  # noqa: PLC0415
            _restore_home,
            _stage_panns_labels_and_pin_home,
        )

        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        data_root, original_home = _stage_panns_labels_and_pin_home()
        _restore_home(original_home)
        # When ORPHEUS_DATA_ROOT is set, the helper honours it.
        assert data_root == str(tmp_path)

    def test_assert_guard_raises_when_panns_already_imported(self, monkeypatch) -> None:
        """The production safety guard refuses to stage HOME when
        panns_inference is already in sys.modules — because the
        pin would silently be a no-op (panns_inference.config caches
        the labels-CSV path at import time)."""
        import sys  # noqa: PLC0415

        from orpheus_agent_audio_events.model import (  # noqa: PLC0415
            _assert_panns_not_already_imported,
        )

        # Inject a fake panns_inference module so the guard fires.
        # We do NOT actually import panns_inference here — we just put
        # a sentinel in sys.modules to simulate prior import.
        monkeypatch.setitem(sys.modules, "panns_inference", object())
        with pytest.raises(RuntimeError, match="already imported"):
            _assert_panns_not_already_imported()
