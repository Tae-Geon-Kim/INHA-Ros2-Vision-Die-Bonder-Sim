import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import Pose
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String


DEFAULT_MICRO_TOPICS = [
    "/vision/micro_camera_1/image_raw",
    "/vision/micro_camera_2/image_raw",
    "/vision/micro_camera_3/image_raw",
    "/vision/micro_camera_4/image_raw",
]


def add_vision_node_to_path():
    env_path = os.environ.get("VISION_ALIGNER_DIR")
    candidates = []
    if env_path:
        candidates.append(Path(env_path))

    current = Path(__file__).resolve()
    for parent in current.parents:
        candidates.append(parent / "vision_node")

    for candidate in candidates:
        if (candidate / "vision_aligner.py").exists():
            sys.path.insert(0, str(candidate))
            return

    raise ImportError(
        "vision_aligner.py not found. Set VISION_ALIGNER_DIR or run from ros2_vision_ws."
    )


add_vision_node_to_path()
from vision_aligner import MacroCalibration, VisionAligner  # noqa: E402


def yaw_deg_from_pose(msg: Pose) -> float:
    q = msg.orientation
    if q.x == 0.0 and q.y == 0.0 and q.z == 0.0 and q.w == 0.0:
        return 0.0

    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.degrees(math.atan2(siny_cosp, cosy_cosp))


def set_pose_yaw_deg(msg: Pose, theta_deg: float) -> None:
    theta_rad = math.radians(theta_deg)
    msg.orientation.x = 0.0
    msg.orientation.y = 0.0
    msg.orientation.z = math.sin(theta_rad / 2.0)
    msg.orientation.w = math.cos(theta_rad / 2.0)


