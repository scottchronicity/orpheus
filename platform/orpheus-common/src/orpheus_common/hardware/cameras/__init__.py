"""
Camera implementations for Orpheus.

Currently supports:
- Amcrest IP cameras (IP5M-B1186EW-AI-V3 and compatible models)

Additional camera types can be added by implementing the Camera base class.
"""

from orpheus_common.hardware.cameras.amcrest import AmcrestCamera

# Map of camera type strings to classes
CAMERA_TYPE_MAP = {
    "amcrest": AmcrestCamera,
}

__all__ = [
    "AmcrestCamera",
    "CAMERA_TYPE_MAP",
]
