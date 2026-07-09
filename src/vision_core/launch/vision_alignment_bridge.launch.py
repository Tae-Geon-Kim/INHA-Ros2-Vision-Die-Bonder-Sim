from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


IMAGE_BRIDGE_ARGS = [
    "/vision/macro_camera/image_raw@sensor_msgs/msg/Image[ignition.msgs.Image",
    "/vision/micro_camera_1/image_raw@sensor_msgs/msg/Image[ignition.msgs.Image",
    "/vision/micro_camera_2/image_raw@sensor_msgs/msg/Image[ignition.msgs.Image",
    "/vision/micro_camera_3/image_raw@sensor_msgs/msg/Image[ignition.msgs.Image",
    "/vision/micro_camera_4/image_raw@sensor_msgs/msg/Image[ignition.msgs.Image",
]


def generate_launch_description():
    alignment_process = LaunchConfiguration("alignment_process")
    place_mode = LaunchConfiguration("place_mode")
    auto_command = LaunchConfiguration("auto_command")
    backend_log_url = LaunchConfiguration("backend_log_url")
    history_id = LaunchConfiguration("history_id")
    pixel_size_x_mm = LaunchConfiguration("pixel_size_x_mm")
    pixel_size_y_mm = LaunchConfiguration("pixel_size_y_mm")

    return LaunchDescription([
        DeclareLaunchArgument(
            "alignment_process",
            default_value="pick",
            description="Alignment process: macro, pick, or place.",
        ),
        DeclareLaunchArgument(
            "place_mode",
            default_value="array",
            description="Place alignment mode: array or stacking.",
        ),
        DeclareLaunchArgument(
            "auto_command",
            default_value="false",
            description="Publish correction commands to /robot/command_pose.",
        ),
        DeclareLaunchArgument(
            "backend_log_url",
            default_value="",
            description="Optional backend POST URL for vision-align logs.",
        ),
        DeclareLaunchArgument(
            "history_id",
            default_value="0",
            description="Optional work_history id for backend vision-align logging.",
        ),
        DeclareLaunchArgument(
            "pixel_size_x_mm",
            default_value="1.0",
            description="Camera x calibration in mm/pixel.",
        ),
        DeclareLaunchArgument(
            "pixel_size_y_mm",
            default_value="1.0",
            description="Camera y calibration in mm/pixel.",
        ),
        SetEnvironmentVariable(name="IGN_IP", value="127.0.0.1"),
        SetEnvironmentVariable(name="GZ_IP", value="127.0.0.1"),
        SetEnvironmentVariable(name="IGN_PARTITION", value="inha_die_bonder"),
        SetEnvironmentVariable(name="GZ_PARTITION", value="inha_die_bonder"),
        Node(
            package="ros_gz_bridge",
            executable="parameter_bridge",
            name="vision_camera_image_bridge",
            arguments=IMAGE_BRIDGE_ARGS,
            output="screen",
        ),
        Node(
            package="vision_core",
            executable="vision_alignment_bridge",
            name="vision_alignment_bridge",
            parameters=[{
                "alignment_process": alignment_process,
                "place_mode": place_mode,
                "auto_command": auto_command,
                "backend_log_url": backend_log_url,
                "history_id": history_id,
                "pixel_size_x_mm": pixel_size_x_mm,
                "pixel_size_y_mm": pixel_size_y_mm,
            }],
            output="screen",
        ),
    ])
