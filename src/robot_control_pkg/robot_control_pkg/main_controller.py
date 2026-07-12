import argparse
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import Pose
from ros_gz_interfaces.msg import Contacts
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from tf2_msgs.msg import TFMessage


STATE_PATH = Path(os.environ.get("ROBOT_CONTROL_STATE", "/tmp/robot_control_pose_state.json"))
VACUUM_ON = True
VACUUM_OFF = False
DEFAULT_SUBSTRATE_CENTER_X_M = 0.14
DEFAULT_SUBSTRATE_CENTER_Y_M = 0.0
DEFAULT_GRIPPER_HOME_X_MM = DEFAULT_SUBSTRATE_CENTER_X_M * 1000.0
DEFAULT_GRIPPER_HOME_Y_MM = DEFAULT_SUBSTRATE_CENTER_Y_M * 1000.0
DEFAULT_GRIPPER_HOME_Z_MM = 165.0
DEFAULT_STACK_CHIP_COUNT = 4
MAX_STACK_CHIP_COUNT = 16
DEFAULT_STATE = {
    "x": DEFAULT_GRIPPER_HOME_X_MM,
    "y": DEFAULT_GRIPPER_HOME_Y_MM,
    "z": DEFAULT_GRIPPER_HOME_Z_MM,
    "theta_deg": 0.0,
    "vacuum_attached": VACUUM_OFF,
    "chip_x": 0.0,
    "chip_y": 0.0,
    "chip_z": 0.0,
    "chip_theta_deg": 0.0,
}
MIN_STACK_COUNT = 4
MAX_STACK_COUNT = 16


def validate_stack_count(value):
    try:
        stack_count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'stack_count는 정수여야 합니다: {value}') from exc
    if not MIN_STACK_COUNT <= stack_count <= MAX_STACK_COUNT:
        raise ValueError(
            f'stack_count는 {MIN_STACK_COUNT}~{MAX_STACK_COUNT} 범위여야 합니다: '
            f'{stack_count}'
        )
    return stack_count


