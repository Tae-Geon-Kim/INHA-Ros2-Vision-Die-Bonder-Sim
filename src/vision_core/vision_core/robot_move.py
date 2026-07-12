import argparse
import json
import os
import subprocess
import sys
import time


STATE_PATH = "/tmp/robot_move_state.json"

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

CHIP_SURFACE_Z = 0.05005
CHIP_JOINT_X_AT_CENTER = 0.0
CHIP_JOINT_Y_AT_CENTER = 0.0
TOOL_FRAME_Z_AT_ZERO = 0.215
TOOL_REFERENCE_Z_OFFSET = -0.050
TOOL_REFERENCE_Z_AT_ZERO = TOOL_FRAME_Z_AT_ZERO + TOOL_REFERENCE_Z_OFFSET

DEFAULT_STATE = {"x": 0.0, "y": 0.0, "z": 0.0, "theta": 0.0}

PRESETS = {
    "home": {"x": 0.0, "y": 0.0, "z": 0.0, "theta": 0.0},
    "ready": {"x": 0.0, "y": 0.0, "z": 0.03, "theta": 0.0},
    "z_high": {"x": 0.0, "y": 0.0, "z": 0.095, "theta": 0.0},
    "z_low": {"x": 0.0, "y": 0.0, "z": -0.11, "theta": 0.0},
    "chip_ready": {"x": 0.0, "y": -0.0, "z": CHIP_SURFACE_Z + 0.03 - TOOL_REFERENCE_Z_AT_ZERO, "theta": 0.0},
    "chip_pick": {"x": 0.0, "y": -0.0, "z": CHIP_SURFACE_Z + 0.005 - TOOL_REFERENCE_Z_AT_ZERO, "theta": 0.0},
    "pick": {"x": -0.15, "y": 0.12, "z": 0.03, "theta": 0.0},
    "pick_down": {"x": -0.15, "y": 0.12, "z": -0.08, "theta": 0.0},
    "place": {"x": 0.25, "y": -0.12, "z": 0.03, "theta": 0.0},
    "place_down": {"x": 0.25, "y": -0.12, "z": -0.08, "theta": 0.0},
}

DEMO_SEQUENCE = [
    "home",
    "pick",
    "pick_down",
    "pick",
    "place",
    "place_down",
    "place",
    "home",
]


def validate_position(position):
    for axis, value in position.items():
        if axis not in JOINT_LIMITS:
            continue
        lower, upper = JOINT_LIMITS[axis]
        if not lower <= value <= upper:
            raise ValueError(
                f"{axis}={value} is outside joint limit [{lower}, {upper}]"
            )


def load_state():
    if not os.path.exists(STATE_PATH):
        return DEFAULT_STATE.copy()
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as state_file:
            state = json.load(state_file)
    except (OSError, json.JSONDecodeError):
        return DEFAULT_STATE.copy()

    return {
        "x": float(state.get("x", DEFAULT_STATE["x"])),
        "y": float(state.get("y", DEFAULT_STATE["y"])),
        "z": float(state.get("z", DEFAULT_STATE["z"])),
        "theta": float(state.get("theta", DEFAULT_STATE["theta"])),
    }


def save_state(position):
    with open(STATE_PATH, "w", encoding="utf-8") as state_file:
        json.dump(position, state_file)


def publish_joint(axis, value):
    topic = JOINT_TOPICS[axis]
    command = [
        "ign",
        "topic",
        "-t",
        topic,
        "-m",
        "ignition.msgs.Double",
        "-p",
        f"data: {value}",
    ]
    subprocess.run(command, check=True)


def move_to(position):
    validate_position(position)
    for axis in ("x", "y", "z", "theta"):
        if axis in position:
            publish_joint(axis, position[axis])
    save_state({
        "x": position.get("x", DEFAULT_STATE["x"]),
        "y": position.get("y", DEFAULT_STATE["y"]),
        "z": position.get("z", DEFAULT_STATE["z"]),
        "theta": position.get("theta", DEFAULT_STATE["theta"]),
    })


