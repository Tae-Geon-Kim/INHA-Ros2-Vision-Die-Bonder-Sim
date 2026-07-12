import math
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


MIN_STACK_COUNT = 2
MAX_STACK_COUNT = 16

GAZEBO_TRANSPORT_ENV = [
    SetEnvironmentVariable(name="IGN_IP", value="127.0.0.1"),
    SetEnvironmentVariable(name="GZ_IP", value="127.0.0.1"),
    SetEnvironmentVariable(name="IGN_PARTITION", value="inha_die_bonder"),
    SetEnvironmentVariable(name="GZ_PARTITION", value="inha_die_bonder"),
]


def spawn_stack_chips(context, check_chip_sdf):
    stack_count = int(LaunchConfiguration("stack_count").perform(context))
    if not MIN_STACK_COUNT <= stack_count <= MAX_STACK_COUNT:
        raise RuntimeError(
            f"stack_count must be between {MIN_STACK_COUNT} and "
            f"{MAX_STACK_COUNT}: {stack_count}"
        )

    actions = []
    for chip_offset in range(stack_count):
        ratio = chip_offset / (stack_count - 1)
        chip_index = chip_offset + 1
        model_name = "check_chip" if chip_index == 1 else f"check_chip_{chip_index}"
        y_m = 0.4 + ratio * (-0.4 - 0.4)
        theta_rad = math.radians(45.0 * ratio)
        actions.append(
            TimerAction(
                period=7.0 + 0.4 * chip_offset,
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
                            model_name,
                            "-x",
                            "0.5",
                            "-y",
                            f"{y_m:.9f}",
                            "-z",
                            "0.05005",
                            "-Y",
                            f"{theta_rad:.12f}",
                        ],
                        output="screen",
                    ),
                ],
            )
        )
    return actions


def start_gazebo(context, world_sdf):
    render_engine = LaunchConfiguration("render_engine").perform(context).strip()
    gui_render_engine = LaunchConfiguration(
        "gui_render_engine"
    ).perform(context).strip()
    split_value = LaunchConfiguration(
        "split_gui_software"
    ).perform(context).strip().lower()
    split_gui_software = split_value in {"1", "true", "yes", "on"}

    server_engine_args = (
        [] if not render_engine else ["--render-engine", render_engine]
    )
    gui_engine_args = (
        [] if not gui_render_engine
        else ["--render-engine", gui_render_engine]
    )
    if not split_gui_software:
        command = ["ign", "gazebo", "-r", *server_engine_args, world_sdf]
        return [ExecuteProcess(cmd=command, output="screen")]

    server = ExecuteProcess(
        cmd=["ign", "gazebo", "-s", "-r", *server_engine_args, world_sdf],
        output="screen",
    )
    gui = ExecuteProcess(
        cmd=["ign", "gazebo", "-g", *gui_engine_args],
        output="screen",
        additional_env={
            "GALLIUM_DRIVER": "llvmpipe",
            "LIBGL_ALWAYS_SOFTWARE": "1",
            "MESA_D3D12_DEFAULT_ADAPTER_NAME": "",
            "QT_QPA_PLATFORM": "xcb",
            "QT_XCB_GL_INTEGRATION": "xcb_glx",
            "WAYLAND_DISPLAY": "",
            "vblank_mode": "1",
        },
    )
    return [server, TimerAction(period=1.0, actions=[gui])]


def generate_launch_description():
    pkg_share = Path(get_package_share_directory("robot_system_description"))
    install_share = str(pkg_share.parent)
    robot_urdf = str(pkg_share / "urdf" / "robot_system_compiled.urdf")
    check_chip_sdf = str(pkg_share / "models" / "red_check_chip" / "model.sdf")
    world_sdf = str(pkg_share / "worlds" / "empty_with_sensors.sdf")
    spawn_robot = TimerAction(
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
    )

    return LaunchDescription([
        DeclareLaunchArgument("stack_count", default_value="4"),
        DeclareLaunchArgument("render_engine", default_value="ogre"),
        DeclareLaunchArgument("gui_render_engine", default_value="ogre2"),
        DeclareLaunchArgument("split_gui_software", default_value="false"),
        *GAZEBO_TRANSPORT_ENV,
        SetEnvironmentVariable(
            name="IGN_GAZEBO_RESOURCE_PATH",
            value=install_share,
        ),
        SetEnvironmentVariable(
            name="GZ_SIM_RESOURCE_PATH",
            value=install_share,
        ),
        OpaqueFunction(
            function=start_gazebo,
            args=[world_sdf],
        ),
        spawn_robot,
        OpaqueFunction(
            function=spawn_stack_chips,
            args=[check_chip_sdf],
        ),
    ])
