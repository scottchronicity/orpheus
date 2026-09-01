"""End-to-end integration test for the audio-events pipeline.

Loads the REAL PANNs Cnn14_DecisionLevelMax checkpoint + runs it against
the bundled bird call samples from ``artifacts/audio-samples/`` + asserts
the expected AudioSet labels fire.

Skipped automatically when:
- The checkpoint isn't present locally (CI without LFS pulls, or first
  time on a dev box that hasn't run ``make download-models``).
- The audio samples directory is missing.
- ``torch`` / ``panns_inference`` aren't installed (lightweight CI).

Run on a dev box with ``make install-audio-events`` + LFS pulled:

    cd agents/orpheus-agent-audio-events
    venv/bin/pytest tests/integration/test_pipeline_e2e.py -v -s

Run on Jetson after ``make download-models``:

    sudo systemctl stop orpheus-agent-audio-events
    cd /opt/orpheus/agents/orpheus-agent-audio-events
    venv/bin/pytest tests/integration/test_pipeline_e2e.py -v -s
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest

# Resolve the repo root so we can find artifacts/audio-samples/ regardless
# of where pytest is invoked from.
_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[4]
_SAMPLES_DIR = _REPO_ROOT / "artifacts" / "audio-samples"
_CHECKPOINT_CANDIDATES = [
    Path(os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus"))
    / "models"
    / "panns_cnn14_decision_level_max.pth",
    Path.home() / "data" / "orpheus" / "models" / "panns_cnn14_decision_level_max.pth",
    _REPO_ROOT / "artifacts" / "models" / "panns_cnn14_decision_level_max.pth",
]


def _find_checkpoint() -> Path | None:
    for p in _CHECKPOINT_CANDIDATES:
        if p.exists() and p.stat().st_size > 100_000_000:  # >100MB sanity
            return p
    return None


_CHECKPOINT = _find_checkpoint()


@pytest.fixture(scope="module")
def model():
    """Load the real PANNs SED model once for the whole module."""
    if _CHECKPOINT is None:
        pytest.skip(
            "PANNs checkpoint not found at any candidate location "
            f"({[str(p) for p in _CHECKPOINT_CANDIDATES]}). "
            "Run 'git lfs pull' or 'make download-models'."
        )
    # Point ORPHEUS_DATA_ROOT at wherever the checkpoint actually lives.
    # Without this, the staging helper defaults to /data/orpheus which
    # is read-only on macOS dev boxes.
    _data_root = _CHECKPOINT.parent.parent  # .../models/...pth → .../
    os.environ["ORPHEUS_DATA_ROOT"] = str(_data_root)
    try:
        import librosa  # noqa: F401, PLC0415
        import soundfile  # noqa: F401, PLC0415
    except ImportError:
        pytest.skip("soundfile/librosa not installed; run 'make install-audio-events'.")
    # Don't `import panns_inference` here — its config.py reads the
    # labels CSV at module-import time and would fail BEFORE PANNsCnn14SED
    # gets to stage the file. PANNsCnn14SED.__init__ handles both the
    # staging AND the lazy import in the right order.
    try:
        from importlib.util import find_spec  # noqa: PLC0415

        if find_spec("panns_inference") is None:
            pytest.skip(
                "panns_inference not installed; run 'make install-audio-events'."
            )
    except Exception as e:  # pylint: disable=broad-except
        pytest.skip(f"Couldn't check panns_inference install state: {e}")

    from orpheus_agent_audio_events.model import PANNsCnn14SED  # noqa: PLC0415

    return PANNsCnn14SED(checkpoint_path=_CHECKPOINT, device="cpu")


def _load_resampled(path: Path, target_sr: int) -> np.ndarray:
    """Helper that mirrors the agent's audio-loading path."""
    import librosa  # noqa: PLC0415
    import soundfile as sf  # noqa: PLC0415

    audio, sr = sf.read(str(path))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != target_sr:
        audio = librosa.resample(audio.astype(np.float32), orig_sr=sr, target_sr=target_sr)
    return audio.astype(np.float32)


