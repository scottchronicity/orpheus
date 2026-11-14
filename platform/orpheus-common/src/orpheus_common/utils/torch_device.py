"""Shared torch device-selection policy.

Every torch-using agent has to decide whether to run on GPU or CPU. This shared
selector supports CUDA and CPU by default; callers may opt into MPS for
platforms that support it. It accepts injectable probes so the policy can be
tested without an accelerator or torch installed.

orpheus-common has no hard ``torch`` dependency, so accelerator probes are
lazy-imported inside the function and injectable.
"""

from __future__ import annotations

from typing import Callable, Optional

from orpheus_common.logging import get_logger

logger = get_logger(__name__)


def select_torch_device(
    requested: str = "auto",
    *,
    cuda_available: Optional[Callable[[], bool]] = None,
    mps_available: Optional[Callable[[], bool]] = None,
    prefer_mps: bool = False,
) -> str:
    """Resolve a requested device string to one that is actually usable.

    Args:
        requested: ``"auto"`` (or ``""``/``None``) selects CUDA when available,
            else optionally MPS when ``prefer_mps`` is true and MPS is available,
            else CPU. Explicit ``"cuda"`` or ``"mps"`` fails if unavailable;
            ``"cpu"`` always selects CPU. Other strings are passed through for
            callers that intentionally support device-specific names.
        cuda_available: Override the CUDA probe (for tests). Defaults to a lazy
            ``torch.cuda.is_available`` import so orpheus-common stays
            torch-free.
        mps_available: Override the MPS probe (for tests).
        prefer_mps: Whether ``auto`` may select MPS after CUDA is unavailable.

    Returns:
        The resolved device string to hand to ``torch.device(...)``.

    Raises:
        RuntimeError: ``requested="cuda"`` but CUDA is unavailable.
    """
    normalized = (requested or "auto").strip().lower()

    if normalized not in ("auto", "cuda", "cpu", "mps"):
        # An explicit, more specific device (cuda:1, mps, ...). Trust the
        # operator — resolving these is their responsibility.
        return requested

    if normalized == "cpu":
        return "cpu"

    if normalized == "mps":
        mps_probe = mps_available if mps_available is not None else _mps_is_available
        if not mps_probe():
            raise RuntimeError(
                "device='mps' was requested but MPS is not available. "
                "Set device: auto to select an available accelerator or CPU, "
                "or device: cpu to run on CPU explicitly."
            )
        return "mps"

    probe = cuda_available if cuda_available is not None else _cuda_is_available
    has_cuda = probe()

    if normalized == "cuda":
        if not has_cuda:
            raise RuntimeError(
                "device='cuda' was requested but CUDA is not available. "
                "Set device: auto to fall back to CPU automatically, or "
                "device: cpu to run on CPU explicitly."
            )
        return "cuda"

    # normalized == "auto"
    if has_cuda:
        return "cuda"
    if prefer_mps:
        mps_probe = mps_available if mps_available is not None else _mps_is_available
        if mps_probe():
            return "mps"
    logger.warning(
        "CUDA not available; falling back to CPU (device=auto)",
        requested=requested,
    )
    return "cpu"


def _cuda_is_available() -> bool:
    """Lazy CUDA probe — imports torch only when actually called, so
    orpheus-common takes no torch dependency at import time. Returns False if
    torch isn't installed."""
    try:
        import torch  # noqa: PLC0415

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001 - no torch / broken CUDA stack → treat as CPU
        return False


def _mps_is_available() -> bool:
    """Lazy MPS probe; CPU-only installs need no Apple-specific dependency."""
    try:
        import torch  # noqa: PLC0415

        return bool(torch.backends.mps.is_available())
    except Exception:  # noqa: BLE001 - no MPS build/device → treat as unavailable
        return False
