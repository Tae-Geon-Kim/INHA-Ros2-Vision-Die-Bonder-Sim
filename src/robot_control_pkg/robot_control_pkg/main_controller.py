import argparse
import json
import math
import os
from pathlib import Path
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Pose


STATE_PATH = Path(os.environ.get("ROBOT_CONTROL_STATE", "/tmp/robot_control_pose_state.json"))
DEFAULT_STATE = {"x": 0.0, "y": 0.0, "z": 50.0, "theta_deg": 0.0}


def load_state():
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {
            "x": float(data.get("x", DEFAULT_STATE["x"])),
            "y": float(data.get("y", DEFAULT_STATE["y"])),
            "z": float(data.get("z", DEFAULT_STATE["z"])),
            "theta_deg": float(data.get("theta_deg", DEFAULT_STATE["theta_deg"])),
        }
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return DEFAULT_STATE.copy()


def save_state(x, y, z, theta_deg):
    STATE_PATH.write_text(
        json.dumps({
            "x": float(x),
            "y": float(y),
            "z": float(z),
            "theta_deg": float(theta_deg),
        }),
        encoding="utf-8",
    )


def set_pose_yaw(msg, theta_deg):
    theta_rad = math.radians(theta_deg)
    msg.orientation.z = math.sin(theta_rad / 2.0)
    msg.orientation.w = math.cos(theta_rad / 2.0)


class MainControllerNode(Node):
    def __init__(self):
        super().__init__('main_controller_node')
        
        # 로봇 하드웨어 명령 퍼블리셔 (Command topic: /robot/command_pose)
        self.cmd_pub = self.create_publisher(Pose, '/robot/command_pose', 10)
        
        # 그리퍼 중심점 기준 카메라의 상대 위치 오프셋
        self.GRIPPER_TO_CAMERA_DX = 50.0  
        self.GRIPPER_TO_CAMERA_DY = 20.0  
        
        # 수직 방향(Z) 제어 높이
        self.HOVER_Z = 50.0   # 이동 시 충돌 방지용 공중 높이(mm)
        self.PRESS_Z = 5.0    # 칩 픽업 및 본딩 시 접촉 높이(mm)
        self.MOVE_SETTLE_SEC = 3.5

        # 상태 추적 변수 (로봇의 현재 x, y 좌표를 추적)
        state = load_state()
        self.last_sent_x = state["x"]
        self.last_sent_y = state["y"]
        self.last_sent_z = state["z"]
        self.last_sent_theta_deg = state["theta_deg"]

    # 1. 통합 이동 전송 및 위치 기록 함수
    def publish_move(self, x, y, z, theta_deg=None):
        """
        로봇에게 이동 명령을 쏘는 동시에, 현재 SW에 로봇의 XY/Z/theta 위치를 저장함.
        이를 통해 'execute_z_press' 명령 시 정확한 위치에서 하강이 가능함.
        """
        target_theta = self.last_sent_theta_deg if theta_deg is None else theta_deg
        self.last_sent_x = x
        self.last_sent_y = y
        self.last_sent_z = z
        self.last_sent_theta_deg = target_theta
        save_state(x, y, z, target_theta)
        
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

    def vacuum_on(self):
        self.get_logger().info('vacuum_on: 현재 데모에서는 흡착 동작을 로그로만 처리합니다.')

    def vacuum_off(self):
        self.get_logger().info('vacuum_off: 현재 데모에서는 릴리즈 동작을 로그로만 처리합니다.')

    def run_pick_place_demo(
        self,
        pick_x=0.0,
        pick_y=0.0,
        place_x=150.0,
        place_y=0.0,
        safe_z=None,
        contact_z=None,
        settle_sec=None,
    ):

        """
        칩 기준 좌표계에서 pick -> lift -> place -> release 흐름을 실행함.
        단위는 mm이며, 실제 흡착/릴리즈는 아직 로그로만 표현함.
        """

        safe_height = self.HOVER_Z if safe_z is None else safe_z
        contact_height = self.PRESS_Z if contact_z is None else contact_z

        self.get_logger().info(
            f'pick_place_demo 시작: pick=({pick_x}, {pick_y})mm, '
            f'place=({place_x}, {place_y})mm, safe_z={safe_height}mm, '
            f'contact_z={contact_height}mm'
        )

        self.get_logger().info('1/8 pick 위치 상공으로 이동')
        self.publish_move(pick_x, pick_y, safe_height)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('2/8 pick 접촉 높이로 하강')
        self.publish_move(pick_x, pick_y, contact_height)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('3/8 칩 흡착')
        self.vacuum_on()
        time.sleep(0.5)

        self.get_logger().info('4/8 pick 위치에서 상승')
        self.publish_move(pick_x, pick_y, safe_height)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('5/8 place 위치 상공으로 이동')
        self.publish_move(place_x, place_y, safe_height)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('6/8 place 접촉 높이로 하강')
        self.publish_move(place_x, place_y, contact_height)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('7/8 칩 릴리즈')
        self.vacuum_off()
        time.sleep(0.5)

        self.get_logger().info('8/8 place 위치에서 상승')
        self.publish_move(place_x, place_y, safe_height)
        self.wait_for_motion(settle_sec)

        self.get_logger().info('pick_place_demo 완료')

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
            (0.0, 0.0, 80.0, 0.0, 'Z 80mm'),
            (0.0, 0.0, 5.0, 0.0, 'Z 5mm'),
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

    camera_parser = subparsers.add_parser('camera_center')
    camera_parser.add_argument('chip_x', type=float)
    camera_parser.add_argument('chip_y', type=float)

    transfer_parser = subparsers.add_parser('transfer')
    transfer_parser.add_argument('x', type=float)
    transfer_parser.add_argument('y', type=float)

    subparsers.add_parser('press')
    subparsers.add_parser('lift')
    subparsers.add_parser('z_demo')

    theta_demo_parser = subparsers.add_parser('theta_demo')
    theta_demo_parser.add_argument('--settle-sec', type=float, default=None)

    joint_demo_parser = subparsers.add_parser('joint_demo')
    joint_demo_parser.add_argument('--settle-sec', type=float, default=None)

    pick_place_parser = subparsers.add_parser('pick_place_demo')
    pick_place_parser.add_argument('--pick-x', type=float, default=0.0)
    pick_place_parser.add_argument('--pick-y', type=float, default=0.0)
    pick_place_parser.add_argument('--place-x', type=float, default=150.0)
    pick_place_parser.add_argument('--place-y', type=float, default=0.0)
    pick_place_parser.add_argument('--safe-z', type=float, default=50.0)
    pick_place_parser.add_argument('--contact-z', type=float, default=5.0)
    pick_place_parser.add_argument('--settle-sec', type=float, default=None)

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
    elif args.command == 'camera_center':
        node.set_camera_center(args.chip_x, args.chip_y)
    elif args.command == 'transfer':
        node.transfer_position(args.x, args.y)
    elif args.command == 'press':
        node.execute_z_press()
    elif args.command == 'lift':
        node.lift_to_safety()
    elif args.command == 'z_demo':
        node.move_z(80.0)
        time.sleep(1.5)
        node.move_z(5.0)
        time.sleep(1.5)
        node.move_z(80.0)
    elif args.command == 'theta_demo':
        node.run_theta_demo(settle_sec=args.settle_sec)
    elif args.command == 'joint_demo':
        node.run_joint_demo(settle_sec=args.settle_sec)
    elif args.command == 'pick_place_demo':
        node.run_pick_place_demo(
            pick_x=args.pick_x,
            pick_y=args.pick_y,
            place_x=args.place_x,
            place_y=args.place_y,
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
