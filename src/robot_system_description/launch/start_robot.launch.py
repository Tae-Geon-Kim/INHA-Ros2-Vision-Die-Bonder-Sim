import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess, TimerAction


def prepend_env_path(env, name, path):
    path = str(path)
    current_value = env.get(name)
    env[name] = f"{path}:{current_value}" if current_value else path


def generate_launch_description():
    gazebo_env = dict(os.environ)

    package_share = Path(get_package_share_directory("robot_system_description"))
    install_share = package_share.parent
    robot_urdf = package_share / "urdf" / "robot_system_compiled.urdf"

    prepend_env_path(gazebo_env, "IGN_GAZEBO_RESOURCE_PATH", install_share)
    prepend_env_path(gazebo_env, "GZ_SIM_RESOURCE_PATH", install_share)

    gazebo = ExecuteProcess(
        cmd=["ign", "gazebo", "empty.sdf"],
        env=gazebo_env,
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
                    str(robot_urdf),
                    "-name",
                    "robot_system",
                    "-z",
                    "0.05",
                ],
                output="screen",
            ),
        ],
    )

    return LaunchDescription([
        gazebo,
        spawn_robot,
        ExecuteProcess(cmd=["rqt"], output="screen"),
        ExecuteProcess(cmd=["rqt"], output="screen"),
    ])
