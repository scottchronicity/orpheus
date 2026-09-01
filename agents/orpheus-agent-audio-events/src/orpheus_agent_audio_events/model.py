"""SED model interface plus a deterministic fake and the PANNs wrapper.

``SEDModel`` is the abstraction the agent talks to. ``DeterministicFakeSED``
gives us a synthesizable, reproducible model for unit tests so we never need
to download model weights or import PyTorch / panns_inference in CI.
``PANNsCnn14SED`` is the production implementation; it imports
``panns_inference`` lazily inside ``__init__`` so tests aren't dragged into
a 300+ MB dependency chain when they don't need it.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np


class SEDModel(ABC):
    """A Sound Event Detection model that produces framewise scores.

    Implementations consume mono audio at a fixed sample rate (see
    ``sample_rate``) and return a 2-D matrix of per-frame sigmoid scores
    across a fixed class set.
    """

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Sample rate (Hz) the model expects on ``predict()``."""

    @property
    @abstractmethod
    def num_classes(self) -> int:
        """Number of output classes."""

    @property
    @abstractmethod
    def frame_duration_seconds(self) -> float:
        """Duration of one output frame, in seconds.

        For PANNs Cnn14_DecisionLevelMax at 32 kHz this is 0.01 seconds
        (10 ms) — hop_size=320 / sample_rate=32000. Post-processing uses
        this to translate frame indices into clip-relative time
        intervals. NB: older PANNs docs / variants quote 32 ms; that's
        a different model.
        """

    @abstractmethod
    def predict(self, audio_mono: np.ndarray) -> np.ndarray:
        """Run inference on a mono audio clip.

        Args:
            audio_mono: 1-D float32 array at ``self.sample_rate``.

        Returns:
            2-D array of shape ``(num_frames, num_classes)`` with sigmoid
            scores in [0, 1].
        """


class DeterministicFakeSED(SEDModel):
    """A synthesizable, reproducible SED for unit tests.

    Produces framewise outputs that are 0.0 by default, with caller-injected
    "events" raising a specific class's score in a specific time range. The
    agent's pipeline (post-processing → Detection construction → MQTT publish)
    can be exercised end-to-end without loading PyTorch.
    """

    def __init__(
        self,
        sample_rate: int = 32000,
        num_classes: int = 527,
        frame_duration_seconds: float = 0.032,
    ) -> None:
        self._sample_rate = sample_rate
        self._num_classes = num_classes
        self._frame_duration_seconds = frame_duration_seconds
        # List of (class_index, start_seconds, end_seconds, score).
        self._events: list = []

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def num_classes(self) -> int:
        return self._num_classes

    @property
    def frame_duration_seconds(self) -> float:
        return self._frame_duration_seconds

    def inject_event(
        self,
        class_index: int,
        start_seconds: float,
        end_seconds: float,
        score: float = 0.9,
    ) -> None:
        """Make this class score ``score`` between ``start`` and ``end`` seconds."""
        if not 0 <= class_index < self._num_classes:
            raise ValueError(f"class_index {class_index} out of range")
        if start_seconds < 0 or end_seconds <= start_seconds:
            raise ValueError("require 0 <= start_seconds < end_seconds")
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be in [0, 1]")
        self._events.append((class_index, start_seconds, end_seconds, score))

    def predict(self, audio_mono: np.ndarray) -> np.ndarray:
        clip_seconds = audio_mono.size / float(self._sample_rate)
        num_frames = max(1, round(clip_seconds / self._frame_duration_seconds))
        out = np.zeros((num_frames, self._num_classes), dtype=np.float32)
        for class_index, start_seconds, end_seconds, score in self._events:
            start_frame = max(0, int(start_seconds / self._frame_duration_seconds))
            end_frame = min(num_frames, round(end_seconds / self._frame_duration_seconds))
            if end_frame > start_frame:
                out[start_frame:end_frame, class_index] = score
        return out


# Module-level lock guarding the HOME-pinning critical section.
# Two concurrent PANNsCnn14SED() constructors would otherwise interleave
# their read-original-HOME / set-staged-HOME / import-panns / restore-HOME
# windows, and one thread can permanently strand HOME at the staged
# value if its restore runs AFTER the other thread's pin. The lock
# serialises the entire stage+import+restore sequence in the caller.
_PANNS_STAGE_LOCK = threading.Lock()


