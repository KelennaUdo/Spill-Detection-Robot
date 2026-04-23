"""
Robotics control helpers for the wet-floor hazard robot.

The original `FSDEROBOT` class is preserved for low-level motor access, and a
small wrapper is added on top so the rest of the project can issue clearer
drive and camera commands.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

try:
    import smbus  # type: ignore
except ImportError:  # pragma: no cover - exercised on non-Pi development hosts
    smbus = None

try:
    from gpiozero import LED  # type: ignore
except ImportError:  # pragma: no cover - exercised on non-Pi development hosts
    LED = None


class _NullSMBus:
    def write_byte_data(self, address: int, reg: int, value: int) -> None:
        return None

    def read_byte_data(self, address: int, reg: int) -> int:
        return 0


class _MockLED:
    def __init__(self, pin: int):
        self.pin = pin
        self.state = False

    def on(self) -> None:
        self.state = True

    def off(self) -> None:
        self.state = False


Dir = ["forward", "backward"]


class PCA9685:
    __SUBADR1 = 0x02
    __SUBADR2 = 0x03
    __SUBADR3 = 0x04
    __MODE1 = 0x00
    __PRESCALE = 0xFE
    __LED0_ON_L = 0x06
    __LED0_ON_H = 0x07
    __LED0_OFF_L = 0x08
    __LED0_OFF_H = 0x09
    __ALLLED_ON_L = 0xFA
    __ALLLED_ON_H = 0xFB
    __ALLLED_OFF_L = 0xFC
    __ALLLED_OFF_H = 0xFD

    def __init__(self, address: int, debug: bool = False):
        self.address = address
        self.debug = debug
        self.hardware_ready = True
        try:
            if smbus is None:
                raise ImportError("smbus is not available")
            self.bus = smbus.SMBus(1)
        except Exception:
            self.bus = _NullSMBus()
            self.hardware_ready = False
        self.write(self.__MODE1, 0x00)

    def write(self, reg: int, value: int) -> None:
        self.bus.write_byte_data(self.address, reg, value)

    def read(self, reg: int) -> int:
        return self.bus.read_byte_data(self.address, reg)

    def setPWMFreq(self, freq: int) -> None:
        prescaleval = 25000000.0
        prescaleval /= 4096.0
        prescaleval /= float(freq)
        prescaleval -= 1.0
        prescale = math.floor(prescaleval + 0.5)

        oldmode = self.read(self.__MODE1)
        newmode = (oldmode & 0x7F) | 0x10

        self.write(self.__MODE1, newmode)
        self.write(self.__PRESCALE, int(math.floor(prescale)))
        self.write(self.__MODE1, oldmode)
        time.sleep(0.005)
        self.write(self.__MODE1, oldmode | 0x80)

    def setPWM(self, channel: int, on: int, off: int) -> None:
        self.write(self.__LED0_ON_L + 4 * channel, on & 0xFF)
        self.write(self.__LED0_ON_H + 4 * channel, on >> 8)
        self.write(self.__LED0_OFF_L + 4 * channel, off & 0xFF)
        self.write(self.__LED0_OFF_H + 4 * channel, off >> 8)

    def setDutycycle(self, channel: int, pulse: int) -> None:
        self.setPWM(channel, 0, int(pulse * (4096 / 100)))

    def setLevel(self, channel: int, value: int) -> None:
        if value == 1:
            self.setPWM(channel, 0, 4095)
        else:
            self.setPWM(channel, 0, 0)


class FSDEROBOT:
    def __init__(self):
        self.PWMA = 0
        self.AIN1 = 2
        self.AIN2 = 1

        self.PWMB = 5
        self.BIN1 = 3
        self.BIN2 = 4

        self.PWMC = 6
        self.CIN2 = 7
        self.CIN1 = 8

        self.PWMD = 11
        self.DIN1 = 25
        self.DIN2 = 24

        self.pwm = PCA9685(0x40, debug=False)
        self.pwm.setPWMFreq(50)

        gpio_devices_present = any(
            Path(device_path).exists()
            for device_path in ("/dev/gpiomem", "/dev/mem", "/dev/gpiochip0")
        )
        try:
            if LED is None or not gpio_devices_present:
                raise RuntimeError("GPIO backend is unavailable")
            self.motorD1 = LED(self.DIN1)
            self.motorD2 = LED(self.DIN2)
        except Exception:
            self.motorD1 = _MockLED(self.DIN1)
            self.motorD2 = _MockLED(self.DIN2)

    def MotorRun(self, motor: int, index: str, speed: int) -> None:
        speed = max(0, min(speed, 100))

        if motor == 0:
            self.pwm.setDutycycle(self.PWMA, speed)
            if index == Dir[0]:
                self.pwm.setLevel(self.AIN1, 0)
                self.pwm.setLevel(self.AIN2, 1)
            else:
                self.pwm.setLevel(self.AIN1, 1)
                self.pwm.setLevel(self.AIN2, 0)

        elif motor == 1:
            self.pwm.setDutycycle(self.PWMB, speed)
            if index == Dir[0]:
                self.pwm.setLevel(self.BIN1, 1)
                self.pwm.setLevel(self.BIN2, 0)
            else:
                self.pwm.setLevel(self.BIN1, 0)
                self.pwm.setLevel(self.BIN2, 1)

        elif motor == 2:
            self.pwm.setDutycycle(self.PWMC, speed)
            if index == Dir[0]:
                self.pwm.setLevel(self.CIN1, 1)
                self.pwm.setLevel(self.CIN2, 0)
            else:
                self.pwm.setLevel(self.CIN1, 0)
                self.pwm.setLevel(self.CIN2, 1)

        elif motor == 3:
            self.pwm.setDutycycle(self.PWMD, speed)
            if index == Dir[0]:
                self.motorD1.off()
                self.motorD2.on()
            else:
                self.motorD1.on()
                self.motorD2.off()

    def MotorStop(self, motor: int) -> None:
        if motor == 0:
            self.pwm.setDutycycle(self.PWMA, 0)
        elif motor == 1:
            self.pwm.setDutycycle(self.PWMB, 0)
        elif motor == 2:
            self.pwm.setDutycycle(self.PWMC, 0)
        elif motor == 3:
            self.pwm.setDutycycle(self.PWMD, 0)

    def t_up(self, speed: int, t_time: float) -> None:
        self.MotorRun(0, "forward", speed)
        self.MotorRun(1, "forward", speed)
        self.MotorRun(2, "forward", speed)
        self.MotorRun(3, "forward", speed)
        time.sleep(t_time)

    def t_down(self, speed: int, t_time: float) -> None:
        self.MotorRun(0, "backward", speed)
        self.MotorRun(1, "backward", speed)
        self.MotorRun(2, "backward", speed)
        self.MotorRun(3, "backward", speed)
        time.sleep(t_time)

    def moveLeft(self, speed: int, t_time: float) -> None:
        self.MotorRun(0, "backward", speed)
        self.MotorRun(1, "forward", speed)
        self.MotorRun(2, "forward", speed)
        self.MotorRun(3, "backward", speed)
        time.sleep(t_time)

    def moveRight(self, speed: int, t_time: float) -> None:
        self.MotorRun(0, "forward", speed)
        self.MotorRun(1, "backward", speed)
        self.MotorRun(2, "backward", speed)
        self.MotorRun(3, "forward", speed)
        time.sleep(t_time)

    def turnLeft(self, speed: int, t_time: float) -> None:
        self.MotorRun(0, "backward", speed)
        self.MotorRun(1, "forward", speed)
        self.MotorRun(2, "backward", speed)
        self.MotorRun(3, "forward", speed)
        time.sleep(t_time)

    def turnRight(self, speed: int, t_time: float) -> None:
        self.MotorRun(0, "forward", speed)
        self.MotorRun(1, "backward", speed)
        self.MotorRun(2, "forward", speed)
        self.MotorRun(3, "backward", speed)
        time.sleep(t_time)

    def forward_Left(self, speed: int, t_time: float) -> None:
        self.MotorStop(0)
        self.MotorRun(1, "forward", speed)
        self.MotorRun(2, "forward", speed)
        self.MotorStop(3)
        time.sleep(t_time)

    def forward_Right(self, speed: int, t_time: float) -> None:
        self.MotorRun(0, "forward", speed)
        self.MotorStop(1)
        self.MotorStop(2)
        self.MotorRun(3, "forward", speed)
        time.sleep(t_time)

    def backward_Left(self, speed: int, t_time: float) -> None:
        self.MotorRun(0, "backward", speed)
        self.MotorStop(1)
        self.MotorStop(2)
        self.MotorRun(3, "backward", speed)
        time.sleep(t_time)

    def backward_Right(self, speed: int, t_time: float) -> None:
        self.MotorStop(0)
        self.MotorRun(1, "backward", speed)
        self.MotorRun(2, "backward", speed)
        self.MotorStop(3)
        time.sleep(t_time)

    def t_stop(self, t_time: float) -> None:
        self.MotorStop(0)
        self.MotorStop(1)
        self.MotorStop(2)
        self.MotorStop(3)
        time.sleep(t_time)

    def set_servo_pulse(self, channel: int, pulse: int) -> None:
        pulse_length = 1000000
        pulse_length //= 60
        pulse_length //= 4096
        pulse *= 1000
        pulse //= pulse_length
        self.pwm.setPWM(channel, 0, pulse)

    def set_servo_angle(self, channel: int, angle: int) -> None:
        angle = max(0, min(angle, 180))
        pulse = 4096 * ((angle * 11) + 500) / 20000
        self.pwm.setPWM(channel, 0, int(pulse))


@dataclass
class CameraServoConfig:
    pan_channel: int = 10
    tilt_channel: int = 9
    pan_limits: Tuple[int, int] = (0, 180)
    tilt_limits: Tuple[int, int] = (0, 90)
    home_pan: int = 90
    home_tilt: int = 10
    invert_pan: bool = True
    invert_tilt: bool = False


class RemoteRobotController:
    DRIVE_PATTERNS = {
        "forward": ((0, "forward"), (1, "forward"), (2, "forward"), (3, "forward")),
        "backward": ((0, "backward"), (1, "backward"), (2, "backward"), (3, "backward")),
        "left": ((0, "backward"), (1, "forward"), (2, "forward"), (3, "backward")),
        "right": ((0, "forward"), (1, "backward"), (2, "backward"), (3, "forward")),
        "turn_left": ((0, "backward"), (1, "forward"), (2, "backward"), (3, "forward")),
        "turn_right": ((0, "forward"), (1, "backward"), (2, "forward"), (3, "backward")),
    }

    def __init__(
        self,
        default_speed: int = 40,
        servo_config: CameraServoConfig | None = None,
        auto_center_camera: bool = True,
    ):
        self.robot = FSDEROBOT()
        self.default_speed = default_speed
        self.servo_config = servo_config or CameraServoConfig()
        self.camera_angles: Dict[str, int] = {
            "pan": self.servo_config.home_pan,
            "tilt": self.servo_config.home_tilt,
        }
        if auto_center_camera:
            self.center_camera()

    def stop_all(self) -> None:
        for motor in range(4):
            self.robot.MotorStop(motor)

    def drive(self, command: str, speed: int | None = None) -> None:
        if command == "stop":
            self.stop_all()
            return

        if command not in self.DRIVE_PATTERNS:
            raise ValueError(f"Unsupported drive command: {command}")

        self.stop_all()
        chosen_speed = max(0, min(speed or self.default_speed, 100))
        for motor, direction in self.DRIVE_PATTERNS[command]:
            self.robot.MotorRun(motor, direction, chosen_speed)

    def center_camera(self) -> Dict[str, int]:
        self.set_camera_angle("pan", self.servo_config.home_pan)
        self.set_camera_angle("tilt", self.servo_config.home_tilt)
        return dict(self.camera_angles)

    def set_camera_angle(self, axis: str, angle: int) -> Dict[str, int]:
        if axis not in self.camera_angles:
            raise ValueError(f"Unsupported camera axis: {axis}")

        limits = (
            self.servo_config.pan_limits
            if axis == "pan"
            else self.servo_config.tilt_limits
        )
        bounded_angle = max(limits[0], min(angle, limits[1]))
        channel = (
            self.servo_config.pan_channel
            if axis == "pan"
            else self.servo_config.tilt_channel
        )
        self.robot.set_servo_angle(channel, bounded_angle)
        self.camera_angles[axis] = bounded_angle
        return dict(self.camera_angles)

    def nudge_camera(self, axis: str, delta: int) -> Dict[str, int]:
        if axis == "pan" and self.servo_config.invert_pan:
            delta *= -1
        if axis == "tilt" and self.servo_config.invert_tilt:
            delta *= -1
        return self.set_camera_angle(axis, self.camera_angles[axis] + delta)

    def snapshot_state(self) -> Dict[str, object]:
        return {
            "default_speed": self.default_speed,
            "camera": dict(self.camera_angles),
            "hardware_ready": getattr(self.robot.pwm, "hardware_ready", False),
            "servo_channels": {
                "pan": self.servo_config.pan_channel,
                "tilt": self.servo_config.tilt_channel,
            },
        }
