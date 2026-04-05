"""Geographic filtering for BirdNET using seasonal occurrence data.

This module provides geographic filtering for bird species detection using the
BirdNET Meta Model (TFLite). The model uses a custom 48-week calendar system
and location coordinates to predict which species are likely to occur at a
given location and time of year.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
import tensorflow as tf
from orpheus_common.logging import get_logger

logger = get_logger(__name__)


class GeoFilterError(Exception):
    """Exception raised for geographic filter errors."""


def get_week_48(date: datetime) -> int:
    """Convert a date to BirdNET's 48-week calendar index (1-48).

    BirdNET uses a custom 48-week calendar that differs from ISO 8601:
    - Each month has exactly 4 weeks (Weeks 1-48 total for the year)
    - Week numbering: Week N = (Month - 1) * 4 + WeekInMonth
    - WeekInMonth is calculated as: min(floor((Day - 1) / 7) + 1, 4)
    - This ensures days 29-31 of any month map to Week 4 of that month

    Args:
        date: The date to convert.

    Returns:
        Week index (1-48) for BirdNET's seasonal model.

    Examples:
        >>> get_week_48(datetime(2024, 1, 1))   # Jan 1 -> Week 1
        1
        >>> get_week_48(datetime(2024, 1, 8))   # Jan 8 -> Week 2
        2
        >>> get_week_48(datetime(2024, 1, 29))  # Jan 29 -> Week 4 (edge case)
        4
        >>> get_week_48(datetime(2024, 2, 1))   # Feb 1 -> Week 5
        5
        >>> get_week_48(datetime(2024, 12, 31)) # Dec 31 -> Week 48
        48
    """
    month = date.month
    day = date.day

    # Calculate week within month (1-4, with days 29-31 clamped to week 4)
    week_in_month = min(((day - 1) // 7) + 1, 4)

    # Calculate overall week index (1-48)
    return (month - 1) * 4 + week_in_month


class GeographicFilter:
    """Geographic filter using BirdNET Meta Model for seasonal species prediction.

    This class loads the BirdNET Meta Model (TFLite) and uses it to predict
    which bird species are likely to occur at a given location and time based
    on geographic coordinates and week of year.
    """

    def __init__(self, model_path: Optional[str] = None):
        """Initialize the geographic filter.

        Args:
            model_path: Path to birdnet_meta.tflite model. If None, uses
                       $ORPHEUS_DATA_ROOT/models/birdnet_meta.tflite or
                       /data/orpheus/models/birdnet_meta.tflite as fallback.

        Raises:
            FileNotFoundError: If model file doesn't exist.
            GeoFilterError: If TFLite model fails to load.
        """
        # Determine model path
        if model_path is None:
            data_root = os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus")
            model_path = f"{data_root}/models/birdnet_meta.tflite"

        self.model_path = Path(model_path)

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"BirdNET Meta Model not found: {self.model_path}. "
                "Run 'make download-models' to fetch required models."
            )

        # Load TFLite model
        try:
            self.interpreter = tf.lite.Interpreter(model_path=str(self.model_path))
            self.interpreter.allocate_tensors()

            # Get input and output details
            self.input_details = self.interpreter.get_input_details()
            self.output_details = self.interpreter.get_output_details()

            logger.info(
                "Geographic filter initialized",
                model_path=str(self.model_path),
                input_shape=self.input_details[0]["shape"],
                output_shape=self.output_details[0]["shape"],
            )
        except Exception as e:
            raise GeoFilterError(f"Failed to load TFLite model: {e}") from e

    def predict_species(
        self,
        lat: Optional[float],
        lon: Optional[float],
        date: datetime,
        min_prob: float = 0.03,
    ) -> Optional[List[str]]:
        """Predict species codes that are likely to occur at the given location and time.

        Args:
            lat: Latitude in decimal degrees. If None, returns None (Open World mode).
            lon: Longitude in decimal degrees. If None, returns None (Open World mode).
            date: Date for seasonal filtering.
            min_prob: Minimum probability threshold (0.0-1.0) for including a species.

        Returns:
            List of species codes (e.g., ['amecro', 'blujay']) that exceed min_prob,
            or None if lat/lon is None (signals "Open World" mode - no filtering).

        Note:
            Current implementation returns numeric indices as strings. The mapping from
            model output indices to species codes should be handled by the caller using
            the labels.json file.

        Raises:
            GeoFilterError: If TFLite inference fails.
        """
        # Handle Open World mode (no geographic filtering)
        if lat is None or lon is None:
            logger.debug(
                "Geographic filtering disabled (Open World mode)",
                lat=lat,
                lon=lon,
            )
            return None

        # Convert date to week index
        week_index = get_week_48(date)

        # Prepare input tensor: [lat, lon, week_index]
        # Note: BirdNET meta model expects week index as 0-47, so subtract 1
        input_data = np.array([[lat, lon, week_index - 1]], dtype=np.float32)

        try:
            # Run inference
            self.interpreter.set_tensor(self.input_details[0]["index"], input_data)
            self.interpreter.invoke()

            # Get output probabilities
            output_data = self.interpreter.get_tensor(self.output_details[0]["index"])
            probabilities = output_data[0]  # Shape: [num_species]

            # Filter species by threshold and return indices
            # Note: The output indices correspond to species in labels.json
            # Caller should map these indices to actual species codes
            species_indices = np.where(probabilities >= min_prob)[0]
            species_codes = [str(idx) for idx in species_indices]

            logger.debug(
                "Geographic filter prediction",
                lat=lat,
                lon=lon,
                week=week_index,
                num_species=len(species_codes),
                min_prob=min_prob,
            )

            return species_codes
        except Exception as e:
            raise GeoFilterError(f"TFLite inference failed: {e}") from e
