"""BirdNET ONNX model wrapper for bird species detection."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from orpheus_common.detection.species import CORVID_SPECIES  # noqa: F401
from orpheus_common.logging import get_logger

from .geo_filter import GeoFilterError, GeographicFilter

logger = get_logger(__name__)


class BirdNETModel:
    """
    BirdNET ONNX model wrapper for bird species identification.

    The model expects audio input at 48kHz sample rate in 3-second windows.
    """

    def __init__(self, model_path: str | Path) -> None:
        """
        Initialize BirdNET model.

        Args:
            model_path: Path to ONNX model file
        """
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            msg = f"Model file not found: {model_path}"
            raise FileNotFoundError(msg)

        logger.info("Loading BirdNET model", model_path=model_path)
        self.session = ort.InferenceSession(str(self.model_path))

        # Get model input/output metadata
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

        # Load species labels if available
        self.labels = self._load_labels()
        logger.info("BirdNET model loaded", species_count=len(self.labels))

        # Initialize geographic filter (optional)
        self.geo_filter = self._init_geo_filter()

    def _load_labels(self) -> list[str]:
        """
        Load species label mapping.

        Looks for labels.json next to the model file.
        """
        labels_path = self.model_path.parent / "labels.json"
        if labels_path.exists():
            try:
                with labels_path.open() as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict):
                        # Handle different label file formats
                        return list(data.values()) if "0" in data else list(data.keys())
            except Exception as e:
                logger.warning("Error loading labels", labels_path=labels_path, error=str(e))

        # Return empty list if no labels file found
        logger.warning("No labels file found, using indices", labels_path=labels_path)
        return []

    def _init_geo_filter(self) -> Optional[GeographicFilter]:
        """Initialize geographic filter from meta model adjacent to ONNX model.

        Returns:
            GeographicFilter instance, or None if not available.
        """
        meta_model_path = str(self.model_path.parent / "birdnet_meta.tflite")
        try:
            return GeographicFilter(meta_model_path)
        except (FileNotFoundError, GeoFilterError) as e:
            logger.warning(
                "Geographic filter not available, running in Open World mode",
                error=str(e),
            )
            return None

    def predict(
        self,
        audio: np.ndarray,
        sample_rate: int = 48000,
        min_confidence: float = 0.1,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        date: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Predict species from audio.

        Args:
            audio: Audio samples as numpy array.
            sample_rate: Sample rate in Hz (must be 48000).
            min_confidence: Minimum acoustic confidence threshold.
            lat: Latitude for geographic filtering. None disables filtering.
            lon: Longitude for geographic filtering. None disables filtering.
            date: Date for seasonal filtering. Defaults to now if not provided.
        """
        if sample_rate != 48000:
            msg = f"BirdNET requires 48kHz audio, got {sample_rate}Hz"
            raise ValueError(msg)

        # Prepare audio for model (3-second windows)
        window_samples = 3 * sample_rate
        detections = []
        stride_samples = int(1.5 * sample_rate)
        start = 0

        while start + window_samples <= len(audio):
            window = audio[start : start + window_samples]

            # Normalize audio
            if np.max(np.abs(window)) > 0:
                window = window / np.max(np.abs(window))

            # Reshape for model input [1, samples]
            input_data = window.astype(np.float32).reshape(1, -1)

            # Run inference
            outputs = self.session.run([self.output_name], {self.input_name: input_data})
            logits = outputs[0][0]  # [num_species]

            # APPLY SOFTMAX to convert logits to probabilities
            predictions = np.exp(logits) / np.sum(np.exp(logits))

            # Get top predictions above threshold
            for idx, confidence in enumerate(predictions):
                if confidence >= min_confidence:
                    # VALIDATE INDEX BOUNDS
                    if idx >= len(self.labels):
                        logger.warning(
                            "Model output index exceeds labels",
                            idx=idx,
                            num_labels=len(self.labels),
                        )
                        continue

                    species_code = self.labels[idx]

                    # SKIP INVALID LABELS
                    if species_code.startswith(("<", ">")):
                        logger.warning("Skipping invalid label", label=species_code, idx=idx)
                        continue

                    detection = {
                        "species_code": self._parse_species_code(species_code),
                        "species_scientific": self._parse_scientific_name(species_code),
                        "species_common": self._parse_common_name(species_code),
                        "confidence": float(confidence),
                        "start_time": start / sample_rate,
                        "end_time": (start + window_samples) / sample_rate,
                        "_label_idx": idx,
                    }
                    detections.append(detection)

            start += stride_samples

        merged = self._merge_detections(detections)

        # Apply geographic filter
        merged = self._apply_geo_filter(merged, lat, lon, date)

        # Remove temporary _label_idx from results
        for det in merged:
            det.pop("_label_idx", None)

        return merged

    def _apply_geo_filter(
        self,
        detections: list[dict[str, Any]],
        lat: Optional[float],
        lon: Optional[float],
        date: Optional[datetime],
    ) -> list[dict[str, Any]]:
        """Apply geographic filtering to suppress unlikely species.

        Args:
            detections: List of detection dicts (must contain '_label_idx').
            lat: Latitude for geographic filtering.
            lon: Longitude for geographic filtering.
            date: Date for seasonal filtering.

        Returns:
            Filtered list of detections.
        """
        if self.geo_filter is None:
            return detections

        if date is None:
            date = datetime.now(tz=timezone.utc)

        try:
            allowed = self.geo_filter.predict_species(lat, lon, date, min_prob=0.03)
        except (GeoFilterError, Exception):
            logger.warning("Geographic filter failed, defaulting to allow-all")
            return detections

        # None means Open World mode (no lat/lon provided)
        if allowed is None:
            return detections

        allowed_set = set(allowed)
        filtered = []
        for det in detections:
            if str(det.get("_label_idx", "")) in allowed_set:
                filtered.append(det)
            else:
                logger.info(
                    "Suppressed %s (%.2f) due to geographic filter",
                    det["species_code"],
                    det["confidence"],
                )

        return filtered

    def _parse_species_code(self, label: str) -> str:
        """
        Parse species code from label.

        BirdNET labels are typically in format: "Scientific Name_Common Name"
        We use the first 6 chars of scientific name as species code.
        """
        if "_" in label:
            scientific = label.split("_", maxsplit=1)[0].replace(" ", "")
            return scientific[:6].lower()
        return label[:6].lower()

    def _parse_scientific_name(self, label: str) -> str:
        """Parse scientific name from label."""
        if "_" in label:
            return label.split("_", maxsplit=1)[0]
        return label

    def _parse_common_name(self, label: str) -> str:
        """Parse common name from label."""
        if "_" in label:
            return label.split("_")[1]
        return label

    def _merge_detections(self, detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Merge overlapping detections of the same species.

        Keeps highest confidence detection for each species.
        """
        if not detections:
            return []

        # Group by species code
        species_map: dict[str, dict[str, Any]] = {}
        for det in detections:
            code = det["species_code"]
            if code not in species_map or det["confidence"] > species_map[code]["confidence"]:
                species_map[code] = det

        return list(species_map.values())


def download_model(output_dir: str | Path) -> Path:
    """
    Download BirdNET ONNX model from HuggingFace.

    Args:
        output_dir: Directory to save model files

    Returns:
        Path to downloaded model file
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading BirdNET model from HuggingFace...")

    model_file = hf_hub_download(
        repo_id="onnx-community/BirdNET",
        filename="model.onnx",
        cache_dir=str(output_path),
    )

    logger.info("Model downloaded", model_file=model_file)
    return Path(model_file)