def stack_count_arg(value):
    try:
        return validate_stack_count(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def chip_model_name(layer_number):
    return 'check_chip' if layer_number == 1 else f'check_chip_{layer_number}'


def chip_pick_specs():
    """Return default pick poses in mm/deg, preserving the original first two."""
    specs = [
        (500.0, 400.0, 0.0),
        (500.0, 0.0, 30.0),
    ]
    for x_mm in (500.0, 400.0, 300.0, 200.0):
        for y_mm in (400.0, 200.0, 0.0, -200.0, -400.0):
            if any((x_mm, y_mm) == spec[:2] for spec in specs):
                continue
            specs.append((x_mm, y_mm, 0.0))
            if len(specs) == MAX_STACK_COUNT:
                return specs
    return specs


def load_state():
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {
            "x": float(data.get("x", DEFAULT_STATE["x"])),
            "y": float(data.get("y", DEFAULT_STATE["y"])),
            "z": float(data.get("z", DEFAULT_STATE["z"])),
            "theta_deg": float(data.get("theta_deg", DEFAULT_STATE["theta_deg"])),
            "vacuum_attached": bool(data.get(
                "vacuum_attached",
                DEFAULT_STATE["vacuum_attached"],
            )),
            "chip_x": float(data.get("chip_x", DEFAULT_STATE["chip_x"])),
            "chip_y": float(data.get("chip_y", DEFAULT_STATE["chip_y"])),
            "chip_z": float(data.get("chip_z", DEFAULT_STATE["chip_z"])),
            "chip_theta_deg": float(data.get(
                "chip_theta_deg",
                DEFAULT_STATE["chip_theta_deg"],
            )),
        }
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return DEFAULT_STATE.copy()


def save_state(
    x,
    y,
    z,
    theta_deg,
    vacuum_attached=None,
    chip_x=None,
    chip_y=None,
    chip_z=None,
    chip_theta_deg=None,
):
    state = load_state()
    state.update({
        "x": float(x),
        "y": float(y),
        "z": float(z),
        "theta_deg": float(theta_deg),
    })

    optional_values = {
        "vacuum_attached": vacuum_attached,
        "chip_x": chip_x,
        "chip_y": chip_y,
        "chip_z": chip_z,
        "chip_theta_deg": chip_theta_deg,
    }
    for key, value in optional_values.items():
        if value is not None:
            state[key] = bool(value) if key == "vacuum_attached" else float(value)

    STATE_PATH.write_text(json.dumps(state), encoding="utf-8")


def set_pose_yaw(msg, theta_deg):
    theta_rad = math.radians(theta_deg)
    msg.orientation.z = math.sin(theta_rad / 2.0)
    msg.orientation.w = math.cos(theta_rad / 2.0)


def quaternion_yaw_deg(quaternion):
    siny_cosp = 2.0 * (
        quaternion.w * quaternion.z
        + quaternion.x * quaternion.y
    )
    cosy_cosp = 1.0 - 2.0 * (
        quaternion.y * quaternion.y
        + quaternion.z * quaternion.z
    )
    return math.degrees(math.atan2(siny_cosp, cosy_cosp))


def env_flag(name, default=False):
    default_value = "1" if default else "0"
    value = os.environ.get(name, default_value).strip().lower()
    return value in ("1", "true", "yes", "on")


class MainControllerNode(Node):
    def __init__(self, stack_chip_count=2):
        super().__init__('main_controller_node')

        configured_stack_chip_count = int(stack_chip_count)
        if (
            configured_stack_chip_count < 2
            or configured_stack_chip_count > MAX_STACK_CHIP_COUNT
        ):
            raise ValueError(
                f'stack_chip_count는 2~{MAX_STACK_CHIP_COUNT} 범위여야 합니다: '
                f'{configured_stack_chip_count}'
            )
        self.STACK_CHIP_COUNT = configured_stack_chip_count

        # 로봇 하드웨어 명령 퍼블리셔 (Command topic: /robot/command_pose)
        self.cmd_pub = self.create_publisher(Pose, '/robot/command_pose', 10)
        self.active_stack_pair_pub = self.create_publisher(
            String,
            '/robot/active_stack_pair',
            10,
        )
        
        # 그리퍼 중심점 기준 카메라의 상대 위치 오프셋
        self.GRIPPER_TO_CAMERA_DX = 50.0  
        self.GRIPPER_TO_CAMERA_DY = 20.0  
        
        # 수직 방향(Z) 제어 높이
        self.BASE_TOP_Z = float(os.environ.get("ROBOT_CONTROL_BASE_TOP_Z_MM", "50.0"))
        self.CHIP_THICKNESS_MM = float(os.environ.get("ROBOT_CONTROL_CHIP_THICKNESS_MM", "0.1"))
        self.SUBSTRATE_THICKNESS_MM = float(os.environ.get("ROBOT_CONTROL_SUBSTRATE_THICKNESS_MM", "5.0"))
        self.GRIPPER_CONTACT_OFFSET_MM = float(os.environ.get(
            "ROBOT_CONTROL_GRIPPER_CONTACT_OFFSET_MM",
            "0.0",
        ))
        self.HOVER_Z = float(os.environ.get("ROBOT_CONTROL_HOVER_Z_MM", "100.0"))
        self.SUBSTRATE_CENTER_X = float(os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_CENTER_X_MM",
            str(DEFAULT_SUBSTRATE_CENTER_X_M * 1000.0),
        ))
        self.SUBSTRATE_CENTER_Y = float(os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_CENTER_Y_MM",
            str(DEFAULT_SUBSTRATE_CENTER_Y_M * 1000.0),
        ))
        self.GRIPPER_HOME_X = float(os.environ.get(
            "ROBOT_CONTROL_GRIPPER_HOME_X_MM",
            str(self.SUBSTRATE_CENTER_X),
        ))
        self.GRIPPER_HOME_Y = float(os.environ.get(
            "ROBOT_CONTROL_GRIPPER_HOME_Y_MM",
            str(self.SUBSTRATE_CENTER_Y),
        ))
        self.GRIPPER_HOME_Z = float(os.environ.get(
            "ROBOT_CONTROL_GRIPPER_HOME_Z_MM",
            str(DEFAULT_GRIPPER_HOME_Z_MM),
        ))
        self.PRESS_Z = float(os.environ.get(
            "ROBOT_CONTROL_PICK_Z_MM",
            str(self.BASE_TOP_Z + self.CHIP_THICKNESS_MM + self.GRIPPER_CONTACT_OFFSET_MM),
        ))
        self.CHIP_REST_Z = float(os.environ.get("ROBOT_CONTROL_CHIP_REST_Z_MM", str(self.BASE_TOP_Z)))
        self.SUBSTRATE_TOP_Z = float(os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_TOP_Z_MM",
            str(
                self.BASE_TOP_Z
                + self.SUBSTRATE_THICKNESS_MM
                + self.CHIP_THICKNESS_MM
                + self.GRIPPER_CONTACT_OFFSET_MM
            ),
        ))
        self.MIN_CONTACT_Z = float(os.environ.get(
            "ROBOT_CONTROL_MIN_CONTACT_Z",
            str(self.BASE_TOP_Z + self.CHIP_THICKNESS_MM + self.GRIPPER_CONTACT_OFFSET_MM),
        ))
        self.DEFAULT_CARRIED_CHIP_BOTTOM_OFFSET_MM = (
            self.CHIP_THICKNESS_MM + self.GRIPPER_CONTACT_OFFSET_MM
        )
        self.carried_chip_bottom_offset_mm = self.DEFAULT_CARRIED_CHIP_BOTTOM_OFFSET_MM
        self.MOVE_SETTLE_SEC = 3.5
        self.CONTACT_APPROACH_OFFSET_MM = float(os.environ.get(
            "ROBOT_CONTROL_CONTACT_APPROACH_OFFSET_MM",
            "0.2",
        ))
        self.CONTACT_DESCENT_STEP_MM = float(os.environ.get(
            "ROBOT_CONTROL_CONTACT_DESCENT_STEP_MM",
            "0.02",
        ))
        self.CONTACT_PROBE_DEPTH_MM = float(os.environ.get(
            "ROBOT_CONTROL_CONTACT_PROBE_DEPTH_MM",
            "0.04",
        ))
        self.CONTACT_FLOOR_TOLERANCE_MM = float(os.environ.get(
            "ROBOT_CONTROL_CONTACT_FLOOR_TOLERANCE_MM",
            "0.05",
        ))
        self.CONTACT_DESCENT_SETTLE_SEC = float(os.environ.get(
            "ROBOT_CONTROL_CONTACT_DESCENT_SETTLE_SEC",
            "0.2",
        ))
        self.CONTACT_DESCENT_MOTION_TIMEOUT_SEC = float(os.environ.get(
            "ROBOT_CONTROL_CONTACT_DESCENT_MOTION_TIMEOUT_SEC",
            "30.0",
        ))
        self.CONTACT_DESCENT_CHECK_TIMEOUT_SEC = float(os.environ.get(
            "ROBOT_CONTROL_CONTACT_DESCENT_CHECK_TIMEOUT_SEC",
            "0.25",
        ))
        self.ALLOW_GEOMETRIC_CONTACT_FALLBACK = env_flag(
            "ROBOT_CONTROL_ALLOW_GEOMETRIC_CONTACT_FALLBACK",
            False,
        )

        # Gazebo 시연용 칩 모델 제어 설정
        self.GAZEBO_WORLD = os.environ.get("ROBOT_CONTROL_GAZEBO_WORLD", "empty")
        self.SIM_POSE_TOPIC = os.environ.get(
            "ROBOT_CONTROL_SIM_POSE_TOPIC",
            f"/world/{self.GAZEBO_WORLD}/pose/info",
        )
        self.SUBSTRATE_MODEL = os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_MODEL",
            "substrate",
        )
        self.PRIMARY_CHIP_MODEL = os.environ.get(
            "ROBOT_CONTROL_CHIP_MODEL",
            "check_chip",
        )
        self.SECOND_CHIP_MODEL = os.environ.get(
            "ROBOT_CONTROL_SECOND_CHIP_MODEL",
            "check_chip_2",
        )
        chip_models = [self.PRIMARY_CHIP_MODEL, self.SECOND_CHIP_MODEL]
        chip_models.extend(
            os.environ.get(
                f"ROBOT_CONTROL_CHIP_{chip_index}_MODEL",
                f"check_chip_{chip_index}",
            )
            for chip_index in range(3, self.STACK_CHIP_COUNT + 1)
        )
        self.CHIP_MODELS = tuple(chip_models)
        self.RED_CHIP_MODEL = self.PRIMARY_CHIP_MODEL
        self.USE_DETACHABLE_JOINT = env_flag("ROBOT_CONTROL_USE_DETACHABLE_JOINT", True)
        self.REQUIRE_PICKER_CONTACT = env_flag("ROBOT_CONTROL_REQUIRE_PICKER_CONTACT", True)
        primary_attach_topic = os.environ.get(
            "ROBOT_CONTROL_ATTACH_TOPIC",
            "/model/robot_system/vacuum/attach",
        )
        primary_detach_topic = os.environ.get(
            "ROBOT_CONTROL_DETACH_TOPIC",
            "/model/robot_system/vacuum/detach",
        )
        primary_bond_attach_topic = os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_ATTACH_TOPIC",
            "/model/robot_system/substrate_bond/attach",
        )
        primary_bond_detach_topic = os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_DETACH_TOPIC",
            "/model/robot_system/substrate_bond/detach",
        )
        self.VACUUM_JOINT_TOPICS = {}
        self.STACK_BOND_TOPICS = {}
        for chip_index, model_name in enumerate(self.CHIP_MODELS, start=1):
            if chip_index == 1:
                vacuum_topics = {
                    "attach": primary_attach_topic,
                    "detach": primary_detach_topic,
                    "state": "/model/robot_system/vacuum/state",
                }
                bond_topics = {
                    "attach": primary_bond_attach_topic,
                    "detach": primary_bond_detach_topic,
                    "state": "/model/robot_system/substrate_bond/state",
                }
            elif chip_index == 2:
                vacuum_topics = {
                    "attach": os.environ.get(
                        "ROBOT_CONTROL_SECOND_ATTACH_TOPIC",
                        "/model/robot_system/vacuum_2/attach",
                    ),
                    "detach": os.environ.get(
                        "ROBOT_CONTROL_SECOND_DETACH_TOPIC",
                        "/model/robot_system/vacuum_2/detach",
                    ),
                    "state": os.environ.get(
                        "ROBOT_CONTROL_SECOND_VACUUM_STATE_TOPIC",
                        "/model/robot_system/vacuum_2/state",
                    ),
                }
                bond_topics = {
                    "attach": os.environ.get(
                        "ROBOT_CONTROL_SECOND_BOND_ATTACH_TOPIC",
                        "/model/robot_system/stack_bond_2/attach",
                    ),
                    "detach": os.environ.get(
                        "ROBOT_CONTROL_SECOND_BOND_DETACH_TOPIC",
                        "/model/robot_system/stack_bond_2/detach",
                    ),
                    "state": os.environ.get(
                        "ROBOT_CONTROL_SECOND_BOND_STATE_TOPIC",
                        "/model/robot_system/stack_bond_2/state",
                    ),
                }
            else:
                env_prefix = f"ROBOT_CONTROL_CHIP_{chip_index}"
                vacuum_base = f"/model/robot_system/vacuum_{chip_index}"
                bond_base = f"/model/robot_system/stack_bond_{chip_index}"
                vacuum_topics = {
                    "attach": os.environ.get(
                        f"{env_prefix}_ATTACH_TOPIC",
                        f"{vacuum_base}/attach",
                    ),
                    "detach": os.environ.get(
                        f"{env_prefix}_DETACH_TOPIC",
                        f"{vacuum_base}/detach",
                    ),
                    "state": os.environ.get(
                        f"{env_prefix}_VACUUM_STATE_TOPIC",
                        f"{vacuum_base}/state",
                    ),
                }
                bond_topics = {
                    "attach": os.environ.get(
                        f"{env_prefix}_BOND_ATTACH_TOPIC",
                        f"{bond_base}/attach",
                    ),
                    "detach": os.environ.get(
                        f"{env_prefix}_BOND_DETACH_TOPIC",
                        f"{bond_base}/detach",
                    ),
                    "state": os.environ.get(
                        f"{env_prefix}_BOND_STATE_TOPIC",
                        f"{bond_base}/state",
                    ),
                }
            self.VACUUM_JOINT_TOPICS[model_name] = vacuum_topics
            self.STACK_BOND_TOPICS[model_name] = bond_topics
        self.DYNAMIC_SYSTEM_SERVICE = os.environ.get(
            "ROBOT_CONTROL_DYNAMIC_SYSTEM_SERVICE",
            f"/world/{self.GAZEBO_WORLD}/entity/system/add",
        )
        self.DYNAMIC_SYSTEM_TIMEOUT_MS = int(os.environ.get(
            "ROBOT_CONTROL_DYNAMIC_SYSTEM_TIMEOUT_MS",
            "1500",
        ))
        self.DYNAMIC_TOPIC_DISCOVERY_TIMEOUT_SEC = float(os.environ.get(
            "ROBOT_CONTROL_DYNAMIC_TOPIC_DISCOVERY_TIMEOUT_SEC",
            "4.0",
        ))
        self.PICKER_CONTACT_TOPIC = os.environ.get(
            "ROBOT_CONTROL_PICKER_CONTACT_TOPIC",
            "/model/robot_system/picker/contact",
        )
        self.PICKER_CONTACT_SENSOR_TOPIC = (
            f"/world/{self.GAZEBO_WORLD}/model/robot_system/link/"
            "theta_link_1/sensor/picker_contact_sensor/contact"
        )
        contact_topics = os.environ.get(
            "ROBOT_CONTROL_PICKER_CONTACT_TOPICS",
            f"{self.PICKER_CONTACT_SENSOR_TOPIC},{self.PICKER_CONTACT_TOPIC}",
        )
        self.PICKER_CONTACT_TOPICS = []
        for topic in contact_topics.split(","):
            topic = topic.strip()
            if topic and topic not in self.PICKER_CONTACT_TOPICS:
                self.PICKER_CONTACT_TOPICS.append(topic)
        self.SUBSTRATE_CONTACT_TOPIC = os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_CONTACT_TOPIC",
            "/model/robot_system/substrate/contact",
        )
        self.SUBSTRATE_CONTACT_SENSOR_TOPIC = (
            f"/world/{self.GAZEBO_WORLD}/model/substrate/link/"
            "substrate_link/sensor/substrate_contact_sensor/contact"
        )
        self.CHIP_CONTACT_SENSOR_TOPICS = {
            model_name: (
                f"/world/{self.GAZEBO_WORLD}/model/{model_name}/link/"
                "chip_link/sensor/chip_contact_sensor/contact"
            )
            for model_name in self.CHIP_MODELS
        }
        self.CHIP_CONTACT_TOPICS = {
            model_name: f"/model/{model_name}/chip/contact"
            for model_name in self.CHIP_MODELS
        }
        default_stack_contact_topics = [
            self.SUBSTRATE_CONTACT_SENSOR_TOPIC,
            self.SUBSTRATE_CONTACT_TOPIC,
            *self.CHIP_CONTACT_SENSOR_TOPICS.values(),
            *self.CHIP_CONTACT_TOPICS.values(),
        ]
        substrate_contact_topics = os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_CONTACT_TOPICS",
            ",".join(default_stack_contact_topics),
        )
        self.SUBSTRATE_CONTACT_TOPICS = []
        for topic in substrate_contact_topics.split(",") + default_stack_contact_topics:
            topic = topic.strip()
            if topic and topic not in self.SUBSTRATE_CONTACT_TOPICS:
                self.SUBSTRATE_CONTACT_TOPICS.append(topic)
        self.discovered_picker_contact_topics = []
        self.last_contact_topic_discovery = 0.0
        self.last_picker_contact_time = 0.0
        self.last_substrate_contact_time = 0.0
        self.CONTACT_TOPIC_DISCOVERY_INTERVAL_SEC = 2.0
        self.PICKER_COLLISION_TOKEN = os.environ.get(
            "ROBOT_CONTROL_PICKER_COLLISION_TOKEN",
            "picker_contact_collision",
        ).lower()
        substrate_contact_tokens = os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_CONTACT_TOKENS",
            "substrate_link_collision,substrate_link",
        )
        self.SUBSTRATE_CONTACT_TOKENS = [
            token.strip().lower()
            for token in substrate_contact_tokens.split(",")
            if token.strip()
        ]
        self.active_stack_level = 0
        self.PLACEMENT_SUPPORT_MODEL = self.SUBSTRATE_MODEL
        self.activate_chip(
            self.PRIMARY_CHIP_MODEL,
            support_model=self.SUBSTRATE_MODEL,
            stack_level=0,
            log=False,
        )
        self.PICKER_CONTACT_TIMEOUT_SEC = float(os.environ.get(
            "ROBOT_CONTROL_PICKER_CONTACT_TIMEOUT_SEC",
            "6.0",
        ))
        self.SUBSTRATE_CONTACT_TIMEOUT_SEC = float(os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_CONTACT_TIMEOUT_SEC",
            "6.0",
        ))
        self.CONTACT_CONFIRM_WINDOW_SEC = float(os.environ.get(
            "ROBOT_CONTROL_CONTACT_CONFIRM_WINDOW_SEC",
            "2.0",
        ))
        self.ATTACH_PUBLISH_DURATION_SEC = float(os.environ.get(
            "ROBOT_CONTROL_ATTACH_PUBLISH_DURATION_SEC",
            "0.25",
        ))
        self.TRANSFER_RELEASE_LIFT_MM = float(os.environ.get(
            "ROBOT_CONTROL_TRANSFER_RELEASE_LIFT_MM",
            "2.0",
        ))
        self.TRANSFER_RELEASE_MIN_SEPARATION_MM = float(os.environ.get(
            "ROBOT_CONTROL_TRANSFER_RELEASE_MIN_SEPARATION_MM",
            "0.5",
        ))
        self.TRANSFER_RELEASE_TIMEOUT_SEC = float(os.environ.get(
            "ROBOT_CONTROL_TRANSFER_RELEASE_TIMEOUT_SEC",
            "10.0",
        ))
        self.TRANSFER_MAX_STACK_Z_ERROR_MM = float(os.environ.get(
            "ROBOT_CONTROL_TRANSFER_MAX_STACK_Z_ERROR_MM",
            str(self.CHIP_THICKNESS_MM * 0.5),
        ))
        self.TRANSFER_DETACH_RETRY_SEC = float(os.environ.get(
            "ROBOT_CONTROL_TRANSFER_DETACH_RETRY_SEC",
            "0.5",
        ))
        self.REQUIRE_SUBSTRATE_CONTACT = env_flag(
            "ROBOT_CONTROL_REQUIRE_SUBSTRATE_CONTACT",
            True,
        )
        self.USE_IGN_CONTACT_FALLBACK = env_flag(
            "ROBOT_CONTROL_USE_IGN_CONTACT_FALLBACK",
            False,
        )
        self.CONTACT_SEARCH_STEP_MM = float(os.environ.get(
            "ROBOT_CONTROL_CONTACT_SEARCH_STEP_MM",
            "1.0",
        ))
        self.CONTACT_SEARCH_DEPTH_MM = float(os.environ.get(
            "ROBOT_CONTROL_CONTACT_SEARCH_DEPTH_MM",
            "8.0",
        ))
        self.CONTACT_SEARCH_SETTLE_SEC = float(os.environ.get(
            "ROBOT_CONTROL_CONTACT_SEARCH_SETTLE_SEC",
            "3.5",
        ))
        self.CHIP_WORLD_CENTER_X_M = float(os.environ.get("ROBOT_CONTROL_CHIP_CENTER_X_M", "0.0"))
        self.CHIP_WORLD_CENTER_Y_M = float(os.environ.get("ROBOT_CONTROL_CHIP_CENTER_Y_M", "0.0"))
        self.CHIP_SURFACE_WORLD_Z_M = float(os.environ.get(
            "ROBOT_CONTROL_CHIP_SURFACE_WORLD_Z_M",
            str((self.BASE_TOP_Z + self.CHIP_THICKNESS_MM / 2.0) * 0.001),
        ))
        self.ABS_Z_ZERO_WORLD_M = float(os.environ.get("ROBOT_CONTROL_ABS_Z_ZERO_WORLD_M", "0.0"))
        self.CHIP_MIN_CARRIED_HEIGHT_M = float(os.environ.get("ROBOT_CONTROL_CHIP_MIN_CARRIED_HEIGHT_M", "0.003"))
        self.WAIT_FOR_CHIP_SERVICE = env_flag("ROBOT_CONTROL_WAIT_FOR_CHIP_SERVICE", True)
        self.CHIP_SERVICE_TIMEOUT_MS = int(os.environ.get("ROBOT_CONTROL_CHIP_SERVICE_TIMEOUT_MS", "1000"))
        self.COMMAND_LIMITS_MM = {
            "x": (-260.0, 540.0),
            # Source endpoints are +/-400 mm; retain 5 mm for vision servoing.
            "y": (-405.0, 405.0),
            "z": (self.GRIPPER_HOME_Z - 115.0, self.GRIPPER_HOME_Z + 115.0),
        }

        # 기준 영상 요청/응답과 1 um급 반복 정렬 설정
        self.VISION_REQUEST_TOPIC = os.environ.get(
            "ROBOT_CONTROL_VISION_REQUEST_TOPIC",
            "/vision/alignment_request",
        )
        self.VISION_RESULT_TOPIC = os.environ.get(
            "ROBOT_CONTROL_VISION_RESULT_TOPIC",
            "/vision/alignment_result",
        )
        self.VISION_REQUEST_TIMEOUT_SEC = float(os.environ.get(
            "ROBOT_CONTROL_VISION_REQUEST_TIMEOUT_SEC",
            "20.0",
        ))
        self.VISION_REQUEST_RETRY_COUNT = max(1, int(os.environ.get(
            "ROBOT_CONTROL_VISION_REQUEST_RETRY_COUNT",
            "3",
        )))
        self.VISION_TOLERANCE_UM = float(os.environ.get(
            "ROBOT_CONTROL_VISION_TOLERANCE_UM",
            "1.0",
        ))
        self.VISION_Z_TOLERANCE_UM = float(os.environ.get(
            "ROBOT_CONTROL_VISION_Z_TOLERANCE_UM",
            "100.0",
        ))
        self.VISION_ROTATION_RADIUS_MM = float(os.environ.get(
            "ROBOT_CONTROL_VISION_ROTATION_RADIUS_MM",
            "5.5",
        ))
        self.VISION_MACRO_MAX_XY_MM = float(os.environ.get(
            "ROBOT_CONTROL_VISION_MACRO_MAX_XY_MM",
            "10.0",
        ))
        self.VISION_MICRO_MAX_XY_MM = float(os.environ.get(
            "ROBOT_CONTROL_VISION_MICRO_MAX_XY_MM",
            "1.0",
        ))
        self.VISION_MACRO_MAX_Z_MM = float(os.environ.get(
            "ROBOT_CONTROL_VISION_MACRO_MAX_Z_MM",
            "0.1",
        ))
        self.VISION_MICRO_MAX_Z_MM = float(os.environ.get(
            "ROBOT_CONTROL_VISION_MICRO_MAX_Z_MM",
            "0.1",
        ))
        self.VISION_MAX_THETA_DEG = float(os.environ.get(
            "ROBOT_CONTROL_VISION_MAX_THETA_DEG",
            "3.0",
        ))
        self.VISION_MACRO_MAX_THETA_DEG = float(os.environ.get(
            "ROBOT_CONTROL_VISION_MACRO_MAX_THETA_DEG",
            "45.0",
        ))
        self.VISION_Z_WINDOW_MM = float(os.environ.get(
            "ROBOT_CONTROL_VISION_Z_WINDOW_MM",
            "0.5",
        ))
        self.VISION_SETTLE_SEC = float(os.environ.get(
            "ROBOT_CONTROL_VISION_SETTLE_SEC",
            "1.0",
        ))
        self.VISION_MICRO_AVERAGE_WINDOW = max(1, int(os.environ.get(
            "ROBOT_CONTROL_VISION_MICRO_AVERAGE_WINDOW",
            "5",
        )))
        self.VISION_MOTION_TIMEOUT_SEC = float(os.environ.get(
            "ROBOT_CONTROL_VISION_MOTION_TIMEOUT_SEC",
            "60.0",
        ))
        self.VISION_CORRECTION_MOTION_TIMEOUT_SEC = float(os.environ.get(
            "ROBOT_CONTROL_VISION_CORRECTION_MOTION_TIMEOUT_SEC",
            "15.0",
        ))
        self.VISION_REFERENCE_LOCK_SETTLE_SEC = float(os.environ.get(
            "ROBOT_CONTROL_VISION_REFERENCE_LOCK_SETTLE_SEC",
            "2.0",
        ))
        self.VISION_MOTION_POSITION_TOLERANCE_MM = float(os.environ.get(
            "ROBOT_CONTROL_VISION_MOTION_POSITION_TOLERANCE_MM",
            "0.0005",
        ))
        self.VISION_MOTION_Z_TOLERANCE_MM = float(os.environ.get(
            "ROBOT_CONTROL_VISION_MOTION_Z_TOLERANCE_MM",
            "0.1",
        ))
        self.VISION_MOTION_THETA_TOLERANCE_DEG = float(os.environ.get(
            "ROBOT_CONTROL_VISION_MOTION_THETA_TOLERANCE_DEG",
            "0.005",
        ))
        self.VISION_MACRO_CAPTURE_RANGE_MM = float(os.environ.get(
            "ROBOT_CONTROL_VISION_MACRO_CAPTURE_RANGE_MM",
            "30.0",
        ))
        self.REFERENCE_HIDDEN_X_M = float(os.environ.get(
            "ROBOT_CONTROL_REFERENCE_HIDDEN_X_M",
            "5.0",
        ))
        self.REFERENCE_HIDDEN_Y_M = float(os.environ.get(
            "ROBOT_CONTROL_REFERENCE_HIDDEN_Y_M",
            "5.0",
        ))

        # 상태 추적 변수 (로봇의 현재 x, y 좌표를 추적)
        state = load_state()
        self.last_sent_x = state["x"]
        self.last_sent_y = state["y"]
        self.last_sent_z = state["z"]
        self.last_sent_theta_deg = state["theta_deg"]
        restore_vacuum_state = env_flag("ROBOT_CONTROL_RESTORE_VACUUM_STATE", False)
        self.vacuum_attached = (
            VACUUM_ON
            if restore_vacuum_state and state["vacuum_attached"]
            else VACUUM_OFF
        )
        self.chip_x = state["chip_x"]
        self.chip_y = state["chip_y"]
        self.chip_z = state["chip_z"]
        self.chip_theta_deg = state["chip_theta_deg"]

        self.actual_joint_z_m = None
        self.actual_gripper_x_mm = None
        self.actual_gripper_y_mm = None
        self.actual_gripper_z_mm = None
        self.actual_gripper_theta_deg = None
        self.last_joint_feedback_time = 0.0
        self.sim_model_poses = {}
        self.gazebo_model_entity_ids = {}
        self.known_dynamic_joint_topics = set()
        self.ignition_topic_cache_loaded = False
        self.picker_contact_gripper_z_mm = None
        self.substrate_contact_gripper_z_mm = None
        self.vision_results = {}
        self.vision_request_serial = 0
        self.vision_request_pub = self.create_publisher(
            String,
            self.VISION_REQUEST_TOPIC,
            10,
        )
        self.vision_result_sub = self.create_subscription(
            String,
            self.VISION_RESULT_TOPIC,
            self.handle_vision_result,
            10,
        )
        self.contact_subscriptions = [
            self.create_subscription(
                JointState,
                "/model/robot_system/joint_state",
                self.handle_joint_state,
                10,
            ),
            self.create_subscription(
                TFMessage,
                self.SIM_POSE_TOPIC,
                self.handle_sim_pose_info,
                qos_profile_sensor_data,
            ),
            self.create_subscription(
                Contacts,
                self.PICKER_CONTACT_SENSOR_TOPIC,
                self.handle_picker_contacts,
                qos_profile_sensor_data,
            ),
            self.create_subscription(
                Contacts,
                self.SUBSTRATE_CONTACT_SENSOR_TOPIC,
                self.handle_substrate_contacts,
                qos_profile_sensor_data,
            ),
        ]
        self.contact_subscriptions.extend(
            self.create_subscription(
                Contacts,
                topic,
                self.handle_chip_contacts,
                qos_profile_sensor_data,
            )
            for topic in self.CHIP_CONTACT_SENSOR_TOPICS.values()
        )

    def model_collision_tokens(self, model_name):
        normalized = str(model_name).strip().lower()
        return [f'{normalized}::', f'/model/{normalized}/']

    def activate_chip(self, model_name, support_model=None, stack_level=0, log=True):
        normalized_model = str(model_name).strip()
        if normalized_model not in self.CHIP_MODELS:
            raise ValueError(f'지원하지 않는 chip model입니다: {model_name}')

        normalized_support = (
            self.SUBSTRATE_MODEL
            if support_model is None
            else str(support_model).strip()
        )
        self.RED_CHIP_MODEL = normalized_model
        self.ATTACH_TOPIC = self.VACUUM_JOINT_TOPICS[normalized_model]['attach']
        self.DETACH_TOPIC = self.VACUUM_JOINT_TOPICS[normalized_model]['detach']
        self.SUBSTRATE_ATTACH_TOPIC = self.STACK_BOND_TOPICS[normalized_model]['attach']
        self.SUBSTRATE_DETACH_TOPIC = self.STACK_BOND_TOPICS[normalized_model]['detach']
        self.VACUUM_STATE_TOPIC = self.VACUUM_JOINT_TOPICS[normalized_model]['state']
        self.SUBSTRATE_STATE_TOPIC = self.STACK_BOND_TOPICS[normalized_model]['state']
        self.CHIP_CONTACT_SENSOR_TOPIC = self.CHIP_CONTACT_SENSOR_TOPICS[normalized_model]
        self.CHIP_CONTACT_TOPIC = self.CHIP_CONTACT_TOPICS[normalized_model]
        self.CHIP_CONTACT_TOKENS = self.model_collision_tokens(normalized_model)
        self.PLACEMENT_SUPPORT_MODEL = normalized_support
        self.active_stack_level = max(0, int(stack_level))
        if normalized_support == self.SUBSTRATE_MODEL:
            self.PLACEMENT_SUPPORT_TOKENS = self.SUBSTRATE_CONTACT_TOKENS
        else:
            self.PLACEMENT_SUPPORT_TOKENS = self.model_collision_tokens(
                normalized_support,
            )

        pair_msg = String()
        pair_msg.data = f'{self.PLACEMENT_SUPPORT_MODEL}|{self.RED_CHIP_MODEL}'
        self.active_stack_pair_pub.publish(pair_msg)

        if log:
            self.get_logger().info(
                '활성 chip 전환: '
                f'model={self.RED_CHIP_MODEL}, '
                f'place_contact={self.RED_CHIP_MODEL}<->{self.PLACEMENT_SUPPORT_MODEL}, '
                f'stack_level={self.active_stack_level + 1}'
            )

    def handle_vision_result(self, msg):
        try:
            payload = json.loads(msg.data)
        except (json.JSONDecodeError, TypeError):
            return

        request_id = str(payload.get("request_id", "")).strip()
        if request_id:
            self.vision_results[request_id] = payload

    def handle_joint_state(self, msg):
        feedback_updated = False
        for index, name in enumerate(msg.name):
            if index >= len(msg.position):
                continue
            position = float(msg.position[index])
            if name == "joint_x" or name.endswith("/joint_x") or name.endswith("::joint_x"):
                self.actual_gripper_x_mm = self.GRIPPER_HOME_X + position * 1000.0
                feedback_updated = True
            elif name == "joint_y" or name.endswith("/joint_y") or name.endswith("::joint_y"):
                self.actual_gripper_y_mm = self.GRIPPER_HOME_Y - position * 1000.0
                feedback_updated = True
            if name == "joint_z" or name.endswith("/joint_z") or name.endswith("::joint_z"):
                self.actual_joint_z_m = position
                self.actual_gripper_z_mm = (
                    self.actual_joint_z_m * 1000.0 + self.GRIPPER_HOME_Z
                )
                feedback_updated = True
            elif (
                name == "joint_theta"
                or name.endswith("/joint_theta")
                or name.endswith("::joint_theta")
            ):
                self.actual_gripper_theta_deg = math.degrees(position)
                feedback_updated = True

        if feedback_updated:
            self.last_joint_feedback_time = time.monotonic()

    def handle_sim_pose_info(self, msg):
        model_names = (*self.CHIP_MODELS, self.SUBSTRATE_MODEL)
        received_at = time.monotonic()
        for transform_stamped in msg.transforms:
            frame_name = transform_stamped.child_frame_id.replace('::', '/')
            entity_name = frame_name.strip('/').split('/')[-1]
            if entity_name not in model_names:
                continue

            transform = transform_stamped.transform
            self.sim_model_poses[entity_name] = {
                'x_m': float(transform.translation.x),
                'y_m': float(transform.translation.y),
                'z_m': float(transform.translation.z),
                'theta_deg': quaternion_yaw_deg(transform.rotation),
                'received_at': received_at,
                'frame_name': transform_stamped.child_frame_id,
            }

    def contact_message_has_pair(self, msg, first_tokens, second_tokens):
        for contact in msg.contacts:
            first_name = contact.collision1.name.lower()
            second_name = contact.collision2.name.lower()
            direct_match = (
                any(token in first_name for token in first_tokens)
                and any(token in second_name for token in second_tokens)
            )
            reverse_match = (
                any(token in second_name for token in first_tokens)
                and any(token in first_name for token in second_tokens)
            )
            if direct_match or reverse_match:
                return True
        return False

    def handle_picker_contacts(self, msg):
        if not self.contact_message_has_pair(
            msg,
            [self.PICKER_COLLISION_TOKEN],
            self.CHIP_CONTACT_TOKENS,
        ):
            return

        self.last_picker_contact_time = time.monotonic()
        if self.actual_gripper_z_mm is not None:
            self.picker_contact_gripper_z_mm = self.actual_gripper_z_mm

    def handle_substrate_contacts(self, msg):
        if not self.contact_message_has_pair(
            msg,
            self.PLACEMENT_SUPPORT_TOKENS,
            self.CHIP_CONTACT_TOKENS,
        ):
            return

        self.last_substrate_contact_time = time.monotonic()
        if self.actual_gripper_z_mm is not None:
            self.substrate_contact_gripper_z_mm = self.actual_gripper_z_mm

    def handle_chip_contacts(self, msg):
        self.handle_picker_contacts(msg)
        self.handle_substrate_contacts(msg)

    def publish_empty_ign_topic(self, topic, duration_sec=0.3):
        cmd = [
            "ign",
            "topic",
            "-t",
            topic,
            "-m",
            "ignition.msgs.Empty",
            "-p",
            "unused: true",
            "-d",
            str(duration_sec),
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=duration_sec + 1.5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            self.get_logger().warn(f'Gazebo vacuum topic publish 실패({topic}): {exc}')
            return False

        if result.returncode != 0:
            detail = result.stderr.strip()
            self.get_logger().warn(f'Gazebo vacuum topic publish 실패({topic}): {detail}')
            return False

        return True

    def ignition_topic_exists(self, topic):
        if topic in self.known_dynamic_joint_topics:
            return True

        if self.ignition_topic_cache_loaded:
            return False

        try:
            result = subprocess.run(
                ["ign", "topic", "-l"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=self.DYNAMIC_TOPIC_DISCOVERY_TIMEOUT_SEC,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

        available = {line.strip() for line in result.stdout.splitlines()}
        self.known_dynamic_joint_topics.update(available)
        self.ignition_topic_cache_loaded = True
        return topic in available

    def add_runtime_detachable_joint(
        self,
        parent_model,
        parent_link,
        child_model,
        attach_topic,
        detach_topic,
        state_topic,
    ):
        parent_entity_id = self.gazebo_model_entity_id(parent_model)
        if parent_entity_id is None:
            self.get_logger().error(
                f'Gazebo parent model entity ID를 찾지 못했습니다: {parent_model}'
            )
            return False

        inner_xml = (
            f'<parent_link>{parent_link}</parent_link>'
            f'<child_model>{child_model}</child_model>'
            '<child_link>chip_link</child_link>'
            f'<attach_topic>{attach_topic}</attach_topic>'
            f'<detach_topic>{detach_topic}</detach_topic>'
            f'<output_topic>{state_topic}</output_topic>'
        )
        request = (
            f'entity {{ id: {parent_entity_id} type: MODEL }} '
            'plugins { '
            'name: "ignition::gazebo::systems::DetachableJoint" '
            'filename: "ignition-gazebo-detachable-joint-system" '
            f'innerxml: "{inner_xml}" '
            '}'
        )
        cmd = [
            "ign",
            "service",
            "-s",
            self.DYNAMIC_SYSTEM_SERVICE,
            "--reqtype",
            "ignition.msgs.EntityPlugin_V",
            "--reptype",
            "ignition.msgs.Boolean",
            "--timeout",
            str(self.DYNAMIC_SYSTEM_TIMEOUT_MS),
            "--req",
            request,
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.DYNAMIC_SYSTEM_TIMEOUT_MS / 1000.0 + 1.0,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            self.get_logger().error(
                f'Gazebo runtime detachable joint 추가 실패({child_model}): {exc}'
            )
            return False

        response = f'{result.stdout}\n{result.stderr}'.strip().lower()
        accepted = result.returncode == 0 and (
            'data: true' in response or 'data: 1' in response
        )
        if not accepted:
            self.get_logger().error(
                'Gazebo runtime detachable joint 추가 거부: '
                f'parent={parent_model}::{parent_link}, child={child_model}, '
                f'response={response or "empty"}'
            )
            return False

        self.known_dynamic_joint_topics.add(state_topic)
        time.sleep(0.2)
        self.get_logger().info(
            'Gazebo runtime detachable joint 추가 및 접촉 위치 고정: '
            f'parent={parent_model}::{parent_link}, child={child_model}'
        )
        return True

    def gazebo_model_entity_id(self, model_name):
        if model_name in self.gazebo_model_entity_ids:
            return self.gazebo_model_entity_ids[model_name]

        try:
            result = subprocess.run(
                ["ign", "model", "-m", str(model_name)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2.0,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None

        match = re.search(r'Model:\s*\[(\d+)\]', result.stdout)
        if match is not None:
            entity_id = int(match.group(1))
            self.gazebo_model_entity_ids[model_name] = entity_id
            return entity_id

        pose_topic = f'/world/{self.GAZEBO_WORLD}/pose/info'
        try:
            result = subprocess.run(
                ["ign", "topic", "-e", "-t", pose_topic, "-n", "1"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2.0,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None

        model_pattern = re.compile(
            rf'pose\s*\{{\s*name:\s*"{re.escape(str(model_name))}"'
            r'\s*id:\s*(\d+)',
        )
        match = model_pattern.search(result.stdout)
        if match is None:
            return None
        entity_id = int(match.group(1))
        self.gazebo_model_entity_ids[model_name] = entity_id
        return entity_id

    def ensure_picker_joint(self):
        if self.ignition_topic_exists(self.VACUUM_STATE_TOPIC):
            return True, False
        added = self.add_runtime_detachable_joint(
            'robot_system',
            'theta_link_1',
            self.RED_CHIP_MODEL,
            self.ATTACH_TOPIC,
            self.DETACH_TOPIC,
            self.VACUUM_STATE_TOPIC,
        )
        return added, added

    def ensure_stack_bond_joint(self):
        if self.ignition_topic_exists(self.SUBSTRATE_STATE_TOPIC):
            return True, False
        parent_link = (
            'substrate_link'
            if self.PLACEMENT_SUPPORT_MODEL == self.SUBSTRATE_MODEL
            else 'chip_link'
        )
        added = self.add_runtime_detachable_joint(
            self.PLACEMENT_SUPPORT_MODEL,
            parent_link,
            self.RED_CHIP_MODEL,
            self.SUBSTRATE_ATTACH_TOPIC,
            self.SUBSTRATE_DETACH_TOPIC,
            self.SUBSTRATE_STATE_TOPIC,
        )
        return added, added

    def contact_output_has_token_pair(self, output, first_tokens, second_tokens):
        normalized = output.lower()
        if not any(token in normalized for token in first_tokens):
            return False
        if not any(token in normalized for token in second_tokens):
            return False

        contact_blocks = normalized.split("contact {")
        if len(contact_blocks) <= 1:
            return True

        for block in contact_blocks[1:]:
            if not any(token in block for token in first_tokens):
                continue
            if any(token in block for token in second_tokens):
                return True

        return False

    def contact_output_has_picker_chip_pair(self, output):
        return self.contact_output_has_token_pair(
            output,
            [self.PICKER_COLLISION_TOKEN],
            self.CHIP_CONTACT_TOKENS,
        )

    def contact_output_has_substrate_chip_pair(self, output):
        return self.contact_output_has_token_pair(
            output,
            self.PLACEMENT_SUPPORT_TOKENS,
            self.CHIP_CONTACT_TOKENS,
        )

    def contact_output_has_any_contact(self, output):
        normalized = output.lower()
        return "contact {" in normalized and "collision" in normalized

    def read_contact_topic_once(
        self,
        topic,
        matcher,
        timeout_sec=0.25,
        allow_any_contact=False,
    ):
        cmd = [
            "ign",
            "topic",
            "-e",
            "-t",
            topic,
            "-n",
            "1",
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False
        except (FileNotFoundError, OSError) as exc:
            self.get_logger().warn(f'contact topic 읽기 실패({topic}): {exc}')
            return False

        output = f"{result.stdout}\n{result.stderr}".lower()
        if matcher(output):
            return True
        return allow_any_contact and self.contact_output_has_any_contact(output)

    def read_picker_contact_topic_once(self, topic, timeout_sec=0.25):
        return self.read_contact_topic_once(
            topic,
            self.contact_output_has_picker_chip_pair,
            timeout_sec=timeout_sec,
            allow_any_contact=False,
        )

    def read_substrate_contact_topic_once(self, topic, timeout_sec=0.25):
        return self.read_contact_topic_once(
            topic,
            self.contact_output_has_substrate_chip_pair,
            timeout_sec=timeout_sec,
            allow_any_contact=False,
        )

    def spin_callbacks(self, timeout_sec=0.02):
        if not rclpy.ok():
            return
        rclpy.spin_once(self, timeout_sec=max(0.0, float(timeout_sec)))

    def refresh_picker_contact_topics(self):
        now = time.monotonic()
        if now - self.last_contact_topic_discovery < self.CONTACT_TOPIC_DISCOVERY_INTERVAL_SEC:
            return

        self.last_contact_topic_discovery = now
        try:
            result = subprocess.run(
                ["ign", "topic", "-l"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=0.5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return

        if result.returncode != 0:
            return

        discovered = []
        for line in result.stdout.splitlines():
            topic = line.strip()
            normalized = topic.lower()
            if "contact" not in normalized:
                continue
            if "picker_contact_sensor" not in normalized and "picker/contact" not in normalized:
                continue
            if topic not in discovered:
                discovered.append(topic)

        if discovered:
            self.discovered_picker_contact_topics = discovered

    def get_picker_contact_topics(self):
        if self.USE_IGN_CONTACT_FALLBACK:
            self.refresh_picker_contact_topics()
        topics = []
        active_chip_topics = [
            self.CHIP_CONTACT_SENSOR_TOPIC,
            self.CHIP_CONTACT_TOPIC,
        ]
        for topic in (
            self.PICKER_CONTACT_TOPICS
            + active_chip_topics
            + self.discovered_picker_contact_topics
        ):
            if topic and topic not in topics:
                topics.append(topic)
        return topics or [self.PICKER_CONTACT_TOPIC]

    def read_picker_contact_once(self, timeout_sec=0.25):
        topics = self.get_picker_contact_topics()
        per_topic_timeout = max(0.2, timeout_sec / len(topics))
        for topic in topics:
            if self.read_picker_contact_topic_once(topic, timeout_sec=per_topic_timeout):
                self.last_picker_contact_time = time.monotonic()
                return True
        return False

    def read_substrate_contact_once(self, timeout_sec=0.25):
        topics = self.SUBSTRATE_CONTACT_TOPICS
        per_topic_timeout = max(0.2, timeout_sec / len(topics))
        for topic in topics:
            if self.read_substrate_contact_topic_once(topic, timeout_sec=per_topic_timeout):
                self.last_substrate_contact_time = time.monotonic()
                return True
        return False

    def has_recent_picker_contact(self):
        return (
            self.last_picker_contact_time > 0.0
            and time.monotonic() - self.last_picker_contact_time
            <= self.CONTACT_CONFIRM_WINDOW_SEC
        )

    def has_recent_substrate_contact(self):
        return (
            self.last_substrate_contact_time > 0.0
            and time.monotonic() - self.last_substrate_contact_time
            <= self.CONTACT_CONFIRM_WINDOW_SEC
        )

    def mark_geometric_contact(self, contact_name):
        now = time.monotonic()
        normalized = str(contact_name).lower()
        if 'picker' in normalized and 'chip' in normalized:
            self.last_picker_contact_time = now
        else:
            self.last_substrate_contact_time = now

    def wait_for_picker_contact(self, timeout_sec=None):
        if not self.REQUIRE_PICKER_CONTACT:
            return True

        wait_timeout = self.PICKER_CONTACT_TIMEOUT_SEC if timeout_sec is None else timeout_sec
        deadline = time.monotonic() + wait_timeout
        topics = self.get_picker_contact_topics()
        self.get_logger().info(
            'picker-chip 실제 접촉 대기: '
            f'{", ".join(topics)}'
        )
        while time.monotonic() < deadline:
            self.spin_callbacks(min(0.02, max(0.0, deadline - time.monotonic())))
            if self.has_recent_picker_contact():
                self.get_logger().info('picker-chip contact 감지됨(ROS contact bridge)')
                return True
            remaining = max(0.05, min(0.25, deadline - time.monotonic()))
            if (
                self.USE_IGN_CONTACT_FALLBACK
                and self.read_picker_contact_once(timeout_sec=remaining)
            ):
                if self.actual_gripper_z_mm is not None:
                    self.picker_contact_gripper_z_mm = self.actual_gripper_z_mm
                self.get_logger().info('picker-chip contact 감지됨(Ignition topic)')
                return True

        self.get_logger().info('현재 위치에서는 picker-chip contact가 아직 감지되지 않았습니다.')
        return False

    def wait_for_substrate_contact(self, timeout_sec=None):
        if not self.REQUIRE_SUBSTRATE_CONTACT:
            return True

        wait_timeout = self.SUBSTRATE_CONTACT_TIMEOUT_SEC if timeout_sec is None else timeout_sec
        deadline = time.monotonic() + wait_timeout
        self.get_logger().info(
            f'{self.RED_CHIP_MODEL}-{self.PLACEMENT_SUPPORT_MODEL} 실제 접촉 대기: '
            f'{", ".join(self.SUBSTRATE_CONTACT_TOPICS)}'
        )
        while time.monotonic() < deadline:
            self.spin_callbacks(min(0.02, max(0.0, deadline - time.monotonic())))
            if self.has_recent_substrate_contact():
                self.get_logger().info(
                    f'{self.RED_CHIP_MODEL}-{self.PLACEMENT_SUPPORT_MODEL} '
                    'contact 감지됨(ROS contact bridge)'
                )
                return True
            remaining = max(0.05, min(0.25, deadline - time.monotonic()))
            if (
                self.USE_IGN_CONTACT_FALLBACK
                and self.read_substrate_contact_once(timeout_sec=remaining)
            ):
                if self.actual_gripper_z_mm is not None:
                    self.substrate_contact_gripper_z_mm = self.actual_gripper_z_mm
                self.get_logger().info(
                    f'{self.RED_CHIP_MODEL}-{self.PLACEMENT_SUPPORT_MODEL} '
                    'contact 감지됨(Ignition topic)'
                )
                return True

        self.get_logger().info(
            f'현재 위치에서는 {self.RED_CHIP_MODEL}-'
            f'{self.PLACEMENT_SUPPORT_MODEL} contact가 아직 감지되지 않았습니다.'
        )
        return False

    def confirm_contact_at_z_floor(self, contact_wait_fn, contact_name):
        self.get_logger().info(
            f'{contact_name}: Z 안전 한계에서 추가 하강 없이 '
            'contact sensor를 한 번 더 확인합니다.'
        )
        if not contact_wait_fn(
            timeout_sec=max(0.25, self.CONTACT_DESCENT_CHECK_TIMEOUT_SEC),
        ):
            return False

        contact_z = self.actual_gripper_z_mm
        self.get_logger().info(
            f'{contact_name}: 지연 도착한 contact 감지, 현재 Z에서 정지'
        )
        if contact_z is not None:
            self.get_logger().info(
                f'{contact_name}: 실제 gripper z={contact_z:.3f}mm'
            )
        return True

    def descend_until_contact(
        self,
        x_mm,
        y_mm,
        target_z_mm,
        contact_recent_fn,
        contact_wait_fn,
        contact_name,
        theta_deg=0.0,
    ):
        if self.CONTACT_DESCENT_STEP_MM <= 0.0:
            self.get_logger().warn('contact 단계 하강 step이 0 이하라 하강을 중단합니다.')
            return False

        contact_floor_z = float(target_z_mm)
        probe_depth = max(0.0, self.CONTACT_PROBE_DEPTH_MM)
        command_floor_z = max(
            self.COMMAND_LIMITS_MM["z"][0],
            contact_floor_z - probe_depth,
        )
        approach_z = (
            contact_floor_z + max(0.0, self.CONTACT_APPROACH_OFFSET_MM)
        )
        current_z = approach_z

        self.get_logger().info(
            f'{contact_name}: {approach_z:.2f}mm 접근 후 '
            f'예상 접촉면 {contact_floor_z:.2f}mm, '
            f'접촉 탐색 명령 하한 {command_floor_z:.2f}mm까지 단계 하강합니다.'
        )
        if not self.publish_move(x_mm, y_mm, approach_z, theta_deg=theta_deg):
            return False
        contact_detected = self.wait_for_descent_motion_or_contact(
            contact_recent_fn,
            timeout_sec=self.CONTACT_DESCENT_MOTION_TIMEOUT_SEC,
        )

        if contact_detected or contact_wait_fn(
            timeout_sec=self.CONTACT_DESCENT_CHECK_TIMEOUT_SEC,
        ):
            contact_z = self.actual_gripper_z_mm
            self.get_logger().info(f'{contact_name}: 접근 높이에서 contact 감지, 하강 정지')
            if contact_z is not None:
                self.get_logger().info(
                    f'{contact_name}: 실제 gripper z={contact_z:.3f}mm'
                )
            return True

        if self.actual_z_below_contact_floor(contact_floor_z):
            if self.confirm_contact_at_z_floor(contact_wait_fn, contact_name):
                return True
            self.recover_from_z_floor_violation(x_mm, y_mm, approach_z, theta_deg)
            return False

        while current_z > command_floor_z:
            next_z = max(
                command_floor_z,
                current_z - self.CONTACT_DESCENT_STEP_MM,
            )
            if next_z >= current_z:
                break

            self.get_logger().info(
                f'{contact_name}: gripper z={next_z:.2f}mm로 단계 하강'
            )
            if not self.publish_move(x_mm, y_mm, next_z, theta_deg=theta_deg):
                return False
            contact_detected = self.wait_for_descent_motion_or_contact(
                contact_recent_fn,
                timeout_sec=self.CONTACT_DESCENT_MOTION_TIMEOUT_SEC,
            )
            current_z = next_z

            if contact_detected or contact_wait_fn(
                timeout_sec=self.CONTACT_DESCENT_CHECK_TIMEOUT_SEC,
            ):
                contact_z = self.actual_gripper_z_mm
                self.get_logger().info(
                    f'{contact_name}: contact 감지, z={current_z:.2f}mm에서 정지'
                )
                if contact_z is not None:
                    self.get_logger().info(
                        f'{contact_name}: 실제 gripper z={contact_z:.3f}mm'
                    )
                return True

            if self.actual_z_below_contact_floor(contact_floor_z):
                if self.confirm_contact_at_z_floor(contact_wait_fn, contact_name):
                    return True
                self.recover_from_z_floor_violation(x_mm, y_mm, approach_z, theta_deg)
                return False

        self.get_logger().info(
            f'{contact_name}: 접촉 탐색 하한 {command_floor_z:.2f}mm까지 '
            '도달했지만 contact 미감지'
        )
        if self.ALLOW_GEOMETRIC_CONTACT_FALLBACK:
            self.mark_geometric_contact(contact_name)
            self.get_logger().warn(
                f'{contact_name}: contact sensor는 미감지였지만 '
                f'모델 치수상 접촉 한계 z={contact_floor_z:.2f}mm에 '
                '도달했으므로 '
                '추가 하강 없이 이 위치에서 접촉으로 처리합니다.'
            )
            return True
        return False

    def wait_for_descent_motion_or_contact(self, contact_recent_fn, timeout_sec):
        self.wait_for_motion(self.CONTACT_DESCENT_SETTLE_SEC)
        deadline = time.monotonic() + max(0.0, float(timeout_sec))
        stable_samples = 0
        while time.monotonic() < deadline:
            self.spin_callbacks(min(0.02, deadline - time.monotonic()))
            if contact_recent_fn():
                return True

            actual_values = (
                self.actual_gripper_x_mm,
                self.actual_gripper_y_mm,
                self.actual_gripper_z_mm,
                self.actual_gripper_theta_deg,
            )
            if any(value is None for value in actual_values):
                continue
            if time.monotonic() - self.last_joint_feedback_time > 1.0:
                continue

            theta_error = math.degrees(math.atan2(
                math.sin(math.radians(
                    self.actual_gripper_theta_deg - self.last_sent_theta_deg
                )),
                math.cos(math.radians(
                    self.actual_gripper_theta_deg - self.last_sent_theta_deg
                )),
            ))
            target_reached = (
                abs(self.actual_gripper_x_mm - self.last_sent_x)
                <= self.VISION_MOTION_POSITION_TOLERANCE_MM
                and abs(self.actual_gripper_y_mm - self.last_sent_y)
                <= self.VISION_MOTION_POSITION_TOLERANCE_MM
                and abs(self.actual_gripper_z_mm - self.last_sent_z)
                <= self.VISION_MOTION_Z_TOLERANCE_MM
                and abs(theta_error)
                <= self.VISION_MOTION_THETA_TOLERANCE_DEG
            )
            stable_samples = stable_samples + 1 if target_reached else 0
            if stable_samples >= 5:
                return False

        return contact_recent_fn()

    def actual_z_below_contact_floor(self, floor_z_mm, tolerance_mm=None):
        if self.actual_gripper_z_mm is None:
            return False
        if time.monotonic() - self.last_joint_feedback_time > 1.0:
            return False
        tolerance = (
            self.CONTACT_FLOOR_TOLERANCE_MM
            if tolerance_mm is None
            else max(0.0, float(tolerance_mm))
        )
        return self.actual_gripper_z_mm < float(floor_z_mm) - tolerance

    def recover_from_z_floor_violation(self, x_mm, y_mm, recovery_z_mm, theta_deg):
        self.get_logger().error(
            'Z 안전 한계 침범 감지: '
            f'actual_gripper_z={self.actual_gripper_z_mm:.3f}mm. '
            f'{float(recovery_z_mm):.2f}mm로 즉시 복귀합니다.'
        )
        self.publish_move(x_mm, y_mm, recovery_z_mm, theta_deg=theta_deg)
        self.wait_for_motion(self.CONTACT_DESCENT_SETTLE_SEC)

    def search_picker_contact_downward(self):
        if not self.REQUIRE_PICKER_CONTACT:
            return True

        if self.CONTACT_SEARCH_STEP_MM <= 0.0 or self.CONTACT_SEARCH_DEPTH_MM <= 0.0:
            return False

        start_z = self.last_sent_z
        searched = 0.0
        lower_limit = max(self.COMMAND_LIMITS_MM["z"][0], self.MIN_CONTACT_Z)
        self.get_logger().info(
            f'contact 탐색 시작: {start_z:.2f}mm -> {lower_limit:.2f}mm '
            f'(step={self.CONTACT_SEARCH_STEP_MM:.2f}mm)'
        )

        while searched < self.CONTACT_SEARCH_DEPTH_MM:
            next_z = max(
                lower_limit,
                start_z - searched - self.CONTACT_SEARCH_STEP_MM,
            )
            if next_z >= self.last_sent_z:
                break

            searched = start_z - next_z
            self.get_logger().info(
                f'contact 미감지: gripper를 {next_z:.2f}mm까지 추가 하강해 재확인합니다.'
            )
            if not self.publish_move(
                self.last_sent_x,
                self.last_sent_y,
                next_z,
                theta_deg=self.last_sent_theta_deg,
            ):
                return False

            if self.wait_for_picker_contact(timeout_sec=self.CONTACT_SEARCH_SETTLE_SEC):
                return True

            if next_z <= lower_limit:
                break

        return False

    def attach_red_chip_to_picker(self, require_contact=True):
        if not self.USE_DETACHABLE_JOINT:
            return False

        if (
            require_contact
            and self.REQUIRE_PICKER_CONTACT
            and not self.has_recent_picker_contact()
            and not self.read_picker_contact_once(timeout_sec=0.5)
        ):
            self.get_logger().warn(
                'attach 직전 picker-chip contact 재확인 실패: attach 요청을 보내지 않습니다.'
            )
            return False

        joint_ready, newly_added = self.ensure_picker_joint()
        if not joint_ready:
            return False
        if newly_added:
            return True

        attached = self.publish_empty_ign_topic(
            self.ATTACH_TOPIC,
            duration_sec=self.ATTACH_PUBLISH_DURATION_SEC,
        )
        if attached:
            self.get_logger().info(
                f'Gazebo fixed joint attach 요청: {self.ATTACH_TOPIC}'
            )
        return attached

    def detach_red_chip_from_picker(self):
        if not self.USE_DETACHABLE_JOINT:
            return False
        if not self.ignition_topic_exists(self.VACUUM_STATE_TOPIC):
            self.get_logger().debug(
                f'vacuum joint가 아직 생성되지 않아 detach를 생략합니다: '
                f'{self.RED_CHIP_MODEL}'
            )
            return True

        detached = self.publish_empty_ign_topic(
            self.DETACH_TOPIC,
            duration_sec=self.ATTACH_PUBLISH_DURATION_SEC,
        )
        if detached:
            self.get_logger().info(
                f'Gazebo fixed joint detach 요청: {self.DETACH_TOPIC}'
            )
        return detached

    def attach_chip_to_substrate(self, require_contact=True):
        if not self.USE_DETACHABLE_JOINT:
            return False

        if (
            require_contact
            and self.REQUIRE_SUBSTRATE_CONTACT
            and not self.has_recent_substrate_contact()
            and not self.read_substrate_contact_once(timeout_sec=0.5)
        ):
            self.get_logger().warn(
                f'stack attach 직전 {self.RED_CHIP_MODEL}-'
                f'{self.PLACEMENT_SUPPORT_MODEL} contact 재확인 실패: '
                'attach 요청을 보내지 않습니다.'
            )
            return False

        joint_ready, newly_added = self.ensure_stack_bond_joint()
        if not joint_ready:
            return False
        if newly_added:
            return True

        attached = self.publish_empty_ign_topic(
            self.SUBSTRATE_ATTACH_TOPIC,
            duration_sec=self.ATTACH_PUBLISH_DURATION_SEC,
        )
        if attached:
            self.get_logger().info(
                f'Gazebo stack bond attach 요청({self.RED_CHIP_MODEL}): '
                f'{self.SUBSTRATE_ATTACH_TOPIC}'
            )
        return attached

    def detach_chip_from_substrate(self):
        if not self.USE_DETACHABLE_JOINT:
            return False
        if not self.ignition_topic_exists(self.SUBSTRATE_STATE_TOPIC):
            self.get_logger().debug(
                f'stack bond joint가 아직 생성되지 않아 detach를 생략합니다: '
                f'{self.RED_CHIP_MODEL}'
            )
            return True

        detached = self.publish_empty_ign_topic(
            self.SUBSTRATE_DETACH_TOPIC,
            duration_sec=self.ATTACH_PUBLISH_DURATION_SEC,
        )
        if detached:
            self.get_logger().info(
                f'Gazebo stack bond detach 요청({self.RED_CHIP_MODEL}): '
                f'{self.SUBSTRATE_DETACH_TOPIC}'
            )
        return detached

    def force_vacuum_detached(self, reason):
        self.vacuum_attached = VACUUM_OFF
        if self.USE_DETACHABLE_JOINT:
            self.get_logger().info(f'vacuum detach 초기화: {reason}')
            self.detach_red_chip_from_picker()
        self.save_current_state()

    def force_substrate_bond_detached(self, reason):
        if self.USE_DETACHABLE_JOINT:
            self.get_logger().info(f'substrate bond detach 초기화: {reason}')
            self.detach_chip_from_substrate()
        self.save_current_state()

    def validate_command_pose(self, x, y, z):
        values = {"x": x, "y": y, "z": z}
        for axis, value in values.items():
            lower, upper = self.COMMAND_LIMITS_MM[axis]
            if not lower <= float(value) <= upper:
                self.get_logger().error(
                    f'{axis}={value}mm는 명령 가능 범위 [{lower}, {upper}]mm 밖입니다.'
                )
                return False
        return True

    # 1. 통합 이동 전송 및 위치 기록 함수
    def publish_move(self, x, y, z, theta_deg=None):
        """
        로봇에게 이동 명령을 쏘는 동시에, 현재 SW에 로봇의 XY/Z/theta 위치를 저장함.
        이를 통해 'execute_z_press' 명령 시 정확한 위치에서 하강이 가능함.
        """
        if not self.validate_command_pose(x, y, z):
            return False

        target_theta = self.last_sent_theta_deg if theta_deg is None else theta_deg
        self.last_sent_x = x
        self.last_sent_y = y
        self.last_sent_z = z
        self.last_sent_theta_deg = target_theta
        
        msg = Pose()
        msg.position.x = float(x)
        msg.position.y = float(y)
        msg.position.z = float(z)
        set_pose_yaw(msg, target_theta)
        
        # 하드웨어로 명령 전송
        self.cmd_pub.publish(msg)
        self.get_logger().debug(
            f' Command Sent: X={x}, Y={y}, Z={z}, theta={target_theta}deg'
        )

        if self.vacuum_attached and not self.USE_DETACHABLE_JOINT:
            self.move_red_chip_with_tool(x, y, z, target_theta)
        else:
            self.save_current_state()
        return True

    def save_current_state(self):
        save_state(
            self.last_sent_x,
            self.last_sent_y,
            self.last_sent_z,
            self.last_sent_theta_deg,
            vacuum_attached=self.vacuum_attached,
            chip_x=self.chip_x,
            chip_y=self.chip_y,
            chip_z=self.chip_z,
            chip_theta_deg=self.chip_theta_deg,
        )

    def command_xy_to_world(self, x_mm, y_mm):
        return (
            self.CHIP_WORLD_CENTER_X_M + float(x_mm) * 0.001,
            self.CHIP_WORLD_CENTER_Y_M + float(y_mm) * 0.001,
        )

    def absolute_to_world(self, x_mm, y_mm, z_mm):
        return (
            float(x_mm) * 0.001,
            float(y_mm) * 0.001,
            self.ABS_Z_ZERO_WORLD_M + float(z_mm) * 0.001,
        )

    def chip_bottom_to_center_z(self, bottom_z_mm):
        return float(bottom_z_mm) + self.CHIP_THICKNESS_MM / 2.0

    def substrate_top_z_mm(self):
        return self.BASE_TOP_Z + self.SUBSTRATE_THICKNESS_MM

    def stack_contact_surface_z_mm(self):
        return (
            self.substrate_top_z_mm()
            + self.active_stack_level * self.CHIP_THICKNESS_MM
        )

    def record_carried_chip_offset(self, chip_bottom_z_mm):
        self.spin_callbacks(0.05)
        gripper_z = None
        source = "post-attach joint feedback"
        if (
            self.actual_gripper_z_mm is not None
            and time.monotonic() - self.last_joint_feedback_time <= 1.0
        ):
            gripper_z = self.actual_gripper_z_mm
        elif self.picker_contact_gripper_z_mm is not None:
            gripper_z = self.picker_contact_gripper_z_mm
            source = "contact feedback fallback"
        if gripper_z is None:
            gripper_z = self.last_sent_z
            source = "command fallback"

        measured_offset = float(gripper_z) - float(chip_bottom_z_mm)
        self.carried_chip_bottom_offset_mm = max(
            self.DEFAULT_CARRIED_CHIP_BOTTOM_OFFSET_MM,
            measured_offset,
        )
        self.get_logger().info(
            'pick 오프셋 기록: '
            f'gripper_z={float(gripper_z):.3f}mm({source}), '
            f'chip_bottom_z={float(chip_bottom_z_mm):.2f}mm, '
            f'gripper-chip_bottom={self.carried_chip_bottom_offset_mm:.3f}mm'
        )
        return self.carried_chip_bottom_offset_mm

    def carried_chip_place_z_mm(self):
        return self.stack_contact_surface_z_mm() + self.carried_chip_bottom_offset_mm

    def carried_chip_world_z(self, z_mm):
        carried_height = max(float(z_mm) * 0.001, self.CHIP_MIN_CARRIED_HEIGHT_M)
        return self.CHIP_SURFACE_WORLD_Z_M + carried_height

    def set_red_chip_pose(self, x_m, y_m, z_m, theta_deg=0.0):
        theta_rad = math.radians(theta_deg)
        req = (
            f'name: "{self.RED_CHIP_MODEL}" '
            f'position {{ x: {x_m:.6f} y: {y_m:.6f} z: {z_m:.6f} }} '
            f'orientation {{ x: 0 y: 0 z: {math.sin(theta_rad / 2.0):.9f} '
            f'w: {math.cos(theta_rad / 2.0):.9f} }}'
        )
        cmd = [
            "ign",
            "service",
            "-s",
            f"/world/{self.GAZEBO_WORLD}/set_pose",
            "--reqtype",
            "ignition.msgs.Pose",
            "--reptype",
            "ignition.msgs.Boolean",
            "--timeout",
            str(self.CHIP_SERVICE_TIMEOUT_MS),
            "--req",
            req,
        ]

        try:
            if not self.WAIT_FOR_CHIP_SERVICE:
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.chip_x = x_m
                self.chip_y = y_m
                self.chip_z = z_m
                self.chip_theta_deg = theta_deg
                self.save_current_state()
                return True

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=(self.CHIP_SERVICE_TIMEOUT_MS / 1000.0) + 0.5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            self.get_logger().warn(f'{self.RED_CHIP_MODEL} 위치 갱신 실패: {exc}')
            return False

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            self.get_logger().warn(f'{self.RED_CHIP_MODEL} 위치 갱신 실패: {detail}')
            return False

        self.chip_x = x_m
        self.chip_y = y_m
        self.chip_z = z_m
        self.chip_theta_deg = theta_deg
        self.save_current_state()
        return True

    def set_gazebo_model_pose(self, model_name, x_m, y_m, z_m, theta_deg=0.0):
        theta_rad = math.radians(theta_deg)
        req = (
            f'name: "{model_name}" '
            f'position {{ x: {float(x_m):.6f} y: {float(y_m):.6f} '
            f'z: {float(z_m):.6f} }} '
            f'orientation {{ x: 0 y: 0 z: {math.sin(theta_rad / 2.0):.9f} '
            f'w: {math.cos(theta_rad / 2.0):.9f} }}'
        )
        cmd = [
            "ign",
            "service",
            "-s",
            f"/world/{self.GAZEBO_WORLD}/set_pose",
            "--reqtype",
            "ignition.msgs.Pose",
            "--reptype",
            "ignition.msgs.Boolean",
            "--timeout",
            str(self.CHIP_SERVICE_TIMEOUT_MS),
            "--req",
            req,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=(self.CHIP_SERVICE_TIMEOUT_MS / 1000.0) + 0.5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            self.get_logger().warn(f'{model_name} 위치 갱신 실패: {exc}')
            return False

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            self.get_logger().warn(f'{model_name} 위치 갱신 실패: {detail}')
            return False
        return True

    def set_substrate_pose_abs(self, x_mm, y_mm):
        center_z_mm = self.BASE_TOP_Z + self.SUBSTRATE_THICKNESS_MM / 2.0
        world_x, world_y, world_z = self.absolute_to_world(
            x_mm,
            y_mm,
            center_z_mm,
        )
        return self.set_gazebo_model_pose(
            self.SUBSTRATE_MODEL,
            world_x,
            world_y,
            world_z,
        )

    def set_red_chip_pose_abs(self, x_mm, y_mm, z_mm, theta_deg=0.0):
        world_x, world_y, world_z = self.absolute_to_world(
            x_mm,
            y_mm,
            self.chip_bottom_to_center_z(z_mm),
        )
        return self.set_red_chip_pose(
            world_x,
            world_y,
            world_z,
            theta_deg=theta_deg,
        )

    def wait_for_red_chip_pose_abs(
        self,
        x_mm,
        y_mm,
        z_mm,
        theta_deg,
        timeout_sec=1.0,
    ):
        target_x_m, target_y_m, target_z_m = self.absolute_to_world(
            x_mm,
            y_mm,
            self.chip_bottom_to_center_z(z_mm),
        )
        deadline = time.monotonic() + max(0.0, float(timeout_sec))
        while time.monotonic() < deadline:
            self.spin_callbacks(min(0.02, deadline - time.monotonic()))
            pose = self.sim_model_poses.get(self.RED_CHIP_MODEL)
            if pose is None:
                continue
            theta_error_deg = math.degrees(math.atan2(
                math.sin(math.radians(pose['theta_deg'] - float(theta_deg))),
                math.cos(math.radians(pose['theta_deg'] - float(theta_deg))),
            ))
            if (
                abs(pose['x_m'] - target_x_m) <= 0.0005
                and abs(pose['y_m'] - target_y_m) <= 0.0005
                and abs(pose['z_m'] - target_z_m) <= 0.0001
                and abs(theta_error_deg) <= 0.1
            ):
                return True
        return False

    def place_red_chip(self, x_mm, y_mm, theta_deg=0.0):
        return self.set_red_chip_pose_abs(
            x_mm,
            y_mm,
            self.CHIP_REST_Z,
            theta_deg=theta_deg,
        )

    def move_red_chip_with_tool(self, x_mm, y_mm, z_mm, theta_deg=0.0):
        return self.set_red_chip_pose_abs(
            x_mm,
            y_mm,
            float(z_mm) - self.GRIPPER_CONTACT_OFFSET_MM - self.CHIP_THICKNESS_MM,
            theta_deg=theta_deg,
        )

    def reset_red_chip(
        self,
        x_mm=500.0,
        y_mm=400.0,
        z_mm=None,
        theta_deg=0.0,
        verify_pose=False,
    ):
        chip_z = self.CHIP_REST_Z if z_mm is None else float(z_mm)
        self.force_vacuum_detached('chip_reset 전에 기존 detachable joint를 해제')
        self.force_substrate_bond_detached('chip_reset 전에 기존 substrate bond를 해제')
        self.get_logger().info(
            f'{self.RED_CHIP_MODEL}을 절대좌표 '
            f'({x_mm}, {y_mm}, {chip_z})mm, theta={float(theta_deg):.3f}deg에 배치합니다.'
        )
        attempts = 3 if verify_pose else 1
        for attempt in range(1, attempts + 1):
            pose_updated = self.set_red_chip_pose_abs(
                x_mm,
                y_mm,
                chip_z,
                theta_deg=theta_deg,
            )
            pose_verified = (
                not verify_pose
                or (
                    pose_updated
                    and self.wait_for_red_chip_pose_abs(
                        x_mm,
                        y_mm,
                        chip_z,
                        theta_deg,
                    )
                )
            )
            if pose_updated and pose_verified:
                self.save_current_state()
                return True
            if attempt >= attempts:
                break
            self.get_logger().warn(
                f'{self.RED_CHIP_MODEL} 공급 위치 확인 실패: '
                f'detach/set_pose 재시도 {attempt + 1}/{attempts}'
            )
            self.force_vacuum_detached('chip pose 재시도 전 picker 고정 해제')
            self.force_substrate_bond_detached('chip pose 재시도 전 stack bond 해제')

        self.save_current_state()
        return False

    # 거시 카메라를 칩 중앙에 정렬
    def set_camera_center(self, chip_x, chip_y):

        """
        그리퍼 대신 옆에 달린 '카메라'가 칩 정중앙을 보도록 로봇 몸체를 오프셋만큼 이동시킴.
        """

        self.get_logger().info(f'카메라를 칩({chip_x}, {chip_y}) 정중앙에 위치시킵니다.')
        
        # 기구적 오프셋 보정 계산
        target_x = chip_x - self.GRIPPER_TO_CAMERA_DX
        target_y = chip_y - self.GRIPPER_TO_CAMERA_DY
        
        # 안전 높이에서 이동 실행 (기억 로직 포함)
        self.publish_move(target_x, target_y, self.HOVER_Z)

    # 3. 칩을 place할 위치로 칩 이동 (z축 이동은 x)
    def transfer_position(self, b_x, b_y):

        """
        칩을 픽업한 후, 타겟 구역 B의 전역 좌표로 이송함.
        """

        self.get_logger().info(f'구역 B({b_x}, {b_y})로 칩 이송을 시작합니다.')
        
        # place 목표 좌표로 이동 (기억 로직 포함)
        self.publish_move(b_x, b_y, self.HOVER_Z)

    # z축 압축
    def execute_z_press(self):

        """
        가장 최근에 이동했던(last_sent_x/y) 위치 그대로 Z축만 하강하여 누르기를 실행함.
        """

        self.get_logger().info('현재 위치에서 Z축 하강 및 가압 실행')

        # 저장된 XY 좌표와 바닥 높이(PRESS_Z)를 사용하여 명령 전송
        self.publish_move(self.last_sent_x, self.last_sent_y, self.PRESS_Z)

    # z축 압축 후 안전 높이로 복귀
    def lift_to_safety(self):

        """
        작업 완료 후 칩을 든 상태(또는 본딩 후)로 안전 높이까지 다시 상승.
        """

        self.get_logger().info('Z축 안전 높이로 복귀')
        self.publish_move(self.last_sent_x, self.last_sent_y, self.HOVER_Z)

    # 현재 XY는 유지하고 Z 높이만 변경
    def move_z(self, z):

        """
        현재 저장된 XY 위치에서 Z축 높이만 변경함.
        """

        self.get_logger().info(f'현재 XY 유지, Z={z}mm로 이동')
        self.publish_move(self.last_sent_x, self.last_sent_y, z)

    def move_relative(self, dx=0.0, dy=0.0, dz=0.0, dtheta_deg=0.0):

        """
        마지막으로 명령한 위치를 기준으로 상대 이동함.
        dx/dy/dz 단위는 mm, dtheta_deg 단위는 deg.
        """

        target_x = self.last_sent_x + dx
        target_y = self.last_sent_y + dy
        target_z = self.last_sent_z + dz
        target_theta = self.last_sent_theta_deg + dtheta_deg

        self.get_logger().info(
            f'상대 이동: dx={dx}mm, dy={dy}mm, dz={dz}mm, '
            f'dtheta={dtheta_deg}deg -> '
            f'({target_x}, {target_y}, {target_z}, {target_theta}deg)'
        )
        self.publish_move(target_x, target_y, target_z, theta_deg=target_theta)

    def move_back(self, distance_mm=30.0):

        """
        작업 좌표계 중심 기준 뒤쪽(-Y) 절대 위치로 이동함.
        예: distance_mm=30이면 (0, -30, HOVER_Z)로 이동.
        """

        target_y = -abs(distance_mm)
        self.get_logger().info(
            f'절대 이동: 중심 기준 뒤쪽 위치 (0, {target_y}, {self.HOVER_Z})mm'
        )
        self.publish_move(0.0, target_y, self.HOVER_Z, theta_deg=0.0)

    def move_theta(self, theta_deg):

        """
        현재 XYZ는 유지하고 theta 회전 관절만 변경함.
        """

        self.get_logger().info(f'현재 XYZ 유지, theta={theta_deg}deg로 회전')
        self.publish_move(
            self.last_sent_x,
            self.last_sent_y,
            self.last_sent_z,
            theta_deg=theta_deg,
        )

    def wait_for_motion(self, seconds=None):
        wait_time = self.MOVE_SETTLE_SEC if seconds is None else seconds
        deadline = time.monotonic() + max(0.0, float(wait_time))
        while time.monotonic() < deadline:
            self.spin_callbacks(min(0.02, deadline - time.monotonic()))

    def wait_for_vision_motion(self, minimum_settle_sec=None, timeout_sec=None):
        minimum_settle = (
            self.VISION_SETTLE_SEC
            if minimum_settle_sec is None
            else max(0.0, float(minimum_settle_sec))
        )
        self.wait_for_motion(minimum_settle)

        timeout = (
            self.VISION_MOTION_TIMEOUT_SEC
            if timeout_sec is None
            else max(0.0, float(timeout_sec))
        )
        deadline = time.monotonic() + timeout
        stable_samples = 0
        last_errors = None
        while time.monotonic() < deadline:
            self.spin_callbacks(min(0.02, deadline - time.monotonic()))
            actual_values = (
                self.actual_gripper_x_mm,
                self.actual_gripper_y_mm,
                self.actual_gripper_z_mm,
                self.actual_gripper_theta_deg,
            )
            if any(value is None for value in actual_values):
                continue
            if time.monotonic() - self.last_joint_feedback_time > 1.0:
                continue

            theta_error = math.degrees(math.atan2(
                math.sin(math.radians(
                    self.actual_gripper_theta_deg - self.last_sent_theta_deg
                )),
                math.cos(math.radians(
                    self.actual_gripper_theta_deg - self.last_sent_theta_deg
                )),
            ))
            last_errors = {
                'x': self.actual_gripper_x_mm - self.last_sent_x,
                'y': self.actual_gripper_y_mm - self.last_sent_y,
                'z': self.actual_gripper_z_mm - self.last_sent_z,
                'theta': theta_error,
            }
            xy_ok = all(
                abs(last_errors[axis])
                <= self.VISION_MOTION_POSITION_TOLERANCE_MM
                for axis in ('x', 'y')
            )
            z_ok = (
                abs(last_errors['z'])
                <= self.VISION_MOTION_Z_TOLERANCE_MM
            )
            theta_ok = (
                abs(last_errors['theta'])
                <= self.VISION_MOTION_THETA_TOLERANCE_DEG
            )
            if xy_ok and z_ok and theta_ok:
                stable_samples += 1
                if stable_samples >= 5:
                    return True
            else:
                stable_samples = 0

        self.get_logger().warn(
            '비전 촬영 전 joint 목표 정착 시간 초과: '
            f'timeout={timeout:.1f}s, '
            f'target=({self.last_sent_x:.3f}, {self.last_sent_y:.3f}, '
            f'{self.last_sent_z:.3f}, {self.last_sent_theta_deg:.4f}deg), '
            f'errors={last_errors}. 현재 실제 영상으로 보정을 계속합니다.'
        )
        return False

    def actual_pose_within_vision_capture_range(self):
        actual_values = (
            self.actual_gripper_x_mm,
            self.actual_gripper_y_mm,
            self.actual_gripper_z_mm,
        )
        if any(value is None for value in actual_values):
            return False
        return (
            abs(self.actual_gripper_x_mm - self.last_sent_x)
            <= self.VISION_MACRO_CAPTURE_RANGE_MM
            and abs(self.actual_gripper_y_mm - self.last_sent_y)
            <= self.VISION_MACRO_CAPTURE_RANGE_MM
            and abs(self.actual_gripper_z_mm - self.last_sent_z)
            <= self.VISION_Z_WINDOW_MM
        )

    def resolve_contact_height(self, contact_z):
        requested_height = self.PRESS_Z if contact_z is None else float(contact_z)
        if requested_height < self.MIN_CONTACT_Z:
            self.get_logger().warn(
                f'contact_z={requested_height}mm는 Z 하한에 너무 가까워 '
                f'{self.MIN_CONTACT_Z}mm로 보정합니다.'
            )
            return self.MIN_CONTACT_Z
        return requested_height

    def vacuum_on(self):
        self.get_logger().info('vacuum_on: picker-chip 접촉 확인 후 고정합니다.')
        if self.has_recent_picker_contact():
            self.get_logger().info('vacuum_on: 직전 picker-chip contact를 사용합니다.')
        elif not self.wait_for_picker_contact() and not self.search_picker_contact_downward():
            self.get_logger().warn(
                'picker-chip contact 최종 미감지: vacuum attach를 수행하지 않습니다.'
            )
            self.vacuum_attached = VACUUM_OFF
            self.save_current_state()
            return False

        self.vacuum_attached = VACUUM_ON
        if self.USE_DETACHABLE_JOINT:
            if not self.attach_red_chip_to_picker():
                self.vacuum_attached = VACUUM_OFF
                self.save_current_state()
                return False
        else:
            self.move_red_chip_with_tool(
                self.last_sent_x,
                self.last_sent_y,
                self.last_sent_z,
                self.last_sent_theta_deg,
            )
        self.save_current_state()
        return True

    def vacuum_off(self):
        if not self.vacuum_attached:
            self.get_logger().warn('vacuum_off: 현재 흡착 상태가 아니므로 chip 위치를 변경하지 않습니다.')
            self.save_current_state()
            return False

        self.get_logger().info(f'vacuum_off: picker와 {self.RED_CHIP_MODEL} 고정을 해제합니다.')
        if self.USE_DETACHABLE_JOINT:
            if not self.detach_red_chip_from_picker():
                self.get_logger().error(
                    'vacuum_off: Gazebo picker detach 요청이 실패해 흡착 상태를 유지합니다.'
                )
                return False
        else:
            self.set_red_chip_pose_abs(
                self.last_sent_x,
                self.last_sent_y,
                self.last_sent_z - self.CHIP_THICKNESS_MM,
                theta_deg=self.last_sent_theta_deg,
            )
        self.vacuum_attached = VACUUM_OFF
        self.save_current_state()
        return True

    def substrate_bond_on(self):
        self.get_logger().info(
            'stack_bond_on: '
            f'{self.RED_CHIP_MODEL}-{self.PLACEMENT_SUPPORT_MODEL} '
            '접촉 확인 후 고정합니다.'
        )
        if self.has_recent_substrate_contact():
            self.get_logger().info('stack_bond_on: 직전 적층 contact를 사용합니다.')
        elif not self.wait_for_substrate_contact():
            self.get_logger().warn(
                f'{self.RED_CHIP_MODEL}-{self.PLACEMENT_SUPPORT_MODEL} '
                'contact 최종 미감지: stack bond attach를 수행하지 않습니다.'
            )
            return False

        if self.USE_DETACHABLE_JOINT:
            return self.attach_chip_to_substrate()

        return True

    def transfer_chip_to_substrate(self, x_mm, y_mm, theta_deg=0.0):
        self.get_logger().info(
            'stack transfer: 현재 접촉 위치에서 '
            f'{self.RED_CHIP_MODEL}을 받침에 먼저 고정한 뒤 picker를 해제합니다.'
        )

        self.spin_callbacks(0.05)
        contact_gripper_z = (
            self.actual_gripper_z_mm
            if self.actual_gripper_z_mm is not None
            else self.last_sent_z
        )
        if not self.substrate_bond_on():
            return False

        self.get_logger().info(
            'stack transfer: 적층 bond 생성 완료, picker vacuum을 해제합니다.'
        )
        if self.vacuum_attached and not self.vacuum_off():
            self.detach_chip_from_substrate()
            return False

        release_z = min(
            self.GRIPPER_HOME_Z,
            contact_gripper_z + max(0.0, self.TRANSFER_RELEASE_LIFT_MM),
        )
        if not self.publish_move(
            x_mm,
            y_mm,
            release_z,
            theta_deg=theta_deg,
        ):
            return False

        deadline = time.monotonic() + self.TRANSFER_RELEASE_TIMEOUT_SEC
        next_detach_retry = time.monotonic() + self.TRANSFER_DETACH_RETRY_SEC
        gripper_separated = False
        stack_height_valid = False
        stack_z_error_mm = None
        while time.monotonic() < deadline:
            self.spin_callbacks(min(0.02, deadline - time.monotonic()))
            if self.actual_gripper_z_mm is not None:
                gripper_separated = (
                    self.actual_gripper_z_mm - contact_gripper_z
                    >= self.TRANSFER_RELEASE_MIN_SEPARATION_MM
                )

            chip_pose_now = self.sim_model_poses.get(self.RED_CHIP_MODEL)
            support_pose_now = self.sim_model_poses.get(
                self.PLACEMENT_SUPPORT_MODEL,
            )
            if chip_pose_now is not None and support_pose_now is not None:
                expected_center_gap_mm = (
                    self.SUBSTRATE_THICKNESS_MM / 2.0
                    + self.CHIP_THICKNESS_MM / 2.0
                    if self.PLACEMENT_SUPPORT_MODEL == self.SUBSTRATE_MODEL
                    else self.CHIP_THICKNESS_MM
                )
                actual_center_gap_mm = (
                    float(chip_pose_now['z_m'])
                    - float(support_pose_now['z_m'])
                ) * 1000.0
                stack_z_error_mm = abs(
                    actual_center_gap_mm - expected_center_gap_mm
                )
                stack_height_valid = (
                    stack_z_error_mm <= self.TRANSFER_MAX_STACK_Z_ERROR_MM
                )

            if gripper_separated and stack_height_valid:
                break

            if not gripper_separated and time.monotonic() >= next_detach_retry:
                self.get_logger().warn(
                    'stack transfer: picker 분리가 아직 확인되지 않아 detach를 재요청합니다.'
                )
                self.detach_red_chip_from_picker()
                next_detach_retry = (
                    time.monotonic() + self.TRANSFER_DETACH_RETRY_SEC
                )

        if not gripper_separated or not stack_height_valid:
            stack_error_text = (
                'unavailable'
                if stack_z_error_mm is None
                else f'{stack_z_error_mm:.3f}mm'
            )
            self.get_logger().error(
                'stack transfer 중단: 분리 또는 적층 높이 검증에 실패했습니다. '
                f'gripper_separated={gripper_separated}, '
                f'support_z_error={stack_error_text}'
            )
            return False

        self.get_logger().info(
            'stack transfer: bond 유지 및 picker 실제 분리 확인 완료 '
            f'(gripper 상승={self.actual_gripper_z_mm - contact_gripper_z:.3f}mm, '
            f'support_z_error='
            f'{0.0 if stack_z_error_mm is None else stack_z_error_mm:.3f}mm)'
        )

        self.save_current_state()
        return True

    def wait_for_vision_bridge(self, timeout_sec=None):
        timeout = self.VISION_REQUEST_TIMEOUT_SEC if timeout_sec is None else float(timeout_sec)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.count_subscribers(self.VISION_REQUEST_TOPIC) > 0:
                return True
            self.spin_callbacks(min(0.05, deadline - time.monotonic()))

        self.get_logger().error(
            f'비전 브리지를 찾지 못했습니다: {self.VISION_REQUEST_TOPIC}'
        )
        return False

    def request_vision(self, payload, timeout_sec=None):
        timeout = self.VISION_REQUEST_TIMEOUT_SEC if timeout_sec is None else float(timeout_sec)
        if not self.wait_for_vision_bridge(timeout_sec=timeout):
            return None

        self.vision_request_serial += 1
        request_id = (
            f'{os.getpid()}-{time.monotonic_ns()}-{self.vision_request_serial}'
        )
        request = dict(payload)
        request['request_id'] = request_id
        self.vision_results.pop(request_id, None)

        msg = String()
        msg.data = json.dumps(request, ensure_ascii=False)
        self.vision_request_pub.publish(msg)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.spin_callbacks(min(0.05, deadline - time.monotonic()))
            result = self.vision_results.pop(request_id, None)
            if result is None:
                continue
            if not result.get('success', False):
                self.get_logger().error(
                    f'비전 요청 실패({request.get("action")}): '
                    f'{result.get("error", "알 수 없는 오류")}'
                )
                return None
            return result

        self.get_logger().error(
            f'비전 요청 응답 시간 초과: id={request_id}, '
            f'action={request.get("action")}, stage={request.get("stage", "-")}'
        )
        return None

    def request_vision_with_retries(self, payload):
        for attempt in range(1, self.VISION_REQUEST_RETRY_COUNT + 1):
            result = self.request_vision(payload)
            if result is not None:
                return result
            if attempt >= self.VISION_REQUEST_RETRY_COUNT:
                break
            self.get_logger().warn(
                f'비전 요청 재시도 {attempt + 1}/'
                f'{self.VISION_REQUEST_RETRY_COUNT}: '
                f'action={payload.get("action")}, stage={payload.get("stage", "-")}'
            )
            self.wait_for_motion(0.25)
        return None

    def lock_vision_reference_chip(self, reference_set):
        if not self.USE_DETACHABLE_JOINT:
            self.get_logger().error(
                '기준 영상 장면 고정에는 Gazebo detachable joint가 필요합니다.'
            )
            return False

        normalized = str(reference_set).strip().lower()
        if normalized == 'pick':
            topic = self.ATTACH_TOPIC
            parent = 'theta_link_1'
            attached = self.attach_red_chip_to_picker(require_contact=False)
        else:
            topic = self.SUBSTRATE_ATTACH_TOPIC
            parent = 'substrate_link'
            attached = self.attach_chip_to_substrate(require_contact=False)

        if not attached:
            self.get_logger().error(
                f'기준 영상용 chip 고정 실패: parent={parent}, topic={topic}'
            )
            return False

        self.get_logger().info(
            '기준 영상 전용 고정 완료: '
            f'check_chip을 {parent}에 현재 상대 자세 그대로 고정했습니다.'
        )
        return True

    def prepare_vision_reference_scene(self, reference_set, settle_sec=None):
        normalized = str(reference_set).strip().lower()
        if normalized not in {'pick', 'place_empty', 'place_stacked'}:
            self.get_logger().error(f'지원하지 않는 기준 영상 세트입니다: {reference_set}')
            return False

        self.force_vacuum_detached('기준 영상 촬영 전 picker 고정 해제')
        self.force_substrate_bond_detached('기준 영상 촬영 전 substrate 고정 해제')
        if not self.publish_move(
            self.GRIPPER_HOME_X,
            self.GRIPPER_HOME_Y,
            self.GRIPPER_HOME_Z,
            theta_deg=0.0,
        ):
            return False
        if not self.wait_for_vision_motion(minimum_settle_sec=settle_sec):
            self.get_logger().error(
                '기준 영상 촬영 자세에 정착하지 못해 촬영을 중단합니다.'
            )
            return False

        hidden_x = self.REFERENCE_HIDDEN_X_M
        hidden_y = self.REFERENCE_HIDDEN_Y_M
        hidden_z = (self.BASE_TOP_Z + self.CHIP_THICKNESS_MM / 2.0) * 0.001
        if normalized == 'pick':
            scene_ok = self.set_gazebo_model_pose(
                self.SUBSTRATE_MODEL,
                hidden_x,
                hidden_y,
                (self.BASE_TOP_Z + self.SUBSTRATE_THICKNESS_MM / 2.0) * 0.001,
            )
            scene_ok = self.set_red_chip_pose_abs(
                self.GRIPPER_HOME_X,
                self.GRIPPER_HOME_Y,
                self.BASE_TOP_Z,
                theta_deg=0.0,
            ) and scene_ok
        elif normalized == 'place_empty':
            scene_ok = self.set_substrate_pose_abs(
                self.SUBSTRATE_CENTER_X,
                self.SUBSTRATE_CENTER_Y,
            )
            scene_ok = self.set_red_chip_pose(
                hidden_x,
                hidden_y,
                hidden_z,
                theta_deg=0.0,
            ) and scene_ok
        else:
            scene_ok = self.set_substrate_pose_abs(
                self.SUBSTRATE_CENTER_X,
                self.SUBSTRATE_CENTER_Y,
            )
            scene_ok = self.set_red_chip_pose_abs(
                self.SUBSTRATE_CENTER_X,
                self.SUBSTRATE_CENTER_Y,
                self.substrate_top_z_mm(),
                theta_deg=0.0,
            ) and scene_ok

        if not scene_ok:
            self.get_logger().error('기준 영상용 Gazebo 장면 배치에 실패했습니다.')
            return False

        if not self.lock_vision_reference_chip(normalized):
            return False
        if not self.publish_move(
            self.GRIPPER_HOME_X,
            self.GRIPPER_HOME_Y,
            self.GRIPPER_HOME_Z,
            theta_deg=0.0,
        ):
            return False
        if not self.wait_for_vision_motion(
            minimum_settle_sec=max(
                self.VISION_REFERENCE_LOCK_SETTLE_SEC,
                0.0 if settle_sec is None else float(settle_sec),
            ),
        ):
            self.get_logger().error(
                '기준 장면 고정 후 gripper/camera 자세가 안정되지 않았습니다.'
            )
            return False
        self.get_logger().info(
            '기준 장면 정착 확인 완료: camera/gripper/chip/substrate 고정 상태에서 촬영합니다.'
        )
        return True

    def restore_default_vision_scene(self, settle_sec=None):
        self.force_vacuum_detached('기준 영상 촬영 종료 후 picker 고정 해제')
        self.force_substrate_bond_detached('기준 영상 촬영 종료 후 substrate 고정 해제')
        substrate_ok = self.set_substrate_pose_abs(
            self.SUBSTRATE_CENTER_X,
            self.SUBSTRATE_CENTER_Y,
        )
        chip_ok = self.set_red_chip_pose_abs(
            500.0,
            400.0,
            self.CHIP_REST_Z,
            theta_deg=0.0,
        )
        move_ok = self.publish_move(
            self.GRIPPER_HOME_X,
            self.GRIPPER_HOME_Y,
            self.GRIPPER_HOME_Z,
            theta_deg=0.0,
        )
        self.wait_for_vision_motion(minimum_settle_sec=settle_sec)
        return substrate_ok and chip_ok and move_ok

    def run_vision_reference_capture(
        self,
        reference_set,
        settle_sec=None,
        vision_timeout_sec=None,
        motion_timeout_sec=None,
    ):
        normalized = str(reference_set).strip().lower()
        if vision_timeout_sec is not None:
            self.VISION_REQUEST_TIMEOUT_SEC = max(
                0.0,
                float(vision_timeout_sec),
            )
        if motion_timeout_sec is not None:
            self.VISION_MOTION_TIMEOUT_SEC = max(
                0.0,
                float(motion_timeout_sec),
            )
        self.get_logger().info(
            f'비전 기준 영상 촬영 시작: set={normalized}, '
            f'gripper=({self.GRIPPER_HOME_X:.1f}, {self.GRIPPER_HOME_Y:.1f}, '
            f'{self.GRIPPER_HOME_Z:.1f}, 0.0deg)mm, '
            f'vision_timeout={self.VISION_REQUEST_TIMEOUT_SEC:.1f}s, '
            f'request_topic={self.VISION_REQUEST_TOPIC}'
        )
        if not self.wait_for_vision_bridge():
            return False

        success = False
        try:
            if not self.prepare_vision_reference_scene(normalized, settle_sec=settle_sec):
                return False
            result = self.request_vision({
                'action': 'capture',
                'reference_set': normalized,
            })
            if result is None:
                return False
            self.get_logger().info(
                f'비전 기준 영상 저장 완료: {result.get("output_dir")} '
                f'({result.get("image_count", 0)}장)'
            )
            success = True
            return True
        finally:
            restored = self.restore_default_vision_scene(settle_sec=settle_sec)
            if not restored:
                self.get_logger().warn('기준 영상 촬영 후 기본 장면 복원에 실패했습니다.')
            if not success:
                self.get_logger().warn(f'비전 기준 영상 촬영 실패: set={normalized}')

    def vision_error_metrics(self, result):
        xy_um = max(
            abs(float(result.get('dx', 0.0))),
            abs(float(result.get('dy', 0.0))),
        ) * 1000.0
        optical_z_um = abs(float(result.get('dz', 0.0))) * 1000.0
        theta_deg = abs(float(result.get('dtheta', 0.0)))
        theta_edge_um = (
            math.radians(theta_deg)
            * self.VISION_ROTATION_RADIUS_MM
            * 1000.0
        )
        return xy_um, optical_z_um, theta_edge_um

    def alignment_joint_z_error_um(self):
        if self.actual_gripper_z_mm is None:
            return math.inf
        return abs(
            self.actual_gripper_z_mm - self.GRIPPER_HOME_Z
        ) * 1000.0

    def vision_error_within_tolerance(self, result):
        xy_um, optical_z_um, theta_edge_um = self.vision_error_metrics(result)
        return (
            xy_um <= self.VISION_TOLERANCE_UM
            and optical_z_um <= self.VISION_Z_TOLERANCE_UM
            and theta_edge_um <= self.VISION_TOLERANCE_UM
        )

    def vision_xy_theta_within_tolerance(self, result):
        xy_um, _, theta_edge_um = self.vision_error_metrics(result)
        return (
            xy_um <= self.VISION_TOLERANCE_UM
            and theta_edge_um <= self.VISION_TOLERANCE_UM
        )

    def log_vision_result(self, label, result):
        xy_um, optical_z_um, theta_edge_um = self.vision_error_metrics(result)
        joint_z_um = self.alignment_joint_z_error_um()
        raw_z_text = ""
        if "raw_dz" in result:
            raw_z_text = (
                f'raw_dz={float(result["raw_dz"]):+.6f}mm, '
                f'optical_z_bias={float(result.get("optical_z_bias", 0.0)):+.6f}mm, '
            )
        self.get_logger().info(
            f'{label} [VISION_ESTIMATE][USED_FOR_ALIGNMENT]: '
            f'dx={float(result["dx"]):+.6f}mm, '
            f'dy={float(result["dy"]):+.6f}mm, '
            f'dz={float(result["dz"]):+.6f}mm, '
            f'dtheta={float(result["dtheta"]):+.6f}deg, '
            f'{raw_z_text}'
            f'max_xy={xy_um:.3f}um, abs_z={optical_z_um:.3f}um, '
            f'theta_edge={theta_edge_um:.3f}um, '
            f'score={float(result.get("score", 0.0)):.4f}, '
            f'feature={result.get("alignment_feature", "unspecified")}, '
            f'reference={result.get("reference_set_used", result.get("reference_set", "-"))}, '
            f'source={result.get("source", "vision")}'
        )
        self.get_logger().info(
            f'{label} [SIM_JOINT_MONITOR][NOT_ALIGNMENT_ERROR]: '
            f'gripper_z_command_error={joint_z_um:.3f}um'
        )

    def measure_placement_error_from_vision(self):
        result = self.request_vision({
            'action': 'measure_placement',
            'reference_set': 'place_stacked',
        })
        if result is None:
            self.get_logger().warn(
                '최종 chip-substrate 배치 오차를 촬영하지 못했습니다. '
                'place_stacked 기준 영상과 카메라 topic을 확인하세요.'
            )
            return None
        return result

    def wait_for_fresh_sim_model_poses(self, timeout_sec=5.0, model_names=None):
        requested_at = time.monotonic()
        required_models = tuple(
            (self.RED_CHIP_MODEL, self.SUBSTRATE_MODEL)
            if model_names is None
            else model_names
        )
        deadline = requested_at + max(0.0, float(timeout_sec))
        while time.monotonic() < deadline:
            self.spin_callbacks(min(0.05, deadline - time.monotonic()))
            if all(
                model in self.sim_model_poses
                and self.sim_model_poses[model]['received_at'] >= requested_at
                for model in required_models
            ):
                return True

        missing = [
            model
            for model in required_models
            if model not in self.sim_model_poses
            or self.sim_model_poses[model]['received_at'] < requested_at
        ]
        self.get_logger().warn(
            '[SIM_GROUND_TRUTH][REPORT_ONLY] fresh Gazebo model poses '
            f'not received from {self.SIM_POSE_TOPIC}: missing={missing}'
        )
        return False

    def simulation_chip_substrate_ground_truth(
        self,
        chip_model,
        stack_level,
        wait_for_fresh=True,
    ):
        required_models = (str(chip_model), self.SUBSTRATE_MODEL)
        if wait_for_fresh and not self.wait_for_fresh_sim_model_poses(
            model_names=required_models,
        ):
            return None
        if any(model not in self.sim_model_poses for model in required_models):
            return None

        chip_pose = self.sim_model_poses[str(chip_model)]
        substrate_pose = self.sim_model_poses[self.SUBSTRATE_MODEL]
        delta_x_m = chip_pose['x_m'] - substrate_pose['x_m']
        delta_y_m = chip_pose['y_m'] - substrate_pose['y_m']
        substrate_yaw_rad = math.radians(substrate_pose['theta_deg'])
        cos_yaw = math.cos(substrate_yaw_rad)
        sin_yaw = math.sin(substrate_yaw_rad)
        local_x_m = cos_yaw * delta_x_m + sin_yaw * delta_y_m
        local_y_m = -sin_yaw * delta_x_m + cos_yaw * delta_y_m
        expected_center_delta_z_m = (
            self.SUBSTRATE_THICKNESS_MM / 2.0
            + (int(stack_level) + 0.5) * self.CHIP_THICKNESS_MM
        ) * 0.001
        theta_error_deg = chip_pose['theta_deg'] - substrate_pose['theta_deg']
        theta_error_deg = math.degrees(math.atan2(
            math.sin(math.radians(theta_error_deg)),
            math.cos(math.radians(theta_error_deg)),
        ))

        return {
            'dx': local_x_m * 1000.0,
            'dy': local_y_m * 1000.0,
            'dz': (
                chip_pose['z_m']
                - substrate_pose['z_m']
                - expected_center_delta_z_m
            ) * 1000.0,
            'dtheta': theta_error_deg,
            'chip_frame': chip_pose['frame_name'],
            'substrate_frame': substrate_pose['frame_name'],
        }

    def simulation_placement_ground_truth(self):
        return self.simulation_chip_substrate_ground_truth(
            self.RED_CHIP_MODEL,
            self.active_stack_level,
        )

    def log_stack_absolute_errors(self, chip_specs):
        required_models = [
            self.SUBSTRATE_MODEL,
            *(spec['model'] for spec in chip_specs),
        ]
        self.get_logger().info(
            '[STACK_ABSOLUTE_ERROR_SUMMARY][SIM_GROUND_TRUTH] '
            f'substrate={self.SUBSTRATE_MODEL}, chips={len(chip_specs)}, '
            'reference=substrate_pose, usage=REPORT_ONLY_NOT_CONTROL'
        )
        if not self.wait_for_fresh_sim_model_poses(
            timeout_sec=5.0,
            model_names=required_models,
        ):
            self.get_logger().warn(
                '[STACK_ABSOLUTE_ERROR_SUMMARY][SIM_GROUND_TRUTH] unavailable'
            )
            return

        results = []
        for spec in chip_specs:
            result = self.simulation_chip_substrate_ground_truth(
                spec['model'],
                spec['stack_level'],
                wait_for_fresh=False,
            )
            if result is None:
                self.get_logger().warn(
                    '[STACK_ABSOLUTE_ERROR][SIM_GROUND_TRUTH] '
                    f'chip={spec["index"]}, model={spec["model"]}, unavailable'
                )
                continue

            dx_um = float(result['dx']) * 1000.0
            dy_um = float(result['dy']) * 1000.0
            dz_um = float(result['dz']) * 1000.0
            dtheta_deg = float(result['dtheta'])
            xy_um = math.hypot(dx_um, dy_um)
            theta_edge_um = (
                abs(math.radians(dtheta_deg))
                * self.VISION_ROTATION_RADIUS_MM
                * 1000.0
            )
            results.append((xy_um, dz_um, dtheta_deg))
            self.get_logger().info(
                '[STACK_ABSOLUTE_ERROR][SIM_GROUND_TRUTH][SUBSTRATE_REFERENCE]: '
                f'chip={spec["index"]}, model={spec["model"]}, '
                f'layer={spec["stack_level"] + 1}, '
                f'dx={dx_um:+.3f}um, dy={dy_um:+.3f}um, '
                f'xy_abs={xy_um:.3f}um, dz={dz_um:+.3f}um, '
                f'dtheta={dtheta_deg:+.6f}deg, '
                f'theta_edge_abs={theta_edge_um:.3f}um'
            )

        if not results:
            return
        max_xy_um = max(result[0] for result in results)
        rms_xy_um = math.sqrt(
            sum(result[0] ** 2 for result in results) / len(results)
        )
        max_abs_z_um = max(abs(result[1]) for result in results)
        max_abs_theta_deg = max(abs(result[2]) for result in results)
        self.get_logger().info(
            '[STACK_ABSOLUTE_ERROR_SUMMARY][SIM_GROUND_TRUTH] '
            f'reported={len(results)}/{len(chip_specs)}, '
            f'max_xy_abs={max_xy_um:.3f}um, rms_xy_abs={rms_xy_um:.3f}um, '
            f'max_z_abs={max_abs_z_um:.3f}um, '
            f'max_theta_abs={max_abs_theta_deg:.6f}deg'
        )

    def log_final_placement_errors(self, vision_result):
        simulation_result = self.simulation_placement_ground_truth()
        if simulation_result is not None:
            sim_dx_um = float(simulation_result['dx']) * 1000.0
            sim_dy_um = float(simulation_result['dy']) * 1000.0
            sim_dz_um = float(simulation_result['dz']) * 1000.0
            sim_theta_deg = float(simulation_result['dtheta'])
            sim_theta_edge_um = (
                abs(math.radians(sim_theta_deg))
                * self.VISION_ROTATION_RADIUS_MM
                * 1000.0
            )
            self.get_logger().info(
                '[FINAL_RESULT][SIM_GROUND_TRUTH][REPORT_ONLY_NOT_CONTROL]: '
                f'model={self.RED_CHIP_MODEL}, layer={self.active_stack_level + 1}, '
                f'dx={sim_dx_um:+.3f}um, dy={sim_dy_um:+.3f}um, '
                f'xy={math.hypot(sim_dx_um, sim_dy_um):.3f}um, '
                f'dz={sim_dz_um:+.3f}um, '
                f'dtheta={sim_theta_deg:+.6f}deg, '
                f'theta_edge={sim_theta_edge_um:.3f}um'
            )
        else:
            self.get_logger().info(
                '[FINAL_RESULT][SIM_GROUND_TRUTH][REPORT_ONLY_NOT_CONTROL]: '
                f'model={self.RED_CHIP_MODEL}, layer={self.active_stack_level + 1}, '
                'unavailable'
            )

        if vision_result is None:
            self.get_logger().warn(
                '[FINAL_RESULT][VISION_ESTIMATE] final vision error unavailable'
            )
            return

        dx_um = float(vision_result['dx']) * 1000.0
        dy_um = float(vision_result['dy']) * 1000.0
        dz_um = float(vision_result['dz']) * 1000.0
        xy_um = math.hypot(dx_um, dy_um)
        theta_deg = float(vision_result['dtheta'])
        theta_edge_um = (
            abs(math.radians(theta_deg))
            * self.VISION_ROTATION_RADIUS_MM
            * 1000.0
        )
        self.get_logger().info(
            '[FINAL_RESULT][VISION_ESTIMATE][IMAGE_ONLY]: '
            f'model={self.RED_CHIP_MODEL}, layer={self.active_stack_level + 1}, '
            f'dx={dx_um:+.3f}um, dy={dy_um:+.3f}um, '
            f'xy={xy_um:.3f}um, dz={dz_um:+.3f}um, '
            f'dtheta={theta_deg:+.6f}deg, '
            f'theta_edge={theta_edge_um:.3f}um, '
            f'score={float(vision_result.get("score", 0.0)):.4f}'
        )

    def apply_vision_correction(self, result, stage, settle_sec=None):
        values = [
            float(result.get('dx', 0.0)),
            float(result.get('dy', 0.0)),
            float(result.get('dz', 0.0)),
            float(result.get('dtheta', 0.0)),
        ]
        if not all(math.isfinite(value) for value in values):
            self.get_logger().error(f'비전 보정값에 유효하지 않은 수가 있습니다: {values}')
            return False

        normalized_stage = str(stage).strip().lower()
        max_xy = (
            self.VISION_MACRO_MAX_XY_MM
            if normalized_stage == 'macro'
            else self.VISION_MICRO_MAX_XY_MM
        )
        max_z = (
            self.VISION_MACRO_MAX_Z_MM
            if normalized_stage == 'macro'
            else self.VISION_MICRO_MAX_Z_MM
        )

        def limit(value, maximum):
            return max(-maximum, min(maximum, value))

        dx = limit(values[0], max_xy)
        dy = limit(values[1], max_xy)
        dz = limit(values[2], max_z)
        max_theta = (
            self.VISION_MACRO_MAX_THETA_DEG
            if normalized_stage == 'macro'
            else self.VISION_MAX_THETA_DEG
        )
        dtheta = limit(values[3], max_theta)
        if normalized_stage == 'micro':
            position_deadband_mm = self.VISION_TOLERANCE_UM * 0.001
            z_deadband_mm = self.VISION_Z_TOLERANCE_UM * 0.001
            theta_deadband_deg = math.degrees(
                position_deadband_mm / self.VISION_ROTATION_RADIUS_MM
            )
            if abs(dx) <= position_deadband_mm:
                dx = 0.0
            if abs(dy) <= position_deadband_mm:
                dy = 0.0
            if abs(dz) <= z_deadband_mm:
                dz = 0.0
            if abs(dtheta) <= theta_deadband_deg:
                dtheta = 0.0
        target_theta = self.last_sent_theta_deg + dtheta
        target_z = max(
            self.GRIPPER_HOME_Z - self.VISION_Z_WINDOW_MM,
            min(
                self.GRIPPER_HOME_Z + self.VISION_Z_WINDOW_MM,
                self.last_sent_z + dz,
            ),
        )
        x_lower, x_upper = self.COMMAND_LIMITS_MM['x']
        y_lower, y_upper = self.COMMAND_LIMITS_MM['y']
        target_x = max(x_lower, min(x_upper, self.last_sent_x + dx))
        target_y = max(y_lower, min(y_upper, self.last_sent_y + dy))

        if not self.publish_move(
            target_x,
            target_y,
            target_z,
            theta_deg=target_theta,
        ):
            return False
        settled = self.wait_for_vision_motion(
            minimum_settle_sec=(
                self.VISION_SETTLE_SEC if settle_sec is None else settle_sec
            ),
            timeout_sec=self.VISION_CORRECTION_MOTION_TIMEOUT_SEC,
        )
        if not settled:
            self.get_logger().error(
                '비전 보정 목표가 정착하지 않아 다음 영상을 촬영하지 않습니다.'
            )
            return False
        return True

    def median_vision_results(self, results):
        filtered = {
            key: float(statistics.median(
                float(result.get(key, 0.0)) for result in results
            ))
            for key in ('dx', 'dy', 'dz', 'dtheta', 'score')
        }
        filtered['source'] = 'vision_temporal_median'
        latest = results[-1]
        for key in ('alignment_feature', 'reference_set', 'reference_set_used'):
            if key in latest:
                filtered[key] = latest[key]
        return filtered

    def align_at_reference_height(
        self,
        reference_set,
        target,
        max_micro_iterations=20,
        settle_sec=None,
    ):
        if abs(self.last_sent_z - self.GRIPPER_HOME_Z) > 1e-9:
            if not self.publish_move(
                self.last_sent_x,
                self.last_sent_y,
                self.GRIPPER_HOME_Z,
                theta_deg=self.last_sent_theta_deg,
            ):
                return False
            if not self.wait_for_vision_motion(
                minimum_settle_sec=settle_sec,
                timeout_sec=self.VISION_CORRECTION_MOTION_TIMEOUT_SEC,
            ):
                self.get_logger().error(
                    '비전 기준 높이에 정착하지 못해 정렬을 시작하지 않습니다.'
                )
                return False

        macro_result = self.request_vision_with_retries({
            'action': 'align',
            'reference_set': reference_set,
            'target': target,
            'stage': 'macro',
        })
        if macro_result is None:
            return False
        self.log_vision_result(f'{target} Macro 1/1', macro_result)
        if not self.apply_vision_correction(
            macro_result,
            'macro',
            settle_sec=settle_sec,
        ):
            return False

        micro_history = []
        optical_z_bias = None
        optical_z_baseline_samples = []
        optical_z_stability_mm = self.VISION_Z_TOLERANCE_UM * 0.001
        for iteration in range(1, int(max_micro_iterations) + 1):
            raw_micro_result = self.request_vision_with_retries({
                'action': 'align',
                'reference_set': reference_set,
                'target': target,
                'stage': 'micro',
            })
            if raw_micro_result is None:
                return False
            micro_result = dict(raw_micro_result)
            raw_dz = float(raw_micro_result.get('dz', 0.0))
            if optical_z_bias is None:
                baseline_probe = raw_micro_result
                baseline_from_temporal_median = False
                window_size = self.VISION_MICRO_AVERAGE_WINDOW
                if (
                    window_size > 1
                    and len(micro_history) >= window_size - 1
                ):
                    baseline_probe = self.median_vision_results([
                        *micro_history[-(window_size - 1):],
                        raw_micro_result,
                    ])
                    baseline_from_temporal_median = True

                if self.vision_xy_theta_within_tolerance(baseline_probe):
                    baseline_dz = float(baseline_probe.get('dz', 0.0))
                    if baseline_from_temporal_median:
                        optical_z_bias = baseline_dz
                        micro_result = dict(baseline_probe)
                        raw_dz = baseline_dz
                    elif (
                        optical_z_baseline_samples
                        and abs(baseline_dz - optical_z_baseline_samples[-1])
                        > optical_z_stability_mm
                    ):
                        optical_z_baseline_samples = [baseline_dz]
                    else:
                        optical_z_baseline_samples.append(baseline_dz)

                    if (
                        optical_z_bias is None
                        and len(optical_z_baseline_samples) >= 2
                    ):
                        optical_z_bias = float(statistics.median(
                            optical_z_baseline_samples[-2:],
                        ))

                    if optical_z_bias is not None:
                        micro_history.clear()
                        baseline_description = (
                            f'temporal_median_window={window_size}'
                            if baseline_from_temporal_median
                            else f'samples={optical_z_baseline_samples[-2:]}'
                        )
                        self.get_logger().info(
                            f'{target} [VISION_Z_BASELINE][IMAGE_ONLY]: '
                            f'bias={optical_z_bias:+.6f}mm, '
                            f'{baseline_description}, '
                            'simulation ground truth는 사용하지 않았습니다.'
                        )
                else:
                    optical_z_baseline_samples.clear()

            if optical_z_bias is not None:
                micro_result['raw_dz'] = raw_dz
                micro_result['optical_z_bias'] = optical_z_bias
                micro_result['dz'] = raw_dz - optical_z_bias
                micro_result['source'] = 'vision_optical_z_bias_compensated'
            else:
                micro_result['source'] = 'vision_optical_z_baseline_pending'
            self.log_vision_result(
                f'{target} Micro {iteration}/{int(max_micro_iterations)}',
                micro_result,
            )
            micro_history.append(micro_result)
            if (
                optical_z_bias is not None
                and self.vision_error_within_tolerance(micro_result)
            ):
                self.get_logger().info(
                    f'{target} 비전 정렬 완료: vision XY/theta 환산 오차 '
                    f'{self.VISION_TOLERANCE_UM:.3f}um 이하, vision Z 추정 '
                    f'오차 {self.VISION_Z_TOLERANCE_UM:.3f}um 이하입니다.'
                )
                return True
            window_size = self.VISION_MICRO_AVERAGE_WINDOW
            correction_result = dict(micro_result)
            if optical_z_bias is None:
                correction_result['dz'] = 0.0
            if len(micro_history) >= window_size:
                filtered_result = self.median_vision_results(
                    micro_history[-window_size:],
                )
                if (
                    optical_z_bias is not None
                    and self.vision_error_within_tolerance(filtered_result)
                ):
                    self.log_vision_result(
                        f'{target} Micro 최근 {window_size}프레임 중앙값',
                        filtered_result,
                    )
                    self.get_logger().info(
                        f'{target} 비전 정렬 완료: simulation 값 없이 '
                        f'최근 {window_size}개 image estimate 중앙값이 '
                        f'XY/theta {self.VISION_TOLERANCE_UM:.3f}um, '
                        f'Z {self.VISION_Z_TOLERANCE_UM:.3f}um 이하입니다.'
                    )
                    return True
                # Temporal filtering is needed for noisy optical scale (Z),
                # while XY/theta must follow the newest closed-loop image.
                correction_result = dict(micro_result)
                correction_result['dz'] = filtered_result['dz']
                correction_result['source'] = 'vision_latest_xytheta_median_z'
                if optical_z_bias is None:
                    correction_result['dz'] = 0.0
            if iteration >= int(max_micro_iterations):
                break
            if not self.apply_vision_correction(
                correction_result,
                'micro',
                settle_sec=settle_sec,
            ):
                return False

        self.get_logger().error(
            f'{target} Micro 정렬이 {int(max_micro_iterations)}회 안에 '
            f'vision XY/theta={self.VISION_TOLERANCE_UM:.3f}um, '
            f'vision Z={self.VISION_Z_TOLERANCE_UM:.3f}um 기준으로 '
            '수렴하지 않았습니다.'
        )
        return False

    def recover_vision_demo(self, chip_attached, settle_sec=None):
        self.get_logger().warn(
            '비전 데모 복구: 현재 XY에서 기준 정렬 높이로 상승합니다.'
        )
        self.publish_move(
            self.last_sent_x,
            self.last_sent_y,
            self.GRIPPER_HOME_Z,
            theta_deg=self.last_sent_theta_deg,
        )
        self.wait_for_vision_motion(minimum_settle_sec=settle_sec)
        if chip_attached:
            self.get_logger().warn(
                'chip 손실 방지를 위해 vacuum을 유지합니다. 접촉/비전 상태를 확인한 뒤 해제하세요.'
            )
            return

        self.publish_move(
            self.GRIPPER_HOME_X,
            self.GRIPPER_HOME_Y,
            self.GRIPPER_HOME_Z,
            theta_deg=0.0,
        )
        self.wait_for_vision_motion(minimum_settle_sec=settle_sec)

    def run_vision_pick_place_demo(
        self,
        pick_x=500.0,
        pick_y=400.0,
        chip_z=None,
        chip_theta_deg=0.0,
        pick_gripper_theta_deg=None,
        place_x=None,
        place_y=None,
        place_theta_deg=0.0,
        contact_z=None,
        place_reference='place_empty',
        chip_model=None,
        support_model=None,
        stack_level=0,
        max_micro_iterations=20,
        settle_sec=None,
        vision_settle_sec=None,
        vision_timeout_sec=None,
        motion_timeout_sec=None,
        xy_theta_tolerance_um=None,
        z_tolerance_um=None,
        reset_chip_before_pick=True,
        measure_final_error=True,
    ):
        """기준 영상으로 4축 정렬한 뒤 기존 접촉 기반 pick/place를 실행합니다."""

        target_chip_model = (
            self.PRIMARY_CHIP_MODEL
            if chip_model is None
            else str(chip_model).strip()
        )
        target_support_model = (
            self.SUBSTRATE_MODEL
            if support_model is None
            else str(support_model).strip()
        )
        self.activate_chip(
            target_chip_model,
            support_model=target_support_model,
            stack_level=stack_level,
        )

        if vision_timeout_sec is not None:
            self.VISION_REQUEST_TIMEOUT_SEC = float(vision_timeout_sec)
        if motion_timeout_sec is not None:
            self.VISION_MOTION_TIMEOUT_SEC = max(0.0, float(motion_timeout_sec))
        if xy_theta_tolerance_um is not None:
            self.VISION_TOLERANCE_UM = max(
                0.0,
                float(xy_theta_tolerance_um),
            )
        if z_tolerance_um is not None:
            self.VISION_Z_TOLERANCE_UM = max(0.0, float(z_tolerance_um))
        max_iterations = max(1, int(max_micro_iterations))
        vision_wait = (
            self.VISION_SETTLE_SEC
            if vision_settle_sec is None
            else max(0.0, float(vision_settle_sec))
        )
        chip_height = self.CHIP_REST_Z if chip_z is None else float(chip_z)
        chip_spawn_theta = float(chip_theta_deg)
        nominal_pick_theta = (
            0.0
            if pick_gripper_theta_deg is None
            else float(pick_gripper_theta_deg)
        )
        nominal_place_theta = float(place_theta_deg)
        pick_height = self.PRESS_Z if contact_z is None else float(contact_z)
        pick_surface_height = (
            chip_height
            + self.CHIP_THICKNESS_MM
            + self.GRIPPER_CONTACT_OFFSET_MM
        )
        pick_height = max(pick_height, pick_surface_height)
        target_place_x = self.SUBSTRATE_CENTER_X if place_x is None else float(place_x)
        target_place_y = self.SUBSTRATE_CENTER_Y if place_y is None else float(place_y)
        normalized_place_reference = str(place_reference).strip().lower()
        if normalized_place_reference not in {'place_empty', 'place_stacked'}:
            self.get_logger().error(
                f'place_reference는 place_empty 또는 place_stacked여야 합니다: '
                f'{place_reference}'
            )
            return False

        self.get_logger().info(
            'vision_pick_place_demo 시작: '
            f'pick=({pick_x:.3f}, {pick_y:.3f})mm, '
            f'place=({target_place_x:.3f}, {target_place_y:.3f})mm, '
            f'chip_model={self.RED_CHIP_MODEL}, '
            f'chip_spawn_theta={chip_spawn_theta:.3f}deg, '
            f'pick_gripper_theta={nominal_pick_theta:.3f}deg, '
            f'place_theta={nominal_place_theta:.3f}deg, '
            f'contact_pair={self.RED_CHIP_MODEL}<->{self.PLACEMENT_SUPPORT_MODEL}, '
            f'layer={self.active_stack_level + 1}, '
            f'alignment_z={self.GRIPPER_HOME_Z:.3f}mm, '
            f'xy_theta_tolerance={self.VISION_TOLERANCE_UM:.3f}um, '
            f'z_tolerance={self.VISION_Z_TOLERANCE_UM:.3f}um, '
            'alignment_feedback=vision_image_only, '
            f'motion_timeout={self.VISION_MOTION_TIMEOUT_SEC:.1f}s, '
            f'place_reference={normalized_place_reference}'
        )
        if not self.wait_for_vision_bridge():
            return False
        if self.active_stack_level == 0:
            if not self.set_substrate_pose_abs(
                self.SUBSTRATE_CENTER_X,
                self.SUBSTRATE_CENTER_Y,
            ):
                return False
        else:
            self.get_logger().info(
                '기존 substrate 및 하부 chip 적층 자세를 유지합니다.'
            )
        if reset_chip_before_pick and not self.reset_red_chip(
            pick_x,
            pick_y,
            chip_height,
            theta_deg=chip_spawn_theta,
        ):
            self.get_logger().error(
                f'{self.RED_CHIP_MODEL}을 pick 시작 위치로 초기화하지 못했습니다.'
            )
            return False

        self.get_logger().info('1/11 예상 chip 위치의 기준 정렬 높이로 이동')
        if not self.publish_move(
            pick_x,
            pick_y,
            self.GRIPPER_HOME_Z,
            theta_deg=nominal_pick_theta,
        ):
            return False
        pick_settled = self.wait_for_vision_motion(minimum_settle_sec=settle_sec)
        if not pick_settled and not self.actual_pose_within_vision_capture_range():
            self.get_logger().error(
                '예정 pick 위치가 Macro 시야 안에 들어오지 않아 비전 정렬을 시작하지 않습니다.'
            )
            self.recover_vision_demo(False, settle_sec=settle_sec)
            return False

        self.get_logger().info('2/11 pick 비전 정렬: Macro 1회 후 Micro 반복')
        if not self.align_at_reference_height(
            'pick',
            'pick',
            max_micro_iterations=max_iterations,
            settle_sec=vision_wait,
        ):
            self.recover_vision_demo(False, settle_sec=settle_sec)
            return False
        aligned_pick_x = self.last_sent_x
        aligned_pick_y = self.last_sent_y
        aligned_pick_theta = self.last_sent_theta_deg

        self.get_logger().info('3/11 정렬된 위치에서 chip 접촉까지 단계 하강')
        self.last_picker_contact_time = 0.0
        self.picker_contact_gripper_z_mm = None
        if not self.descend_until_contact(
            aligned_pick_x,
            aligned_pick_y,
            pick_height,
            self.has_recent_picker_contact,
            self.wait_for_picker_contact,
            'vision picker-chip',
            theta_deg=aligned_pick_theta,
        ):
            self.recover_vision_demo(False, settle_sec=settle_sec)
            return False

        self.get_logger().info('4/11 접촉이 확인된 chip 흡착')
        if not self.vacuum_on():
            self.recover_vision_demo(False, settle_sec=settle_sec)
            return False
        carried_offset = self.record_carried_chip_offset(chip_height)
        place_height = self.stack_contact_surface_z_mm() + carried_offset

        self.get_logger().info('5/11 pick 위치에서 기준 정렬 높이로 상승')
        if not self.publish_move(
            aligned_pick_x,
            aligned_pick_y,
            self.GRIPPER_HOME_Z,
            theta_deg=aligned_pick_theta,
        ):
            self.recover_vision_demo(True, settle_sec=settle_sec)
            return False
        self.wait_for_vision_motion(minimum_settle_sec=settle_sec)

        self.get_logger().info('6/11 예상 substrate 중심의 기준 정렬 높이로 이동')
        if not self.publish_move(
            target_place_x,
            target_place_y,
            self.GRIPPER_HOME_Z,
            theta_deg=nominal_place_theta,
        ):
            self.recover_vision_demo(True, settle_sec=settle_sec)
            return False
        place_settled = self.wait_for_vision_motion(minimum_settle_sec=settle_sec)
        if not place_settled and not self.actual_pose_within_vision_capture_range():
            self.get_logger().error(
                '예정 substrate 위치가 Macro 시야 안에 들어오지 않아 place 정렬을 시작하지 않습니다.'
            )
            self.recover_vision_demo(True, settle_sec=settle_sec)
            return False

        self.get_logger().info('7/11 place 비전 정렬: Macro 1회 후 Micro 반복')
        if not self.align_at_reference_height(
            normalized_place_reference,
            'place',
            max_micro_iterations=max_iterations,
            settle_sec=vision_wait,
        ):
            self.recover_vision_demo(True, settle_sec=settle_sec)
            return False
        aligned_place_x = self.last_sent_x
        aligned_place_y = self.last_sent_y
        aligned_place_theta = self.last_sent_theta_deg

        self.get_logger().info(
            '8/11 정렬된 위치에서 적층 접촉까지 단계 하강: '
            f'pair={self.RED_CHIP_MODEL}<->{self.PLACEMENT_SUPPORT_MODEL}, '
            f'surface_z={self.stack_contact_surface_z_mm():.3f}mm, '
            f'limit_z={place_height:.3f}mm'
        )
        self.last_substrate_contact_time = 0.0
        self.substrate_contact_gripper_z_mm = None
        if not self.descend_until_contact(
            aligned_place_x,
            aligned_place_y,
            place_height,
            self.has_recent_substrate_contact,
            self.wait_for_substrate_contact,
            f'vision {self.RED_CHIP_MODEL}-{self.PLACEMENT_SUPPORT_MODEL}',
            theta_deg=aligned_place_theta,
        ):
            self.recover_vision_demo(True, settle_sec=settle_sec)
            return False

        self.get_logger().info('9/11 접촉 위치에서 substrate에 고정 후 vacuum 해제')
        if not self.transfer_chip_to_substrate(
            aligned_place_x,
            aligned_place_y,
            theta_deg=aligned_place_theta,
        ):
            self.recover_vision_demo(True, settle_sec=settle_sec)
            return False
        time.sleep(0.3)

        step_10_description = (
            'substrate 위에서 기준 정렬 높이로 상승 후 배치 오차 측정'
            if measure_final_error
            else 'substrate 위에서 기준 정렬 높이로 상승'
        )
        self.get_logger().info(f'10/11 {step_10_description}')
        if not self.publish_move(
            aligned_place_x,
            aligned_place_y,
            self.GRIPPER_HOME_Z,
            theta_deg=aligned_place_theta,
        ):
            return False
        self.wait_for_vision_motion(minimum_settle_sec=settle_sec)
        final_vision_error = (
            self.measure_placement_error_from_vision()
            if measure_final_error
            else None
        )

        self.get_logger().info('11/11 초기 spawn 기준점으로 복귀')
        if not self.publish_move(
            self.GRIPPER_HOME_X,
            self.GRIPPER_HOME_Y,
            self.GRIPPER_HOME_Z,
            theta_deg=0.0,
        ):
            return False
        self.wait_for_motion(settle_sec)
        if measure_final_error:
            self.log_final_placement_errors(final_vision_error)
        self.get_logger().info('vision_pick_place_demo 완료')
        return True

    def build_stack_chip_specs(
        self,
        stack_count,
        pick_x,
        first_pick_y,
        last_pick_y,
        first_chip_theta_deg,
        last_chip_theta_deg,
    ):
        count = int(stack_count)
        if count < 2 or count > MAX_STACK_CHIP_COUNT:
            raise ValueError(
                f'stack_count는 2~{MAX_STACK_CHIP_COUNT} 범위여야 합니다: {count}'
            )
        if count > len(self.CHIP_MODELS):
            raise ValueError(
                f'controller가 {len(self.CHIP_MODELS)}개 chip용으로 초기화되어 '
                f'{count}개 stack을 실행할 수 없습니다.'
            )

        specs = []
        for stack_level in range(count):
            ratio = stack_level / (count - 1)
            specs.append({
                'index': stack_level + 1,
                'stack_level': stack_level,
                'model': self.CHIP_MODELS[stack_level],
                'pick_x': float(pick_x),
                'pick_y': (
                    float(first_pick_y)
                    + ratio * (float(last_pick_y) - float(first_pick_y))
                ),
                'theta_deg': (
                    float(first_chip_theta_deg)
                    + ratio
                    * (float(last_chip_theta_deg) - float(first_chip_theta_deg))
                ),
            })
        return specs

    def prepare_stack_source_chips(self, chip_specs, chip_height):
        for spec in reversed(chip_specs):
            support_model = (
                self.SUBSTRATE_MODEL
                if spec['stack_level'] == 0
                else chip_specs[spec['stack_level'] - 1]['model']
            )
            self.activate_chip(
                spec['model'],
                support_model=support_model,
                stack_level=spec['stack_level'],
                log=False,
            )
            if not self.reset_red_chip(
                spec['pick_x'],
                spec['pick_y'],
                chip_height,
                theta_deg=spec['theta_deg'],
                verify_pose=True,
            ):
                self.get_logger().error(
                    f'chip {spec["index"]}({spec["model"]}) 초기화 실패: '
                    'Gazebo를 동일한 STACK_COUNT로 실행했는지 확인하세요.'
                )
                return False
        return True

    def run_vision_stack_demo(
        self,
        stack_count=DEFAULT_STACK_CHIP_COUNT,
        pick_x=500.0,
        first_pick_y=400.0,
        last_pick_y=-400.0,
        first_chip_theta_deg=0.0,
        last_chip_theta_deg=45.0,
        chip_z=None,
        place_x=None,
        place_y=None,
        contact_z=None,
        max_micro_iterations=20,
        settle_sec=None,
        vision_settle_sec=None,
        vision_timeout_sec=None,
        motion_timeout_sec=None,
        xy_theta_tolerance_um=None,
        z_tolerance_um=None,
    ):
        """비전과 실제 contact를 사용해 2~16개의 chip을 순차 적층합니다."""

        try:
            chip_specs = self.build_stack_chip_specs(
                stack_count,
                pick_x,
                first_pick_y,
                last_pick_y,
                first_chip_theta_deg,
                last_chip_theta_deg,
            )
        except (TypeError, ValueError) as exc:
            self.get_logger().error(str(exc))
            return False

        requested_count = (
            self.STACK_COUNT
            if stack_count is None
            else validate_stack_count(stack_count)
        )
        if requested_count > len(self.CHIP_MODELS):
            raise ValueError(
                f'controller가 {len(self.CHIP_MODELS)}개 chip으로 초기화되어 '
                f'{requested_count}개 적층을 실행할 수 없습니다.'
            )
        chip_height = self.CHIP_REST_Z if chip_z is None else float(chip_z)
        target_place_x = self.SUBSTRATE_CENTER_X if place_x is None else float(place_x)
        target_place_y = self.SUBSTRATE_CENTER_Y if place_y is None else float(place_y)
        y_step = (chip_specs[-1]['pick_y'] - chip_specs[0]['pick_y']) / (
            len(chip_specs) - 1
        )
        theta_step = (
            chip_specs[-1]['theta_deg'] - chip_specs[0]['theta_deg']
        ) / (len(chip_specs) - 1)
        self.get_logger().info(
            'vision_stack_demo 시작: '
            f'chips={len(chip_specs)}, pick_x={float(pick_x):.3f}mm, '
            f'pick_y={chip_specs[0]["pick_y"]:.3f}..'
            f'{chip_specs[-1]["pick_y"]:.3f}mm(step={y_step:.3f}mm), '
            f'chip_theta={chip_specs[0]["theta_deg"]:.3f}..'
            f'{chip_specs[-1]["theta_deg"]:.3f}deg(step={theta_step:.3f}deg), '
            f'stack=({target_place_x:.3f}, {target_place_y:.3f})mm, '
            'place_alignment=substrate_only(place_empty), '
            'per_layer_final_camera_measurement=disabled'
        )
        for spec in chip_specs:
            self.get_logger().info(
                '[STACK_SOURCE] '
                f'chip={spec["index"]}, model={spec["model"]}, '
                f'pose=({spec["pick_x"]:.3f}, {spec["pick_y"]:.3f}, '
                f'{chip_height:.3f})mm, theta={spec["theta_deg"]:.3f}deg'
            )

        try:
            if not self.prepare_stack_source_chips(chip_specs, chip_height):
                return False

            for spec in chip_specs:
                stack_level = spec['stack_level']
                support_model = (
                    self.SUBSTRATE_MODEL
                    if stack_level == 0
                    else chip_specs[stack_level - 1]['model']
                )
                contact_description = (
                    'substrate_link-chip contact'
                    if stack_level == 0
                    else f'{support_model}-{spec["model"]} chip-chip contact'
                )
                self.get_logger().info(
                    f'적층 {spec["index"]}/{len(chip_specs)}: '
                    f'{contact_description}를 기준으로 배치합니다.'
                )
                success = self.run_vision_pick_place_demo(
                    pick_x=spec['pick_x'],
                    pick_y=spec['pick_y'],
                    chip_z=chip_height,
                    chip_theta_deg=spec['theta_deg'],
                    pick_gripper_theta_deg=0.0,
                    place_x=target_place_x,
                    place_y=target_place_y,
                    place_theta_deg=0.0,
                    contact_z=contact_z,
                    place_reference='place_empty',
                    chip_model=spec['model'],
                    support_model=support_model,
                    stack_level=stack_level,
                    max_micro_iterations=max_micro_iterations,
                    settle_sec=settle_sec,
                    vision_settle_sec=vision_settle_sec,
                    vision_timeout_sec=vision_timeout_sec,
                    motion_timeout_sec=motion_timeout_sec,
                    xy_theta_tolerance_um=xy_theta_tolerance_um,
                    z_tolerance_um=z_tolerance_um,
                    reset_chip_before_pick=False,
                    measure_final_error=False,
                )
                if not success:
                    self.get_logger().error(
                        f'chip {spec["index"]}/{len(chip_specs)} '
                        f'({spec["model"]}) 적층 실패: 이후 공정을 중단합니다.'
                    )
                    return False

            self.log_stack_absolute_errors(chip_specs)
            self.get_logger().info(
                f'vision_stack_demo 완료: {len(chip_specs)}개 chip이 '
                '각 층의 실제 contact 위치에서 순차 고정되었습니다.'
            )
            return True
        finally:
            self.activate_chip(
                self.PRIMARY_CHIP_MODEL,
                support_model=self.SUBSTRATE_MODEL,
                stack_level=0,
                log=False,
            )

    def run_pick_place_demo(
        self,
        pick_x=500.0,
        pick_y=400.0,
        pick_z=None,
        chip_z=None,
        place_x=None,
        place_y=None,
        place_z=None,
        safe_z=None,
        contact_z=None,
        settle_sec=None,
    ):

        """
        그리퍼 기준점 절대좌표 기준 pick -> lift -> place -> release 흐름을 실행함.
        기본값은 절대좌표 (500, 400)mm 작업면 위 칩을 substrate 위로 옮깁니다.
        """

        safe_height = self.HOVER_Z if safe_z is None else safe_z
        pick_height = self.PRESS_Z if pick_z is None else float(pick_z)
        if contact_z is not None:
            pick_height = float(contact_z)
        chip_height = self.CHIP_REST_Z if chip_z is None else float(chip_z)
        target_place_x = self.SUBSTRATE_CENTER_X if place_x is None else float(place_x)
        target_place_y = self.SUBSTRATE_CENTER_Y if place_y is None else float(place_y)
        explicit_place_height = place_z is not None
        place_height = self.SUBSTRATE_TOP_Z if place_z is None else float(place_z)
        pick_surface_height = (
            chip_height
            + self.CHIP_THICKNESS_MM
            + self.GRIPPER_CONTACT_OFFSET_MM
        )
        if pick_height < pick_surface_height:
            self.get_logger().warn(
                f'pick_height={pick_height:.2f}mm가 theta_link_1 최하단이 chip 윗면에 닿는 '
                f'{pick_surface_height:.2f}mm보다 낮아 보정합니다.'
            )
            pick_height = pick_surface_height
        minimum_place_height = (
            self.BASE_TOP_Z
            + self.SUBSTRATE_THICKNESS_MM
            + self.CHIP_THICKNESS_MM
            + self.GRIPPER_CONTACT_OFFSET_MM
        )
        if place_height < minimum_place_height:
            self.get_logger().warn(
                f'place_height={place_height:.2f}mm가 theta_link_1 최하단이 substrate 위 chip에 닿는 '
                f'{minimum_place_height:.2f}mm보다 낮아 보정합니다.'
            )
            place_height = minimum_place_height

        self.get_logger().info(
            f'pick_place_demo 시작(gripper_abs_ref): '
            f'pick=({pick_x}, {pick_y}, {pick_height})mm, '
            f'chip_bottom_z={chip_height}mm, '
            f'place=({target_place_x}, {target_place_y}, {place_height})mm, '
            f'place_world=({target_place_x * 0.001:.3f}, {target_place_y * 0.001:.3f})m, '
            f'substrate_center=({self.SUBSTRATE_CENTER_X}, {self.SUBSTRATE_CENTER_Y})mm, '
            f'substrate_world=({self.SUBSTRATE_CENTER_X * 0.001:.3f}, '
            f'{self.SUBSTRATE_CENTER_Y * 0.001:.3f})m, '
            f'gripper_contact_offset={self.GRIPPER_CONTACT_OFFSET_MM}mm, '
            f'safe_z={safe_height}mm, '
            f'home=({self.GRIPPER_HOME_X}, {self.GRIPPER_HOME_Y}, {self.GRIPPER_HOME_Z})mm'
        )
        self.reset_red_chip(pick_x, pick_y, chip_height)

        self.get_logger().info('1/9 pick 위치 상공으로 이동')
        self.publish_move(pick_x, pick_y, safe_height, theta_deg=0.0)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('2/9 pick 접촉까지 단계 하강')
        self.last_picker_contact_time = 0.0
        self.picker_contact_gripper_z_mm = None
        if not self.descend_until_contact(
            pick_x,
            pick_y,
            pick_height,
            self.has_recent_picker_contact,
            self.wait_for_picker_contact,
            'picker-chip',
            theta_deg=0.0,
        ):
            self.get_logger().warn(
                'pick 단계에서 picker-chip contact가 감지되지 않아 '
                'chip을 움직이지 않고 pick_place_demo를 중단합니다.'
            )
            return False

        self.get_logger().info('3/9 칩 흡착')
        if not self.vacuum_on():
            self.get_logger().warn('pick 접촉/흡착 실패: chip을 움직이지 않고 pick_place_demo를 중단합니다.')
            return False
        carried_offset = self.record_carried_chip_offset(chip_height)
        carried_place_height = self.carried_chip_place_z_mm()
        if explicit_place_height and place_height < carried_place_height:
            self.get_logger().warn(
                f'place_height={place_height:.2f}mm는 pick 오프셋 '
                f'{carried_offset:.2f}mm를 반영한 접촉 높이 '
                f'{carried_place_height:.2f}mm보다 낮아 보정합니다.'
            )
            place_height = carried_place_height
        elif not explicit_place_height:
            place_height = carried_place_height
        self.get_logger().info(
            f'place 접촉 높이 보정: substrate_top={self.substrate_top_z_mm():.2f}mm, '
            f'carried_offset={carried_offset:.2f}mm -> place_z={place_height:.2f}mm'
        )
        time.sleep(0.5)

        self.get_logger().info('4/9 pick 위치에서 상승')
        self.publish_move(pick_x, pick_y, safe_height, theta_deg=0.0)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('5/9 place 위치 상공으로 이동')
        self.publish_move(target_place_x, target_place_y, safe_height, theta_deg=0.0)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('6/9 place 접촉까지 단계 하강')
        self.last_substrate_contact_time = 0.0
        self.substrate_contact_gripper_z_mm = None
        if not self.descend_until_contact(
            target_place_x,
            target_place_y,
            place_height,
            self.has_recent_substrate_contact,
            self.wait_for_substrate_contact,
            'chip-substrate',
            theta_deg=0.0,
        ):
            self.get_logger().warn(
                'place 단계에서 chip-substrate contact가 감지되지 않아 '
                'vacuum을 유지한 채 place 위치 상공으로 복귀합니다.'
            )
            self.publish_move(target_place_x, target_place_y, safe_height, theta_deg=0.0)
            self.wait_for_motion(settle_sec)
            return False

        self.get_logger().info('7/9 substrate_link 접촉 위치에서 칩 고정')
        if not self.transfer_chip_to_substrate(
            target_place_x,
            target_place_y,
            theta_deg=0.0,
        ):
            self.get_logger().warn(
                'place 접촉/접착 실패: vacuum을 유지한 채 place 위치 상공으로 복귀합니다.'
            )
            self.publish_move(target_place_x, target_place_y, safe_height, theta_deg=0.0)
            self.wait_for_motion(settle_sec)
            return False
        time.sleep(0.3)

        self.get_logger().info('8/9 칩 릴리즈 확인')
        if self.vacuum_attached:
            self.vacuum_off()
        else:
            self.get_logger().info('vacuum은 substrate transfer 중 이미 해제되었습니다.')
        time.sleep(0.5)

        self.get_logger().info('9/9 substrate 중심 상공으로 복귀')
        self.publish_move(target_place_x, target_place_y, safe_height, theta_deg=0.0)
        self.wait_for_motion(settle_sec)
        self.publish_move(
            target_place_x,
            target_place_y,
            self.GRIPPER_HOME_Z,
            theta_deg=0.0,
        )
        self.wait_for_motion(settle_sec)

        self.get_logger().info('pick_place_demo 완료')
        return True

    def run_three_chip_demo(
        self,
        safe_z=None,
        contact_z=None,
        settle_sec=None,
    ):

        """
        로봇 중심 좌표 (0, 0, 50)mm에서 시작해 칩 3개를 순서대로 pick/place하는 데모.
        실제 칩/트레이 위치가 확정되면 chip_jobs의 좌표만 교체하면 됨.
        """

        safe_height = self.HOVER_Z if safe_z is None else safe_z
        contact_height = self.resolve_contact_height(contact_z)
        chip_jobs = (
            ("chip_1", -170.0, -80.0, 170.0, -80.0),
            ("chip_2", -170.0, 0.0, 170.0, 0.0),
            ("chip_3", -170.0, 80.0, 170.0, 80.0),
        )

        self.get_logger().info(
            f'three_chip_demo 시작: center=(0, 0, {safe_height})mm'
        )
        self.publish_move(0.0, 0.0, safe_height, theta_deg=0.0)
        self.wait_for_motion(settle_sec)

        for label, pick_x, pick_y, place_x, place_y in chip_jobs:
            self.get_logger().info(
                f'{label}: pick=({pick_x}, {pick_y})mm -> '
                f'place=({place_x}, {place_y})mm'
            )
            self.run_pick_place_demo(
                pick_x=pick_x,
                pick_y=pick_y,
                place_x=place_x,
                place_y=place_y,
                safe_z=safe_height,
                contact_z=contact_height,
                settle_sec=settle_sec,
            )

        self.get_logger().info('중심 위치로 복귀')
        self.publish_move(0.0, 0.0, safe_height, theta_deg=0.0)
        self.wait_for_motion(settle_sec)
        self.get_logger().info('three_chip_demo 완료')

    def run_theta_demo(self, settle_sec=None):

        """
        현재 위치에서 theta 회전 관절만 좌우로 움직이는 데모.
        """

        self.get_logger().info('theta_demo 시작')
        for theta_deg in (0.0, 90.0, -90.0, 45.0, 0.0):
            self.move_theta(theta_deg)
            self.wait_for_motion(settle_sec)
        self.get_logger().info('theta_demo 완료')

    def run_joint_demo(self, settle_sec=None):

        """
        X/Y/Z/theta 관절이 각각 움직이는지 확인하는 데모.
        """

        self.get_logger().info('joint_demo 시작')
        demo_steps = (
            (0.0, 0.0, 50.0, 0.0, '기준 위치'),
            (80.0, 0.0, 50.0, 0.0, 'X +80mm'),
            (-80.0, 0.0, 50.0, 0.0, 'X -80mm'),
            (0.0, 0.0, 50.0, 0.0, 'X 복귀'),
            (0.0, 60.0, 50.0, 0.0, 'Y +60mm'),
            (0.0, -60.0, 50.0, 0.0, 'Y -60mm'),
            (0.0, 0.0, 50.0, 0.0, 'Y 복귀'),
            (0.0, 0.0, 100.0, 0.0, 'Z 상단 100mm'),
            (0.0, 0.0, 50.0, 0.0, 'Z 작업면 50mm'),
            (0.0, 0.0, 50.0, 0.0, 'Z 복귀'),
            (0.0, 0.0, 50.0, 90.0, 'theta +90deg'),
            (0.0, 0.0, 50.0, -90.0, 'theta -90deg'),
            (0.0, 0.0, 50.0, 0.0, 'theta 복귀'),
        )

        for x, y, z, theta_deg, label in demo_steps:
            self.get_logger().info(label)
            self.publish_move(x, y, z, theta_deg=theta_deg)
            self.wait_for_motion(settle_sec)

        self.get_logger().info('joint_demo 완료')

    def run_range_demo(self, settle_sec=None):

        """
        팀 시연용으로 X/Y/Z/theta를 약 75% 구동범위까지 순서대로 움직이는 데모.
        X/Y/Z 입력 단위는 /robot/command_pose 기준 mm, theta는 deg임.
        """

        self.get_logger().info('range_demo 시작: 각 관절 약 75% 구동범위 시연')
        demo_steps = (
            (0.0, 0.0, 50.0, 0.0, '기준 위치'),
            (300.0, 0.0, 50.0, 0.0, 'X +300mm'),
            (-200.0, 0.0, 50.0, 0.0, 'X -200mm'),
            (0.0, 0.0, 50.0, 0.0, 'X 복귀'),
            (0.0, 300.0, 50.0, 0.0, 'Y +300mm'),
            (0.0, -300.0, 50.0, 0.0, 'Y -300mm'),
            (0.0, 0.0, 50.0, 0.0, 'Y 복귀'),
            (0.0, 0.0, 100.0, 0.0, 'Z 상단'),
            (0.0, 0.0, 45.0, 0.0, 'Z 하단 약 75%'),
            (0.0, 0.0, 50.0, 0.0, 'Z 복귀'),
            (0.0, 0.0, 50.0, 135.0, 'theta +135deg'),
            (0.0, 0.0, 50.0, -135.0, 'theta -135deg'),
            (0.0, 0.0, 50.0, 0.0, 'theta 복귀'),
        )

        for x, y, z, theta_deg, label in demo_steps:
            self.get_logger().info(label)
            self.publish_move(x, y, z, theta_deg=theta_deg)
            self.wait_for_motion(settle_sec)

        self.get_logger().info('range_demo 완료')

def main(args=None):
    rclpy.init(args=args)
    parser = build_parser()
    parsed_args = parser.parse_args(args)
    stack_chip_count = (
        parsed_args.stack_count
        if parsed_args.command == 'vision_stack_demo'
        else 2
    )
    node = MainControllerNode(stack_chip_count=stack_chip_count)

    command_result = None
    try:
        if parsed_args.command is None:
            # 노드가 살아있으면서 명령을 대기하도록 설정
            rclpy.spin(node)
        else:
            command_result = run_command(node, parsed_args)
    except (KeyboardInterrupt, ExternalShutdownException):
        command_result = False
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    return 1 if command_result is False else 0


def build_parser():
    parser = argparse.ArgumentParser(
        description='Publish high-level robot Pose commands to /robot/command_pose.'
    )
    subparsers = parser.add_subparsers(dest='command')

    move_parser = subparsers.add_parser('move')
    move_parser.add_argument('x', type=float)
    move_parser.add_argument('y', type=float)
    move_parser.add_argument('z', type=float)
    move_parser.add_argument('--theta-deg', type=float, default=None)

    z_parser = subparsers.add_parser('z')
    z_parser.add_argument('height_mm', type=float)

    theta_parser = subparsers.add_parser('theta')
    theta_parser.add_argument('theta_deg', type=float)

    relative_parser = subparsers.add_parser('relative')
    relative_parser.add_argument('dx', type=float)
    relative_parser.add_argument('dy', type=float)
    relative_parser.add_argument('dz', type=float)
    relative_parser.add_argument('--dtheta-deg', type=float, default=0.0)

    back_parser = subparsers.add_parser('back')
    back_parser.add_argument('distance_mm', type=float, nargs='?', default=30.0)

    camera_parser = subparsers.add_parser('camera_center')
    camera_parser.add_argument('chip_x', type=float)
    camera_parser.add_argument('chip_y', type=float)

    transfer_parser = subparsers.add_parser('transfer')
    transfer_parser.add_argument('x', type=float)
    transfer_parser.add_argument('y', type=float)

    chip_reset_parser = subparsers.add_parser('chip_reset')
    chip_reset_parser.add_argument('x', type=float, nargs='?', default=500.0)
    chip_reset_parser.add_argument('y', type=float, nargs='?', default=400.0)
    chip_reset_parser.add_argument('z', type=float, nargs='?', default=None)

    subparsers.add_parser('press')
    subparsers.add_parser('lift')
    subparsers.add_parser('vacuum_on')
    subparsers.add_parser('vacuum_off')
    subparsers.add_parser('z_demo')

    theta_demo_parser = subparsers.add_parser('theta_demo')
    theta_demo_parser.add_argument('--settle-sec', type=float, default=None)

    joint_demo_parser = subparsers.add_parser('joint_demo')
    joint_demo_parser.add_argument('--settle-sec', type=float, default=None)

    range_demo_parser = subparsers.add_parser('range_demo')
    range_demo_parser.add_argument('--settle-sec', type=float, default=None)

    pick_place_parser = subparsers.add_parser('pick_place_demo')
    pick_place_parser.add_argument('--pick-x', type=float, default=500.0)
    pick_place_parser.add_argument('--pick-y', type=float, default=400.0)
    pick_place_parser.add_argument('--pick-z', type=float, default=None)
    pick_place_parser.add_argument('--chip-z', type=float, default=None)
    pick_place_parser.add_argument('--place-x', type=float, default=None)
    pick_place_parser.add_argument('--place-y', type=float, default=None)
    pick_place_parser.add_argument('--place-x-m', type=float, default=None)
    pick_place_parser.add_argument('--place-y-m', type=float, default=None)
    pick_place_parser.add_argument('--place-z', type=float, default=None)
    pick_place_parser.add_argument('--safe-z', type=float, default=100.0)
    pick_place_parser.add_argument('--contact-z', type=float, default=None)
    pick_place_parser.add_argument('--settle-sec', type=float, default=None)

    vision_reference_parser = subparsers.add_parser('vision_reference_capture')
    vision_reference_parser.add_argument(
        'reference_set',
        choices=('pick', 'place_empty', 'place_stacked'),
    )
    vision_reference_parser.add_argument('--settle-sec', type=float, default=None)
    vision_reference_parser.add_argument('--vision-timeout-sec', type=float, default=None)
    vision_reference_parser.add_argument('--motion-timeout-sec', type=float, default=None)

    vision_demo_parser = subparsers.add_parser('vision_pick_place_demo')
    vision_demo_parser.add_argument('--pick-x', type=float, default=500.0)
    vision_demo_parser.add_argument('--pick-y', type=float, default=400.0)
    vision_demo_parser.add_argument('--chip-z', type=float, default=None)
    vision_demo_parser.add_argument('--place-x', type=float, default=None)
    vision_demo_parser.add_argument('--place-y', type=float, default=None)
    vision_demo_parser.add_argument('--contact-z', type=float, default=None)
    vision_demo_parser.add_argument(
        '--place-reference',
        choices=('place_empty', 'place_stacked'),
        default='place_empty',
    )
    vision_demo_parser.add_argument('--max-micro-iterations', type=int, default=20)
    vision_demo_parser.add_argument('--settle-sec', type=float, default=None)
    vision_demo_parser.add_argument('--vision-settle-sec', type=float, default=None)
    vision_demo_parser.add_argument('--vision-timeout-sec', type=float, default=None)
    vision_demo_parser.add_argument('--motion-timeout-sec', type=float, default=None)
    vision_demo_parser.add_argument(
        '--xy-theta-tolerance-um',
        type=float,
        default=None,
    )
    vision_demo_parser.add_argument('--z-tolerance-um', type=float, default=None)

    vision_stack_parser = subparsers.add_parser('vision_stack_demo')
    vision_stack_parser.add_argument(
        '--stack-count',
        type=int,
        default=DEFAULT_STACK_CHIP_COUNT,
    )
    vision_stack_parser.add_argument('--pick-x', type=float, default=500.0)
    vision_stack_parser.add_argument('--first-pick-y', type=float, default=400.0)
    vision_stack_parser.add_argument('--last-pick-y', type=float, default=-400.0)
    vision_stack_parser.add_argument(
        '--first-chip-theta-deg',
        type=float,
        default=0.0,
    )
    vision_stack_parser.add_argument(
        '--last-chip-theta-deg',
        type=float,
        default=45.0,
    )
    vision_stack_parser.add_argument('--chip-z', type=float, default=None)
    vision_stack_parser.add_argument('--place-x', type=float, default=None)
    vision_stack_parser.add_argument('--place-y', type=float, default=None)
    vision_stack_parser.add_argument('--contact-z', type=float, default=None)
    vision_stack_parser.add_argument('--max-micro-iterations', type=int, default=20)
    vision_stack_parser.add_argument('--settle-sec', type=float, default=None)
    vision_stack_parser.add_argument('--vision-settle-sec', type=float, default=None)
    vision_stack_parser.add_argument('--vision-timeout-sec', type=float, default=None)
    vision_stack_parser.add_argument('--motion-timeout-sec', type=float, default=None)
    vision_stack_parser.add_argument(
        '--xy-theta-tolerance-um',
        type=float,
        default=None,
    )
    vision_stack_parser.add_argument('--z-tolerance-um', type=float, default=None)

    three_chip_parser = subparsers.add_parser('three_chip_demo')
    three_chip_parser.add_argument('--safe-z', type=float, default=100.0)
    three_chip_parser.add_argument('--contact-z', type=float, default=None)
    three_chip_parser.add_argument('--settle-sec', type=float, default=None)

    subparsers.add_parser('demo')

    return parser


def run_command(node, args):
    time.sleep(0.5)
    command_result = None

    if args.command == 'move':
        node.publish_move(args.x, args.y, args.z, theta_deg=args.theta_deg)
    elif args.command == 'z':
        node.move_z(args.height_mm)
    elif args.command == 'theta':
        node.move_theta(args.theta_deg)
    elif args.command == 'relative':
        node.move_relative(
            dx=args.dx,
            dy=args.dy,
            dz=args.dz,
            dtheta_deg=args.dtheta_deg,
        )
    elif args.command == 'back':
        node.move_back(args.distance_mm)
    elif args.command == 'camera_center':
        node.set_camera_center(args.chip_x, args.chip_y)
    elif args.command == 'transfer':
        node.transfer_position(args.x, args.y)
    elif args.command == 'chip_reset':
        node.reset_red_chip(args.x, args.y, args.z)
    elif args.command == 'press':
        node.execute_z_press()
    elif args.command == 'lift':
        node.lift_to_safety()
    elif args.command == 'vacuum_on':
        node.vacuum_on()
    elif args.command == 'vacuum_off':
        node.vacuum_off()
    elif args.command == 'z_demo':
        node.move_z(100.0)
        time.sleep(1.5)
        node.move_z(50.0)
        time.sleep(1.5)
        node.move_z(100.0)
    elif args.command == 'theta_demo':
        node.run_theta_demo(settle_sec=args.settle_sec)
    elif args.command == 'joint_demo':
        node.run_joint_demo(settle_sec=args.settle_sec)
    elif args.command == 'range_demo':
        node.run_range_demo(settle_sec=args.settle_sec)
    elif args.command == 'pick_place_demo':
        place_x = (
            args.place_x_m * 1000.0
            if args.place_x_m is not None
            else args.place_x
        )
        place_y = (
            args.place_y_m * 1000.0
            if args.place_y_m is not None
            else args.place_y
        )
        node.run_pick_place_demo(
            pick_x=args.pick_x,
            pick_y=args.pick_y,
            pick_z=args.pick_z,
            chip_z=args.chip_z,
            place_x=place_x,
            place_y=place_y,
            place_z=args.place_z,
            safe_z=args.safe_z,
            contact_z=args.contact_z,
            settle_sec=args.settle_sec,
        )
    elif args.command == 'vision_reference_capture':
        command_result = node.run_vision_reference_capture(
            args.reference_set,
            settle_sec=args.settle_sec,
            vision_timeout_sec=args.vision_timeout_sec,
            motion_timeout_sec=args.motion_timeout_sec,
        )
    elif args.command == 'vision_pick_place_demo':
        command_result = node.run_vision_pick_place_demo(
            pick_x=args.pick_x,
            pick_y=args.pick_y,
            chip_z=args.chip_z,
            place_x=args.place_x,
            place_y=args.place_y,
            contact_z=args.contact_z,
            place_reference=args.place_reference,
            max_micro_iterations=args.max_micro_iterations,
            settle_sec=args.settle_sec,
            vision_settle_sec=args.vision_settle_sec,
            vision_timeout_sec=args.vision_timeout_sec,
            motion_timeout_sec=args.motion_timeout_sec,
            xy_theta_tolerance_um=args.xy_theta_tolerance_um,
            z_tolerance_um=args.z_tolerance_um,
        )
    elif args.command == 'vision_stack_demo':
        command_result = node.run_vision_stack_demo(
            stack_count=args.stack_count,
            pick_x=args.pick_x,
            first_pick_y=args.first_pick_y,
            last_pick_y=args.last_pick_y,
            first_chip_theta_deg=args.first_chip_theta_deg,
            last_chip_theta_deg=args.last_chip_theta_deg,
            chip_z=args.chip_z,
            place_x=args.place_x,
            place_y=args.place_y,
            contact_z=args.contact_z,
            max_micro_iterations=args.max_micro_iterations,
            settle_sec=args.settle_sec,
            vision_settle_sec=args.vision_settle_sec,
            vision_timeout_sec=args.vision_timeout_sec,
            motion_timeout_sec=args.motion_timeout_sec,
            xy_theta_tolerance_um=args.xy_theta_tolerance_um,
            z_tolerance_um=args.z_tolerance_um,
        )
    elif args.command == 'three_chip_demo':
        node.run_three_chip_demo(
            safe_z=args.safe_z,
            contact_z=args.contact_z,
            settle_sec=args.settle_sec,
        )
    elif args.command == 'demo':
        node.run_pick_place_demo()

    rclpy.spin_once(node, timeout_sec=0.1)
    time.sleep(0.5)
    return command_result

if __name__ == '__main__':
    main()
