"""Tests for BirdNET model wrapper."""

from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

import numpy as np
import pytest

from orpheus_agent_bird_detection.birdnet import BirdNETModel


class TestBirdNETModel:
    """Tests for BirdNETModel."""

    @pytest.fixture
    def mock_onnx_session(self) -> Mock:
        """Create mock ONNX session."""
        session = Mock()
        session.get_inputs.return_value = [Mock(name="input")]
        session.get_outputs.return_value = [Mock(name="output")]
        return session

    @pytest.fixture(autouse=True)
    def patch_logger(self):
        """Patch structlog logger to accept arbitrary kwargs."""

        def fake_log_method(*args, **kwargs):
            pass

        class FakeLogger:
            def debug(self, *args, **kwargs):
                fake_log_method(*args, **kwargs)

            def info(self, *args, **kwargs):
                fake_log_method(*args, **kwargs)

            def warning(self, *args, **kwargs):
                fake_log_method(*args, **kwargs)

            def error(self, *args, **kwargs):
                fake_log_method(*args, **kwargs)

            def exception(self, *args, **kwargs):
                fake_log_method(*args, **kwargs)

        with patch("orpheus_common.logging.get_logger", return_value=FakeLogger()):
            yield

    @pytest.fixture(autouse=True)
    def patch_logger_and_labels(self):
        """Patch structlog logger and Path.open for labels.json."""

        def fake_log_method(*args, **kwargs):
            pass

        class FakeLogger:
            def debug(self, *args, **kwargs):
                fake_log_method(*args, **kwargs)

            def info(self, *args, **kwargs):
                fake_log_method(*args, **kwargs)

            def warning(self, *args, **kwargs):
                fake_log_method(*args, **kwargs)

            def error(self, *args, **kwargs):
                fake_log_method(*args, **kwargs)

            def exception(self, *args, **kwargs):
                fake_log_method(*args, **kwargs)

        # Patch logger
        logger_patch = patch("orpheus_common.logging.get_logger", return_value=FakeLogger())
        # Patch Path.open to return a dummy labels.json
        labels_json = '["Corvus brachyrhynchos_American Crow", "Corvus corax_Common Raven"]'
        open_patch = patch("pathlib.Path.open", mock_open(read_data=labels_json))

        with logger_patch, open_patch:
            yield

    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_model_init(
        self, mock_exists: Mock, mock_session_class: Mock, mock_onnx_session: Mock
    ) -> None:
        """Should initialize model successfully."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session

        model = BirdNETModel("/fake/model.onnx")

        assert model.model_path == Path("/fake/model.onnx")
        assert model.session == mock_onnx_session
        mock_session_class.assert_called_once_with("/fake/model.onnx")

    @patch("pathlib.Path.exists")
    def test_model_init_file_not_found(self, mock_exists: Mock) -> None:
        """Should raise FileNotFoundError if model file doesn't exist."""
        mock_exists.return_value = False

        with pytest.raises(FileNotFoundError, match="Model file not found"):
            BirdNETModel("/fake/model.onnx")

    def test_parse_species_code(self) -> None:
        """Should parse species code from label."""
        # Create a minimal model instance for testing helper methods
        with (
            patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            model = BirdNETModel("/fake/model.onnx")

        # Test with BirdNET format label
        assert model._parse_species_code("Corvus brachyrhynchos_American Crow") == "corvus"

        # Test with simple label
        assert model._parse_species_code("simple") == "simple"

    def test_parse_scientific_name(self) -> None:
        """Should parse scientific name from label."""
        with (
            patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            model = BirdNETModel("/fake/model.onnx")

        assert (
            model._parse_scientific_name("Corvus brachyrhynchos_American Crow")
            == "Corvus brachyrhynchos"
        )
        assert model._parse_scientific_name("simple") == "simple"

    def test_parse_common_name(self) -> None:
        """Should parse common name from label."""
        with (
            patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            model = BirdNETModel("/fake/model.onnx")

        assert model._parse_common_name("Corvus brachyrhynchos_American Crow") == "American Crow"
        assert model._parse_common_name("simple") == "simple"

    def test_merge_detections(self) -> None:
        """Should merge overlapping detections of same species."""
        with (
            patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            model = BirdNETModel("/fake/model.onnx")

        detections = [
            {
                "species_code": "amecro",
                "species_common": "American Crow",
                "confidence": 0.7,
            },
            {
                "species_code": "amecro",
                "species_common": "American Crow",
                "confidence": 0.9,  # Higher confidence
            },
            {
                "species_code": "comrav",
                "species_common": "Common Raven",
                "confidence": 0.6,
            },
        ]

        merged = model._merge_detections(detections)

        assert len(merged) == 2
        # Should keep highest confidence detection for amecro
        amecro_det = next(d for d in merged if d["species_code"] == "amecro")
        assert amecro_det["confidence"] == 0.9

    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_predict_invalid_sample_rate(
        self, mock_exists: Mock, mock_session_class: Mock, mock_onnx_session: Mock
    ) -> None:
        """Should raise error for invalid sample rate."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session

        model = BirdNETModel("/fake/model.onnx")
        audio = np.random.randn(44100)  # 1 second at 44.1kHz

        with pytest.raises(ValueError, match="BirdNET requires 48kHz"):
            model.predict(audio, sample_rate=44100)

    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_predict_with_detections(
        self, mock_exists: Mock, mock_session_class: Mock, mock_onnx_session: Mock
    ) -> None:
        """Should return detections above threshold."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session

        # Mock model output - array of probabilities
        predictions = np.zeros(100)
        predictions[0] = 10.0  # High logit for first species (softmax ~1.0)
        predictions[1] = 1.0  # Lower logit for second species
        mock_onnx_session.run.return_value = [[predictions]]

        model = BirdNETModel("/fake/model.onnx")
        model.labels = [
            "Corvus brachyrhynchos_American Crow",
            "Corvus corax_Common Raven",
        ] + ["species_" + str(i) for i in range(2, 100)]

        audio = np.random.randn(144000)  # 3 seconds at 48kHz
        detections = model.predict(audio, sample_rate=48000, min_confidence=0.5)

        assert len(detections) >= 1
        # Should have detection for American Crow
        crow_det = next((d for d in detections if d["species_code"] == "corvus"), None)
        assert crow_det is not None
        assert crow_det["confidence"] >= 0.5

    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_init_geo_filter_not_found(
        self, mock_exists: Mock, mock_session_class: Mock, mock_onnx_session: Mock
    ) -> None:
        """Should set geo_filter to None when meta model not found."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session

        model = BirdNETModel("/fake/model.onnx")

        # geo_filter should be None since birdnet_meta.tflite doesn't exist
        assert model.geo_filter is None

    @patch("orpheus_agent_bird_detection.birdnet.GeographicFilter")
    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_init_geo_filter_success(
        self,
        mock_exists: Mock,
        mock_session_class: Mock,
        mock_geo_filter_class: Mock,
        mock_onnx_session: Mock,
    ) -> None:
        """Should initialize geo_filter when meta model exists."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session
        mock_geo_filter_instance = Mock()
        mock_geo_filter_class.return_value = mock_geo_filter_instance

        model = BirdNETModel("/fake/model.onnx")

        assert model.geo_filter is mock_geo_filter_instance
        mock_geo_filter_class.assert_called_once_with("/fake/birdnet_meta.tflite")

    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_apply_geo_filter_no_filter(
        self, mock_exists: Mock, mock_session_class: Mock, mock_onnx_session: Mock
    ) -> None:
        """Should pass all detections through when geo_filter is None."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session

        model = BirdNETModel("/fake/model.onnx")
        assert model.geo_filter is None

        detections = [
            {"species_code": "amecro", "confidence": 0.9, "_label_idx": 0},
            {"species_code": "comrav", "confidence": 0.7, "_label_idx": 1},
        ]

        result = model._apply_geo_filter(
            detections,
            lat=51.5,
            lon=-0.1,
            date=datetime(2024, 6, 15),
        )

        assert len(result) == 2

    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_apply_geo_filter_open_world(
        self, mock_exists: Mock, mock_session_class: Mock, mock_onnx_session: Mock
    ) -> None:
        """Should pass all detections through in Open World mode (None lat/lon)."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session

        model = BirdNETModel("/fake/model.onnx")
        model.geo_filter = Mock()
        model.geo_filter.predict_species.return_value = None

        detections = [
            {"species_code": "amecro", "confidence": 0.9, "_label_idx": 0},
        ]

        result = model._apply_geo_filter(
            detections,
            lat=None,
            lon=None,
            date=datetime(2024, 6, 15),
        )

        assert len(result) == 1

    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_apply_geo_filter_suppresses_species(
        self, mock_exists: Mock, mock_session_class: Mock, mock_onnx_session: Mock
    ) -> None:
        """Should suppress species not in geo-allowed list."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session

        model = BirdNETModel("/fake/model.onnx")
        model.geo_filter = Mock()
        # Only index "0" is allowed (American Crow)
        model.geo_filter.predict_species.return_value = ["0"]

        detections = [
            {
                "species_code": "amecro",
                "species_common": "American Crow",
                "confidence": 0.9,
                "_label_idx": 0,
            },
            {
                "species_code": "gymnor",
                "species_common": "Australian Magpie",
                "confidence": 0.8,
                "_label_idx": 42,
            },
        ]

        result = model._apply_geo_filter(detections, lat=51.5, lon=-0.1, date=datetime(2024, 6, 15))

        assert len(result) == 1
        assert result[0]["species_code"] == "amecro"

    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_apply_geo_filter_allows_all_present(
        self, mock_exists: Mock, mock_session_class: Mock, mock_onnx_session: Mock
    ) -> None:
        """Should keep all detections when all species are in geo-allowed list."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session

        model = BirdNETModel("/fake/model.onnx")
        model.geo_filter = Mock()
        model.geo_filter.predict_species.return_value = ["0", "1"]

        detections = [
            {"species_code": "amecro", "confidence": 0.9, "_label_idx": 0},
            {"species_code": "comrav", "confidence": 0.7, "_label_idx": 1},
        ]

        result = model._apply_geo_filter(detections, lat=51.5, lon=-0.1, date=datetime(2024, 6, 15))

        assert len(result) == 2

    @patch("orpheus_agent_bird_detection.birdnet.logger")
    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_apply_geo_filter_logs_suppressed(
        self,
        mock_exists: Mock,
        mock_session_class: Mock,
        mock_logger: Mock,
        mock_onnx_session: Mock,
    ) -> None:
        """Should log suppressed detections at INFO level."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session

        model = BirdNETModel("/fake/model.onnx")
        model.geo_filter = Mock()
        model.geo_filter.predict_species.return_value = ["0"]

        detections = [
            {
                "species_code": "amecro",
                "species_common": "American Crow",
                "confidence": 0.9,
                "_label_idx": 0,
            },
            {
                "species_code": "gymnor",
                "species_common": "Australian Magpie",
                "confidence": 0.85,
                "_label_idx": 42,
            },
        ]

        model._apply_geo_filter(
            detections,
            lat=51.5,
            lon=-0.1,
            date=datetime(2024, 6, 15),
        )

        # Should log the suppressed detection
        mock_logger.info.assert_called()
        call_args = mock_logger.info.call_args_list
        suppressed_calls = [c for c in call_args if "Suppressed" in str(c)]
        assert len(suppressed_calls) == 1
        assert "gymnor" in str(suppressed_calls[0])

    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_predict_removes_label_idx(
        self, mock_exists: Mock, mock_session_class: Mock, mock_onnx_session: Mock
    ) -> None:
        """Should not include _label_idx in final predict results."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session

        predictions = np.zeros(100)
        predictions[0] = 10.0
        mock_onnx_session.run.return_value = [[predictions]]

        model = BirdNETModel("/fake/model.onnx")
        model.labels = [
            "Corvus brachyrhynchos_American Crow",
        ] + ["species_" + str(i) for i in range(1, 100)]

        audio = np.random.randn(144000)
        detections = model.predict(audio, sample_rate=48000, min_confidence=0.5)

        for det in detections:
            assert "_label_idx" not in det

    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_predict_with_geo_filter(
        self, mock_exists: Mock, mock_session_class: Mock, mock_onnx_session: Mock
    ) -> None:
        """Should apply geo filter when lat/lon provided."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session

        # Two species detected by ONNX
        predictions = np.zeros(100)
        predictions[0] = 10.0  # High logit
        predictions[1] = 8.0  # Also high logit
        mock_onnx_session.run.return_value = [[predictions]]

        model = BirdNETModel("/fake/model.onnx")
        model.labels = [
            "Corvus brachyrhynchos_American Crow",
            "Gymnorhina tibicen_Australian Magpie",
        ] + ["species_" + str(i) for i in range(2, 100)]

        # Geo filter only allows index 0 (American Crow)
        model.geo_filter = Mock()
        model.geo_filter.predict_species.return_value = ["0"]

        audio = np.random.randn(144000)
        detections = model.predict(
            audio,
            sample_rate=48000,
            min_confidence=0.01,
            lat=51.5,
            lon=-0.1,
            date=datetime(2024, 6, 15),
        )

        # Only American Crow should remain
        species_codes = [d["species_code"] for d in detections]
        assert "corvus" in species_codes
        assert "gymnor" not in species_codes

        # Verify geo filter was called with correct params
        model.geo_filter.predict_species.assert_called_once_with(
            51.5, -0.1, datetime(2024, 6, 15), min_prob=0.03
        )

    @patch("orpheus_agent_bird_detection.birdnet.ort.InferenceSession")
    @patch("pathlib.Path.exists")
    def test_apply_geo_filter_fails_open(
        self, mock_exists: Mock, mock_session_class: Mock, mock_onnx_session: Mock
    ) -> None:
        """Should return all detections if geo filter raises an exception."""
        mock_exists.return_value = True
        mock_session_class.return_value = mock_onnx_session

        model = BirdNETModel("/fake/model.onnx")
        model.geo_filter = Mock()
        model.geo_filter.predict_species.side_effect = RuntimeError("TFLite corrupted")

        detections = [
            {"species_code": "amecro", "confidence": 0.9, "_label_idx": 0},
            {"species_code": "comrav", "confidence": 0.7, "_label_idx": 1},
        ]

        result = model._apply_geo_filter(
            detections,
            lat=51.5,
            lon=-0.1,
            date=datetime(2024, 6, 15),
        )

        # All detections should pass through on error
        assert len(result) == 2