def _stage_panns_labels_and_pin_home() -> tuple[str, str | None]:
    """Stage the AudioSet labels CSV in a predictable location and point
    ``panns_inference`` at it via ``$HOME`` before its module-level
    ``Path.home()`` runs.

    Why this song-and-dance: panns_inference hardcodes
    ``Path.home() / 'panns_data' / 'class_labels_indices.csv'`` at
    MODULE-IMPORT time (see panns_inference/config.py — no parameter,
    no env var, no constructor argument). On systemd we don't know
    who's running the service (User=orpheus? root?) or whether their
    HOME directory is writable, exists, or is shared with other users.

    Solution: relocate the panns "home" to a predictable location
    derived from ``ORPHEUS_DATA_ROOT`` (the env var the rest of the
    system already uses for cross-user paths). For systemd
    User=orpheus this lands at ``/data/orpheus/panns_data/`` — same
    path regardless of which user runs the service.

    **Caller MUST hold ``_PANNS_STAGE_LOCK``** for the duration of the
    stage → panns_inference import → restore sequence. The constructor
    in ``PANNsCnn14SED.__init__`` does this; no other entry point
    should be calling these helpers directly.

    Returns the original ``HOME`` value (or ``None`` if it was unset)
    so the caller can restore it after panns_inference is imported.

    See also ``_assert_panns_not_already_imported()`` — production
    callers (the ``PANNsCnn14SED`` ctor) MUST call that BEFORE this
    helper to detect the already-imported case where HOME-pinning is a
    no-op.
    """
    import os  # noqa: PLC0415
    import shutil  # noqa: PLC0415

    data_root = Path(os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus"))
    target = data_root / "panns_data" / "class_labels_indices.csv"
    if not target.exists():
        bundled = Path(__file__).parent / "data" / "panns_class_labels_indices.csv"
        if not bundled.exists():
            raise FileNotFoundError(
                f"Neither {target} nor the bundled {bundled} exists. "
                "Reinstall orpheus-agent-audio-events to restore the "
                "AudioSet labels CSV."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(bundled, target)

    # Pin HOME for the duration of the panns_inference import. After
    # the import, Path.home() inside that module has already been
    # evaluated + cached, so restoring HOME is safe.
    original_home = os.environ.get("HOME")
    os.environ["HOME"] = str(data_root)
    return str(data_root), original_home


def _restore_home(original_home: str | None) -> None:
    """Restore ``$HOME`` after the panns_inference import. Caller must
    hold ``_PANNS_STAGE_LOCK``."""
    import os  # noqa: PLC0415

    if original_home is None:
        os.environ.pop("HOME", None)
    else:
        os.environ["HOME"] = original_home


def _assert_panns_not_already_imported() -> None:
    """Raise if ``panns_inference`` is already in ``sys.modules``.

    The HOME-pin trick in ``_stage_panns_labels_and_pin_home`` works
    only when panns_inference is imported AFTER HOME is pinned —
    because ``panns_inference.config`` evaluates ``Path.home()`` at
    module-import time and caches the labels-CSV path. If anything
    else in the process (a sibling agent, a test fixture, code doing
    ``from panns_inference import ...`` at module level) has already
    imported it, the pin is silently a no-op and labels resolution
    falls back to whatever the library cached first.

    We refuse loudly rather than silently load against the wrong path.
    Tests that exercise the helpers directly (not via PANNsCnn14SED)
    don't need to call this guard.
    """
    import sys  # noqa: PLC0415

    if "panns_inference" in sys.modules or "panns_inference.config" in sys.modules:
        raise RuntimeError(
            "panns_inference is already imported in this process; "
            "the HOME-pin in _stage_panns_labels_and_pin_home cannot "
            "redirect its labels-CSV lookup post-import. The labels "
            "path is cached in panns_inference.config at import time. "
            "Either ensure no code imports panns_inference before "
            "PANNsCnn14SED is constructed, or pre-place "
            "class_labels_indices.csv under ~/panns_data/ for the user "
            "running this process."
        )


class PANNsCnn14SED(SEDModel):
    """Production model: PANNs Cnn14_DecisionLevelMax via ``panns_inference``.

    The constructor lazily imports ``panns_inference`` so tests that use
    ``DeterministicFakeSED`` never load PyTorch.

    Constraints (see ``docs/designs/audio-events-agent.md`` §3.2 and the
    upstream PANNs paper):

    - Sample rate: 32 kHz mono. Caller must resample upstream.
    - Output: framewise sigmoid scores of shape ``(T, 527)`` over the
      AudioSet 527-class ontology.
    - Frame duration: 0.01 s (10 ms), i.e. ``T ≈ duration_seconds *
      100``. The framewise output is at PANNs Cnn14_DecisionLevelMax's
      hop rate (hop_size=320 / sample_rate=32000). Don't propagate the
      older "~32 ms" figure that appeared in upstream PANNs docs for
      a different variant.
    """

    PANNS_SAMPLE_RATE = 32000
    PANNS_NUM_CLASSES = 527
    # PANNs Cnn14_DecisionLevelMax emits framewise output at 100 Hz:
    # hop_size=320 / sample_rate=32000 = 0.01 s. Measured empirically
    # from the integration test (e.g. an 8.05 s clip produces 805
    # framewise rows). Earlier doc/comment that said "~32 ms" referred
    # to a different upstream PANNs variant (Cnn14 standard, not the
    # DecisionLevelMax we use); using the wrong constant here causes
    # post_process()'s time bounds to be off by 3.2x and min_interval_ms
    # filters to fire on the wrong durations.
    PANNS_FRAME_DURATION_SECONDS = 0.01

    def __init__(
        self,
        checkpoint_path: Path,
        device: str = "cuda",
    ) -> None:
        if not Path(checkpoint_path).exists():
            raise FileNotFoundError(
                f"PANNs SED checkpoint missing at {checkpoint_path}. "
                "Run 'make download-models' first."
            )

        # Stage the AudioSet labels at $ORPHEUS_DATA_ROOT/panns_data/
        # and temporarily point HOME at $ORPHEUS_DATA_ROOT so the
        # ``panns_inference`` import finds them there — see
        # ``_stage_panns_labels_and_pin_home`` for the full rationale.
        #
        # The stage/import/restore sequence is wrapped in
        # _PANNS_STAGE_LOCK to serialise it against any concurrent
        # PANNsCnn14SED() constructor. Without the lock, two
        # constructors can interleave their read-HOME / set-staged /
        # restore-HOME windows and one thread permanently strands HOME
        # at the staged value for the rest of the process.
        with _PANNS_STAGE_LOCK:
            # Guard: if panns_inference was already imported by ANYTHING
            # earlier in the process, the HOME-pin is silently a no-op
            # (its config evaluates Path.home() at import time, once).
            # Refuse loudly so ops sees the issue immediately.
            _assert_panns_not_already_imported()
            _data_root, _original_home = _stage_panns_labels_and_pin_home()
            try:
                # Lazy import — keeps unit tests free of torch / panns_inference.
                from panns_inference import SoundEventDetection  # noqa: PLC0415

                self._sed = SoundEventDetection(
                    checkpoint_path=str(checkpoint_path),
                    device=device,
                )
            finally:
                # Even if the import or SoundEventDetection ctor fails,
                # don't leave the process with a corrupted $HOME.
                _restore_home(_original_home)
        self._device = device

    @property
    def sample_rate(self) -> int:
        return self.PANNS_SAMPLE_RATE

    @property
    def num_classes(self) -> int:
        return self.PANNS_NUM_CLASSES

    @property
    def frame_duration_seconds(self) -> float:
        return self.PANNS_FRAME_DURATION_SECONDS

    def predict(self, audio_mono: np.ndarray) -> np.ndarray:
        # panns_inference expects shape (batch, samples); we always pass batch=1.
        if audio_mono.ndim != 1:
            raise ValueError(
                f"audio_mono must be 1-D; got shape {audio_mono.shape}"
            )
        batched = audio_mono.astype(np.float32, copy=False)[np.newaxis, :]
        framewise_output = self._sed.inference(batched)  # (1, T, 527)
        return np.asarray(framewise_output)[0]


def build_model(
    *,
    variant: str,
    checkpoint_path: Path | None = None,
    device: str = "cuda",
) -> SEDModel:
    """Factory for SEDModel instances by config variant string.

    Args:
        variant: ``"cnn14_sed"`` for production PANNs Cnn14, ``"fake"`` for
            the deterministic test fake.
        checkpoint_path: Required for non-fake variants.
        device: ``"cuda"`` or ``"cpu"`` (PANNs only).

    Returns:
        An ``SEDModel`` instance.

    Raises:
        ValueError: For an unknown variant.
        FileNotFoundError: If ``variant`` requires a checkpoint and it's missing.
    """
    if variant == "fake":
        return DeterministicFakeSED()
    if variant == "cnn14_sed":
        if checkpoint_path is None:
            raise ValueError("cnn14_sed requires a checkpoint_path")
        return PANNsCnn14SED(checkpoint_path=checkpoint_path, device=device)
    raise ValueError(f"Unknown model variant: {variant!r}")
