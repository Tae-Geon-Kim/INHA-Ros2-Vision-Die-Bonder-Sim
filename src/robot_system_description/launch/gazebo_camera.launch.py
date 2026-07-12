from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    SetEnvironmentVariable,
    TimerAction,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration


GAZEBO_TRANSPORT_ENV = [
    SetEnvironmentVariable(name="IGN_IP", value="127.0.0.1"),
    SetEnvironmentVariable(name="GZ_IP", value="127.0.0.1"),
    SetEnvironmentVariable(name="IGN_PARTITION", value="inha_die_bonder"),
    SetEnvironmentVariable(name="GZ_PARTITION", value="inha_die_bonder"),
]


def generate_launch_description():
    pkg_share = Path(get_package_share_directory("robot_system_description"))
    install_share = str(pkg_share.parent)
    robot_urdf = str(pkg_share / "urdf" / "robot_system_compiled.urdf")
    check_chip_sdf = str(pkg_share / "models" / "red_check_chip" / "model.sdf")
    world_sdf = str(pkg_share / "worlds" / "empty_with_sensors.sdf")

    # GUI and server processes are separate so a remote machine can run Gazebo
    # without forwarding its 3D window over SSH.
    gazebo_with_gui = ExecuteProcess(
        cmd=[
            "ign",
            "gazebo",
            "-r",
            world_sdf,
        ],
        output="screen",
        condition=IfCondition(LaunchConfiguration("gui")),
    )

    gazebo_headless = ExecuteProcess(
        cmd=[
            "ign",
            "gazebo",
            "-s",
            "-r",
            world_sdf,
        ],
        output="screen",
        condition=UnlessCondition(LaunchConfiguration("gui")),
    )

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

    spawn_check_chip = TimerAction(
        period=7.0,
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
                    "check_chip",
                    "-x",
                    "0.5",
                    "-y",
                    "0.4",
                    "-z",
                    "0.05005",
                ],
                output="screen",
            ),
        ],
    )

    spawn_second_check_chip = TimerAction(
        period=9.0,
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
                    "check_chip_2",
                    "-x",
                    "0.5",
                    "-y",
                    "0.0",
                    "-z",
                    "0.05005",
                    "-Y",
                    "0.5235987756",
                ],
                output="screen",
            ),
        ],
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            "gui",
            default_value="true",
            description="Start the Gazebo GUI. Set false on a remote server.",
        ),
        *GAZEBO_TRANSPORT_ENV,
        SetEnvironmentVariable(
            name="IGN_GAZEBO_RESOURCE_PATH",
            value=install_share,
        ),
        SetEnvironmentVariable(
            name="GZ_SIM_RESOURCE_PATH",
            value=install_share,
        ),
        gazebo_with_gui,
        gazebo_headless,
        spawn_robot,
        spawn_check_chip,
        spawn_second_check_chip,
    ])
