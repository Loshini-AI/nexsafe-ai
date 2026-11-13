import torch
from torch import nn


class RoadRiskMLP(nn.Module):
    def __init__(self, feature_count: int, class_count: int) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(feature_count, 128),
            nn.ReLU(),
            nn.Dropout(p=0.2),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Dropout(p=0.2),
            nn.Linear(64, class_count),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.layers(features)
