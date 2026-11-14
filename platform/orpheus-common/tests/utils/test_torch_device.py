"""Tests for the shared torch device-selection policy.

The CUDA probe is injectable, so the policy is fully exercised without torch
installed (orpheus-common takes no torch dependency).
"""

import pytest

from orpheus_common.utils import select_torch_device


class TestSelectTorchDevice:
    def test_auto_picks_cuda_when_available(self) -> None:
        assert select_torch_device("auto", cuda_available=lambda: True) == "cuda"

    def test_auto_falls_back_to_cpu_when_no_cuda(self) -> None:
        assert select_torch_device("auto", cuda_available=lambda: False) == "cpu"

    def test_default_argument_is_auto(self) -> None:
        assert select_torch_device(cuda_available=lambda: True) == "cuda"
        assert select_torch_device(cuda_available=lambda: False) == "cpu"

    def test_empty_and_none_treated_as_auto(self) -> None:
        assert select_torch_device("", cuda_available=lambda: False) == "cpu"
        assert select_torch_device(None, cuda_available=lambda: False) == "cpu"

    def test_explicit_cuda_returns_cuda_when_available(self) -> None:
        assert select_torch_device("cuda", cuda_available=lambda: True) == "cuda"

    def test_explicit_cuda_fails_loud_when_unavailable(self) -> None:
        # The operator explicitly demanded a GPU — surface it clearly instead of
        # crashing deep in the model constructor.
        with pytest.raises(RuntimeError, match="CUDA is not available"):
            select_torch_device("cuda", cuda_available=lambda: False)

    def test_explicit_cpu_never_consults_the_probe(self) -> None:
        def boom() -> bool:
            raise AssertionError("probe must not be called for an explicit cpu")

        assert select_torch_device("cpu", cuda_available=boom) == "cpu"

    def test_case_insensitive(self) -> None:
        assert select_torch_device("CUDA", cuda_available=lambda: True) == "cuda"
        assert select_torch_device("Auto", cuda_available=lambda: False) == "cpu"

    def test_specific_device_passed_through_unchanged(self) -> None:
        # Indexed CUDA names remain caller-owned; crow config does not expose them.
        assert select_torch_device("cuda:1", cuda_available=lambda: True) == "cuda:1"

    def test_explicit_mps_requires_availability(self) -> None:
        assert (
            select_torch_device("mps", mps_available=lambda: True)
            == "mps"
        )
        with pytest.raises(RuntimeError, match="MPS is not available"):
            select_torch_device("mps", mps_available=lambda: False)

    def test_auto_can_prefer_mps_only_when_caller_opts_in(self) -> None:
        assert (
            select_torch_device(
                "auto",
                cuda_available=lambda: False,
                mps_available=lambda: True,
                prefer_mps=True,
            )
            == "mps"
        )
        # Existing Torch users keep their CPU behavior unless they opt into MPS.
        assert (
            select_torch_device(
                "auto",
                cuda_available=lambda: False,
                mps_available=lambda: True,
            )
            == "cpu"
        )

    def test_default_lazy_probe_resolves_without_torch(self) -> None:
        # No injected probe → the lazy torch import runs. orpheus-common's venv
        # has no torch, so _cuda_is_available swallows the ImportError and the
        # call still resolves to a valid device string (never raises for auto).
        assert select_torch_device("auto") in ("cuda", "cpu")
