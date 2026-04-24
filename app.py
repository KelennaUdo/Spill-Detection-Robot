from __future__ import annotations

import cv2
from flask import Flask, Response, jsonify, request

from hazard_monitor import DEFAULT_MODEL_PATH, HazardMonitorService
from robot_control import RemoteRobotController

app = Flask(__name__)
controller = RemoteRobotController(default_speed=40)
monitor_service = HazardMonitorService(
    model_path=DEFAULT_MODEL_PATH,
    location="Building A",
    output_dir="incidents",
    on_incident_confirmed=controller.stop_all,
)


def _parse_int(name: str, default: int) -> int:
    raw_value = request.args.get(name, default)
    return int(raw_value)


def _mjpeg_generator():
    monitor_service.ensure_started()
    while True:
        frame = monitor_service.get_latest_frame()
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 70],
        )
        if not ok:
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + encoded.tobytes() + b"\r\n"
        )


@app.route("/")
def home():
    return """
    <html>
    <head>
        <title>Spill Detection Robot</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
            :root {
                --accent: #14532d;
                --accent-soft: #22c55e;
                --danger: #b91c1c;
                --warning: #b45309;
                --ink: #102a43;
                --panel: #f8fafc;
                --line: #d9e2ec;
            }
            body {
                margin: 0;
                padding: 24px;
                font-family: "Trebuchet MS", sans-serif;
                color: var(--ink);
                background:
                    radial-gradient(circle at top, rgba(34, 197, 94, 0.15), transparent 35%),
                    linear-gradient(180deg, #f0fdf4 0%, #f8fafc 100%);
            }
            h1, h2, p {
                margin-top: 0;
            }
            .layout {
                display: grid;
                gap: 20px;
                grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
                max-width: 1180px;
                margin: 0 auto;
            }
            .panel {
                background: rgba(255, 255, 255, 0.94);
                border: 1px solid var(--line);
                border-radius: 18px;
                padding: 20px;
                box-shadow: 0 14px 30px rgba(16, 42, 67, 0.08);
            }
            .grid {
                display: inline-grid;
                grid-template-columns: repeat(3, minmax(72px, 1fr));
                gap: 12px;
                width: 100%;
            }
            .monitor-actions {
                display: flex;
                gap: 12px;
                flex-wrap: wrap;
                margin-bottom: 12px;
            }
            button {
                padding: 16px 12px;
                min-height: 54px;
                border-radius: 14px;
                border: none;
                font-size: 16px;
                font-weight: 700;
                background: var(--accent);
                color: white;
                box-shadow: inset 0 -2px 0 rgba(0, 0, 0, 0.15);
            }
            button.secondary {
                background: #0f766e;
            }
            button.warning {
                background: var(--warning);
            }
            button:active {
                transform: translateY(1px);
            }
            .status {
                margin-top: 16px;
                padding: 12px 14px;
                border-radius: 12px;
                background: var(--panel);
                border: 1px solid var(--line);
                font-size: 14px;
                white-space: pre-line;
            }
            .video {
                width: 100%;
                border-radius: 16px;
                border: 1px solid var(--line);
                background: #0f172a;
                aspect-ratio: 4 / 3;
                object-fit: cover;
            }
            .incident-list {
                margin: 0;
                padding-left: 18px;
            }
            .incident-list li {
                margin-bottom: 10px;
            }
            label {
                display: block;
                margin-bottom: 10px;
                font-weight: 700;
            }
            input[type="range"] {
                width: 100%;
            }
        </style>
    </head>
    <body>
        <div class="layout">
            <section class="panel">
                <h1>Spill Monitor</h1>
                <p>The live feed, detector, and incident logger all use the same camera stream.</p>
                <div class="monitor-actions">
                    <button id="start-monitor">Start Monitor</button>
                    <button id="stop-monitor" class="warning">Stop Monitor</button>
                </div>
                <img class="video" src="/video_feed" alt="Robot camera feed" />
                <div id="monitor-status" class="status">Loading monitor status...</div>
            </section>

            <section class="panel">
                <h2>Robot Drive</h2>
                <p>Hold a drive button or use W/S/A/D to move. Release anywhere to stop.</p>
                <label for="speed">Drive Speed: <span id="speed-value">40</span></label>
                <input id="speed" type="range" min="0" max="100" value="40" />
                <div class="grid">
                    <div></div>
                    <button data-drive="forward">W Forward</button>
                    <div></div>

                    <button data-drive="left">A Strafe Left</button>
                    <div></div>
                    <button data-drive="right">D Strafe Right</button>

                    <button data-drive="turn_left">Q Turn Left</button>
                    <button data-drive="backward">S Reverse</button>
                    <button data-drive="turn_right">E Turn Right</button>
                </div>
                <div id="drive-status" class="status">Loading robot state...</div>
            </section>

            <section class="panel">
                <h2>Camera Servo</h2>
                <p>Tap these buttons or use I/J/K/L to pan or tilt the Raspberry Pi camera.</p>
                <label for="step">Servo Step: <span id="step-value">10</span> deg</label>
                <input id="step" type="range" min="1" max="30" value="10" />
                <div class="grid">
                    <div></div>
                    <button class="secondary" data-camera="tilt_up">I Tilt Up</button>
                    <div></div>

                    <button class="secondary" data-camera="pan_left">J Pan Left</button>
                    <button class="secondary" data-camera="center">Center</button>
                    <button class="secondary" data-camera="pan_right">L Pan Right</button>

                    <div></div>
                    <button class="secondary" data-camera="tilt_down">K Tilt Down</button>
                    <div></div>
                </div>
            </section>

            <section class="panel">
                <h2>Recent Incidents</h2>
                <p>Confirmed spill alerts appear here after multi-frame confirmation.</p>
                <ul id="incident-list" class="incident-list">
                    <li>No incidents reported yet.</li>
                </ul>
            </section>
        </div>

        <script>
            const speedInput = document.getElementById('speed');
            const stepInput = document.getElementById('step');
            const speedValue = document.getElementById('speed-value');
            const stepValue = document.getElementById('step-value');
            const driveStatusEl = document.getElementById('drive-status');
            const monitorStatusEl = document.getElementById('monitor-status');
            const incidentListEl = document.getElementById('incident-list');
            const activeDriveKeys = new Set();
            const driveKeyMap = {
                w: 'forward',
                s: 'backward',
                a: 'left',
                d: 'right',
                q: 'turn_left',
                e: 'turn_right'
            };
            const cameraKeyMap = {
                i: 'tilt_up',
                j: 'pan_left',
                k: 'tilt_down',
                l: 'pan_right'
            };

            speedInput.addEventListener('input', () => {
                speedValue.textContent = speedInput.value;
            });

            stepInput.addEventListener('input', () => {
                stepValue.textContent = stepInput.value;
            });

            async function refreshStatus() {
                try {
                    const [robotResponse, monitorResponse, incidentsResponse] = await Promise.all([
                        fetch('/status'),
                        fetch('/monitor/status'),
                        fetch('/incidents/recent')
                    ]);

                    const robotState = await robotResponse.json();
                    const monitorState = await monitorResponse.json();
                    const incidents = await incidentsResponse.json();

                    driveStatusEl.textContent =
                        `Camera pan ${robotState.camera.pan} deg, tilt ${robotState.camera.tilt} deg, hardware ready: ${robotState.hardware_ready}`;

                    monitorStatusEl.textContent =
                        `Running: ${monitorState.running}\n` +
                        `Backend: ${monitorState.camera_backend || 'none'}\n` +
                        `Model: ${monitorState.model_path}\n` +
                        `Loaded: ${monitorState.model_loaded}\n` +
                        `Detector: ${monitorState.detector_message}\n` +
                        `Detections in latest frame: ${monitorState.latest_detection_count}\n` +
                        `Recent incidents: ${monitorState.recent_incident_count}\n` +
                        `Last error: ${monitorState.last_error || 'none'}`;

                    if (incidents.length === 0) {
                        incidentListEl.innerHTML = '<li>No incidents reported yet.</li>';
                    } else {
                        incidentListEl.innerHTML = incidents.map((incident) =>
                            `<li><strong>${incident.label}</strong> at ${incident.zone} ` +
                            `(conf ${incident.confidence})<br>${incident.timestamp}</li>`
                        ).join('');
                    }
                } catch (error) {
                    monitorStatusEl.textContent = `Monitor request failed: ${error}`;
                }
            }

            async function startMonitor() {
                try {
                    await fetch('/monitor/start', { method: 'POST' });
                } finally {
                    refreshStatus();
                }
            }

            async function stopMonitor() {
                try {
                    await fetch('/monitor/stop', { method: 'POST' });
                } finally {
                    refreshStatus();
                }
            }

            async function startMove(cmd) {
                await fetch(`/move/${cmd}?speed=${speedInput.value}`, { method: 'POST' });
                refreshStatus();
            }

            async function stopMove() {
                await fetch('/move/stop', { method: 'POST' });
            }

            async function moveCamera(action) {
                await fetch(`/camera/${action}?step=${stepInput.value}`, { method: 'POST' });
                refreshStatus();
            }

            document.getElementById('start-monitor').addEventListener('click', startMonitor);
            document.getElementById('stop-monitor').addEventListener('click', stopMonitor);

            document.querySelectorAll('[data-drive]').forEach(button => {
                const cmd = button.dataset.drive;

                button.addEventListener('mousedown', () => startMove(cmd));
                button.addEventListener('mouseup', stopMove);
                button.addEventListener('mouseleave', stopMove);

                button.addEventListener('touchstart', (event) => {
                    event.preventDefault();
                    startMove(cmd);
                }, { passive: false });

                button.addEventListener('touchend', (event) => {
                    event.preventDefault();
                    stopMove();
                });
            });

            document.querySelectorAll('[data-camera]').forEach(button => {
                button.addEventListener('click', () => moveCamera(button.dataset.camera));
            });

            document.addEventListener('keydown', (event) => {
                const key = event.key.toLowerCase();

                if (event.repeat) {
                    return;
                }

                const driveCommand = driveKeyMap[key];
                if (driveCommand) {
                    event.preventDefault();
                    activeDriveKeys.add(key);
                    startMove(driveCommand);
                    return;
                }

                const cameraAction = cameraKeyMap[key];
                if (cameraAction) {
                    event.preventDefault();
                    moveCamera(cameraAction);
                }
            });

            document.addEventListener('keyup', (event) => {
                const key = event.key.toLowerCase();
                if (!driveKeyMap[key]) {
                    return;
                }

                event.preventDefault();
                activeDriveKeys.delete(key);

                const remainingKeys = Array.from(activeDriveKeys);
                if (remainingKeys.length === 0) {
                    stopMove();
                    return;
                }

                const nextCommand = driveKeyMap[remainingKeys[remainingKeys.length - 1]];
                if (nextCommand) {
                    startMove(nextCommand);
                }
            });

            document.addEventListener('mouseup', stopMove);
            document.addEventListener('touchend', stopMove);
            window.addEventListener('blur', () => {
                activeDriveKeys.clear();
                stopMove();
            });

            startMonitor().then(() => refreshStatus());
            setInterval(refreshStatus, 4000);
        </script>
    </body>
    </html>
    """


