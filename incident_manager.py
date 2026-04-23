from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, Iterable, List

from detector import HazardDetection


@dataclass
class ConfirmedIncident:
    incident_id: str
    confirmed_at: datetime
    supporting_frames: int
    detection: HazardDetection

    def to_dict(self) -> dict:
        payload = self.detection.to_dict()
        payload.update(
            {
                "incident_id": self.incident_id,
                "confirmed_at": self.confirmed_at.isoformat(),
                "supporting_frames": self.supporting_frames,
            }
        )
        return payload


class IncidentManager:
    def __init__(
        self,
        frames_required: int = 3,
        window_size: int = 5,
        cooldown_seconds: int = 30,
    ):
        if frames_required > window_size:
            raise ValueError("frames_required must be less than or equal to window_size")

        self.frames_required = frames_required
        self.window_size = window_size
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self.history: Dict[str, Deque[bool]] = defaultdict(
            lambda: deque(maxlen=self.window_size)
        )
        self.last_detection: Dict[str, HazardDetection] = {}
        self.last_reported_at: Dict[str, datetime] = {}

    def update(
        self,
        detections: Iterable[HazardDetection],
        observed_at: datetime | None = None,
    ) -> List[ConfirmedIncident]:
        timestamp = observed_at or datetime.now(timezone.utc)
        detections = list(detections)
        present_keys = set()
        confirmed_incidents: List[ConfirmedIncident] = []

        for detection in detections:
            key = self._key_for(detection)
            present_keys.add(key)
            self.last_detection[key] = detection
            self.history[key].append(True)

            supporting_frames = sum(self.history[key])
            if supporting_frames < self.frames_required:
                continue

            if self._is_in_cooldown(key, timestamp):
                continue

            incident = ConfirmedIncident(
                incident_id=f"{key}-{int(timestamp.timestamp())}",
                confirmed_at=timestamp,
                supporting_frames=supporting_frames,
                detection=detection,
            )
            confirmed_incidents.append(incident)
            self.last_reported_at[key] = timestamp
            self.history[key].clear()

        for key, states in list(self.history.items()):
            if key not in present_keys:
                states.append(False)
            if not any(states):
                self.history.pop(key, None)
                self.last_detection.pop(key, None)

        return confirmed_incidents

    def _is_in_cooldown(self, key: str, timestamp: datetime) -> bool:
        last_reported = self.last_reported_at.get(key)
        if last_reported is None:
            return False
        return timestamp - last_reported < self.cooldown

    @staticmethod
    def _key_for(detection: HazardDetection) -> str:
        normalized_label = detection.label.strip().lower().replace(" ", "_")
        normalized_zone = detection.zone.strip().lower().replace(" ", "_")
        return f"{normalized_label}@{normalized_zone}"