def interpolate_position(start, end, ratio):
    return {
        axis: start[axis] + (end[axis] - start[axis]) * ratio
        for axis in ("x", "y", "z", "theta")
    }


def move_smooth(start, end, steps, step_delay):
    validate_position(start)
    validate_position(end)
    for step in range(1, steps + 1):
        ratio = step / steps
        move_to(interpolate_position(start, end, ratio))
        time.sleep(step_delay)


def run_preset(name, instant, steps, step_delay):
    if name not in PRESETS:
        raise ValueError(f"unknown preset: {name}")
    target = PRESETS[name]
    if instant:
        move_to(target)
        return
    move_smooth(load_state(), target, steps, step_delay)


def run_xyz(position, instant, steps, step_delay):
    if instant:
        move_to(position)
        return
    move_smooth(load_state(), position, steps, step_delay)


def chip_to_joint_position(x, y, z, theta):
    return {
        "x": CHIP_JOINT_X_AT_CENTER + x,
        "y": CHIP_JOINT_Y_AT_CENTER - y,
        "z": CHIP_SURFACE_Z + z - TOOL_REFERENCE_Z_AT_ZERO,
        "theta": theta,
    }


def run_demo(delay, steps, step_delay):
    current = PRESETS[DEMO_SEQUENCE[0]]
    print(f"[robot_move] {DEMO_SEQUENCE[0]}: {current}")
    move_to(current)
    time.sleep(delay)

    for preset in DEMO_SEQUENCE[1:]:
        target = PRESETS[preset]
        print(f"[robot_move] {preset}: {target}")
        move_smooth(current, target, steps, step_delay)
        current = target
        time.sleep(delay)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Send simple Gazebo joint position commands to robot_system."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preset_parser = subparsers.add_parser("preset")
    preset_parser.add_argument("name", choices=sorted(PRESETS.keys()))
    preset_parser.add_argument("--instant", action="store_true")
    preset_parser.add_argument("--steps", type=int, default=80)
    preset_parser.add_argument("--step-delay", type=float, default=0.04)

    xyz_parser = subparsers.add_parser("xyz")
    xyz_parser.add_argument("x", type=float)
    xyz_parser.add_argument("y", type=float)
    xyz_parser.add_argument("z", type=float)
    xyz_parser.add_argument("--theta", type=float, default=0.0)
    xyz_parser.add_argument("--instant", action="store_true")
    xyz_parser.add_argument("--steps", type=int, default=80)
    xyz_parser.add_argument("--step-delay", type=float, default=0.04)

    chip_xyz_parser = subparsers.add_parser("chip_xyz")
    chip_xyz_parser.add_argument("x", type=float)
    chip_xyz_parser.add_argument("y", type=float)
    chip_xyz_parser.add_argument("z", type=float)
    chip_xyz_parser.add_argument("--theta", type=float, default=0.0)
    chip_xyz_parser.add_argument("--instant", action="store_true")
    chip_xyz_parser.add_argument("--steps", type=int, default=80)
    chip_xyz_parser.add_argument("--step-delay", type=float, default=0.04)

    demo_parser = subparsers.add_parser("demo")
    demo_parser.add_argument("--delay", type=float, default=1.5)
    demo_parser.add_argument("--steps", type=int, default=100)
    demo_parser.add_argument("--step-delay", type=float, default=0.04)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "preset":
            run_preset(args.name, args.instant, args.steps, args.step_delay)
        elif args.command == "xyz":
            run_xyz({
                "x": args.x,
                "y": args.y,
                "z": args.z,
                "theta": args.theta,
            }, args.instant, args.steps, args.step_delay)
        elif args.command == "chip_xyz":
            run_xyz(
                chip_to_joint_position(args.x, args.y, args.z, args.theta),
                args.instant,
                args.steps,
                args.step_delay,
            )
        elif args.command == "demo":
            run_demo(args.delay, args.steps, args.step_delay)
        else:
            parser.error(f"unknown command: {args.command}")
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"[robot_move] failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
