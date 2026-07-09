cmake_minimum_required(VERSION 3.8)
project(robot_system_description)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)

# meshes, urdf, materials, launch, worlds 폴더를 ROS 2가 인식할 수 있게 설치합니다.
install(DIRECTORY
  meshes
  urdf
  materials
  launch
  worlds
  DESTINATION share/${PROJECT_NAME}
)

foreach(script_name
  die_bonder_commander.py
  send_target_pose.py
)
  if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/launch/${script_name}")
    install(PROGRAMS
      "launch/${script_name}"
      DESTINATION lib/${PROJECT_NAME}
    )
  endif()
endforeach()

ament_package()
