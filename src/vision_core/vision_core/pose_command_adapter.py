import math
import threading
import time

import rclpy
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from geometry_msgs.msg import Pose
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from ros_gz_interfaces.msg import Contacts
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64, String

from vision_core.joint_commander import load_state, save_state
from vision_core.motion_profile import (
    AXES,
    JOINT_TOPICS,
    JOINT_LIMITS,
    PRESETS,
    JointPose,
    chip_to_joint_pose,
    gripper_abs_to_joint_pose,
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
CONTACT_DESCENT_EPSILON = 0.0002
CONTACT_PAIR_REARM_SEC = 5.0
PICK_CONTACT_TARGET_Z_MAX = -0.112
MIN_STACK_COUNT = 2
MAX_STACK_COUNT = 16
DEFAULT_STACK_COUNT = 4
PICKER_CONTACT_TOKENS = ("picker_contact_collision",)
SUBSTRATE_CONTACT_TOKENS = ("substrate_link_collision", "substrate_link")


def chip_model_name(layer_number: int) -> str:
    return "check_chip" if layer_number == 1 else f"check_chip_{layer_number}"


def format_joint_pose_si(pose: JointPose) -> str:
    return (
        f"(x={pose.x:.9f}m, y={pose.y:.9f}m, z={pose.z:.9f}m, "
        f"theta={pose.theta:.9f}rad)"
    )


def format_joint_error_si(errors: dict[str, float] | None) -> str:
    if errors is None:
        return "unavailable"
    return (
        f"(x={errors['x'] * 1e6:.3f}um, "
        f"y={errors['y'] * 1e6:.3f}um, "
        f"z={errors['z'] * 1e6:.3f}um, "
        f"theta={errors['theta'] * 1e6:.3f}urad)"
    )


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
        self.declare_parameter("restore_state", False)
        self.declare_parameter("idle_hold_period", 0.05)
        self.declare_parameter("stack_count", DEFAULT_STACK_COUNT)

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
        self.restore_state = bool(self.get_parameter("restore_state").value)
        self.idle_hold_period = float(
            self.get_parameter("idle_hold_period").value
        )
        self.stack_count = int(self.get_parameter("stack_count").value)
        if not MIN_STACK_COUNT <= self.stack_count <= MAX_STACK_COUNT:
            raise ValueError(
                f"stack_count must be between {MIN_STACK_COUNT} and "
                f"{MAX_STACK_COUNT}: {self.stack_count}"
            )
        self.chip_models = tuple(
            chip_model_name(index)
            for index in range(1, self.stack_count + 1)
        )
        self.active_chip_model = self.chip_models[0]
        self.active_support_model = "substrate"

        self.publishers_by_axis = {
            axis: self.create_publisher(Float64, topic, 10)
            for axis, topic in JOINT_TOPICS.items()
        }
        self.current_pose = (
            load_state(PRESETS["home"])
            if self.restore_state
            else PRESETS["home"]
        )
        self.actual_pose = None
        self.last_joint_state_time = 0.0
        self.feedback_lock = threading.Lock()
        self.contact_lock = threading.Lock()
        self.picker_contact_generation = 0
        self.substrate_contact_generation = 0
        self.placement_contact_last_seen = {}
        self.contact_motion_mode = "idle"
        self.active_picked_chip_model = None
        self.motion_stopped_by_contact = False
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
        self.active_stack_pair_subscription = self.create_subscription(
            String,
            "/robot/active_stack_pair",
            self.handle_active_stack_pair,
            10,
            callback_group=self.feedback_group,
        )
        self.create_subscription(
            Contacts,
            "/world/empty/model/substrate/link/substrate_link/"
            "sensor/substrate_contact_sensor/contact",
            self.handle_substrate_contacts,
            qos_profile_sensor_data,
            callback_group=self.feedback_group,
        )
        self.idle_hold_timer = self.create_timer(
            max(0.01, self.idle_hold_period),
            self.hold_current_target,
            callback_group=self.command_group,
        )
        self.chip_contact_subscriptions = [
            self.create_subscription(
                Contacts,
                f"/world/empty/model/{model_name}/link/chip_link/"
                "sensor/chip_contact_sensor/contact",
                self.handle_substrate_contacts,
                qos_profile_sensor_data,
                callback_group=self.feedback_group,
            )
            for model_name in self.chip_models
        ]

        self.get_logger().info(
            f"listening on /robot/command_pose as {self.coordinate_frame} coordinates "
            f"in {self.get_parameter('input_unit').value}; "
            f"stack_count={self.stack_count}"
        )
        if self.feedback_enabled:
            self.get_logger().info(
                "[SIM_JOINT_FEEDBACK][NOT_VISION] using Gazebo joint_state from "
                f"{self.joint_state_topic}; internal units=(m, m, m, rad)"
            )

    def hold_current_target(self) -> None:
        self.publish_pose(self.current_pose)

    def pose_to_joint_pose(self, msg: Pose) -> JointPose:
        x = msg.position.x * self.scale
        y = msg.position.y * self.scale
        z = msg.position.z * self.scale
        theta = yaw_from_pose(msg)

        if self.coordinate_frame == "chip":
            return chip_to_joint_pose(x, y, z, theta)
        if self.coordinate_frame in ("gripper_abs", "gripper", "absolute"):
            return gripper_abs_to_joint_pose(x, y, z, theta)
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

    def handle_substrate_contacts(self, msg: Contacts) -> None:
        for contact in msg.contacts:
            first_name = contact.collision1.name.lower()
            second_name = contact.collision2.name.lower()
            picker_chip_match = (
                any(token in first_name for token in PICKER_CONTACT_TOKENS)
                and self.collision_matches_model(
                    second_name,
                    self.active_chip_model,
                )
            ) or (
                any(token in second_name for token in PICKER_CONTACT_TOKENS)
                and self.collision_matches_model(
                    first_name,
                    self.active_chip_model,
                )
            )
            direct_match = (
                self.collision_matches_model(
                    first_name,
                    self.active_support_model,
                )
                and self.collision_matches_model(
                    second_name,
                    self.active_chip_model,
                )
            )
            reverse_match = (
                self.collision_matches_model(
                    second_name,
                    self.active_support_model,
                )
                and self.collision_matches_model(
                    first_name,
                    self.active_chip_model,
                )
            )
            if not (picker_chip_match or direct_match or reverse_match):
                continue

            contact_pair = tuple(sorted((first_name, second_name)))
            now = time.monotonic()
            with self.contact_lock:
                if picker_chip_match:
                    if self.contact_motion_mode != "pick":
                        continue
                    self.active_picked_chip_model = self.active_chip_model
                else:
                    if (
                        self.contact_motion_mode != "place"
                        or self.active_picked_chip_model != self.active_chip_model
                    ):
                        continue

                last_seen = self.placement_contact_last_seen.get(
                    contact_pair,
                    0.0,
                )
                self.placement_contact_last_seen[contact_pair] = now
                if now - last_seen <= CONTACT_PAIR_REARM_SEC:
                    continue
                if picker_chip_match:
                    self.picker_contact_generation += 1
                else:
                    self.substrate_contact_generation += 1

    def handle_active_stack_pair(self, msg: String) -> None:
        try:
            support_model, chip_model = (
                part.strip()
                for part in msg.data.split("|", maxsplit=1)
            )
        except ValueError:
            self.get_logger().warn(
                f"invalid /robot/active_stack_pair payload: {msg.data}"
            )
            return
        valid_supports = {"substrate", *self.chip_models}
        if (
            chip_model not in self.chip_models
            or support_model not in valid_supports
            or support_model == chip_model
        ):
            self.get_logger().warn(
                f"unsupported active stack pair: {support_model}|{chip_model}"
            )
            return
        self.active_support_model = support_model
        self.active_chip_model = chip_model
        self.active_picked_chip_model = None
        self.get_logger().info(
            f"active placement contact pair: {support_model}<->{chip_model}"
        )

    def collision_matches_model(
        self,
        collision_name: str,
        model_name: str,
    ) -> bool:
        normalized = collision_name.lower()
        if model_name == "substrate":
            return any(
                token in normalized
                for token in SUBSTRATE_CONTACT_TOKENS
            )
        tokens = (f"{model_name}::", f"/model/{model_name}/")
        return any(token in normalized for token in tokens)

    def get_picker_contact_generation(self) -> int:
        with self.contact_lock:
            return self.picker_contact_generation

    def get_substrate_contact_generation(self) -> int:
        with self.contact_lock:
            return self.substrate_contact_generation

    def stop_descent_on_substrate_contact(
        self,
        descending: bool,
        monitor_picker_contact: bool,
        initial_picker_contact_generation: int,
        initial_placement_contact_generation: int,
    ) -> bool:
        if not descending:
            return False

        if monitor_picker_contact:
            contact_detected = (
                self.get_picker_contact_generation()
                > initial_picker_contact_generation
            )
            contact_name = "picker-chip"
        else:
            contact_detected = (
                self.get_substrate_contact_generation()
                > initial_placement_contact_generation
            )
            contact_name = "placement"
        if not contact_detected:
            return False

        actual = self.get_actual_pose()
        hold_target = actual if actual is not None else self.current_pose
        self.publish_pose(hold_target)
        self.current_pose = hold_target
        save_state(hold_target)
        self.motion_stopped_by_contact = True
        self.get_logger().info(
            f"[SIM_CONTACT_SENSOR][NOT_VISION] {contact_name} contact detected: "
            "stopping Z descent at "
            f"joint_z={hold_target.z:.6f}m"
        )
        return True

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

    def wait_until_reached(
        self,
        target: JointPose,
        descending: bool = False,
        monitor_picker_contact: bool = False,
        initial_picker_contact_generation: int = 0,
        initial_placement_contact_generation: int = 0,
    ) -> bool:
        if not self.feedback_enabled:
            return False

        deadline = time.monotonic() + self.arrival_timeout
        first_feedback_deadline = time.monotonic() + self.initial_feedback_timeout
        stable_count = 0
        last_errors = None

        while time.monotonic() < deadline:
            if self.stop_descent_on_substrate_contact(
                descending,
                monitor_picker_contact,
                initial_picker_contact_generation,
                initial_placement_contact_generation,
            ):
                return False
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
                    self.current_pose = target
                    save_state(target)
                    self.get_logger().info(
                        "[SIM_JOINT_FEEDBACK][NOT_VISION] arrived: "
                        f"target_SI={format_joint_pose_si(target)}, "
                        f"actual_SI={format_joint_pose_si(actual)}, "
                        f"abs_error={format_joint_error_si(last_errors)}"
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
            "[SIM_JOINT_FEEDBACK][NOT_VISION] arrival timeout: "
            f"target_SI={format_joint_pose_si(target)}, "
            f"actual_SI={format_joint_pose_si(actual) if actual else 'unavailable'}, "
            f"abs_error={format_joint_error_si(last_errors)}"
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
        self.get_logger().info(
            "[SIM_JOINT_TARGET][NOT_VISION] /robot/command_pose -> "
            f"target_SI={format_joint_pose_si(target)}"
        )
        actual_start = self.get_actual_pose()
        if actual_start is not None:
            self.current_pose = actual_start

        descending = target.z < self.current_pose.z - CONTACT_DESCENT_EPSILON
        monitor_picker_contact = target.z <= PICK_CONTACT_TARGET_Z_MAX
        initial_picker_contact_generation = self.get_picker_contact_generation()
        initial_placement_contact_generation = self.get_substrate_contact_generation()
        self.motion_stopped_by_contact = False
        contact_motion_mode = "idle"
        if descending:
            contact_motion_mode = "pick" if monitor_picker_contact else "place"
        with self.contact_lock:
            self.contact_motion_mode = contact_motion_mode

        linear_delta = max(
            abs(target.x - self.current_pose.x),
            abs(target.y - self.current_pose.y),
            abs(target.z - self.current_pose.z),
        )
        theta_delta = abs(math.atan2(
            math.sin(target.theta - self.current_pose.theta),
            math.cos(target.theta - self.current_pose.theta),
        ))
        profile_steps = max(
            4,
            int(math.ceil(linear_delta / 0.00025)),
            int(math.ceil(theta_delta / math.radians(0.25))),
        )
        profile_steps = min(self.steps, profile_steps)

        try:
            for pose in linear_profile(self.current_pose, target, profile_steps):
                if self.stop_descent_on_substrate_contact(
                    descending,
                    monitor_picker_contact,
                    initial_picker_contact_generation,
                    initial_placement_contact_generation,
                ):
                    return
                self.publish_pose(pose)
                time.sleep(self.period)

            if not self.wait_until_reached(
                target,
                descending=descending,
                monitor_picker_contact=monitor_picker_contact,
                initial_picker_contact_generation=initial_picker_contact_generation,
                initial_placement_contact_generation=initial_placement_contact_generation,
            ):
                if not self.motion_stopped_by_contact:
                    self.hold_pose(target)
                save_state(self.current_pose)
        finally:
            with self.contact_lock:
                self.contact_motion_mode = "idle"

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
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.remove_node(node)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
