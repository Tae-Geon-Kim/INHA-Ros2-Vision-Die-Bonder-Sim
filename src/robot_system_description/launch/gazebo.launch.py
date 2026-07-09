from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess, SetEnvironmentVariable, TimerAction


GAZEBO_TRANSPORT_ENV = [
    SetEnvironmentVariable(name="IGN_IP", value="127.0.0.1"),
    SetEnvironmentVariable(name="GZ_IP", value="127.0.0.1"),
    SetEnvironmentVariable(name="IGN_PARTITION", value="inha_die_bonder"),
    SetEnvironmentVariable(name="GZ_PARTITION", value="inha_die_bonder"),
    SetEnvironmentVariable(name="LIBGL_ALWAYS_SOFTWARE", value="1"),
    SetEnvironmentVariable(name="MESA_LOADER_DRIVER_OVERRIDE", value="llvmpipe"),
    SetEnvironmentVariable(name="QT_QPA_PLATFORM", value="xcb"),
]


def generate_launch_description():
    pkg_share = Path(get_package_share_directory("robot_system_description"))
    install_share = str(pkg_share.parent)
    robot_urdf = str(pkg_share / "urdf" / "robot_system_compiled.urdf")

    gazebo = ExecuteProcess(
        cmd=["ign", "gazebo", "-r", "empty.sdf"],
        output="screen",
    )

    spawn_robot = TimerAction(
        period=5.0,
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
                    "0.2",
                ],
                output="screen",
            ),
        ],
    )

    return LaunchDescription([
        *GAZEBO_TRANSPORT_ENV,
        SetEnvironmentVariable(
            name="IGN_GAZEBO_RESOURCE_PATH",
            value=install_share,
        ),
        SetEnvironmentVariable(
            name="GZ_SIM_RESOURCE_PATH",
            value=install_share,
        ),
        gazebo,
        spawn_robot,
    ])