@app.route("/move/<cmd>", methods=["POST"])
def move(cmd: str):
    try:
        controller.drive(cmd, speed=_parse_int("speed", controller.default_speed))
        return jsonify({"status": "ok", "command": cmd, **controller.snapshot_state()})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/camera/<action>", methods=["POST"])
def camera_action(action: str):
    step = _parse_int("step", 10)

    try:
        if action == "center":
            state = controller.center_camera()
        elif action == "pan_left":
            state = controller.nudge_camera("pan", -step)
        elif action == "pan_right":
            state = controller.nudge_camera("pan", step)
        elif action == "tilt_up":
            state = controller.nudge_camera("tilt", -step)
        elif action == "tilt_down":
            state = controller.nudge_camera("tilt", step)
        else:
            raise ValueError(f"Unsupported camera action: {action}")

        return jsonify({"status": "ok", "camera": state})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/status")
def status():
    return jsonify(controller.snapshot_state())


@app.route("/monitor/start", methods=["POST"])
def start_monitor():
    return jsonify(monitor_service.start())


@app.route("/monitor/stop", methods=["POST"])
def stop_monitor():
    return jsonify(monitor_service.stop())


@app.route("/monitor/status")
def monitor_status():
    return jsonify(monitor_service.status_snapshot())


@app.route("/incidents/recent")
def recent_incidents():
    return jsonify(monitor_service.recent_incidents_snapshot())


@app.route("/video_feed")
def video_feed():
    return Response(
        _mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


if __name__ == "__main__":
    controller.stop_all()
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
    finally:
        monitor_service.stop()
