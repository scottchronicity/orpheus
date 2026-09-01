"""Tests for geographic filter and week-48 conversion logic."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pytest

from orpheus_agent_bird_detection.geo_filter import (
    GeoFilterError,
    GeographicFilter,
    get_week_48,
)


class TestGetWeek48:
    """Tests for get_week_48 function."""

    def test_jan_1_week_1(self) -> None:
        """Jan 1 should map to Week 1."""
        assert get_week_48(datetime(2024, 1, 1)) == 1

    def test_jan_8_week_2(self) -> None:
        """Jan 8 should map to Week 2."""
        assert get_week_48(datetime(2024, 1, 8)) == 2

    def test_jan_29_week_4(self) -> None:
        """Jan 29 should map to Week 4 (edge case: 5th week clamps to 4)."""
        assert get_week_48(datetime(2024, 1, 29)) == 4

    def test_jan_31_week_4(self) -> None:
        """Jan 31 should also map to Week 4."""
        assert get_week_48(datetime(2024, 1, 31)) == 4

    def test_feb_1_week_5(self) -> None:
        """Feb 1 should map to Week 5."""
        assert get_week_48(datetime(2024, 2, 1)) == 5

    def test_dec_31_week_48(self) -> None:
        """Dec 31 should map to Week 48."""
        assert get_week_48(datetime(2024, 12, 31)) == 48

    def test_week_boundaries(self) -> None:
        """Test week boundaries within a month."""
        # Week 1: Days 1-7
        assert get_week_48(datetime(2024, 3, 1)) == 9  # March, Week 1
        assert get_week_48(datetime(2024, 3, 7)) == 9

        # Week 2: Days 8-14
        assert get_week_48(datetime(2024, 3, 8)) == 10
        assert get_week_48(datetime(2024, 3, 14)) == 10

        # Week 3: Days 15-21
        assert get_week_48(datetime(2024, 3, 15)) == 11
        assert get_week_48(datetime(2024, 3, 21)) == 11

        # Week 4: Days 22-31
        assert get_week_48(datetime(2024, 3, 22)) == 12
        assert get_week_48(datetime(2024, 3, 28)) == 12
        assert get_week_48(datetime(2024, 3, 29)) == 12
        assert get_week_48(datetime(2024, 3, 30)) == 12
        assert get_week_48(datetime(2024, 3, 31)) == 12

    def test_all_months(self) -> None:
        """Test first day of each month maps to correct week."""
        expected_weeks = [
            1,  # Jan
            5,  # Feb
            9,  # Mar
            13,  # Apr
            17,  # May
            21,  # Jun
            25,  # Jul
            29,  # Aug
            33,  # Sep
            37,  # Oct
            41,  # Nov
            45,  # Dec
        ]

        for month, expected_week in enumerate(expected_weeks, start=1):
            assert get_week_48(datetime(2024, month, 1)) == expected_week

    def test_february_edge_cases(self) -> None:
        """Test February edge cases (28/29 days)."""
        # Non-leap year
        assert get_week_48(datetime(2023, 2, 28)) == 8  # Week 4 of Feb

        # Leap year
        assert get_week_48(datetime(2024, 2, 29)) == 8  # Week 4 of Feb


class TestGeographicFilter:
    """Tests for GeographicFilter class."""

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

    @patch("pathlib.Path.exists")
    def test_model_not_found(self, mock_exists: Mock) -> None:
        """Should raise FileNotFoundError if model file doesn't exist."""
        mock_exists.return_value = False

        with pytest.raises(FileNotFoundError, match="BirdNET Meta Model not found"):
            GeographicFilter("/fake/model.tflite")

    @patch("orpheus_agent_bird_detection.geo_filter.tf.lite.Interpreter")
    @patch("pathlib.Path.exists")
    def test_model_init_success(self, mock_exists: Mock, mock_interpreter_class: Mock) -> None:
        """Should initialize model successfully."""
        mock_exists.return_value = True

        # Mock TFLite interpreter
        mock_interpreter = MagicMock()
        mock_interpreter.get_input_details.return_value = [{"shape": [1, 3], "index": 0}]
        mock_interpreter.get_output_details.return_value = [{"shape": [1, 6522], "index": 0}]
        mock_interpreter_class.return_value = mock_interpreter

        geo_filter = GeographicFilter("/fake/model.tflite")

        assert geo_filter.model_path == Path("/fake/model.tflite")
        assert geo_filter.interpreter == mock_interpreter
        mock_interpreter.allocate_tensors.assert_called_once()

    @patch("orpheus_agent_bird_detection.geo_filter.tf.lite.Interpreter")
    @patch("pathlib.Path.exists")
    def test_model_init_failure(self, mock_exists: Mock, mock_interpreter_class: Mock) -> None:
        """Should raise GeoFilterError if TFLite model fails to load."""
        mock_exists.return_value = True
        mock_interpreter_class.side_effect = Exception("TFLite error")

        with pytest.raises(GeoFilterError, match="Failed to load TFLite model"):
            GeographicFilter("/fake/model.tflite")

    @patch("orpheus_agent_bird_detection.geo_filter.tf.lite.Interpreter")
    @patch("pathlib.Path.exists")
    def test_predict_probabilities_open_world_none_lat(
        self, mock_exists: Mock, mock_interpreter_class: Mock
    ) -> None:
        """Should return None when lat is None (Open World mode)."""
        mock_exists.return_value = True
        mock_interpreter = MagicMock()
        mock_interpreter.get_input_details.return_value = [{"shape": [1, 3], "index": 0}]
        mock_interpreter.get_output_details.return_value = [{"shape": [1, 6522], "index": 0}]
        mock_interpreter_class.return_value = mock_interpreter

        geo_filter = GeographicFilter("/fake/model.tflite")
        result = geo_filter.predict_probabilities(None, -83.5, datetime(2024, 1, 15))

        assert result is None

    @patch("orpheus_agent_bird_detection.geo_filter.tf.lite.Interpreter")
    @patch("pathlib.Path.exists")
    def test_predict_probabilities_open_world_none_lon(
        self, mock_exists: Mock, mock_interpreter_class: Mock
    ) -> None:
        """Should return None when lon is None (Open World mode)."""
        mock_exists.return_value = True
        mock_interpreter = MagicMock()
        mock_interpreter.get_input_details.return_value = [{"shape": [1, 3], "index": 0}]
        mock_interpreter.get_output_details.return_value = [{"shape": [1, 6522], "index": 0}]
        mock_interpreter_class.return_value = mock_interpreter

        geo_filter = GeographicFilter("/fake/model.tflite")
        result = geo_filter.predict_probabilities(42.5, None, datetime(2024, 1, 15))

        assert result is None

    @patch("orpheus_agent_bird_detection.geo_filter.tf.lite.Interpreter")
    @patch("pathlib.Path.exists")
    def test_predict_probabilities_returns_full_vector(
        self, mock_exists: Mock, mock_interpreter_class: Mock
    ) -> None:
        """Should return the raw per-species probability vector (caller does gating)."""
        mock_exists.return_value = True

        # Mock TFLite interpreter
        mock_interpreter = MagicMock()
        mock_interpreter.get_input_details.return_value = [{"shape": [1, 3], "index": 0}]
        mock_interpreter.get_output_details.return_value = [{"shape": [1, 100], "index": 0}]

        # Mock output probabilities (100 species)
        probabilities = np.zeros(100, dtype=np.float32)
        probabilities[0] = 0.5
        probabilities[5] = 0.08
        probabilities[10] = 0.02
        mock_interpreter.get_tensor.return_value = np.array([probabilities])

        mock_interpreter_class.return_value = mock_interpreter

        geo_filter = GeographicFilter("/fake/model.tflite")

        # NYC, Jan 15
        result = geo_filter.predict_probabilities(
            lat=40.7128, lon=-74.0060, date=datetime(2024, 1, 15)
        )

        assert result is not None
        assert result.shape == (100,)
        # Raw probabilities preserved — no thresholding at this layer
        assert result[0] == pytest.approx(0.5)
        assert result[5] == pytest.approx(0.08)
        assert result[10] == pytest.approx(0.02)
        assert result[1] == 0.0

        # Verify correct input was passed to model
        calls = mock_interpreter.set_tensor.call_args_list
        assert len(calls) == 1
        input_tensor = calls[0][0][1]

        # Check input shape and values
        assert input_tensor.shape == (1, 3)
        assert input_tensor[0][0] == pytest.approx(40.7128)  # lat
        assert input_tensor[0][1] == pytest.approx(-74.0060)  # lon
        # Week 3 of January (Jan 15) -> 0-based index 2 (week_index - 1 = 3 - 1 = 2)
        assert input_tensor[0][2] == 2

    @patch("orpheus_agent_bird_detection.geo_filter.tf.lite.Interpreter")
    @patch("pathlib.Path.exists")
    def test_predict_probabilities_inference_error(
        self, mock_exists: Mock, mock_interpreter_class: Mock
    ) -> None:
        """Should raise GeoFilterError if TFLite inference fails."""
        mock_exists.return_value = True

        mock_interpreter = MagicMock()
        mock_interpreter.get_input_details.return_value = [{"shape": [1, 3], "index": 0}]
        mock_interpreter.get_output_details.return_value = [{"shape": [1, 100], "index": 0}]
        mock_interpreter.invoke.side_effect = Exception("Inference failed")
        mock_interpreter_class.return_value = mock_interpreter

        geo_filter = GeographicFilter("/fake/model.tflite")

        with pytest.raises(GeoFilterError, match="TFLite inference failed"):
            geo_filter.predict_probabilities(40.7128, -74.0060, datetime(2024, 1, 15))

    @patch("orpheus_agent_bird_detection.geo_filter.tf.lite.Interpreter")
    @patch("pathlib.Path.exists")
    @patch("orpheus_agent_bird_detection.geo_filter.os.environ.get")
    def test_default_model_path_with_env_var(
        self, mock_env_get: Mock, mock_exists: Mock, mock_interpreter_class: Mock
    ) -> None:
        """Should use ORPHEUS_DATA_ROOT env var for default model path."""
        mock_exists.return_value = True
        mock_env_get.return_value = "/custom/data/root"

        mock_interpreter = MagicMock()
        mock_interpreter.get_input_details.return_value = [{"shape": [1, 3], "index": 0}]
        mock_interpreter.get_output_details.return_value = [{"shape": [1, 6522], "index": 0}]
        mock_interpreter_class.return_value = mock_interpreter

        geo_filter = GeographicFilter()

        assert str(geo_filter.model_path) == "/custom/data/root/models/birdnet_meta.tflite"

    @patch("orpheus_agent_bird_detection.geo_filter.tf.lite.Interpreter")
    @patch("pathlib.Path.exists")
    @patch("orpheus_agent_bird_detection.geo_filter.os.environ.get")
    def test_default_model_path_without_env_var(
        self, mock_env_get: Mock, mock_exists: Mock, mock_interpreter_class: Mock
    ) -> None:
        """Should use default path when ORPHEUS_DATA_ROOT is not set."""
        mock_exists.return_value = True
        # Mock os.environ.get to return the default value when called with 2 args
        mock_env_get.side_effect = lambda key, default=None: (
            default if key == "ORPHEUS_DATA_ROOT" else None
        )

        mock_interpreter = MagicMock()
        mock_interpreter.get_input_details.return_value = [{"shape": [1, 3], "index": 0}]
        mock_interpreter.get_output_details.return_value = [{"shape": [1, 6522], "index": 0}]
        mock_interpreter_class.return_value = mock_interpreter

        geo_filter = GeographicFilter()

        assert str(geo_filter.model_path) == "/data/orpheus/models/birdnet_meta.tflite"
