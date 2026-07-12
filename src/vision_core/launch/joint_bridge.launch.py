from launch import LaunchDescription
from launch.actions import SetEnvironmentVariable
from launch_ros.actions import Node


def generate_launch_description():
    bridge_args = [
        "/model/robot_system/joint/joint_x/cmd_pos@std_msgs/msg/Float64@ignition.msgs.Double",
        "/model/robot_system/joint/joint_y/cmd_pos@std_msgs/msg/Float64@ignition.msgs.Double",
        "/model/robot_system/joint/joint_z/cmd_pos@std_msgs/msg/Float64@ignition.msgs.Double",
        "/model/robot_system/joint/joint_theta/cmd_pos@std_msgs/msg/Float64@ignition.msgs.Double",
        "/model/robot_system/joint_state@sensor_msgs/msg/JointState[ignition.msgs.Model",
        (
            "/world/empty/pose/info@tf2_msgs/msg/TFMessage"
            "[ignition.msgs.Pose_V"
        ),
        (
            "/world/empty/model/robot_system/link/theta_link_1/sensor/"
            "picker_contact_sensor/contact@ros_gz_interfaces/msg/Contacts"
            "[ignition.msgs.Contacts"
        ),
        (
            "/world/empty/model/substrate/link/substrate_link/sensor/"
            "substrate_contact_sensor/contact@ros_gz_interfaces/msg/Contacts"
            "[ignition.msgs.Contacts"
        ),
        (
            "/world/empty/model/check_chip/link/chip_link/sensor/"
            "chip_contact_sensor/contact@ros_gz_interfaces/msg/Contacts"
            "[ignition.msgs.Contacts"
        ),
        (
            "/world/empty/model/check_chip_2/link/chip_link/sensor/"
            "chip_contact_sensor/contact@ros_gz_interfaces/msg/Contacts"
            "[ignition.msgs.Contacts"
        ),
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
                "coordinate_frame": "gripper_abs",
                "steps": 180,
                "period": 0.008,
                "hold": 0.05,
                "feedback_enabled": True,
                "joint_state_topic": "/model/robot_system/joint_state",
                "arrival_timeout": 10.0,
                "initial_feedback_timeout": 0.5,
                "arrival_tolerance": 0.00002,
                "z_tolerance": 0.0001,
                "theta_tolerance": 0.00015,
                "feedback_stale_timeout": 1.0,
                "settle_samples": 5,
            }],
            output="screen",
        ),
    ])
