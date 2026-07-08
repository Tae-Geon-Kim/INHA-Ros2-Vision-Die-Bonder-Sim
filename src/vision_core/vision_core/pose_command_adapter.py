import math
import time

import rclpy
from geometry_msgs.msg import Pose
from rclpy.node import Node
from std_msgs.msg import Float64

from vision_core.joint_commander import load_state, save_state
from vision_core.motion_profile import (
    AXES,
    JOINT_TOPICS,
    PRESETS,
    JointPose,
    chip_to_joint_pose,
    linear_profile,
    validate_pose,
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

        self.scale = unit_scale(self.get_parameter("input_unit").value)
        self.coordinate_frame = self.get_parameter("coordinate_frame").value
        self.steps = int(self.get_parameter("steps").value)
        self.period = float(self.get_parameter("period").value)
        self.hold = float(self.get_parameter("hold").value)

        self.publishers_by_axis = {
            axis: self.create_publisher(Float64, topic, 10)
            for axis, topic in JOINT_TOPICS.items()
        }
        self.current_pose = load_state(PRESETS["home"])
        self.create_subscription(Pose, "/robot/command_pose", self.handle_command, 10)

        self.get_logger().info(
            f"listening on /robot/command_pose as {self.coordinate_frame} coordinates "
            f"in {self.get_parameter('input_unit').value}"
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

    def hold_pose(self, pose: JointPose) -> None:
        if self.hold <= 0.0:
            return

        end_time = time.monotonic() + self.hold
        while time.monotonic() < end_time:
            self.publish_pose(pose)
            time.sleep(self.period)

    def move_to(self, target: JointPose) -> None:
        self.get_logger().info(f"/robot/command_pose -> {target}")
        for pose in linear_profile(self.current_pose, target, self.steps):
            self.publish_pose(pose)
            time.sleep(self.period)
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

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
