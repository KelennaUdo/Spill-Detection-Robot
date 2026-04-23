from __future__ import annotations

import argparse
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Deque, List

import cv2
import numpy as np

from camera import CameraError, CameraStream
from detector import DEFAULT_HAZARD_LABELS, HazardDetection, YoloHazardDetector
from incident_manager import IncidentManager
from reporter import IncidentReporter

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = str(BASE_DIR / "models" / "best.pt")


class HazardMonitorService:
    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        location: str = "Building A",
        output_dir: str = "incidents",
        server_url: str | None = None,
        width: int = 320,
        height: int = 240,
        fps: int = 8,
        confidence_threshold: float = 0.4,
        iou_threshold: float = 0.5,
        frames_required: int = 3,
        window_size: int = 5,
        cooldown_seconds: int = 30,
        detection_interval_seconds: float = 0.35,
        hazard_labels: list[str] | None = None,
        on_incident_confirmed: Callable[[], None] | None = None,
    ):
        self.model_path = model_path
        self.location = location
        self.width = width
        self.height = height
        self.fps = fps
        self.detection_interval_seconds = detection_interval_seconds
        self.on_incident_confirmed = on_incident_confirmed

        self.detector = YoloHazardDetector(
            model_path=model_path,
            hazard_labels=hazard_labels or sorted(DEFAULT_HAZARD_LABELS),
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
        )
        self.incident_manager = IncidentManager(
            frames_required=frames_required,
            window_size=window_size,
            cooldown_seconds=cooldown_seconds,
        )
        self.reporter = IncidentReporter(
            output_dir=str((BASE_DIR / output_dir).resolve())
            if not Path(output_dir).is_absolute()
            else output_dir,
            server_url=server_url,
        )

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._latest_frame = self._build_status_frame(
            "Monitor is idle. Start monitoring to stream the camera."
        )
        self._latest_detections: list[HazardDetection] = []
        self._recent_incidents: Deque[dict] = deque(maxlen=10)
        self._last_error: str | None = None
        self._camera_backend: str | None = None
        self._last_frame_at: str | None = None
        self._running = False
        self._total_frames = 0

    def start(self) -> dict:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._status_snapshot_unlocked()

            self._stop_event.clear()
            self._last_error = None
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            return self._status_snapshot_unlocked()

    def ensure_started(self) -> dict:
        return self.start()

    def stop(self) -> dict:
        thread: threading.Thread | None
        with self._lock:
            self._stop_event.set()
            thread = self._thread

        if thread is not None:
            thread.join(timeout=2.0)

        with self._lock:
            self._running = False
            self._thread = None
            self._camera_backend = None
            self._latest_frame = self._build_status_frame(
                "Monitor stopped. Start monitoring to resume the feed."
            )
            return self._status_snapshot_unlocked()

    def get_latest_frame(self):
        with self._lock:
            return self._latest_frame.copy()

    def recent_incidents_snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._recent_incidents)

    def status_snapshot(self) -> dict:
        with self._lock:
            return self._status_snapshot_unlocked()

    def _status_snapshot_unlocked(self) -> dict:
        thread_alive = self._thread is not None and self._thread.is_alive()
        return {
            "running": self._running and thread_alive,
            "camera_backend": self._camera_backend,
            "model_path": str(Path(self.model_path).resolve()),
            "model_loaded": self.detector.is_ready,
            "detector_message": self.detector.status_message,
            "last_error": self._last_error,
            "last_frame_at": self._last_frame_at,
            "latest_detection_count": len(self._latest_detections),
            "recent_incident_count": len(self._recent_incidents),
            "total_frames": self._total_frames,
        }

    def _run_loop(self) -> None:
        camera: CameraStream | None = None
        cached_detections: list[HazardDetection] = []
        last_detection_time = 0.0
        try:
            camera = CameraStream(width=self.width, height=self.height, fps=self.fps).start()
            with self._lock:
                self._running = True
                self._camera_backend = camera.backend
                self._last_error = None

            while not self._stop_event.is_set():
                frame = camera.read()
                timestamp = datetime.now(timezone.utc)
                run_detection = (
                    time.monotonic() - last_detection_time
                    >= self.detection_interval_seconds
                )
                if run_detection:
                    cached_detections = self.detector.predict(frame)
                    confirmed = self.incident_manager.update(
                        cached_detections,
                        observed_at=timestamp,
                    )
                    last_detection_time = time.monotonic()
                else:
                    confirmed = []

                annotated = self.detector.annotate_frame(frame, cached_detections)

                for incident in confirmed:
                    packet = self.reporter.report(annotated, incident, location=self.location)
                    if self.on_incident_confirmed is not None:
                        try:
                            self.on_incident_confirmed()
                        except Exception:
                            pass
                    with self._lock:
                        self._recent_incidents.appendleft(packet)

                with self._lock:
                    self._latest_frame = annotated
                    self._latest_detections = list(cached_detections)
                    self._last_frame_at = timestamp.isoformat()
                    self._total_frames += 1

                time.sleep(max(0.0, (1 / self.fps) * 0.05))

        except CameraError as exc:
            self._set_error_state(str(exc))
        except Exception as exc:
            self._set_error_state(f"Monitor error: {exc}")
        finally:
            if camera is not None:
                camera.stop()
            with self._lock:
                self._running = False
                self._camera_backend = None

    def _set_error_state(self, message: str) -> None:
        with self._lock:
            self._last_error = message
            self._latest_frame = self._build_status_frame(message)
            self._latest_detections = []

    @staticmethod
    def _build_status_frame(message: str):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (24, 32, 48)
        cv2.putText(
            frame,
            "Hazard Monitor",
            (45, 150),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        for index, line in enumerate(_wrap_text(message, 44)):
            cv2.putText(
                frame,
                line,
                (45, 220 + index * 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (120, 220, 160),
                2,
                cv2.LINE_AA,
            )
        return frame


def _wrap_text(text: str, width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wet-floor hazard monitoring loop for the Raspberry Pi robot."
    )
    parser.add_argument("--model", default=DEFAULT_MODEL_PATH, help="Path to the YOLO model.")
    parser.add_argument("--location", default="Building A", help="High-level robot location.")
    parser.add_argument("--output-dir", default="incidents", help="Directory for saved images and JSON packets.")
    parser.add_argument("--server-url", default=None, help="Optional endpoint for alert delivery.")
    parser.add_argument("--width", type=int, default=320, help="Camera width.")
    parser.add_argument("--height", type=int, default=240, help="Camera height.")
    parser.add_argument("--fps", type=int, default=8, help="Capture FPS target.")
    parser.add_argument("--confidence", type=float, default=0.4, help="YOLO confidence threshold.")
    parser.add_argument("--iou", type=float, default=0.5, help="YOLO IOU threshold.")
    parser.add_argument("--frames-required", type=int, default=3, help="Frames needed to confirm a hazard.")
    parser.add_argument("--window-size", type=int, default=5, help="Decision window for temporal filtering.")
    parser.add_argument("--cooldown-seconds", type=int, default=30, help="Cooldown before reporting the same zone again.")
    parser.add_argument("--detection-interval", type=float, default=0.35, help="Seconds to wait between YOLO passes.")
    parser.add_argument(
        "--hazard-label",
        action="append",
        dest="hazard_labels",
        help="Hazard class label to treat as a spill detection. Repeat as needed.",
    )
    parser.add_argument("--preview", action="store_true", help="Show an annotated OpenCV preview window.")
    return parser


def run(args: argparse.Namespace) -> None:
    monitor = HazardMonitorService(
        model_path=args.model,
        location=args.location,
        output_dir=args.output_dir,
        server_url=args.server_url,
        width=args.width,
        height=args.height,
        fps=args.fps,
        confidence_threshold=args.confidence,
        iou_threshold=args.iou,
        frames_required=args.frames_required,
        window_size=args.window_size,
        cooldown_seconds=args.cooldown_seconds,
        detection_interval_seconds=args.detection_interval,
        hazard_labels=args.hazard_labels,
    )
    monitor.start()

    try:
        while True:
            frame = monitor.get_latest_frame()
            if args.preview:
                cv2.imshow("Spill Hazard Monitor", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            else:
                time.sleep(0.2)
    finally:
        monitor.stop()
        if args.preview:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    run(build_parser().parse_args())
