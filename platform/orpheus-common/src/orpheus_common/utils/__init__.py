"""
Utility functions for Orpheus platform.

Provides common utilities for time, formatting, and other shared functionality.
"""

from orpheus_common.utils.buffer import PreRollRingBuffer
from orpheus_common.utils.time import (
    parse_iso_timestamp,
    timestamp_age_seconds,
    utc_now,
    utc_now_iso,
)
from orpheus_common.utils.torch_device import select_torch_device
from orpheus_common.utils.urls import redact_url_credentials

__all__ = [
    "PreRollRingBuffer",
    "utc_now",
    "utc_now_iso",
    "parse_iso_timestamp",
    "timestamp_age_seconds",
    "select_torch_device",
    "redact_url_credentials",
]
