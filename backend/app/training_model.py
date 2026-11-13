import torch
from torch import nn


class CNNLSTM(nn.Module):
    def __init__(self, number_of_classes: int) -> None:
        super().__init__()
        self.spatial_encoder = nn.Sequential(
            nn.Conv2d(3, 24, kernel_size=5, stride=2, padding=2),
            nn.BatchNorm2d(24),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(24, 48, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(48),
            nn.ReLU(inplace=True),
            nn.Conv2d(48, 64, kernel_size=3, stride=2, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
        )
        self.temporal_encoder = nn.LSTM(
            input_size=64,
            hidden_size=96,
            num_layers=1,
            batch_first=True,
        )
        self.classifier = nn.Sequential(
            nn.Dropout(p=0.25),
            nn.Linear(96, number_of_classes),
        )

    def forward(self, sequences: torch.Tensor) -> torch.Tensor:
        batch, time, channels, height, width = sequences.shape
        frames = sequences.reshape(batch * time, channels, height, width)
        spatial_features = self.spatial_encoder(frames)
        temporal_features = spatial_features.reshape(batch, time, -1)
        outputs, _ = self.temporal_encoder(temporal_features)
        return self.classifier(outputs[:, -1])
