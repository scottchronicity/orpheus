"""Multi-task neural network model for crow vocalization classification.

This module defines the architecture of the crow classifier model used by the
crow-detection agent. The model performs multi-task learning to classify:
- Quality (is it a crow or noise?)
- Count (how many crows?)
- Age (adult or juvenile?)
- Behaviors (alert, begging, soft_song, rattle, mob)

Model Architecture:
    - Backbone: 2-layer MLP with BatchNorm and ReLU
    - Heads: Separate output layers for each task
    - Input: 768-dimensional embedding from AVES model
    - Output: Multi-task predictions (quality, count, age, behaviors)

Reference: Based on crow-tools classifier trained on labeled crow vocalizations.
"""

from __future__ import annotations

from torch import nn


class MultiTaskCrowNet(nn.Module):
    """Multi-task neural network for crow vocalization classification.

    This model architecture matches the pre-trained mt_70.pt checkpoint from
    the crow-tools project. It uses a shared backbone with task-specific heads
    to predict multiple attributes simultaneously.

    Architecture:
        Backbone:
            - Linear(768, 237)
            - BatchNorm1d(237)
            - ReLU
            - Dropout(0.1)
            - Linear(237, 237)
            - BatchNorm1d(237)
            - ReLU

        Heads:
            - quality_head: Linear(237, 2) -> [noise, crow]
            - crowCount_head: Linear(237, 5) -> [1, 2, 3, 4, 5+ crows]
            - crowAge_head: Linear(237, 2) -> [adult, juvenile]
            - alert_head: Linear(237, 1) -> binary logit
            - begging_head: Linear(237, 1) -> binary logit
            - softSong_head: Linear(237, 1) -> binary logit
            - rattle_head: Linear(237, 1) -> binary logit
            - mob_head: Linear(237, 1) -> binary logit

    Args:
        input_dim: Dimension of input embeddings (default: 768 for AVES)
        hidden_dim: Dimension of hidden layers (default: 237)

    Example:
        >>> model = MultiTaskCrowNet(input_dim=768, hidden_dim=237)
        >>> embedding = torch.randn(1, 768)
        >>> outputs = model(embedding)
        >>> # outputs contains: quality, count, age, alert, begging, softSong, rattle, mob
    """

    def __init__(self, input_dim: int = 768, hidden_dim: int = 237) -> None:
        super().__init__()

        # Shared backbone: 2-layer MLP with BatchNorm and Dropout
        # Structure derived from checkpoint inspection:
        # Indices: 1=Linear, 2=BatchNorm, 5=Linear, 6=BatchNorm
        self.backbone = nn.Sequential(
            nn.Identity(),  # 0
            nn.Linear(input_dim, hidden_dim),  # 1
            nn.BatchNorm1d(hidden_dim),  # 2
            nn.ReLU(),  # 3
            nn.Dropout(0.1),  # 4
            nn.Linear(hidden_dim, hidden_dim),  # 5
            nn.BatchNorm1d(hidden_dim),  # 6
            nn.ReLU(),  # 7
        )

        # Task-specific heads
        # Quality: Is this crow vocalization or noise?
        self.quality_head = nn.Linear(hidden_dim, 2)  # [noise, crow]

        # Count: How many crows are vocalizing?
        self.crowCount_head = nn.Linear(hidden_dim, 5)  # [1, 2, 3, 4, 5+]

        # Age: Adult or juvenile crow?
        self.crowAge_head = nn.Linear(hidden_dim, 2)  # [adult, juvenile]

        # Binary behavior heads: Each outputs a single logit for binary classification
        # Alert: Warning/contact calls
        self.alert_head = nn.Linear(hidden_dim, 1)

        # Begging: Juvenile food requests
        self.begging_head = nn.Linear(hidden_dim, 1)

        # Soft Song: Quiet social vocalizations (subsong)
        self.softSong_head = nn.Linear(hidden_dim, 1)

        # Rattle: Aggressive rattling display
        self.rattle_head = nn.Linear(hidden_dim, 1)

        # Mob: Mobbing behavior (group aggression toward predator/threat)
        self.mob_head = nn.Linear(hidden_dim, 1)

    def forward(self, x):
        """Forward pass through the model.

        Args:
            x: Input tensor of shape (batch_size, input_dim)

        Returns:
            Dictionary containing predictions for all tasks:
                - quality: (batch_size, 2) - logits for [noise, crow]
                - count: (batch_size, 5) - logits for [1, 2, 3, 4, 5+ crows]
                - age: (batch_size, 2) - logits for [adult, juvenile]
                - alert: (batch_size, 1) - logit for alert behavior
                - begging: (batch_size, 1) - logit for begging behavior
                - softSong: (batch_size, 1) - logit for soft song behavior
                - rattle: (batch_size, 1) - logit for rattle behavior
                - mob: (batch_size, 1) - logit for mobbing behavior
        """
        # Compute shared features
        features = self.backbone(x)

        # Return predictions from all heads
        return {
            "quality": self.quality_head(features),
            "count": self.crowCount_head(features),
            "age": self.crowAge_head(features),
            "alert": self.alert_head(features),
            "begging": self.begging_head(features),
            "softSong": self.softSong_head(features),
            "rattle": self.rattle_head(features),
            "mob": self.mob_head(features),
        }
