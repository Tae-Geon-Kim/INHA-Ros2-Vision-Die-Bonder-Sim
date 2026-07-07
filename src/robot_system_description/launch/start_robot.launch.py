import os
from launch import LaunchDescription
from launch.actions import ExecuteProcess

def generate_launch_description():
    # 1. 현재 시스템의 환경 변수 복사하기
    gazebo_env = dict(os.environ)
    
    # 2. 3D 원본 파일이 있는 src 폴더 경로 계산
    ws_src_path = os.path.expanduser('~/colcon_ws/src')
    
    # 3. 기존 경로가 있다면 그 앞에 우리 경로를 붙여주고(Append), 없으면 새로 지정
    if 'IGN_GAZEBO_RESOURCE_PATH' in gazebo_env:
        gazebo_env['IGN_GAZEBO_RESOURCE_PATH'] = f"{ws_src_path}:{gazebo_env['IGN_GAZEBO_RESOURCE_PATH']}"
    else:
        gazebo_env['IGN_GAZEBO_RESOURCE_PATH'] = ws_src_path

    return LaunchDescription([
        # 가제보 프로세스를 켤 때, 위에서 만든 환경 변수(gazebo_env)를 직접 주입합니다. (타이밍 이슈 해결)
        ExecuteProcess(
            cmd=['ign', 'gazebo', 'empty.sdf'],
            env=gazebo_env,
            output='screen'
        ),
        
        # 로봇 소환 (워크스페이스 기준 경로 단단히 고정)
        ExecuteProcess(
            cmd=['ros2', 'run', 'ros_gz_sim', 'create', 
                 '-file', 'src/robot_system_description/urdf/robot_system_compiled.urdf', 
                 '-name', 'robot_system', 
                 '-z', '0.05'],
            cwd=os.path.expanduser('~/colcon_ws'),
            output='screen'
        ),
        
        # RQT 창 1번 (Micro 카메라 4대 배치용)
        ExecuteProcess(
            cmd=['rqt'],
            output='screen'
        ),
        
        # RQT 창 2번 (Macro 카메라 1대 전용)
        ExecuteProcess(
            cmd=['rqt'],
            output='screen'
        )
    ])
    