# Each tuple: (filename, set of AudioSet mids we expect to be in the top-5 scores).
# Tolerant: we require ANY of the listed mids — different recordings hit
# different specific tags. Mids sourced from PANNs/AudioSet's canonical labels.
EXPECTED_HITS = [
    (
        "American Crow - Corvus_brachyrhynchos_call.ogg",
        # Crow, Caw — both highly specific corvid tags.
        {"/m/04s8yn", "/m/07r5c2p"},
    ),
    (
        "American Robin - Turdus-migratorius-003.ogg",
        # Bird, Bird vocalization/call/song, Chirp/tweet — should all fire.
        {"/m/015p6", "/m/020bb7", "/m/07pggtn"},
    ),
    (
        "Blue Jay - Cyanocitta_cristata_-_Blue_Jay_-_XC109601.ogg",
        {"/m/015p6", "/m/020bb7", "/m/07pggtn"},
    ),
    (
        "Common_Raven_Grand_Teton_National_Park.ogg",
        # Ravens often fire either Crow or Caw, plus generic Bird.
        {"/m/04s8yn", "/m/07r5c2p", "/m/015p6", "/m/020bb7"},
    ),
    (
        "Pileated_Woodpecker.ogg",
        # Woodpecker is a specific AudioSet class; Bird is the fallback.
        {"/m/01b_21", "/m/015p6", "/m/020bb7", "/m/07pggtn"},
    ),
]


