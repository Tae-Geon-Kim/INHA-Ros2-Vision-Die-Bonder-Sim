import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Pose


STATE_PATH = Path(os.environ.get("ROBOT_CONTROL_STATE", "/tmp/robot_control_pose_state.json"))
VACUUM_ON = True
VACUUM_OFF = False
DEFAULT_STATE = {
    "x": 0.0,
    "y": 0.0,
    "z": 50.0,
    "theta_deg": 0.0,
    "vacuum_attached": VACUUM_OFF,
    "chip_x": 0.0,
    "chip_y": 0.0,
    "chip_z": 0.0,
    "chip_theta_deg": 0.0,
}


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


def env_flag(name, default=False):
    default_value = "1" if default else "0"
    value = os.environ.get(name, default_value).strip().lower()
    return value in ("1", "true", "yes", "on")


class MainControllerNode(Node):
    def __init__(self):
        super().__init__('main_controller_node')
        
        # 로봇 하드웨어 명령 퍼블리셔 (Command topic: /robot/command_pose)
        self.cmd_pub = self.create_publisher(Pose, '/robot/command_pose', 10)
        
        # 그리퍼 중심점 기준 카메라의 상대 위치 오프셋
        self.GRIPPER_TO_CAMERA_DX = 50.0  
        self.GRIPPER_TO_CAMERA_DY = 20.0  
        
        # 수직 방향(Z) 제어 높이
        self.BASE_TOP_Z = float(os.environ.get("ROBOT_CONTROL_BASE_TOP_Z_MM", "50.0"))
        self.CHIP_THICKNESS_MM = float(os.environ.get("ROBOT_CONTROL_CHIP_THICKNESS_MM", "0.1"))
        self.SUBSTRATE_THICKNESS_MM = float(os.environ.get("ROBOT_CONTROL_SUBSTRATE_THICKNESS_MM", "5.0"))
        self.HOVER_Z = float(os.environ.get("ROBOT_CONTROL_HOVER_Z_MM", "100.0"))
        self.GRIPPER_HOME_X = float(os.environ.get("ROBOT_CONTROL_GRIPPER_HOME_X_MM", "140.0"))
        self.GRIPPER_HOME_Y = float(os.environ.get("ROBOT_CONTROL_GRIPPER_HOME_Y_MM", "0.0"))
        self.GRIPPER_HOME_Z = float(os.environ.get("ROBOT_CONTROL_GRIPPER_HOME_Z_MM", "155.0"))
        self.PRESS_Z = float(os.environ.get(
            "ROBOT_CONTROL_PICK_Z_MM",
            str(self.BASE_TOP_Z + self.CHIP_THICKNESS_MM),
        ))
        self.CHIP_REST_Z = float(os.environ.get("ROBOT_CONTROL_CHIP_REST_Z_MM", str(self.BASE_TOP_Z)))
        self.SUBSTRATE_TOP_Z = float(os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_TOP_Z_MM",
            str(self.BASE_TOP_Z + self.SUBSTRATE_THICKNESS_MM + self.CHIP_THICKNESS_MM),
        ))
        self.MIN_CONTACT_Z = float(os.environ.get(
            "ROBOT_CONTROL_MIN_CONTACT_Z",
            str(self.BASE_TOP_Z - 5.0),
        ))
        self.MOVE_SETTLE_SEC = 3.5

        # Gazebo 시연용 칩 모델 제어 설정
        self.GAZEBO_WORLD = os.environ.get("ROBOT_CONTROL_GAZEBO_WORLD", "empty")
        self.RED_CHIP_MODEL = os.environ.get("ROBOT_CONTROL_CHIP_MODEL", "check_chip")
        self.USE_DETACHABLE_JOINT = env_flag("ROBOT_CONTROL_USE_DETACHABLE_JOINT", True)
        self.REQUIRE_PICKER_CONTACT = env_flag("ROBOT_CONTROL_REQUIRE_PICKER_CONTACT", True)
        self.ATTACH_TOPIC = os.environ.get(
            "ROBOT_CONTROL_ATTACH_TOPIC",
            "/model/robot_system/vacuum/attach",
        )
        self.DETACH_TOPIC = os.environ.get(
            "ROBOT_CONTROL_DETACH_TOPIC",
            "/model/robot_system/vacuum/detach",
        )
        self.SUBSTRATE_ATTACH_TOPIC = os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_ATTACH_TOPIC",
            "/model/robot_system/substrate_bond/attach",
        )
        self.SUBSTRATE_DETACH_TOPIC = os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_DETACH_TOPIC",
            "/model/robot_system/substrate_bond/detach",
        )
        self.PICKER_CONTACT_TOPIC = os.environ.get(
            "ROBOT_CONTROL_PICKER_CONTACT_TOPIC",
            "/model/robot_system/picker/contact",
        )
        fallback_picker_contact_topic = (
            f"/world/{self.GAZEBO_WORLD}/model/robot_system/link/"
            "theta_link_1/sensor/picker_contact_sensor/contact"
        )
        contact_topics = os.environ.get(
            "ROBOT_CONTROL_PICKER_CONTACT_TOPICS",
            f"{fallback_picker_contact_topic},{self.PICKER_CONTACT_TOPIC}",
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
        fallback_substrate_contact_topic = (
            f"/world/{self.GAZEBO_WORLD}/model/robot_system/link/"
            "substrate_link/sensor/substrate_contact_sensor/contact"
        )
        substrate_contact_topics = os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_CONTACT_TOPICS",
            f"{fallback_substrate_contact_topic},{self.SUBSTRATE_CONTACT_TOPIC}",
        )
        self.SUBSTRATE_CONTACT_TOPICS = []
        for topic in substrate_contact_topics.split(","):
            topic = topic.strip()
            if topic and topic not in self.SUBSTRATE_CONTACT_TOPICS:
                self.SUBSTRATE_CONTACT_TOPICS.append(topic)
        self.discovered_picker_contact_topics = []
        self.last_contact_topic_discovery = 0.0
        self.CONTACT_TOPIC_DISCOVERY_INTERVAL_SEC = 2.0
        self.PICKER_COLLISION_TOKEN = os.environ.get(
            "ROBOT_CONTROL_PICKER_COLLISION_TOKEN",
            "picker_contact_collision",
        ).lower()
        chip_contact_tokens = os.environ.get(
            "ROBOT_CONTROL_CHIP_CONTACT_TOKENS",
            f"{self.RED_CHIP_MODEL},chip_link",
        )
        self.CHIP_CONTACT_TOKENS = [
            token.strip().lower()
            for token in chip_contact_tokens.split(",")
            if token.strip()
        ]
        substrate_contact_tokens = os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_CONTACT_TOKENS",
            "substrate_link_collision,substrate_link",
        )
        self.SUBSTRATE_CONTACT_TOKENS = [
            token.strip().lower()
            for token in substrate_contact_tokens.split(",")
            if token.strip()
        ]
        self.PICKER_CONTACT_TIMEOUT_SEC = float(os.environ.get(
            "ROBOT_CONTROL_PICKER_CONTACT_TIMEOUT_SEC",
            "6.0",
        ))
        self.SUBSTRATE_CONTACT_TIMEOUT_SEC = float(os.environ.get(
            "ROBOT_CONTROL_SUBSTRATE_CONTACT_TIMEOUT_SEC",
            "6.0",
        ))
        self.REQUIRE_SUBSTRATE_CONTACT = env_flag(
            "ROBOT_CONTROL_REQUIRE_SUBSTRATE_CONTACT",
            True,
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
            "y": (-400.0, 400.0),
            "z": (self.GRIPPER_HOME_Z - 115.0, self.GRIPPER_HOME_Z + 115.0),
        }

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
            self.SUBSTRATE_CONTACT_TOKENS,
            self.CHIP_CONTACT_TOKENS,
        )

    def read_contact_topic_once(self, topic, matcher, timeout_sec=0.25):
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
        return matcher(output)

    def read_picker_contact_topic_once(self, topic, timeout_sec=0.25):
        return self.read_contact_topic_once(
            topic,
            self.contact_output_has_picker_chip_pair,
            timeout_sec=timeout_sec,
        )

    def read_substrate_contact_topic_once(self, topic, timeout_sec=0.25):
        return self.read_contact_topic_once(
            topic,
            self.contact_output_has_substrate_chip_pair,
            timeout_sec=timeout_sec,
        )

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
        self.refresh_picker_contact_topics()
        topics = []
        for topic in self.PICKER_CONTACT_TOPICS + self.discovered_picker_contact_topics:
            if topic and topic not in topics:
                topics.append(topic)
        return topics or [self.PICKER_CONTACT_TOPIC]

    def read_picker_contact_once(self, timeout_sec=0.25):
        topics = self.get_picker_contact_topics()
        per_topic_timeout = max(0.2, timeout_sec / len(topics))
        for topic in topics:
            if self.read_picker_contact_topic_once(topic, timeout_sec=per_topic_timeout):
                return True
        return False

    def read_substrate_contact_once(self, timeout_sec=0.25):
        topics = self.SUBSTRATE_CONTACT_TOPICS
        per_topic_timeout = max(0.2, timeout_sec / len(topics))
        for topic in topics:
            if self.read_substrate_contact_topic_once(topic, timeout_sec=per_topic_timeout):
                return True
        return False

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
            remaining = max(0.05, min(0.25, deadline - time.monotonic()))
            if self.read_picker_contact_once(timeout_sec=remaining):
                self.get_logger().info('picker-chip contact 감지됨')
                return True

        self.get_logger().info('현재 위치에서는 picker-chip contact가 아직 감지되지 않았습니다.')
        return False

    def wait_for_substrate_contact(self, timeout_sec=None):
        if not self.REQUIRE_SUBSTRATE_CONTACT:
            return True

        wait_timeout = self.SUBSTRATE_CONTACT_TIMEOUT_SEC if timeout_sec is None else timeout_sec
        deadline = time.monotonic() + wait_timeout
        self.get_logger().info(
            'chip-substrate 실제 접촉 대기: '
            f'{", ".join(self.SUBSTRATE_CONTACT_TOPICS)}'
        )
        while time.monotonic() < deadline:
            remaining = max(0.05, min(0.25, deadline - time.monotonic()))
            if self.read_substrate_contact_once(timeout_sec=remaining):
                self.get_logger().info('chip-substrate contact 감지됨')
                return True

        self.get_logger().info('현재 위치에서는 chip-substrate contact가 아직 감지되지 않았습니다.')
        return False

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

    def attach_red_chip_to_picker(self):
        if not self.USE_DETACHABLE_JOINT:
            return False

        if self.REQUIRE_PICKER_CONTACT and not self.read_picker_contact_once(timeout_sec=0.5):
            self.get_logger().warn(
                'attach 직전 picker-chip contact 재확인 실패: attach 요청을 보내지 않습니다.'
            )
            return False

        attached = self.publish_empty_ign_topic(self.ATTACH_TOPIC)
        if attached:
            self.get_logger().info(
                f'Gazebo fixed joint attach 요청: {self.ATTACH_TOPIC}'
            )
        return attached

    def detach_red_chip_from_picker(self):
        if not self.USE_DETACHABLE_JOINT:
            return False

        detached = self.publish_empty_ign_topic(self.DETACH_TOPIC)
        if detached:
            self.get_logger().info(
                f'Gazebo fixed joint detach 요청: {self.DETACH_TOPIC}'
            )
        return detached

    def attach_chip_to_substrate(self):
        if not self.USE_DETACHABLE_JOINT:
            return False

        if self.REQUIRE_SUBSTRATE_CONTACT and not self.read_substrate_contact_once(timeout_sec=0.5):
            self.get_logger().warn(
                'substrate attach 직전 chip-substrate contact 재확인 실패: attach 요청을 보내지 않습니다.'
            )
            return False

        attached = self.publish_empty_ign_topic(self.SUBSTRATE_ATTACH_TOPIC)
        if attached:
            self.get_logger().info(
                f'Gazebo substrate bond attach 요청: {self.SUBSTRATE_ATTACH_TOPIC}'
            )
        return attached

    def detach_chip_from_substrate(self):
        if not self.USE_DETACHABLE_JOINT:
            return False

        detached = self.publish_empty_ign_topic(self.SUBSTRATE_DETACH_TOPIC)
        if detached:
            self.get_logger().info(
                f'Gazebo substrate bond detach 요청: {self.SUBSTRATE_DETACH_TOPIC}'
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
            float(z_mm) - self.CHIP_THICKNESS_MM,
            theta_deg=theta_deg,
        )

    def reset_red_chip(self, x_mm=500.0, y_mm=400.0, z_mm=None):
        chip_z = self.CHIP_REST_Z if z_mm is None else float(z_mm)
        self.force_vacuum_detached('chip_reset 전에 기존 detachable joint를 해제')
        self.force_substrate_bond_detached('chip_reset 전에 기존 substrate bond를 해제')
        self.get_logger().info(
            f'{self.RED_CHIP_MODEL}을 절대좌표 ({x_mm}, {y_mm}, {chip_z})mm에 배치합니다.'
        )
        self.set_red_chip_pose_abs(x_mm, y_mm, chip_z, theta_deg=0.0)
        self.save_current_state()

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
        time.sleep(wait_time)

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
        if not self.wait_for_picker_contact() and not self.search_picker_contact_downward():
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

        self.vacuum_attached = VACUUM_OFF
        self.get_logger().info(f'vacuum_off: picker와 {self.RED_CHIP_MODEL} 고정을 해제합니다.')
        if self.USE_DETACHABLE_JOINT:
            self.detach_red_chip_from_picker()
        else:
            self.set_red_chip_pose_abs(
                self.last_sent_x,
                self.last_sent_y,
                self.last_sent_z - self.CHIP_THICKNESS_MM,
                theta_deg=self.last_sent_theta_deg,
            )
        self.save_current_state()
        return True

    def substrate_bond_on(self):
        self.get_logger().info('substrate_bond_on: chip-substrate 접촉 확인 후 고정합니다.')
        if not self.wait_for_substrate_contact():
            self.get_logger().warn(
                'chip-substrate contact 최종 미감지: substrate bond attach를 수행하지 않습니다.'
            )
            return False

        if self.USE_DETACHABLE_JOINT:
            return self.attach_chip_to_substrate()

        return True

    def run_pick_place_demo(
        self,
        pick_x=500.0,
        pick_y=400.0,
        pick_z=None,
        chip_z=None,
        place_x=0.0,
        place_y=0.0,
        place_z=None,
        safe_z=None,
        contact_z=None,
        settle_sec=None,
    ):

        """
        그리퍼 접촉점 절대좌표 기준 pick -> lift -> place -> release 흐름을 실행함.
        기본값은 절대좌표 (500, 400)mm 작업면 위 칩을 substrate 위로 옮깁니다.
        """

        safe_height = self.HOVER_Z if safe_z is None else safe_z
        pick_height = self.PRESS_Z if pick_z is None else float(pick_z)
        if contact_z is not None:
            pick_height = float(contact_z)
        chip_height = self.CHIP_REST_Z if chip_z is None else float(chip_z)
        place_height = self.SUBSTRATE_TOP_Z if place_z is None else float(place_z)

        self.get_logger().info(
            f'pick_place_demo 시작(gripper_abs): '
            f'pick=({pick_x}, {pick_y}, {pick_height})mm, '
            f'chip_bottom_z={chip_height}mm, '
            f'place=({place_x}, {place_y}, {place_height})mm, '
            f'safe_z={safe_height}mm, '
            f'home=({self.GRIPPER_HOME_X}, {self.GRIPPER_HOME_Y}, {self.GRIPPER_HOME_Z})mm'
        )
        self.reset_red_chip(pick_x, pick_y, chip_height)

        self.get_logger().info('1/9 pick 위치 상공으로 이동')
        self.publish_move(pick_x, pick_y, safe_height, theta_deg=0.0)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('2/9 pick 접촉 높이로 하강')
        self.publish_move(pick_x, pick_y, pick_height, theta_deg=0.0)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('3/9 칩 흡착')
        if not self.vacuum_on():
            self.get_logger().warn('pick 접촉/흡착 실패: chip을 움직이지 않고 pick_place_demo를 중단합니다.')
            return False
        time.sleep(0.5)

        self.get_logger().info('4/9 pick 위치에서 상승')
        self.publish_move(pick_x, pick_y, safe_height, theta_deg=0.0)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('5/9 place 위치 상공으로 이동')
        self.publish_move(place_x, place_y, safe_height, theta_deg=0.0)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('6/9 place 접촉 높이로 하강')
        self.publish_move(place_x, place_y, place_height, theta_deg=0.0)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('7/9 substrate 접촉 후 칩 접착')
        if not self.substrate_bond_on():
            self.get_logger().warn(
                'place 접촉/접착 실패: vacuum을 유지한 채 place 위치 상공으로 복귀합니다.'
            )
            self.publish_move(place_x, place_y, safe_height, theta_deg=0.0)
            self.wait_for_motion(settle_sec)
            return False
        time.sleep(0.3)

        self.get_logger().info('8/9 칩 릴리즈')
        self.vacuum_off()
        time.sleep(0.5)

        self.get_logger().info('9/9 gripper 기준점으로 복귀')
        self.publish_move(place_x, place_y, safe_height, theta_deg=0.0)
        self.wait_for_motion(settle_sec)
        self.publish_move(
            self.GRIPPER_HOME_X,
            self.GRIPPER_HOME_Y,
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
    node = MainControllerNode()

    parser = build_parser()
    parsed_args = parser.parse_args(args)

    try:
        if parsed_args.command is None:
            # 노드가 살아있으면서 명령을 대기하도록 설정
            rclpy.spin(node)
        else:
            run_command(node, parsed_args)
    finally:
        node.destroy_node()
        rclpy.shutdown()


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
    pick_place_parser.add_argument('--pick-z', type=float, default=50.1)
    pick_place_parser.add_argument('--chip-z', type=float, default=None)
    pick_place_parser.add_argument('--place-x', type=float, default=0.0)
    pick_place_parser.add_argument('--place-y', type=float, default=0.0)
    pick_place_parser.add_argument('--place-z', type=float, default=55.1)
    pick_place_parser.add_argument('--safe-z', type=float, default=100.0)
    pick_place_parser.add_argument('--contact-z', type=float, default=None)
    pick_place_parser.add_argument('--settle-sec', type=float, default=None)

    three_chip_parser = subparsers.add_parser('three_chip_demo')
    three_chip_parser.add_argument('--safe-z', type=float, default=100.0)
    three_chip_parser.add_argument('--contact-z', type=float, default=50.1)
    three_chip_parser.add_argument('--settle-sec', type=float, default=None)

    subparsers.add_parser('demo')

    return parser


def run_command(node, args):
    time.sleep(0.5)

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
        node.run_pick_place_demo(
            pick_x=args.pick_x,
            pick_y=args.pick_y,
            pick_z=args.pick_z,
            chip_z=args.chip_z,
            place_x=args.place_x,
            place_y=args.place_y,
            place_z=args.place_z,
            safe_z=args.safe_z,
            contact_z=args.contact_z,
            settle_sec=args.settle_sec,
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

if __name__ == '__main__':
    main()
