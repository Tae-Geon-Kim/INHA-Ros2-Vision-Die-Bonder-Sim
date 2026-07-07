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
  DESTINATION share/${PROJECT_NAME}
)

# launch 폴더 안에 있는 파일들도 잊지 말고 같이 빌드(설치)해 달라는 명령어입니다.
install(DIRECTORY
  launch
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
