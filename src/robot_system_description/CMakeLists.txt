cmake_minimum_required(VERSION 3.8)
project(robot_system_description)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)

# meshes와 urdf 폴더를 ROS 2가 인식할 수 있게 설치(Install)합니다.
install(DIRECTORY
  meshes
  urdf
  materials
  launch
  DESTINATION share/${PROJECT_NAME}
)

install(PROGRAMS
  launch/die_bonder_commander.py
  launch/send_target_pose.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