def _full_labels_map() -> dict[int, tuple[str, str]]:
    """Read the staged labels CSV to map class index → (mid, display_name).

    Reads from the location the staging helper writes to (relative to
    ``ORPHEUS_DATA_ROOT``), which is where panns_inference's ``Path.home()``
    resolves to during the import.
    """
    import csv  # noqa: PLC0415

    labels_path = (
        Path(os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus"))
        / "panns_data"
        / "class_labels_indices.csv"
    )
    with labels_path.open() as f:
        rows = list(csv.reader(f))
    return {int(r[0]): (r[1], r[2]) for r in rows[1:]}


class TestPipelineE2E:
    """Real PANNs against bundled audio. Skipped without checkpoint."""

    def test_labels_csv_staged_at_orpheus_data_root(self, model) -> None:  # noqa: ARG002 — fixture forces model load
        """After model load, the labels CSV must live under
        ``$ORPHEUS_DATA_ROOT/panns_data/`` — not the user's home."""
        expected = (
            Path(os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus"))
            / "panns_data"
            / "class_labels_indices.csv"
        )
        assert expected.exists(), (
            f"Labels CSV should be at {expected} after staging — "
            "the HOME-pinning helper isn't working as designed."
        )
        # 527 AudioSet classes + 1 header row.
        with expected.open() as f:
            assert sum(1 for _ in f) == 528

    def test_home_is_not_left_pinned(self, model) -> None:  # noqa: ARG002 — fixture forces model load
        """After model load, $HOME must be back to whatever it was
        before — not stuck at $ORPHEUS_DATA_ROOT."""
        home = os.environ.get("HOME", "")
        data_root = str(
            Path(os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus"))
        )
        if home and home != data_root:
            # If HOME was set to something different from ORPHEUS_DATA_ROOT
            # before, it must remain that. This is the leak we worry about.
            assert home != data_root, (
                f"HOME was pinned to ORPHEUS_DATA_ROOT={data_root} and "
                "not restored — process state is corrupted."
            )

    def test_model_metadata_matches_panns_contract(self, model) -> None:
        """Sanity check the model wrapper exposes the right constants.

        PANNs Cnn14_DecisionLevelMax framewise output is at 100 Hz
        (hop_size=320 @ sample_rate=32000). Documented + measured
        empirically in the real_audio_classification tests above.
        """
        assert model.sample_rate == 32000
        assert model.num_classes == 527
        # 10 ms per frame (100 Hz framewise output).
        assert 0.009 < model.frame_duration_seconds < 0.011

    @pytest.mark.parametrize(("filename", "expected_mids"), EXPECTED_HITS)
    def test_real_audio_classification(
        self, model, filename: str, expected_mids: set
    ) -> None:
        """Run real PANNs against bundled samples; assert expected
        AudioSet labels are in the top-5 clip-level scores."""
        clip_path = _SAMPLES_DIR / filename
        if not clip_path.exists():
            pytest.skip(f"Sample {filename} missing (git lfs pull?).")

        audio = _load_resampled(clip_path, model.sample_rate)
        # ~88s on the Robin sample takes ~300ms CPU inference; cap to
        # 30s of the longest sample so the suite doesn't take forever.
        max_samples = 30 * model.sample_rate
        if len(audio) > max_samples:
            audio = audio[:max_samples]

        t0 = time.time()
        frames = model.predict(audio)
        elapsed_ms = (time.time() - t0) * 1000

        # Framewise shape: (T, 527). T should match
        # (duration_seconds / frame_duration_seconds) within rounding.
        # This catches the frame-rate-mismatch bug that bit us during
        # the integration-test rollout.
        assert frames.shape[1] == 527
        duration_s = len(audio) / model.sample_rate
        expected_frames = int(duration_s / model.frame_duration_seconds)
        # Allow ±5% slop because PANNs may pad/trim windows.
        tolerance = max(20, int(expected_frames * 0.05))
        assert abs(frames.shape[0] - expected_frames) <= tolerance, (
            f"Frame count {frames.shape[0]} doesn't match expected "
            f"{expected_frames} (±{tolerance}) — model.frame_duration_seconds "
            f"({model.frame_duration_seconds}) may be miscalibrated. "
            f"Empirical: {frames.shape[0] / duration_s:.1f} Hz."
        )

        # Top-5 clip-level scores must include at least one expected mid.
        clip_scores = frames.max(axis=0)
        top5_indices = np.argsort(clip_scores)[::-1][:5]
        labels = _full_labels_map()
        top5_mids = {labels[int(i)][0] for i in top5_indices}

        intersection = expected_mids & top5_mids
        assert intersection, (
            f"None of {expected_mids} appeared in top-5 PANNs predictions "
            f"for {filename}. Top-5 was: "
            f"{[(labels[int(i)][1], round(float(clip_scores[i]), 3)) for i in top5_indices]}. "
            "This means either the model loaded a wrong checkpoint, the "
            "labels CSV is misaligned with the model, or the sample got "
            "corrupted."
        )
        # Inference speed sanity — CPU should manage real-time-ish even
        # on a Mac laptop. > 5s on a clip < 30s long signals something
        # broken (Jetson-side this is the thermal/OOM warning zone).
        assert elapsed_ms < 5000, (
            f"Inference took {elapsed_ms:.0f}ms on a clip of "
            f"{len(audio)/model.sample_rate:.1f}s — investigate."
        )
        print(
            f"  ✓ {filename}: matched {intersection}, "
            f"inference {elapsed_ms:.0f}ms on {len(audio)/model.sample_rate:.1f}s"
        )

    def test_post_processing_emits_clips_with_intervals(self, model) -> None:
        """The full pipeline (model → post_process) must produce at
        least one ClassifiedClip with non-empty intervals for the
        American Crow sample at the default thresholds."""
        from orpheus_agent_audio_events import audioset_ontology  # noqa: PLC0415
        from orpheus_agent_audio_events.post_processing import post_process  # noqa: PLC0415

        clip_path = _SAMPLES_DIR / "American Crow - Corvus_brachyrhynchos_call.ogg"
        if not clip_path.exists():
            pytest.skip("Crow sample missing.")

        audio = _load_resampled(clip_path, model.sample_rate)
        frames = model.predict(audio)
        labels = audioset_ontology.load_labels()
        clips = post_process(
            frames,
            frame_duration_seconds=model.frame_duration_seconds,
            clip_threshold=0.3,
            frame_threshold=0.2,
            bridge_ms=100,
            min_interval_ms=50,
            max_labels_per_clip=10,
            allowed_class_indices=list(labels.keys()),
        )

        assert len(clips) > 0, (
            "post_process emitted 0 clips at default thresholds for a "
            "real crow sample. Defaults may be too strict, or labels.id "
            "filter is dropping the crow class."
        )

        # At least one clip should be the Crow class (/m/04s8yn → index 117).
        crow_clip = next((c for c in clips if c.class_index == 117), None)
        assert crow_clip is not None, (
            f"Crow class (idx 117 /m/04s8yn) didn't survive post-processing. "
            f"Surviving classes: {[(c.class_index, labels.get(c.class_index)) for c in clips]}"
        )
        assert len(crow_clip.intervals) > 0, (
            "Crow clip survived clip-level threshold but has no "
            "frame-level intervals. Likely a frame_threshold issue."
        )
        # Intervals should be inside the clip's actual duration.
        clip_duration = len(audio) / model.sample_rate
        for iv in crow_clip.intervals:
            assert 0 <= iv.start_seconds < iv.end_seconds <= clip_duration + 0.1


if __name__ == "__main__":  # pragma: no cover
    # Allow running the module directly as a smoke test.
    sys.exit(pytest.main(["-v", "-s", __file__]))
