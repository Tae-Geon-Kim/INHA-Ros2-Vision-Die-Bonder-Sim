import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Pose

class MainControllerNode(Node):
    def __init__(self):
        super().__init__('main_controller_node')
        
        # 로봇 하드웨어 명령 퍼블리셔 (Command topic: /robot/command_pose)
        self.cmd_pub = self.create_publisher(Pose, '/robot/command_pose', 10)
        
        # 그리퍼 중심점 기준 카메라의 상대 위치 오프셋
        self.GRIPPER_TO_CAMERA_DX = 50.0  
        self.GRIPPER_TO_CAMERA_DY = 20.0  
        
        # 수직 방향(Z) 제어 높이
        self.HOVER_Z = 50.0   # 이동 시 충돌 방지용 공중 높이
        self.PRESS_Z = 0.0    # 칩 픽업 및 본딩 시 접촉 높이

        # 상태 추적 변수 (로봇의 현재 x, y 좌표를 추적)
        self.last_sent_x = 0.0
        self.last_sent_y = 0.0

    # 1. 통합 이동 전송 및 위치 기록 함수
    def publish_move(self, x, y, z):
        """
        로봇에게 이동 명령을 쏘는 동시에, 현재 SW에 로봇의 XY 위치를 저장함.
        이를 통해 'execute_z_press' 명령 시 정확한 위치에서 하강이 가능함.
        """
        self.last_sent_x = x
        self.last_sent_y = y
        
        msg = Pose()
        msg.position.x = float(x)
        msg.position.y = float(y)
        msg.position.z = float(z)
        
        # 하드웨어로 명령 전송
        self.cmd_pub.publish(msg)
        self.get_logger().debug(f' Command Sent: X={x}, Y={y}, Z={z}')

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

def main(args=None):
    rclpy.init(args=args)
    node = MainControllerNode()
    
    # 노드가 살아있으면서 명령을 대기하도록 설정
    rclpy.spin(node)
    
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()