"""
Hardware abstractions for Orpheus platform.

Provides standardized interfaces for:
- Cameras (Amcrest and future models)
- Audio interfaces (planned)
- Storage devices (T7 external drive)

All hardware access should go through these abstractions to enable
testing, mocking, and consistent error handling.
"""

from orpheus_common.hardware.base import Camera
from orpheus_common.hardware.cameras import CAMERA_TYPE_MAP, AmcrestCamera
from orpheus_common.hardware.registry import CameraRegistry
from orpheus_common.hardware.storage import get_storage_hardware_info

__all__ = [
    "Camera",
    "AmcrestCamera",
    "CAMERA_TYPE_MAP",
    "CameraRegistry",
    "get_storage_hardware_info",
]
