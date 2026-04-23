from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

import cv2

try:
    from ultralytics import YOLO  # type: ignore
except ImportError:  # pragma: no cover - depends on installed package
    YOLO = None


DEFAULT_HAZARD_LABELS = {
    "wet_floor",
    "wet-floor",
    "wet floor",
    "spill",
    "liquid_spill",
    "slippery_surface",
}


@dataclass
class HazardDetection:
    label: str
    confidence: float
    bbox: tuple[int, int, int, int]
    zone: str
    class_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "bbox": list(self.bbox),
            "zone": self.zone,
            "class_id": self.class_id,
        }


def infer_zone(frame_shape: Sequence[int], bbox: tuple[int, int, int, int]) -> str:
    frame_height, frame_width = frame_shape[:2]
    x1, y1, x2, y2 = bbox
    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2

    horizontal = "left" if center_x < frame_width / 3 else "right" if center_x > 2 * frame_width / 3 else "center"
    vertical = "far" if center_y < frame_height / 2 else "near"
    return f"{vertical}-{horizontal}"


class YoloHazardDetector:
    def __init__(
        self,
        model_path: str,
        hazard_labels: Iterable[str] | None = None,
        hazard_class_ids: Iterable[int] | None = None,
        confidence_threshold: float = 0.4,
        iou_threshold: float = 0.5,
    ):
        self.model_path = model_path
        self.hazard_labels = {
            label.strip().lower() for label in (hazard_labels or DEFAULT_HAZARD_LABELS)
        }
        self.hazard_class_ids = set(hazard_class_ids or [])
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.model = None
        self.status_message = "Detector not loaded."

    @property
    def is_ready(self) -> bool:
        return self.model is not None

    def load(self) -> None:
        if self.model is not None:
            return

        if YOLO is None:
            self.status_message = "ultralytics is not installed."
            return

        model_file = Path(self.model_path)
        if not model_file.exists():
            self.status_message = f"YOLO model not found at {model_file}."
            return

        self.model = YOLO(str(model_file))
        self.status_message = f"Loaded YOLO model from {model_file}."

    def predict(self, frame) -> List[HazardDetection]:
        if self.model is None:
            self.load()
        if self.model is None:
            return []

        results = self.model.predict(
            source=frame,
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            verbose=False,
        )

        detections: List[HazardDetection] = []
        for result in results:
            names = result.names or {}
            for box in result.boxes:
                class_id = int(box.cls[0].item())
                label = str(names.get(class_id, class_id))
                if not self._is_hazard(label, class_id):
                    continue

                x1, y1, x2, y2 = (int(value) for value in box.xyxy[0].tolist())
                confidence = float(box.conf[0].item())
                detections.append(
                    HazardDetection(
                        label=label,
                        confidence=confidence,
                        bbox=(x1, y1, x2, y2),
                        zone=infer_zone(frame.shape, (x1, y1, x2, y2)),
                        class_id=class_id,
                    )
                )
        if detections:
            self.status_message = f"Detected {len(detections)} spill candidate(s)."
        else:
            self.status_message = "No spill detected in the latest frame."
        return detections

    def annotate_frame(self, frame, detections: Sequence[HazardDetection]):
        annotated = frame.copy()
        for detection in detections:
            x1, y1, x2, y2 = detection.bbox
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 180, 255), 2)
            label = f"{detection.label} {detection.confidence:.2f} {detection.zone}"
            cv2.putText(
                annotated,
                label,
                (x1, max(24, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 180, 255),
                2,
                cv2.LINE_AA,
            )
        return annotated

    def _is_hazard(self, label: str, class_id: int) -> bool:
        normalized_label = label.strip().lower()
        if normalized_label in self.hazard_labels:
            return True
        if self.hazard_class_ids and class_id in self.hazard_class_ids:
            return True
        return False
