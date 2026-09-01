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


# Labels in the BirdNET v2.4 set that are not bird species. These get suppressed
# before geographic filtering so the suppression log is legible and so we don't
# accidentally surface them via Open World mode. Match is on the human-readable
# common name (the part after the underscore in each label). Conservative
# starter set — expand based on operator observation of suppressed-log noise.
#
# NOTE: This set is BirdNET v2.4 specific. On any model upgrade, re-verify the
# label set: new versions may add/rename non-bird categories.
NON_BIRD_LABELS_COMMON: frozenset[str] = frozenset(
    {
        "Dog",
        "Eastern Chipmunk",  # Tamias striatus — real animal, not a bird; chipmunk
                             # "chuck" call repeatedly soft-admits at avgC=0.93
        "Engine",
        "Fireworks",
        "Gun",
        "Human non-vocal",
        "Human vocal",
        "Human whistle",
        "Noise",
        "Power tools",
        "Siren",
    }
)


class BirdNETModel:
    """
    BirdNET ONNX model wrapper for bird species identification.

    The model expects audio input at 48kHz sample rate in 3-second windows.
    """

    def __init__(
        self,
        model_path: str | Path,
        geo_filter_min_prob: float = 0.03,
        geo_filter_weak_admit_prob: float = 0.0005,
        geo_filter_weak_admit_conf: float = 0.85,
        site_species_whitelist: Optional[list[str]] = None,
    ) -> None:
        """
        Initialize BirdNET model.

        Args:
            model_path: Path to ONNX model file
            geo_filter_min_prob: Primary geographic-probability threshold. Species
                whose meta-model probability at the configured site meets or exceeds
                this are admitted regardless of acoustic confidence (beyond the
                detection threshold). Default 0.03 matches upstream BirdNET-Analyzer.
            geo_filter_weak_admit_prob: Soft-admit lower bound on geo probability.
                Species with geo probability between this and the primary threshold
                are admitted only if their acoustic confidence is very high (see
                next parameter). This is what unlocks locally-confirmed-but-globally-
                patchy species (e.g. Eastern Whip-poor-will) without re-admitting
                geographically implausible species at low acoustic confidence.
            geo_filter_weak_admit_conf: Acoustic-confidence floor required for
                soft-admit. Detections in the weak-admit geo band must clear this
                acoustic confidence to be admitted.
            site_species_whitelist: Optional list of scientific names or full
                BirdNET labels for species the operator has personally confirmed
                at this site. These bypass the geographic filter entirely (still
                subject to confidence threshold and non-bird suppression).
                Resolved to label indices at init time; entries that don't match
                a label are logged as warnings.
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

        # Geo filter tuning (used in _apply_geo_filter)
        self.geo_filter_min_prob = geo_filter_min_prob
        self.geo_filter_weak_admit_prob = geo_filter_weak_admit_prob
        self.geo_filter_weak_admit_conf = geo_filter_weak_admit_conf

        # Resolve site whitelist (scientific names / labels) to label indices
        self._whitelist_indices: set[int] = self._resolve_whitelist(site_species_whitelist)

        # Initialize geographic filter (optional)
        self.geo_filter = self._init_geo_filter()

    def _resolve_whitelist(self, whitelist: Optional[list[str]]) -> set[int]:
        """Resolve operator-supplied scientific names / labels to label indices.

        Accepts either full BirdNET labels (``"Antrostomus vociferus_Eastern
        Whip-poor-will"``) or just the scientific name (``"Antrostomus
        vociferus"``). Matches case-sensitively against ``self.labels``. Logs a
        warning for any entry that doesn't resolve.

        NOTE: Label indices are BirdNET-model-version specific. On any model
        upgrade, re-verify that whitelist entries still resolve (this method
        will log warnings for any that don't; check journal after restart).
        """
        if not whitelist:
            return set()

        resolved: set[int] = set()
        unresolved: list[str] = []
        for entry in whitelist:
            entry_stripped = entry.strip()
            if not entry_stripped:
                continue
            matched = False
            for idx, label in enumerate(self.labels):
                # Try full-label match first, then scientific-name (prefix before "_")
                if label == entry_stripped:
                    resolved.add(idx)
                    matched = True
                    break
                if "_" in label and label.split("_", maxsplit=1)[0] == entry_stripped:
                    resolved.add(idx)
                    matched = True
                    break
            if not matched:
                unresolved.append(entry_stripped)

        if unresolved:
            logger.warning(
                "Some site whitelist entries did not match any BirdNET label",
                unresolved=unresolved,
                resolved_count=len(resolved),
            )
        if resolved:
            logger.info("Site species whitelist resolved", resolved_count=len(resolved))
        return resolved

    def _load_labels(self) -> list[str]:
        """
        Load species label mapping (next to the model file).

        Prefers ``labels.json`` when it's valid JSON (list, or dict of
        index->label). Falls back to a newline-delimited text label set
        (``labels.txt`` / the canonical ``BirdNET_GLOBAL_*_Labels.txt``, one
        ``Scientific_Common`` per line) — the form the BirdNET label set actually
        ships in, and what the model artifacts here contain.
        """
        base = self.model_path.parent

        json_path = base / "labels.json"
        if json_path.exists():
            try:
                with json_path.open() as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return list(data.values()) if "0" in data else list(data.keys())
            except json.JSONDecodeError:
                pass  # not actually JSON (a mislabeled .txt) — fall through to text
            except Exception as e:
                logger.warning("Error loading labels.json", labels_path=json_path, error=str(e))

        for name in ("labels.txt", "BirdNET_GLOBAL_6K_V2.4_Labels.txt"):
            txt_path = base / name
            if txt_path.exists():
                lines = [ln.strip() for ln in txt_path.read_text().splitlines() if ln.strip()]
                if lines:
                    return lines

        logger.warning("No labels file found, using indices", labels_path=base)
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

            # BirdNET is a multi-label classifier (each species has an independent
            # sigmoid head), not a multi-class one. Softmax across ~6500 species
            # would force one dominant species to absorb the probability mass and
            # push co-occurring rarer species (e.g. Eastern Whip-poor-will under a
            # louder Barn Owl/nightjar) below threshold. Use the same flat sigmoid
            # as upstream BirdNET-Analyzer (clip range matches its implementation).
            predictions = 1.0 / (1.0 + np.exp(-np.clip(logits, -15.0, 15.0)))

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

        # Suppress non-bird labels (Dog, Engine, Human voice, etc.) before geo
        # filtering, so the suppression log is legible by reason.
        merged = self._filter_non_bird_labels(merged)

        # Apply geographic filter (with site whitelist + soft-admit rule)
        merged = self._apply_geo_filter(merged, lat, lon, date)

        # Remove temporary _label_idx from results
        for det in merged:
            det.pop("_label_idx", None)

        return merged

    def _filter_non_bird_labels(
        self, detections: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Drop detections whose common name is in the non-bird label set.

        Separated from the geographic filter so the suppression reason is
        unambiguous in logs (and so non-bird suppression keeps working in Open
        World mode where the geo filter is disabled).
        """
        if not NON_BIRD_LABELS_COMMON:
            return detections

        filtered: list[dict[str, Any]] = []
        for det in detections:
            if det.get("species_common") in NON_BIRD_LABELS_COMMON:
                logger.info(
                    "Suppressed %s (%.2f) — non-bird label",
                    det.get("species_common", det.get("species_code", "?")),
                    det.get("confidence", 0.0),
                )
                continue
            filtered.append(det)
        return filtered

    def _apply_geo_filter(
        self,
        detections: list[dict[str, Any]],
        lat: Optional[float],
        lon: Optional[float],
        date: Optional[datetime],
    ) -> list[dict[str, Any]]:
        """Apply geographic filtering with site whitelist + soft-admit rule.

        Admit rule for each detection (first match wins):
          1. Detection's label idx is in the operator-supplied site whitelist → admit
          2. Geo probability ≥ ``geo_filter_min_prob`` → admit (standard)
          3. Geo probability ≥ ``geo_filter_weak_admit_prob`` AND acoustic
             confidence ≥ ``geo_filter_weak_admit_conf`` → admit (soft rule)
          4. Otherwise → suppress (logged with reason)

        The soft-admit rule (step 3) is what unlocks locally-confirmed-but-
        globally-rare species whose meta-model probability falls below the
        primary threshold despite being present. Without it, a binary
        ``min_prob`` cut silently suppresses such species (e.g. Eastern
        Whip-poor-will at a site where it calls nightly).

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
            probabilities = self.geo_filter.predict_probabilities(lat, lon, date)
        except GeoFilterError as e:
            # Known geo-filter failure — soft-fail to allow-all so a
            # geo-meta hiccup doesn't take detection offline.
            logger.warning(
                "Geographic filter raised GeoFilterError; defaulting to allow-all",
                error=str(e),
            )
            return detections
        except Exception as e:
            # Unknown failure (corrupted TFLite, OOM, unexpected
            # NumPy/TF error). Still soft-fail but surface the actual
            # exception type so ops can diagnose.
            logger.exception(
                "Geographic filter raised unexpected exception; defaulting to allow-all",
                error_type=type(e).__name__,
                error=str(e),
            )
            return detections

        # None means Open World mode (no lat/lon provided)
        if probabilities is None:
            return detections

        filtered: list[dict[str, Any]] = []
        for det in detections:
            label_idx = det.get("_label_idx")
            if label_idx is None:
                # No idx — pass through (shouldn't happen post-predict, but be safe)
                filtered.append(det)
                continue

            if label_idx in self._whitelist_indices:
                filtered.append(det)
                continue

            # Out-of-bounds idx would mean labels/meta-model mismatch — pass
            # through rather than silently drop, and log so we notice on upgrade.
            if label_idx >= len(probabilities):
                logger.warning(
                    "Geo-meta-model output shape smaller than label index; "
                    "passing through without geographic gating",
                    label_idx=label_idx,
                    meta_shape=int(probabilities.shape[0]),
                )
                filtered.append(det)
                continue

            geo_prob = float(probabilities[label_idx])
            acoustic_conf = float(det.get("confidence", 0.0))

            if geo_prob >= self.geo_filter_min_prob:
                filtered.append(det)
                continue

            # Log lines below use species_scientific (unique per BirdNET label)
            # rather than species_code (collision-prone). Common name appended in
            # parens for human readability. Grep on scientific name is safe;
            # grepping on species_code would falsely match congeneric species.
            scientific = det.get("species_scientific", "?")
            common = det.get("species_common", "?")

            if (
                geo_prob >= self.geo_filter_weak_admit_prob
                and acoustic_conf >= self.geo_filter_weak_admit_conf
            ):
                logger.info(
                    "Soft-admitted %s (%s) via weak-admit rule — acoustic=%.2f geo=%.4f",
                    scientific,
                    common,
                    acoustic_conf,
                    geo_prob,
                )
                filtered.append(det)
                continue

            logger.info(
                "Suppressed %s (%s) due to geographic filter — acoustic=%.2f geo=%.5f",
                scientific,
                common,
                acoustic_conf,
                geo_prob,
            )

        return filtered

    def _parse_species_code(self, label: str) -> str:
        """
        Parse species code from label.

        BirdNET labels are typically in format: "Scientific Name_Common Name"
        We use the first 6 chars of scientific name as species code.

        WARNING: This scheme collides heavily — against the BirdNET v2.4 label
        set (6,522 entries) it collapses to ~1,800 unique codes, so 87% of
        species share a code with at least one other. Examples: ``antros``
        covers 10 Antrostomus nightjars, ``corvus`` covers 32 crow/raven
        species, ``poecil`` covers 24 chickadees + Old-World tits. **Do not
        use species_code as a primary key for downstream joins** — use
        ``species_scientific`` (which is unique per label) or the composite
        ``(species_code, species_scientific)``. The audit of code-only joins
        across the repo is tracked separately; for now the code field remains
        for human readability and backward compatibility with existing rows.

        On any BirdNET model upgrade, the label set may change — re-verify
        downstream tools' assumptions about what codes exist.
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
        Merge overlapping detections of the same species across sliding windows.

        For each species, returns one detection dict whose ``confidence`` and
        top-level ``start_time``/``end_time`` come from the highest-confidence
        window, plus a ``windows`` list containing all windows where that
        species cleared threshold (each with its own ``start_time``,
        ``end_time``, and ``confidence``). The per-window data feeds the
        ``intervals`` field on the emitted Detection per ADR 0011.

        Dedup key is the BirdNET label index (``_label_idx``) — unique by
        construction. Using ``species_code`` here would be a multi-label
        *anti-pattern*: the 6-char code collapses many distinct species into
        the same key (e.g. American Crow and Common Raven both →
        ``"corvus"``), so a clip with both species across different windows
        would silently lose the lower-confidence one.
        """
        if not detections:
            return []

        species_map: dict[int, dict[str, Any]] = {}
        for det in detections:
            key = det["_label_idx"]
            window_entry = {
                "start_time": det.get("start_time", 0.0),
                "end_time": det.get("end_time", 0.0),
                "confidence": det["confidence"],
            }
            existing = species_map.get(key)
            if existing is None:
                merged = dict(det)
                merged["windows"] = [window_entry]
                species_map[key] = merged
                continue
            # Existing entry — append the window and refresh top-level
            # confidence/start/end if this window is the new best.
            existing["windows"].append(window_entry)
            if det["confidence"] > existing["confidence"]:
                existing["confidence"] = det["confidence"]
                existing["start_time"] = det.get("start_time", existing.get("start_time", 0.0))
                existing["end_time"] = det.get("end_time", existing.get("end_time", 0.0))

        # Sort each species' windows by start_time so the emitted intervals
        # are in chronological order — easier for the UI to render.
        for entry in species_map.values():
            entry["windows"].sort(key=lambda w: w["start_time"])

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
