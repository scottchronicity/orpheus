"""Shared torch device-selection policy.

Every torch-using agent has to decide whether to run on GPU or CPU. The crow
detector already does it the survivable way (``cuda`` if available, else
``cpu``); audio-events hard-pinned ``cuda`` and crashed deep inside the model
constructor on any host without a working CUDA stack — a transient Jetson
driver/thermal fault, or the GPU-less ``db+storage+gui`` host from the
split-machine deployment idea. This lifts ONE policy both can share.

orpheus-common has no hard ``torch`` dependency, so the CUDA probe is
lazy-imported inside the function and injectable (``cuda_available``) — the
policy is fully unit-testable without torch installed.
"""

from __future__ import annotations

from typing import Callable, Optional

from orpheus_common.logging import get_logger

logger = get_logger(__name__)


def select_torch_device(
    requested: str = "auto",
    *,
    cuda_available: Optional[Callable[[], bool]] = None,
) -> str:
    """Resolve a requested device string to one that is actually usable.

    Args:
        requested: ``"auto"`` (or ``""``/``None``) → ``"cuda"`` if CUDA is
            available else ``"cpu"`` (survivable — never crashes on a GPU-less
            host). ``"cuda"`` → ``"cuda"`` if available, else ``RuntimeError``
            (fail-loud: the operator explicitly demanded a GPU). ``"cpu"`` →
            ``"cpu"``. Any other value (e.g. ``"cuda:1"``, ``"mps"``) is
            returned unchanged — the operator knows what they want.
        cuda_available: Override the CUDA probe (for tests). Defaults to a lazy
            ``torch.cuda.is_available`` import so orpheus-common stays
            torch-free.

    Returns:
        The resolved device string to hand to ``torch.device(...)``.

    Raises:
        RuntimeError: ``requested="cuda"`` but CUDA is unavailable.
    """
    normalized = (requested or "auto").strip().lower()

    if normalized not in ("auto", "cuda", "cpu"):
        # An explicit, more specific device (cuda:1, mps, ...). Trust the
        # operator — resolving these is their responsibility.
        return requested

    if normalized == "cpu":
        return "cpu"

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
