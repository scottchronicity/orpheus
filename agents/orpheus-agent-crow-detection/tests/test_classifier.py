"""Tests for crow classifier."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

from orpheus_agent_crow_detection.classifier import CrowClassifier


class TestCrowClassifier:
    """Tests for CrowClassifier."""

    @patch("orpheus_agent_crow_detection.classifier.MultiTaskCrowNet")
    @patch("orpheus_agent_crow_detection.classifier.torch.load")
    @patch("orpheus_agent_crow_detection.classifier.Path.exists")
    def test_init_loads_model(
        self, mock_exists: MagicMock, mock_load: MagicMock, mock_net_cls: MagicMock
    ) -> None:
        """Test classifier initialization loads model."""
        mock_exists.return_value = True

        # Mock the state dict returned by torch.load
        mock_load.return_value = {"state_dict": {"some": "weights"}}

        # Mock the network instance
        mock_net_instance = MagicMock()
        mock_net_cls.return_value = mock_net_instance

        CrowClassifier("/path/to/model.pt")

        # Verify we checked for file existence
        mock_exists.assert_called_once()
        # Verify we loaded the file
        mock_load.assert_called_once()
        # Verify we initialized the specific architecture
        mock_net_cls.assert_called_once()
        # Verify we loaded weights into the model
        mock_net_instance.load_state_dict.assert_called()

    @patch("orpheus_agent_crow_detection.classifier.Path.exists")
    def test_init_raises_if_model_missing(self, mock_exists: MagicMock) -> None:
        """Test classifier initialization raises error if model missing."""
        mock_exists.return_value = False

        with pytest.raises(FileNotFoundError, match="Model not found at"):
            CrowClassifier("/path/to/missing.pt")

    @patch("orpheus_agent_crow_detection.classifier.MultiTaskCrowNet")
    @patch("orpheus_agent_crow_detection.classifier.torch.load")
    @patch("orpheus_agent_crow_detection.classifier.Path.exists")
    def test_classify_positive_detection(
        self,
        mock_exists: MagicMock,
        mock_load: MagicMock,  # noqa: ARG002
        mock_net_cls: MagicMock,
    ) -> None:
        """Test classification with positive crow detection."""
        mock_exists.return_value = True
        mock_net_instance = mock_net_cls.return_value

        # SETUP MOCK OUTPUTS (New Dictionary Format)
        # Quality: [Batch, 2]. Index 1 is "Crow".
        # [Low, High] -> High probability of Crow
        quality_logits = torch.tensor([[-5.0, 5.0]])

        mock_net_instance.return_value = {
            "quality": quality_logits,
            "age": torch.tensor([[0.1, 0.9]]),  # Logits for age
            "count": torch.tensor([[0.1] * 5]),
            # Behaviors (Binary Logits). 5.0 -> Sigmoid ~0.99
            "alert": torch.tensor([[5.0]]),
            "begging": torch.tensor([[-5.0]]),
            "softSong": torch.tensor([[-5.0]]),
            "rattle": torch.tensor([[-5.0]]),
            "mob": torch.tensor([[-5.0]]),
        }

        classifier = CrowClassifier("/path/to/model.pt")
        embedding = np.random.randn(768).astype(np.float32)

        result = classifier.classify(embedding, quality_threshold=0.5)

        assert result.is_crow is True
        assert result.quality_score > 0.9
        assert result.call_type == "alert"
        # New model doesn't distinguish species, defaults to "crow"
        assert result.species == "crow"

    @patch("orpheus_agent_crow_detection.classifier.MultiTaskCrowNet")
    @patch("orpheus_agent_crow_detection.classifier.torch.load")
    @patch("orpheus_agent_crow_detection.classifier.Path.exists")
    def test_classify_low_quality(
        self,
        mock_exists: MagicMock,
        mock_load: MagicMock,  # noqa: ARG002
        mock_net_cls: MagicMock,
    ) -> None:
        """Test classification with low quality score."""
        mock_exists.return_value = True
        mock_net_instance = mock_net_cls.return_value

        # Quality: [High, Low] -> High probability of Noise (Index 0)
        quality_logits = torch.tensor([[5.0, -5.0]])

        mock_net_instance.return_value = {
            "quality": quality_logits,
            "age": torch.tensor([[0.1, 0.1]]),
            "count": torch.tensor([[0.1] * 5]),
            "alert": torch.tensor([[-5.0]]),
            "begging": torch.tensor([[-5.0]]),
            "softSong": torch.tensor([[-5.0]]),
            "rattle": torch.tensor([[-5.0]]),
            "mob": torch.tensor([[-5.0]]),
        }

        classifier = CrowClassifier("/path/to/model.pt")
        embedding = np.random.randn(768).astype(np.float32)

        result = classifier.classify(embedding, quality_threshold=0.5)

        assert result.is_crow is False
        assert result.quality_score < 0.1
        assert result.species == "unknown"

    @patch("orpheus_agent_crow_detection.classifier.MultiTaskCrowNet")
    @patch("orpheus_agent_crow_detection.classifier.torch.load")
    @patch("orpheus_agent_crow_detection.classifier.Path.exists")
    def test_classify_adds_batch_dim(
        self,
        mock_exists: MagicMock,
        mock_load: MagicMock,  # noqa: ARG002
        mock_net_cls: MagicMock,
    ) -> None:
        """Test that classify adds batch dimension if needed."""
        mock_exists.return_value = True
        mock_net_instance = mock_net_cls.return_value

        # Setup dummy return to avoid crash
        mock_net_instance.return_value = {
            "quality": torch.tensor([[0.0, 0.0]]),
            "age": torch.tensor([[0.0, 0.0]]),
            "count": torch.tensor([[0.0] * 5]),
            "alert": torch.tensor([[0.0]]),
            "begging": torch.tensor([[0.0]]),
            "softSong": torch.tensor([[0.0]]),
            "rattle": torch.tensor([[0.0]]),
            "mob": torch.tensor([[0.0]]),
        }

        classifier = CrowClassifier("/path/to/model.pt")
        # 1D array (missing batch dim)
        embedding = np.random.randn(768).astype(np.float32)

        classifier.classify(embedding)

        # Verify model was called with shape [1, 768]
        call_args = mock_net_instance.call_args[0][0]
        assert call_args.dim() == 2
        assert call_args.shape[0] == 1
        assert call_args.shape[1] == 768
