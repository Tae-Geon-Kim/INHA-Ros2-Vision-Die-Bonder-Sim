from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    OpaqueFunction,
    SetEnvironmentVariable,
    TimerAction,
)
from launch.substitutions import LaunchConfiguration


MIN_STACK_COUNT = 4
MAX_STACK_COUNT = 16

GAZEBO_TRANSPORT_ENV = [
    SetEnvironmentVariable(name="IGN_IP", value="127.0.0.1"),
    SetEnvironmentVariable(name="GZ_IP", value="127.0.0.1"),
    SetEnvironmentVariable(name="IGN_PARTITION", value="inha_die_bonder"),
    SetEnvironmentVariable(name="GZ_PARTITION", value="inha_die_bonder"),
]


def chip_model_name(layer_number):
    return "check_chip" if layer_number == 1 else f"check_chip_{layer_number}"


def chip_pick_specs():
    """Return deterministic spawn poses in mm/deg, preserving the old first two."""
    specs = [
        (500.0, 400.0, 0.0),
        (500.0, 0.0, 30.0),
    ]
    for x_mm in (500.0, 400.0, 300.0, 200.0):
        for y_mm in (400.0, 200.0, 0.0, -200.0, -400.0):
            candidate = (x_mm, y_mm)
            if any((x_mm, y_mm) == spec[:2] for spec in specs):
                continue
            specs.append((*candidate, 0.0))
            if len(specs) == MAX_STACK_COUNT:
                return specs
    return specs


def parse_stack_count(context):
    raw_value = LaunchConfiguration("stack_count").perform(context)
    try:
        stack_count = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"stack_count must be an integer: {raw_value}") from exc
    if not MIN_STACK_COUNT <= stack_count <= MAX_STACK_COUNT:
        raise RuntimeError(
            f"stack_count must be between {MIN_STACK_COUNT} and {MAX_STACK_COUNT}: "
            f"{stack_count}"
        )
    return stack_count


def launch_setup(context):
    stack_count = parse_stack_count(context)
    pkg_share = Path(get_package_share_directory("robot_system_description"))
    install_share = str(pkg_share.parent)
    robot_urdf = str(pkg_share / "urdf" / "robot_system_compiled.urdf")
    check_chip_sdf = str(pkg_share / "models" / "red_check_chip" / "model.sdf")
    world_sdf = str(pkg_share / "worlds" / "empty_with_sensors.sdf")

    actions = [
        SetEnvironmentVariable(
            name="IGN_GAZEBO_RESOURCE_PATH",
            value=install_share,
        ),
        SetEnvironmentVariable(
            name="GZ_SIM_RESOURCE_PATH",
            value=install_share,
        ),
        ExecuteProcess(
            cmd=["ign", "gazebo", "-r", world_sdf],
            output="screen",
        ),
        TimerAction(
            period=4.0,
            actions=[
                ExecuteProcess(
                    cmd=[
                        "ros2",
                        "run",
                        "ros_gz_sim",
                        "create",
                        "-file",
                        robot_urdf,
                        "-name",
                        "robot_system",
                        "-z",
                        "0.0",
                    ],
                    output="screen",
                ),
            ],
        ),
    ]

    for index, (x_mm, y_mm, theta_deg) in enumerate(
        chip_pick_specs()[:stack_count],
        start=1,
    ):
        actions.append(
            TimerAction(
                period=7.0 + (index - 1) * 0.35,
                actions=[
                    ExecuteProcess(
                        cmd=[
                            "ros2",
                            "run",
                            "ros_gz_sim",
                            "create",
                            "-file",
                            check_chip_sdf,
                            "-name",
                            chip_model_name(index),
                            "-x",
                            str(x_mm * 0.001),
                            "-y",
                            str(y_mm * 0.001),
                            "-z",
                            "0.05005",
                            "-Y",
                            str(theta_deg * 0.017453292519943295),
                        ],
                        output="screen",
                    ),
                ],
            )
        )

    return actions


def generate_launch_description():
    return LaunchDescription([
        *GAZEBO_TRANSPORT_ENV,
        DeclareLaunchArgument(
            "stack_count",
            default_value=str(MIN_STACK_COUNT),
            description="Number of check-chip models to spawn (4-16).",
        ),
        OpaqueFunction(function=launch_setup),
    ])
