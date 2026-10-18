"""Detection record (PRD section 6, DET-01).

An anomaly means unusual behavior. It does not by itself establish malicious intent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ScoreDirection(StrEnum):
    HIGHER_IS_MORE_ANOMALOUS = "higher_is_more_anomalous"
    LOWER_IS_MORE_ANOMALOUS = "lower_is_more_anomalous"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class Detection:
    user_id: str
    window_start: datetime
    window_end: datetime
    model_version: str
    feature_version: str
    anomaly_score: float
    score_direction: ScoreDirection
    threshold: float
    risk: float
    severity: Severity
    created_at: datetime
    evidence: tuple[str, ...]          # human-readable contextual reasons
    source_event_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")

    @property
    def detection_id(self) -> str:
        """Stable id: the same user, window and model always give the same id (DET-02)."""
        key = "|".join((self.user_id, self.window_start.isoformat(),
                        self.window_end.isoformat(), self.model_version, self.feature_version))
        return hashlib.sha256(key.encode()).hexdigest()[:32]
