from __future__ import annotations

import time
from typing import Optional

import cv2

try:
    from picamera2 import Picamera2  # type: ignore
except ImportError:  # pragma: no cover - depends on Pi image
    Picamera2 = None


class CameraError(RuntimeError):
    pass


class CameraStream:
    def __init__(
        self,
        width: int = 320,
        height: int = 240,
        fps: int = 8,
        camera_index: int = 0,
        warmup_seconds: float = 1.0,
        rotate_180: bool = True,
    ):
        self.width = width
        self.height = height
        self.fps = fps
        self.camera_index = camera_index
        self.warmup_seconds = warmup_seconds
        self.rotate_180 = rotate_180
        self.backend: Optional[str] = None
        self.picam = None
        self.capture = None

    def start(self) -> "CameraStream":
        if Picamera2 is not None:
            try:
                self.picam = Picamera2()
                config = self.picam.create_video_configuration(
                    main={"size": (self.width, self.height), "format": "RGB888"},
                    controls={
                        "FrameDurationLimits": (
                            int(1e6 / self.fps),
                            int(1e6 / self.fps),
                        )
                    },
                )
                self.picam.configure(config)
                self.picam.start()
                self.backend = "picamera2"
                time.sleep(self.warmup_seconds)
                return self
            except Exception:
                self.picam = None

        self.capture = cv2.VideoCapture(self.camera_index)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.capture.set(cv2.CAP_PROP_FPS, self.fps)
        if not self.capture.isOpened():
            raise CameraError("Could not open a Raspberry Pi camera or fallback webcam.")

        self.backend = "opencv"
        time.sleep(min(self.warmup_seconds, 0.3))
        return self

    def read(self):
        if self.picam is not None:
            frame = self.picam.capture_array()
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            return self._post_process(frame)

        if self.capture is None:
            raise CameraError("Camera stream has not been started.")

        ok, frame = self.capture.read()
        if not ok:
            raise CameraError("Camera frame capture failed.")
        return self._post_process(frame)

    def _post_process(self, frame):
        if self.rotate_180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        return frame

    def stop(self) -> None:
        if self.picam is not None:
            self.picam.stop()
            self.picam = None

        if self.capture is not None:
            self.capture.release()
            self.capture = None
