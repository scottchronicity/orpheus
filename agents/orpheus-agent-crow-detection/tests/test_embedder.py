"""Tests for AVES embedder."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

from orpheus_agent_crow_detection.embedder import AVESEmbedder


class TestAVESEmbedder:
    """Tests for AVESEmbedder class."""

    @patch(
        "orpheus_agent_crow_detection.embedder.fairseq.checkpoint_utils.load_model_ensemble_and_task"
    )
    @patch("orpheus_agent_crow_detection.embedder.Path.exists")
    def test_init_loads_model(self, mock_exists: MagicMock, mock_load_ensemble: MagicMock) -> None:
        """Test embedder initialization loads model."""
        mock_exists.return_value = True
        mock_model = MagicMock()
        # fairseq loader returns (models, cfg, task)
        mock_load_ensemble.return_value = ([mock_model], None, None)

        embedder = AVESEmbedder("/path/to/model.pt", sample_rate=16000)

        assert embedder.model == mock_model
        assert embedder.sample_rate == 16000
        mock_load_ensemble.assert_called_once()
        mock_model.eval.assert_called_once()

    @patch("orpheus_agent_crow_detection.embedder.Path.exists")
    def test_init_raises_if_model_missing(self, mock_exists: MagicMock) -> None:
        """Test embedder initialization raises error if model missing."""
        mock_exists.return_value = False
        with pytest.raises(FileNotFoundError, match="AVES model not found"):
            AVESEmbedder("/path/to/missing.pt")

    @patch(
        "orpheus_agent_crow_detection.embedder.fairseq.checkpoint_utils.load_model_ensemble_and_task"
    )
    @patch("orpheus_agent_crow_detection.embedder.Path.exists")
    def test_generate_embedding(
        self, mock_exists: MagicMock, mock_load_ensemble: MagicMock
    ) -> None:
        """Test embedding generation."""
        mock_exists.return_value = True
        mock_model = MagicMock()
        mock_load_ensemble.return_value = ([mock_model], None, None)

        # Simulate model output (1, 768)
        mock_output = torch.randn(1, 768)
        mock_model.return_value = {"x": mock_output}  # FIX: return dict, not tensor

        embedder = AVESEmbedder("/path/to/model.pt")
        audio = np.random.randn(16000).astype(np.float32)

        embedding = embedder.generate_embedding(audio)

        assert isinstance(embedding, np.ndarray)
        # After mean pooling, embedding shape is (1,)
        assert embedding.shape == (1,)
        mock_model.assert_called_once()

    @patch(
        "orpheus_agent_crow_detection.embedder.fairseq.checkpoint_utils.load_model_ensemble_and_task"
    )
    @patch("orpheus_agent_crow_detection.embedder.Path.exists")
    def test_generate_embedding_adds_batch_dim(
        self, mock_exists: MagicMock, mock_load_ensemble: MagicMock
    ) -> None:
        """Test that embedding generation adds batch dimension."""
        mock_exists.return_value = True
        mock_model = MagicMock()
        mock_load_ensemble.return_value = ([mock_model], None, None)
        mock_output = torch.randn(1, 768)
        mock_model.return_value = {"x": mock_output}  # FIX: return dict, not tensor

        embedder = AVESEmbedder("/path/to/model.pt")
        audio = np.random.randn(16000).astype(np.float32)

        embedder.generate_embedding(audio)

        # Verify model was called with correct shape (batch dim added)
        call_args = mock_model.call_args[0][0]
        assert call_args.dim() == 2

    @patch(
        "orpheus_agent_crow_detection.embedder.fairseq.checkpoint_utils.load_model_ensemble_and_task"
    )
    @patch("orpheus_agent_crow_detection.embedder.Path.exists")
    def test_embedding_dim_property(
        self, mock_exists: MagicMock, mock_load_ensemble: MagicMock
    ) -> None:
        """Test embedding_dim property."""
        mock_exists.return_value = True
        mock_model = MagicMock()
        mock_load_ensemble.return_value = ([mock_model], None, None)

        embedder = AVESEmbedder("/path/to/model.pt")
        assert embedder.embedding_dim == 768

    @patch("orpheus_agent_crow_detection.embedder.torch.cuda.is_available")
    @patch(
        "orpheus_agent_crow_detection.embedder.fairseq.checkpoint_utils.load_model_ensemble_and_task"
    )
    @patch("orpheus_agent_crow_detection.embedder.Path.exists")
    def test_uses_cuda_if_available(
        self, mock_exists: MagicMock, mock_load_ensemble: MagicMock, mock_cuda: MagicMock
    ) -> None:
        """Test embedder uses CUDA if available."""
        mock_exists.return_value = True
        mock_cuda.return_value = True
        mock_model = MagicMock()
        mock_load_ensemble.return_value = ([mock_model], None, None)

        embedder = AVESEmbedder("/path/to/model.pt")
        assert embedder.device.type == "cuda"

    @patch("orpheus_agent_crow_detection.embedder.torch.cuda.is_available")
    @patch(
        "orpheus_agent_crow_detection.embedder.fairseq.checkpoint_utils.load_model_ensemble_and_task"
    )
    @patch("orpheus_agent_crow_detection.embedder.Path.exists")
    def test_explicit_cpu_device_overrides_available_cuda(
        self, mock_exists: MagicMock, mock_load_ensemble: MagicMock, mock_cuda: MagicMock
    ) -> None:
        """An explicit device="cpu" pins CPU even when CUDA is available (config knob)."""
        mock_exists.return_value = True
        mock_cuda.return_value = True
        mock_load_ensemble.return_value = ([MagicMock()], None, None)

        embedder = AVESEmbedder("/path/to/model.pt", device="cpu")
        assert embedder.device.type == "cpu"
