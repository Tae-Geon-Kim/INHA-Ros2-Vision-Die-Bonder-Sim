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
    initial_x_mm = LaunchConfiguration("initial_x_mm")
    initial_y_mm = LaunchConfiguration("initial_y_mm")
    request_only = LaunchConfiguration("request_only")
    request_topic = LaunchConfiguration("request_topic")
    result_topic = LaunchConfiguration("result_topic")
    request_timeout_sec = LaunchConfiguration("request_timeout_sec")
    reference_dir = LaunchConfiguration("reference_dir")
    macro_pixel_size_x_mm = LaunchConfiguration("macro_pixel_size_x_mm")
    macro_pixel_size_y_mm = LaunchConfiguration("macro_pixel_size_y_mm")
    micro_pixel_size_x_mm = LaunchConfiguration("micro_pixel_size_x_mm")
    micro_pixel_size_y_mm = LaunchConfiguration("micro_pixel_size_y_mm")
    macro_axis_sign_x = LaunchConfiguration("macro_axis_sign_x")
    macro_axis_sign_y = LaunchConfiguration("macro_axis_sign_y")
    micro_axis_sign_x = LaunchConfiguration("micro_axis_sign_x")
    micro_axis_sign_y = LaunchConfiguration("micro_axis_sign_y")

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
        DeclareLaunchArgument(
            "initial_x_mm",
            default_value="140.0",
            description="Initial gripper x coordinate in mm.",
        ),
        DeclareLaunchArgument(
            "initial_y_mm",
            default_value="0.0",
            description="Initial gripper y coordinate in mm.",
        ),
        DeclareLaunchArgument(
            "request_only",
            default_value="false",
            description="Only process explicit capture/alignment requests.",
        ),
        DeclareLaunchArgument(
            "request_topic",
            default_value="/vision/alignment_request",
            description="Vision request topic for this bridge instance.",
        ),
        DeclareLaunchArgument(
            "result_topic",
            default_value="/vision/alignment_result",
            description="Vision result topic for this bridge instance.",
        ),
        DeclareLaunchArgument(
            "request_timeout_sec",
            default_value="30.0",
            description="Maximum wait for a fresh frame from every requested camera.",
        ),
        DeclareLaunchArgument(
            "reference_dir",
            default_value="vision_references",
            description="Directory containing pick/place reference image sets.",
        ),
        DeclareLaunchArgument(
            "macro_pixel_size_x_mm",
            default_value="0.075",
            description="Macro camera X calibration in mm/pixel.",
        ),
        DeclareLaunchArgument(
            "macro_pixel_size_y_mm",
            default_value="0.075",
            description="Macro camera Y calibration in mm/pixel.",
        ),
        DeclareLaunchArgument(
            "micro_pixel_size_x_mm",
            default_value="0.0068",
            description="Micro camera X calibration in mm/pixel.",
        ),
        DeclareLaunchArgument(
            "micro_pixel_size_y_mm",
            default_value="0.0068",
            description="Micro camera Y calibration in mm/pixel.",
        ),
        DeclareLaunchArgument(
            "macro_axis_sign_x",
            default_value="-1.0",
            description="Macro image X to robot X axis sign.",
        ),
        DeclareLaunchArgument(
            "macro_axis_sign_y",
            default_value="1.0",
            description="Macro image Y to robot Y axis sign.",
        ),
        DeclareLaunchArgument(
            "micro_axis_sign_x",
            default_value="-1.0",
            description="Micro image X to robot X axis sign.",
        ),
        DeclareLaunchArgument(
            "micro_axis_sign_y",
            default_value="1.0",
            description="Micro image Y to robot Y axis sign.",
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
                "initial_x_mm": initial_x_mm,
                "initial_y_mm": initial_y_mm,
                "request_only": request_only,
                "request_topic": request_topic,
                "result_topic": result_topic,
                "request_timeout_sec": request_timeout_sec,
                "reference_dir": reference_dir,
                "macro_pixel_size_x_mm": macro_pixel_size_x_mm,
                "macro_pixel_size_y_mm": macro_pixel_size_y_mm,
                "micro_pixel_size_x_mm": micro_pixel_size_x_mm,
                "micro_pixel_size_y_mm": micro_pixel_size_y_mm,
                "macro_axis_sign_x": macro_axis_sign_x,
                "macro_axis_sign_y": macro_axis_sign_y,
                "micro_axis_sign_x": micro_axis_sign_x,
                "micro_axis_sign_y": micro_axis_sign_y,
            }],
            output="screen",
        ),
    ])
