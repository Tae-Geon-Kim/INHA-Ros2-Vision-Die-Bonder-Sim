from launch import LaunchDescription
from launch.actions import SetEnvironmentVariable
from launch_ros.actions import Node


def generate_launch_description():
    bridge_args = [
        "/model/robot_system/joint/joint_x/cmd_pos@std_msgs/msg/Float64@ignition.msgs.Double",
        "/model/robot_system/joint/joint_y/cmd_pos@std_msgs/msg/Float64@ignition.msgs.Double",
        "/model/robot_system/joint/joint_z/cmd_pos@std_msgs/msg/Float64@ignition.msgs.Double",
        "/model/robot_system/joint/joint_theta/cmd_pos@std_msgs/msg/Float64@ignition.msgs.Double",
    ]

    return LaunchDescription([
        SetEnvironmentVariable(name="IGN_IP", value="127.0.0.1"),
        SetEnvironmentVariable(name="GZ_IP", value="127.0.0.1"),
        SetEnvironmentVariable(name="IGN_PARTITION", value="inha_die_bonder"),
        SetEnvironmentVariable(name="GZ_PARTITION", value="inha_die_bonder"),
        Node(
            package="ros_gz_bridge",
            executable="parameter_bridge",
            name="robot_joint_command_bridge",
            arguments=bridge_args,
            output="screen",
        ),
        Node(
            package="vision_core",
            executable="pose_command_adapter",
            name="pose_command_adapter",
            parameters=[{
                "input_unit": "mm",
                "coordinate_frame": "chip",
                "steps": 120,
                "period": 0.02,
                "hold": 0.8,
            }],
            output="screen",
        ),
    ])
