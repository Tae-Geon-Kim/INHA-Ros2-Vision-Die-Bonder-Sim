import math
import threading
import time

import rclpy
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from geometry_msgs.msg import Pose
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64

from vision_core.joint_commander import load_state, save_state
from vision_core.motion_profile import (
    AXES,
    JOINT_TOPICS,
    JOINT_LIMITS,
    PRESETS,
    JointPose,
    chip_to_joint_pose,
    linear_profile,
    validate_pose,
)


JOINT_NAME_TO_AXIS = {
    "joint_x": "x",
    "joint_y": "y",
    "joint_z": "z",
    "joint_theta": "theta",
}

LIMIT_EPSILON = 1e-6


def yaw_from_pose(pose: Pose) -> float:
    q = pose.orientation
    if q.x == 0.0 and q.y == 0.0 and q.z == 0.0 and q.w == 0.0:
        return 0.0

    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


def unit_scale(unit: str) -> float:
    normalized = unit.lower()
    if normalized in ("m", "meter", "meters"):
        return 1.0
    if normalized in ("mm", "millimeter", "millimeters"):
        return 0.001
    raise ValueError(f"unsupported input_unit: {unit}")


class PoseCommandAdapter(Node):
    def __init__(self) -> None:
        super().__init__("pose_command_adapter")

        self.declare_parameter("input_unit", "mm")
        self.declare_parameter("coordinate_frame", "chip")
        self.declare_parameter("steps", 120)
        self.declare_parameter("period", 0.02)
        self.declare_parameter("hold", 0.8)
        self.declare_parameter("feedback_enabled", True)
        self.declare_parameter("joint_state_topic", "/model/robot_system/joint_state")
        self.declare_parameter("arrival_timeout", 8.0)
        self.declare_parameter("initial_feedback_timeout", 0.5)
        self.declare_parameter("arrival_tolerance", 0.002)
        self.declare_parameter("z_tolerance", 0.008)
        self.declare_parameter("theta_tolerance", 0.02)
        self.declare_parameter("feedback_stale_timeout", 1.0)
        self.declare_parameter("settle_samples", 5)

        self.scale = unit_scale(self.get_parameter("input_unit").value)
        self.coordinate_frame = self.get_parameter("coordinate_frame").value
        self.steps = int(self.get_parameter("steps").value)
        self.period = float(self.get_parameter("period").value)
        self.hold = float(self.get_parameter("hold").value)
        self.feedback_enabled = bool(self.get_parameter("feedback_enabled").value)
        self.joint_state_topic = self.get_parameter("joint_state_topic").value
        self.arrival_timeout = float(self.get_parameter("arrival_timeout").value)
        self.initial_feedback_timeout = float(
            self.get_parameter("initial_feedback_timeout").value
        )
        self.arrival_tolerance = float(self.get_parameter("arrival_tolerance").value)
        self.z_tolerance = float(self.get_parameter("z_tolerance").value)
        self.theta_tolerance = float(self.get_parameter("theta_tolerance").value)
        self.feedback_stale_timeout = float(
            self.get_parameter("feedback_stale_timeout").value
        )
        self.settle_samples = int(self.get_parameter("settle_samples").value)

        self.publishers_by_axis = {
            axis: self.create_publisher(Float64, topic, 10)
            for axis, topic in JOINT_TOPICS.items()
        }
        self.current_pose = load_state(PRESETS["home"])
        self.actual_pose = None
        self.last_joint_state_time = 0.0
        self.feedback_lock = threading.Lock()
        self.command_group = MutuallyExclusiveCallbackGroup()
        self.feedback_group = ReentrantCallbackGroup()
        self.create_subscription(
            Pose,
            "/robot/command_pose",
            self.handle_command,
            10,
            callback_group=self.command_group,
        )
        if self.feedback_enabled:
            self.create_subscription(
                JointState,
                self.joint_state_topic,
                self.handle_joint_state,
                10,
                callback_group=self.feedback_group,
            )

        self.get_logger().info(
            f"listening on /robot/command_pose as {self.coordinate_frame} coordinates "
            f"in {self.get_parameter('input_unit').value}"
        )
        if self.feedback_enabled:
            self.get_logger().info(
                f"using actual joint feedback from {self.joint_state_topic}"
            )

    def pose_to_joint_pose(self, msg: Pose) -> JointPose:
        x = msg.position.x * self.scale
        y = msg.position.y * self.scale
        z = msg.position.z * self.scale
        theta = yaw_from_pose(msg)

        if self.coordinate_frame == "chip":
            return chip_to_joint_pose(x, y, z, theta)
        if self.coordinate_frame == "joint":
            return JointPose(x, y, z, theta)

        raise ValueError(f"unsupported coordinate_frame: {self.coordinate_frame}")

    def publish_pose(self, pose: JointPose) -> None:
        validate_pose(pose)
        values = pose.as_dict()
        for axis in AXES:
            msg = Float64()
            msg.data = float(values[axis])
            self.publishers_by_axis[axis].publish(msg)
        self.current_pose = pose

    def axis_from_joint_name(self, name: str) -> str | None:
        for joint_name, axis in JOINT_NAME_TO_AXIS.items():
            if name == joint_name or name.endswith(f"/{joint_name}"):
                return axis
            if name.endswith(f"::{joint_name}"):
                return axis
        return None

    def handle_joint_state(self, msg: JointState) -> None:
        values = {}
        for index, name in enumerate(msg.name):
            if index >= len(msg.position):
                continue

            axis = self.axis_from_joint_name(name)
            if axis is not None:
                values[axis] = self.clamp_feedback_value(axis, float(msg.position[index]))

        if not all(axis in values for axis in AXES):
            return

        actual_pose = JointPose(
            values["x"],
            values["y"],
            values["z"],
            values["theta"],
        )
        with self.feedback_lock:
            self.actual_pose = actual_pose
            self.last_joint_state_time = time.monotonic()

    def clamp_feedback_value(self, axis: str, value: float) -> float:
        if axis not in JOINT_LIMITS:
            return value

        lower, upper = JOINT_LIMITS[axis]
        if lower - LIMIT_EPSILON <= value < lower:
            return lower
        if upper < value <= upper + LIMIT_EPSILON:
            return upper
        return value

    def get_actual_pose(self) -> JointPose | None:
        with self.feedback_lock:
            if self.actual_pose is None:
                return None
            if time.monotonic() - self.last_joint_state_time > self.feedback_stale_timeout:
                return None
            return self.actual_pose

    def pose_errors(self, actual: JointPose, target: JointPose) -> dict[str, float]:
        return {
            "x": abs(actual.x - target.x),
            "y": abs(actual.y - target.y),
            "z": abs(actual.z - target.z),
            "theta": abs(math.atan2(
                math.sin(actual.theta - target.theta),
                math.cos(actual.theta - target.theta),
            )),
        }

    def reached_target(self, actual: JointPose, target: JointPose) -> bool:
        errors = self.pose_errors(actual, target)
        return (
            errors["x"] <= self.arrival_tolerance
            and errors["y"] <= self.arrival_tolerance
            and errors["z"] <= self.z_tolerance
            and errors["theta"] <= self.theta_tolerance
        )

    def wait_until_reached(self, target: JointPose) -> bool:
        if not self.feedback_enabled:
            return False

        deadline = time.monotonic() + self.arrival_timeout
        first_feedback_deadline = time.monotonic() + self.initial_feedback_timeout
        stable_count = 0
        last_errors = None

        while time.monotonic() < deadline:
            self.publish_pose(target)
            actual = self.get_actual_pose()
            if actual is None:
                if time.monotonic() >= first_feedback_deadline:
                    self.get_logger().warn(
                        "no fresh joint feedback; falling back to command-state tracking"
                    )
                    return False
                time.sleep(self.period)
                continue

            last_errors = self.pose_errors(actual, target)
            if self.reached_target(actual, target):
                stable_count += 1
                if stable_count >= self.settle_samples:
                    self.current_pose = actual
                    save_state(actual)
                    self.get_logger().info(
                        f"arrived with feedback: actual={actual}, errors={last_errors}"
                    )
                    return True
            else:
                stable_count = 0

            time.sleep(self.period)

        actual = self.get_actual_pose()
        if actual is not None:
            self.current_pose = actual
            save_state(actual)

        self.get_logger().warn(
            f"feedback arrival timeout: target={target}, actual={actual}, "
            f"errors={last_errors}"
        )
        return False

    def hold_pose(self, pose: JointPose) -> None:
        if self.hold <= 0.0:
            return

        end_time = time.monotonic() + self.hold
        while time.monotonic() < end_time:
            self.publish_pose(pose)
            time.sleep(self.period)

    def move_to(self, target: JointPose) -> None:
        self.get_logger().info(f"/robot/command_pose -> {target}")
        actual_start = self.get_actual_pose()
        if actual_start is not None:
            self.current_pose = actual_start

        for pose in linear_profile(self.current_pose, target, self.steps):
            self.publish_pose(pose)
            time.sleep(self.period)

        if not self.wait_until_reached(target):
            self.hold_pose(target)
            save_state(self.current_pose)

    def handle_command(self, msg: Pose) -> None:
        try:
            self.move_to(self.pose_to_joint_pose(msg))
        except ValueError as exc:
            self.get_logger().error(str(exc))


def main(args=None) -> int:
    rclpy.init(args=args)
    node = PoseCommandAdapter()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)

    try:
        executor.spin()
    finally:
        executor.remove_node(node)
        node.destroy_node()
        rclpy.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
