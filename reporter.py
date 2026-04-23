from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import cv2
import requests

from incident_manager import ConfirmedIncident


class IncidentReporter:
    def __init__(
        self,
        output_dir: str = "incidents",
        server_url: str | None = None,
        request_timeout: float = 5.0,
    ):
        self.output_dir = Path(output_dir)
        self.images_dir = self.output_dir / "images"
        self.packets_dir = self.output_dir / "packets"
        self.server_url = server_url
        self.request_timeout = request_timeout

        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.packets_dir.mkdir(parents=True, exist_ok=True)

    def report(
        self,
        frame,
        incident: ConfirmedIncident,
        location: str = "unknown",
    ) -> Dict[str, Any]:
        image_path = self.images_dir / f"{incident.incident_id}.jpg"
        packet_path = self.packets_dir / f"{incident.incident_id}.json"

        cv2.imwrite(str(image_path), frame)

        packet = {
            "incident_id": incident.incident_id,
            "timestamp": incident.confirmed_at.isoformat(),
            "location": location,
            "zone": incident.detection.zone,
            "label": incident.detection.label,
            "confidence": round(incident.detection.confidence, 4),
            "supporting_frames": incident.supporting_frames,
            "bbox": list(incident.detection.bbox),
            "image_path": str(image_path.resolve()),
        }

        delivery_status = self._send_packet(packet)
        if delivery_status is not None:
            packet["delivery"] = delivery_status

        packet_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
        return packet

    def _send_packet(self, packet: Dict[str, Any]) -> Dict[str, Any] | None:
        if not self.server_url:
            return None

        try:
            response = requests.post(
                self.server_url,
                json=packet,
                timeout=self.request_timeout,
            )
            return {
                "server_url": self.server_url,
                "status_code": response.status_code,
                "ok": response.ok,
            }
        except requests.RequestException as exc:
            return {
                "server_url": self.server_url,
                "ok": False,
                "error": str(exc),
            }
