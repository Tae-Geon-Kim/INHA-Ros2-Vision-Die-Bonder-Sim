import math
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, Tuple


AXES = ("x", "y", "z", "theta")

JOINT_TOPICS = {
    "x": "/model/robot_system/joint/joint_x/cmd_pos",
    "y": "/model/robot_system/joint/joint_y/cmd_pos",
    "z": "/model/robot_system/joint/joint_z/cmd_pos",
    "theta": "/model/robot_system/joint/joint_theta/cmd_pos",
}

JOINT_LIMITS = {
    "x": (-0.4, 0.4),
    "y": (-0.4, 0.4),
    "z": (-0.115, 0.1),
}

RANGE_DEMO_RATIO = 0.75
THETA_DEMO_LIMIT = math.radians(180.0 * RANGE_DEMO_RATIO)

CHIP_SURFACE_Z = 0.05005
CHIP_JOINT_X_AT_CENTER = 0.0
CHIP_JOINT_Y_AT_CENTER = 0.0
TOOL_FRAME_Z_AT_ZERO = 0.215
TOOL_REFERENCE_Z_OFFSET = -0.0505
TOOL_REFERENCE_Z_AT_ZERO = TOOL_FRAME_Z_AT_ZERO + TOOL_REFERENCE_Z_OFFSET


@dataclass(frozen=True)
class JointPose:
    x: float
    y: float
    z: float
    theta: float = 0.0

    def as_dict(self) -> Dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "theta": self.theta,
        }


def chip_to_joint_pose(x: float, y: float, z: float, theta: float = 0.0) -> JointPose:
    """Convert chip-centered coordinates to robot joint commands.

    x/y are offsets from the chip center. z is the tool reference height above
    the chip surface.
    """
    joint_z = CHIP_SURFACE_Z + z - TOOL_REFERENCE_Z_AT_ZERO
    return JointPose(
        x=CHIP_JOINT_X_AT_CENTER + x,
        y=CHIP_JOINT_Y_AT_CENTER - y,
        z=joint_z,
        theta=theta,
    )


PRESETS = {
    "home": JointPose(0.0, 0.0, 0.0, 0.0),
    "ready": JointPose(0.0, 0.0, 0.03, 0.0),
    "z_high": JointPose(0.0, 0.0, 0.095, 0.0),
    "z_low": JointPose(0.0, 0.0, -0.11, 0.0),
    "chip_ready": chip_to_joint_pose(0.0, 0.0, 0.03, 0.0),
    "chip_pick": chip_to_joint_pose(0.0, 0.0, 0.005, 0.0),
    "pick": JointPose(-0.15, 0.12, 0.03, 0.0),
    "pick_down": JointPose(-0.15, 0.12, -0.08, 0.0),
    "place": JointPose(0.25, -0.12, 0.03, 0.0),
    "place_down": JointPose(0.25, -0.12, -0.08, 0.0),
    "range_x_pos": JointPose(0.4 * RANGE_DEMO_RATIO, 0.0, 0.0, 0.0),
    "range_x_neg": JointPose(-0.4 * RANGE_DEMO_RATIO, 0.0, 0.0, 0.0),
    "range_y_pos": JointPose(0.0, 0.4 * RANGE_DEMO_RATIO, 0.0, 0.0),
    "range_y_neg": JointPose(0.0, -0.4 * RANGE_DEMO_RATIO, 0.0, 0.0),
    "range_z_high": JointPose(0.0, 0.0, 0.1 * RANGE_DEMO_RATIO, 0.0),
    "range_z_low": JointPose(0.0, 0.0, -0.115 * RANGE_DEMO_RATIO, 0.0),
    "range_theta_pos": JointPose(0.0, 0.0, 0.0, THETA_DEMO_LIMIT),
    "range_theta_neg": JointPose(0.0, 0.0, 0.0, -THETA_DEMO_LIMIT),
}

DEMO_SEQUENCE = (
    "home",
    "pick",
    "pick_down",
    "pick",
    "place",
    "place_down",
    "place",
    "home",
)

RANGE_DEMO_SEQUENCE = (
    "home",
    "range_x_pos",
    "range_x_neg",
    "home",
    "range_y_pos",
    "range_y_neg",
    "home",
    "range_z_high",
    "range_z_low",
    "home",
    "range_theta_pos",
    "range_theta_neg",
    "home",
)


def validate_pose(pose: JointPose) -> None:
    for axis, value in pose.as_dict().items():
        if axis not in JOINT_LIMITS:
            continue
        lower, upper = JOINT_LIMITS[axis]
        if not lower <= value <= upper:
            raise ValueError(
                f"{axis}={value} is outside joint limit [{lower}, {upper}]"
            )


def interpolate(start: JointPose, end: JointPose, ratio: float) -> JointPose:
    values = {}
    start_values = start.as_dict()
    end_values = end.as_dict()
    for axis in AXES:
        values[axis] = start_values[axis] + (end_values[axis] - start_values[axis]) * ratio
    return JointPose(**values)


def linear_profile(start: JointPose, end: JointPose, steps: int) -> Iterator[JointPose]:
    if steps < 1:
        raise ValueError("steps must be greater than 0")

    validate_pose(start)
    validate_pose(end)

    for step in range(1, steps + 1):
        yield interpolate(start, end, step / steps)


def poses_from_names(names: Iterable[str]) -> Tuple[JointPose, ...]:
    poses = []
    for name in names:
        if name not in PRESETS:
            raise ValueError(f"unknown preset: {name}")
        poses.append(PRESETS[name])
    return tuple(poses)