def clamp(value: float, max_abs: float) -> float:
    if max_abs <= 0.0:
        return value
    return max(-max_abs, min(max_abs, value))


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class VisionAlignmentBridge(Node):
    def __init__(self):
        super().__init__("vision_alignment_bridge")

        self.declare_parameter("alignment_process", "pick")
        self.declare_parameter("place_mode", "array")
        self.declare_parameter("macro_topic", "/vision/macro_camera/image_raw")
        self.declare_parameter("micro_topics", DEFAULT_MICRO_TOPICS)
        self.declare_parameter("command_topic", "/robot/command_pose")
        self.declare_parameter("result_topic", "/vision/alignment_result")
        self.declare_parameter("auto_command", False)
        self.declare_parameter("align_interval_sec", 1.0)
        self.declare_parameter("min_command_interval_sec", 1.0)
        self.declare_parameter("max_frame_age_sec", 2.0)
        self.declare_parameter("correction_gain", 1.0)
        self.declare_parameter("max_correction_xy_mm", 5.0)
        self.declare_parameter("max_correction_theta_deg", 3.0)
        self.declare_parameter("tolerance_xy_mm", 0.05)
        self.declare_parameter("tolerance_theta_deg", 0.05)
        self.declare_parameter("initial_x_mm", 0.0)
        self.declare_parameter("initial_y_mm", 0.0)
        self.declare_parameter("safe_z_mm", 50.0)
        self.declare_parameter("initial_theta_deg", 0.0)
        self.declare_parameter("pixel_size_x_mm", 1.0)
        self.declare_parameter("pixel_size_y_mm", 1.0)
        self.declare_parameter("backend_log_url", "")
        self.declare_parameter("history_id", 0)
        self.declare_parameter("camera_type", "MICRO")
        self.declare_parameter("debug", False)
        self.declare_parameter("debug_dir", "vision_debug")

        self.alignment_process = (
            self.get_parameter("alignment_process").value.strip().lower()
        )
        self.place_mode = self.get_parameter("place_mode").value
        self.macro_topic = self.get_parameter("macro_topic").value
        self.micro_topics = list(self.get_parameter("micro_topics").value)
        self.command_topic = self.get_parameter("command_topic").value
        self.result_topic = self.get_parameter("result_topic").value
        self.auto_command = as_bool(self.get_parameter("auto_command").value)
        self.align_interval_sec = float(
            self.get_parameter("align_interval_sec").value
        )
        self.min_command_interval_sec = float(
            self.get_parameter("min_command_interval_sec").value
        )
        self.max_frame_age_sec = float(self.get_parameter("max_frame_age_sec").value)
        self.correction_gain = float(self.get_parameter("correction_gain").value)
        self.max_correction_xy_mm = float(
            self.get_parameter("max_correction_xy_mm").value
        )
        self.max_correction_theta_deg = float(
            self.get_parameter("max_correction_theta_deg").value
        )
        self.tolerance_xy_mm = float(self.get_parameter("tolerance_xy_mm").value)
        self.tolerance_theta_deg = float(
            self.get_parameter("tolerance_theta_deg").value
        )
        self.backend_log_url = self.get_parameter("backend_log_url").value.strip()
        self.history_id = int(self.get_parameter("history_id").value)
        self.camera_type = self.get_parameter("camera_type").value
        self.debug = as_bool(self.get_parameter("debug").value)
        self.debug_dir = Path(self.get_parameter("debug_dir").value)

        pixel_size = (
            float(self.get_parameter("pixel_size_x_mm").value),
            float(self.get_parameter("pixel_size_y_mm").value),
        )
        self.aligner = VisionAligner(
            macro_calibration=MacroCalibration(pixel_size=pixel_size),
            micro_camera_specs=VisionAligner.create_default_micro_camera_specs(
                pixel_size=pixel_size
            ),
            debug_mode=self.debug,
        )

        self.current_pose = {
            "x": float(self.get_parameter("initial_x_mm").value),
            "y": float(self.get_parameter("initial_y_mm").value),
            "z": float(self.get_parameter("safe_z_mm").value),
            "theta_deg": float(self.get_parameter("initial_theta_deg").value),
        }
        self.latest_frames = {}
        self.latest_frame_times = {}
        self.last_command_time = 0.0

        self.command_pub = self.create_publisher(Pose, self.command_topic, 10)
        self.result_pub = self.create_publisher(String, self.result_topic, 10)
        self.create_subscription(Pose, self.command_topic, self.handle_command_pose, 10)

        self.create_subscription(
            Image,
            self.macro_topic,
            lambda msg: self.handle_image(self.macro_topic, msg),
            10,
        )
        for topic in self.micro_topics:
            self.create_subscription(
                Image,
                topic,
                lambda msg, topic=topic: self.handle_image(topic, msg),
                10,
            )

        self.create_timer(self.align_interval_sec, self.align_latest_frames)
        self.get_logger().info(
            "vision alignment bridge ready: "
            f"process={self.alignment_process}, auto_command={self.auto_command}"
        )

    def handle_command_pose(self, msg: Pose) -> None:
        self.current_pose = {
            "x": float(msg.position.x),
            "y": float(msg.position.y),
            "z": float(msg.position.z),
            "theta_deg": yaw_deg_from_pose(msg),
        }

    def handle_image(self, topic: str, msg: Image) -> None:
        try:
            self.latest_frames[topic] = self.image_msg_to_bgr(msg)
            self.latest_frame_times[topic] = time.monotonic()
        except ValueError as exc:
            self.get_logger().warn(f"failed to convert image from {topic}: {exc}")

    def image_msg_to_bgr(self, msg: Image) -> np.ndarray:
        encoding = msg.encoding.lower()
        channels_by_encoding = {
            "bgr8": 3,
            "rgb8": 3,
            "bgra8": 4,
            "rgba8": 4,
            "mono8": 1,
            "8uc1": 1,
            "8uc3": 3,
            "8uc4": 4,
        }
        if encoding not in channels_by_encoding:
            raise ValueError(f"unsupported encoding: {msg.encoding}")

        channels = channels_by_encoding[encoding]
        row = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.step)
        frame = row[:, : msg.width * channels].reshape(msg.height, msg.width, channels)

        if encoding in ("bgr8", "8uc3"):
            return frame.copy()
        if encoding == "rgb8":
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        if encoding == "bgra8":
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        if encoding in ("rgba8", "8uc4"):
            return cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
        return cv2.cvtColor(frame.reshape(msg.height, msg.width), cv2.COLOR_GRAY2BGR)

    def required_topics(self) -> list[str]:
        if self.alignment_process == "macro":
            return [self.macro_topic]
        return self.micro_topics

    def frames_ready(self) -> bool:
        now = time.monotonic()
        for topic in self.required_topics():
            if topic not in self.latest_frames:
                return False
            if now - self.latest_frame_times.get(topic, 0.0) > self.max_frame_age_sec:
                return False
        return True

    def align_latest_frames(self) -> None:
        if not self.frames_ready():
            return

        try:
            result = self.compute_alignment()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f"alignment failed: {exc}")
            return

        payload = {
            "process": self.alignment_process,
            "dx": float(result["dx"]),
            "dy": float(result["dy"]),
            "dtheta": float(result["dtheta"]),
            "auto_command": self.auto_command,
            "timestamp": time.time(),
        }
        self.publish_result(payload)
        self.save_debug_frames()
        self.post_backend_log(payload)

        if self.auto_command:
            self.publish_correction(payload)

    def compute_alignment(self) -> dict[str, float]:
        if self.alignment_process == "macro":
            return self.aligner.align_macro(self.latest_frames[self.macro_topic])
        if self.alignment_process == "pick":
            return self.aligner.align_pick([
                self.latest_frames[topic] for topic in self.micro_topics
            ])
        if self.alignment_process == "place":
            return self.aligner.align_place(
                [self.latest_frames[topic] for topic in self.micro_topics],
                mode=self.place_mode,
            )
        raise ValueError(
            "alignment_process must be one of: macro, pick, place. "
            f"received: {self.alignment_process}"
        )

    def publish_result(self, payload: dict) -> None:
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.result_pub.publish(msg)

    def save_debug_frames(self) -> None:
        if not self.debug:
            return

        self.debug_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in self.aligner.last_debug_frames.items():
            cv2.imwrite(str(self.debug_dir / f"{name}.png"), frame)

    def post_backend_log(self, payload: dict) -> None:
        if not self.backend_log_url or self.history_id <= 0:
            return
        if self.alignment_process not in {"pick", "place"}:
            return

        body = {
            "history_id": self.history_id,
            "process_step": self.alignment_process.upper(),
            "camera_type": self.camera_type,
            "offset_x": payload["dx"],
            "offset_y": payload["dy"],
            "offset_theta": payload["dtheta"],
        }
        request = urllib.request.Request(
            self.backend_log_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=0.5).read()
        except (urllib.error.URLError, TimeoutError) as exc:
            self.get_logger().warn(f"failed to post vision log: {exc}")

    def publish_correction(self, payload: dict) -> None:
        now = time.monotonic()
        if now - self.last_command_time < self.min_command_interval_sec:
            return

        raw_dx = float(payload["dx"])
        raw_dy = float(payload["dy"])
        raw_dtheta = float(payload["dtheta"])
        if (
            abs(raw_dx) <= self.tolerance_xy_mm
            and abs(raw_dy) <= self.tolerance_xy_mm
            and abs(raw_dtheta) <= self.tolerance_theta_deg
        ):
            return

        dx = clamp(raw_dx * self.correction_gain, self.max_correction_xy_mm)
        dy = clamp(raw_dy * self.correction_gain, self.max_correction_xy_mm)
        dtheta = clamp(
            raw_dtheta * self.correction_gain,
            self.max_correction_theta_deg,
        )

        command = Pose()
        command.position.x = self.current_pose["x"] + dx
        command.position.y = self.current_pose["y"] + dy
        command.position.z = self.current_pose["z"]
        set_pose_yaw_deg(command, self.current_pose["theta_deg"] + dtheta)

        self.command_pub.publish(command)
        self.last_command_time = now
        self.get_logger().info(
            "published correction: "
            f"dx={dx:.4f}, dy={dy:.4f}, dtheta={dtheta:.4f}"
        )


def main(args=None) -> int:
    rclpy.init(args=args)
    node = VisionAlignmentBridge()

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
