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
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String


DEFAULT_MICRO_TOPICS = [
    "/vision/micro_camera_1/image_raw",
    "/vision/micro_camera_2/image_raw",
    "/vision/micro_camera_3/image_raw",
    "/vision/micro_camera_4/image_raw",
]

PLACE_MICRO_MARKER_ROIS = [
    (0.5, 0.0, 1.0, 0.5),
    (0.0, 0.0, 0.5, 0.5),
    (0.0, 0.5, 0.5, 1.0),
    (0.5, 0.5, 1.0, 1.0),
]

CHIP_MICRO_MARKER_ROIS = [
    (0.0, 0.5, 0.5, 1.0),
    (0.5, 0.5, 1.0, 1.0),
    (0.5, 0.0, 1.0, 0.5),
    (0.0, 0.0, 0.5, 0.5),
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
        self.declare_parameter("initial_x_mm", 140.0)
        self.declare_parameter("initial_y_mm", 0.0)
        self.declare_parameter("safe_z_mm", 100.0)
        self.declare_parameter("initial_theta_deg", 0.0)
        self.declare_parameter("pixel_size_x_mm", 1.0)
        self.declare_parameter("pixel_size_y_mm", 1.0)
        self.declare_parameter("backend_log_url", "")
        self.declare_parameter("history_id", 0)
        self.declare_parameter("camera_type", "MICRO")
        self.declare_parameter("debug", False)
        self.declare_parameter("debug_dir", "vision_debug")
        self.declare_parameter("request_only", False)
        self.declare_parameter("request_topic", "/vision/alignment_request")
        self.declare_parameter("request_timeout_sec", 30.0)
        self.declare_parameter("request_warmup_frames", 1)
        self.declare_parameter("reference_dir", "vision_references")
        self.declare_parameter("macro_pixel_size_x_mm", 0.075)
        self.declare_parameter("macro_pixel_size_y_mm", 0.075)
        self.declare_parameter("micro_pixel_size_x_mm", 0.0068)
        self.declare_parameter("micro_pixel_size_y_mm", 0.0068)
        self.declare_parameter("macro_axis_sign_x", -1.0)
        self.declare_parameter("macro_axis_sign_y", 1.0)
        self.declare_parameter("micro_axis_sign_x", -1.0)
        self.declare_parameter("micro_axis_sign_y", 1.0)
        self.declare_parameter("pick_macro_distance_mm", 126.9)
        self.declare_parameter("pick_micro_distance_mm", 121.4)
        self.declare_parameter("place_macro_distance_mm", 121.9)
        self.declare_parameter("place_micro_distance_mm", 116.4)

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
        self.request_only = as_bool(self.get_parameter("request_only").value)
        self.request_topic = self.get_parameter("request_topic").value
        self.request_timeout_sec = float(
            self.get_parameter("request_timeout_sec").value
        )
        self.request_warmup_frames = max(
            1,
            int(self.get_parameter("request_warmup_frames").value),
        )
        self.reference_dir = Path(self.get_parameter("reference_dir").value).expanduser()
        self.macro_pixel_size = (
            float(self.get_parameter("macro_pixel_size_x_mm").value),
            float(self.get_parameter("macro_pixel_size_y_mm").value),
        )
        self.micro_pixel_size = (
            float(self.get_parameter("micro_pixel_size_x_mm").value),
            float(self.get_parameter("micro_pixel_size_y_mm").value),
        )
        self.macro_axis_sign = (
            float(self.get_parameter("macro_axis_sign_x").value),
            float(self.get_parameter("macro_axis_sign_y").value),
        )
        self.micro_axis_sign = (
            float(self.get_parameter("micro_axis_sign_x").value),
            float(self.get_parameter("micro_axis_sign_y").value),
        )
        self.pick_macro_distance_mm = float(
            self.get_parameter("pick_macro_distance_mm").value
        )
        self.pick_micro_distance_mm = float(
            self.get_parameter("pick_micro_distance_mm").value
        )
        self.place_macro_distance_mm = float(
            self.get_parameter("place_macro_distance_mm").value
        )
        self.place_micro_distance_mm = float(
            self.get_parameter("place_micro_distance_mm").value
        )

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
        self.pending_request = None

        self.command_pub = self.create_publisher(Pose, self.command_topic, 10)
        self.result_pub = self.create_publisher(String, self.result_topic, 10)
        self.create_subscription(Pose, self.command_topic, self.handle_command_pose, 10)
        self.create_subscription(
            String,
            self.request_topic,
            self.handle_alignment_request,
            10,
        )

        self.create_subscription(
            Image,
            self.macro_topic,
            lambda msg: self.handle_image(self.macro_topic, msg),
            qos_profile_sensor_data,
        )
        for topic in self.micro_topics:
            self.create_subscription(
                Image,
                topic,
                lambda msg, topic=topic: self.handle_image(topic, msg),
                qos_profile_sensor_data,
            )

        self.create_timer(self.align_interval_sec, self.align_latest_frames)
        self.create_timer(0.1, self.process_pending_request)
        self.get_logger().info(
            "vision alignment bridge ready: "
            f"process={self.alignment_process}, auto_command={self.auto_command}, "
            f"request_topic={self.request_topic}, result_topic={self.result_topic}"
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
            frame = self.image_msg_to_bgr(msg)
            frame_time = time.monotonic()
            self.latest_frames[topic] = frame
            self.latest_frame_times[topic] = frame_time

            request = self.pending_request
            if request is not None and topic in self.request_topics(request):
                frame_counts = request.setdefault("frame_counts", {})
                frame_counts[topic] = frame_counts.get(topic, 0) + 1
                if frame_counts[topic] >= self.request_warmup_frames:
                    request.setdefault("frames", {})[topic] = frame
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

    def handle_alignment_request(self, msg: String) -> None:
        try:
            request = json.loads(msg.data)
        except (json.JSONDecodeError, TypeError) as exc:
            self.get_logger().warn(f"invalid vision request: {exc}")
            return

        request_id = str(request.get("request_id", "")).strip()
        if not request_id:
            self.get_logger().warn("vision request without request_id ignored")
            return
        if self.pending_request is not None:
            self.publish_result({
                "request_id": request_id,
                "success": False,
                "error": "another vision request is already running",
            })
            return

        action = str(request.get("action", "")).strip().lower()
        if action not in {"capture", "align", "measure_placement"}:
            self.publish_result({
                "request_id": request_id,
                "success": False,
                "error": f"unsupported vision action: {action}",
            })
            return

        request["request_id"] = request_id
        request["action"] = action
        request["requested_at"] = time.monotonic()
        request["frames"] = {}
        request["frame_counts"] = {}
        self.pending_request = request
        self.get_logger().info(
            f"vision request accepted: id={request_id}, action={action}, "
            f"stage={request.get('stage', '-')}, reference={request.get('reference_set', '-')}"
        )

    def request_topics(self, request: dict) -> list[str]:
        if request["action"] == "capture":
            return [self.macro_topic, *self.micro_topics]
        if request["action"] == "measure_placement":
            return self.micro_topics
        if str(request.get("stage", "")).strip().lower() == "macro":
            return [self.macro_topic]
        return self.micro_topics

    def request_frames_ready(self, request: dict) -> bool:
        request_frames = request.get("frames", {})
        return all(topic in request_frames for topic in self.request_topics(request))

    def process_pending_request(self) -> None:
        request = self.pending_request
        if request is None:
            return
        if not self.request_frames_ready(request):
            elapsed = time.monotonic() - float(request["requested_at"])
            if elapsed >= self.request_timeout_sec:
                request_frames = request.get("frames", {})
                frame_counts = request.get("frame_counts", {})
                missing_topics = [
                    topic
                    for topic in self.request_topics(request)
                    if topic not in request_frames
                ]
                self.pending_request = None
                self.publish_result({
                    "request_id": request["request_id"],
                    "action": request["action"],
                    "success": False,
                    "error": (
                        "fresh camera frames were not received before timeout; "
                        f"missing={missing_topics}, received={frame_counts}"
                    ),
                    "timestamp": time.time(),
                })
            return

        try:
            if request["action"] == "capture":
                payload = self.capture_reference_set(request)
            elif request["action"] == "measure_placement":
                payload = self.measure_placement_error(request)
            else:
                payload = self.align_reference_set(request)
            payload.update({
                "request_id": request["request_id"],
                "action": request["action"],
                "success": True,
                "timestamp": time.time(),
            })
        except Exception as exc:  # noqa: BLE001
            payload = {
                "request_id": request["request_id"],
                "action": request["action"],
                "success": False,
                "error": str(exc),
                "timestamp": time.time(),
            }
            self.get_logger().warn(
                f"vision request failed: id={request['request_id']}, error={exc}"
            )

        self.pending_request = None
        self.publish_result(payload)

    def reference_set_dir(self, reference_set: str) -> Path:
        normalized = reference_set.strip().lower()
        if normalized not in {"pick", "place_empty", "place_stacked"}:
            raise ValueError(f"unsupported reference set: {reference_set}")
        return self.reference_dir / normalized

    def capture_reference_set(self, request: dict) -> dict:
        reference_set = str(request.get("reference_set", ""))
        output_dir = self.reference_set_dir(reference_set)
        output_dir.mkdir(parents=True, exist_ok=True)

        image_paths = {"macro": output_dir / "macro.png"}
        image_paths.update({
            f"micro_{index}": output_dir / f"micro_{index}.png"
            for index in range(1, 5)
        })
        request_frames = request["frames"]
        frames = {"macro": request_frames[self.macro_topic]}
        frames.update({
            f"micro_{index}": request_frames[topic]
            for index, topic in enumerate(self.micro_topics, start=1)
        })

        for name, frame in frames.items():
            final_path = image_paths[name]
            temporary_path = final_path.with_name(
                f".{final_path.stem}.tmp{final_path.suffix}"
            )
            if not cv2.imwrite(str(temporary_path), frame):
                raise OSError(f"failed to save reference image: {final_path}")
            verified = cv2.imread(str(temporary_path), cv2.IMREAD_COLOR)
            if verified is None or verified.shape != frame.shape:
                temporary_path.unlink(missing_ok=True)
                raise OSError(f"saved reference image validation failed: {final_path}")
            os.replace(temporary_path, final_path)

        metadata = {
            "reference_set": reference_set,
            "captured_at": time.time(),
            "gripper_pose_mm": self.current_pose,
            "images": {name: path.name for name, path in image_paths.items()},
        }
        metadata_path = output_dir / "metadata.json"
        temporary_metadata_path = output_dir / ".metadata.tmp.json"
        temporary_metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_metadata_path, metadata_path)
        self.get_logger().info(
            f"saved 5 reference images: {output_dir}"
        )
        return {
            "reference_set": reference_set,
            "output_dir": str(output_dir),
            "image_count": 5,
        }

    def align_reference_set(self, request: dict) -> dict:
        reference_set = str(request.get("reference_set", ""))
        reference_dir = self.reference_set_dir(reference_set)
        stage = str(request.get("stage", "micro")).strip().lower()
        target = str(request.get("target", "pick")).strip().lower()
        is_pick = target == "pick"
        request_frames = request["frames"]

        if stage == "macro":
            reference_path = reference_dir / "macro.png"
            if not reference_path.is_file():
                raise FileNotFoundError(f"missing macro reference: {reference_path}")
            result = self.aligner.align_reference_square_marker(
                reference_image=reference_path,
                current_image=request_frames[self.macro_topic],
                pixel_size=self.macro_pixel_size,
                reference_distance_mm=(
                    self.pick_macro_distance_mm
                    if is_pick
                    else self.place_macro_distance_mm
                ),
                axis_sign=self.macro_axis_sign,
            )
        elif stage == "micro":
            reference_paths = [
                reference_dir / f"micro_{index}.png"
                for index in range(1, 5)
            ]
            missing = [str(path) for path in reference_paths if not path.is_file()]
            if missing:
                raise FileNotFoundError(f"missing micro references: {missing}")
            result = self.aligner.align_reference_micro_set(
                reference_images=reference_paths,
                current_images=[request_frames[topic] for topic in self.micro_topics],
                pixel_size=self.micro_pixel_size,
                reference_distance_mm=(
                    self.pick_micro_distance_mm
                    if is_pick
                    else self.place_micro_distance_mm
                ),
                axis_sign=self.micro_axis_sign,
                normalized_rois=(None if is_pick else PLACE_MICRO_MARKER_ROIS),
            )
        else:
            raise ValueError(f"unsupported alignment stage: {stage}")

        result.update({
            "reference_set": reference_set,
            "stage": stage,
            "target": target,
        })
        return result

    def measure_placement_error(self, request: dict) -> dict:
        reference_set = str(request.get("reference_set", "place_stacked"))
        reference_dir = self.reference_set_dir(reference_set)
        reference_paths = [
            reference_dir / f"micro_{index}.png"
            for index in range(1, 5)
        ]
        missing = [str(path) for path in reference_paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"missing placement references: {missing}")

        current_images = [request["frames"][topic] for topic in self.micro_topics]
        common_args = {
            "reference_images": reference_paths,
            "current_images": current_images,
            "pixel_size": self.micro_pixel_size,
            "reference_distance_mm": self.place_micro_distance_mm,
            "axis_sign": self.micro_axis_sign,
        }
        substrate_result = self.aligner.align_reference_micro_set(
            **common_args,
            normalized_rois=PLACE_MICRO_MARKER_ROIS,
        )
        chip_result = self.aligner.align_reference_micro_set(
            **common_args,
            normalized_rois=CHIP_MICRO_MARKER_ROIS,
        )

        dtheta = float(chip_result["dtheta"]) - float(
            substrate_result["dtheta"]
        )
        dtheta = math.degrees(math.atan2(
            math.sin(math.radians(dtheta)),
            math.cos(math.radians(dtheta)),
        ))
        return {
            "reference_set": reference_set,
            "target": "chip_to_substrate",
            "stage": "measurement",
            "dx": float(chip_result["dx"]) - float(substrate_result["dx"]),
            "dy": float(chip_result["dy"]) - float(substrate_result["dy"]),
            "dz": float(chip_result["dz"]) - float(substrate_result["dz"]),
            "dtheta": dtheta,
            "score": min(
                float(chip_result["score"]),
                float(substrate_result["score"]),
            ),
            "chip_alignment": chip_result,
            "substrate_alignment": substrate_result,
        }

    def frames_ready(self) -> bool:
        now = time.monotonic()
        for topic in self.required_topics():
            if topic not in self.latest_frames:
                return False
            if now - self.latest_frame_times.get(topic, 0.0) > self.max_frame_age_sec:
                return False
        return True

    def align_latest_frames(self) -> None:
        if self.request_only:
            return
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
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
