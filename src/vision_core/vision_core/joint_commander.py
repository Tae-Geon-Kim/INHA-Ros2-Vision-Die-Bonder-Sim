import argparse
import json
import os
from pathlib import Path
import time
from typing import Iterable

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64

from vision_core.motion_profile import (
    AXES,
    DEMO_SEQUENCE,
    JOINT_TOPICS,
    PRESETS,
    JointPose,
    chip_to_joint_pose,
    linear_profile,
    poses_from_names,
    validate_pose,
)


STATE_PATH = Path(os.environ.get("JOINT_COMMANDER_STATE", "/tmp/joint_commander_state.json"))


def load_state(default: JointPose) -> JointPose:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        pose = JointPose(
            x=float(data.get("x", default.x)),
            y=float(data.get("y", default.y)),
            z=float(data.get("z", default.z)),
            theta=float(data.get("theta", default.theta)),
        )
        validate_pose(pose)
        return pose
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def save_state(pose: JointPose) -> None:
    STATE_PATH.write_text(json.dumps(pose.as_dict()), encoding="utf-8")


class JointCommander(Node):
    def __init__(self, initial_pose: JointPose | None = None) -> None:
        super().__init__("joint_commander")
        self.publishers_by_axis = {
            axis: self.create_publisher(Float64, topic, 10)
            for axis, topic in JOINT_TOPICS.items()
        }
        self.current_pose = initial_pose or PRESETS["home"]

    def publish_pose(self, pose: JointPose) -> None:
        validate_pose(pose)
        values = pose.as_dict()
        for axis in AXES:
            msg = Float64()
            msg.data = float(values[axis])
            self.publishers_by_axis[axis].publish(msg)
        self.current_pose = pose

    def hold_pose(self, pose: JointPose, duration: float, period: float) -> None:
        if duration <= 0.0:
            return

        end_time = time.monotonic() + duration
        while time.monotonic() < end_time:
            self.publish_pose(pose)
            rclpy.spin_once(self, timeout_sec=0.0)
            time.sleep(period)

    def move_to(self, target: JointPose, steps: int, period: float, hold: float = 0.8) -> None:
        self.get_logger().info(f"moving from {self.current_pose} to {target}")
        for pose in linear_profile(self.current_pose, target, steps):
            self.publish_pose(pose)
            rclpy.spin_once(self, timeout_sec=0.0)
            time.sleep(period)
        self.hold_pose(target, hold, period)

    def run_sequence(
        self,
        poses: Iterable[JointPose],
        steps: int,
        period: float,
        dwell: float,
    ) -> None:
        for pose in poses:
            self.get_logger().info(f"moving to {pose}")
            self.move_to(pose, steps, period)
            time.sleep(dwell)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish ROS2 Float64 joint commands for robot_system."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preset_parser = subparsers.add_parser("preset")
    preset_parser.add_argument("name", choices=sorted(PRESETS.keys()))
    preset_parser.add_argument("--steps", type=int, default=120)
    preset_parser.add_argument("--period", type=float, default=0.02)
    preset_parser.add_argument("--hold", type=float, default=0.8)

    xyz_parser = subparsers.add_parser("xyz")
    xyz_parser.add_argument("x", type=float)
    xyz_parser.add_argument("y", type=float)
    xyz_parser.add_argument("z", type=float)
    xyz_parser.add_argument("--theta", type=float, default=0.0)
    xyz_parser.add_argument("--steps", type=int, default=120)
    xyz_parser.add_argument("--period", type=float, default=0.02)
    xyz_parser.add_argument("--hold", type=float, default=0.8)

    chip_xyz_parser = subparsers.add_parser(
        "chip_xyz",
        help="Move using chip-centered coordinates. Z is height above the chip surface.",
    )
    chip_xyz_parser.add_argument("x", type=float)
    chip_xyz_parser.add_argument("y", type=float)
    chip_xyz_parser.add_argument("z", type=float)
    chip_xyz_parser.add_argument("--theta", type=float, default=0.0)
    chip_xyz_parser.add_argument("--steps", type=int, default=120)
    chip_xyz_parser.add_argument("--period", type=float, default=0.02)
    chip_xyz_parser.add_argument("--hold", type=float, default=0.8)

    demo_parser = subparsers.add_parser("demo")
    demo_parser.add_argument("--steps", type=int, default=120)
    demo_parser.add_argument("--period", type=float, default=0.02)
    demo_parser.add_argument("--dwell", type=float, default=1.0)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    rclpy.init()
    commander = JointCommander(initial_pose=load_state(PRESETS["home"]))

    try:
        time.sleep(0.5)
        if args.command == "preset":
            commander.move_to(PRESETS[args.name], args.steps, args.period, args.hold)
        elif args.command == "xyz":
            commander.move_to(
                JointPose(args.x, args.y, args.z, args.theta),
                args.steps,
                args.period,
                args.hold,
            )
        elif args.command == "chip_xyz":
            commander.move_to(
                chip_to_joint_pose(args.x, args.y, args.z, args.theta),
                args.steps,
                args.period,
                args.hold,
            )
        elif args.command == "demo":
            commander.run_sequence(
                poses_from_names(DEMO_SEQUENCE),
                args.steps,
                args.period,
                args.dwell,
            )
        else:
            parser.error(f"unknown command: {args.command}")
        save_state(commander.current_pose)
    finally:
        commander.destroy_node()
        rclpy.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
