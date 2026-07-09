SHELL := /bin/bash

ROS_SETUP ?= /opt/ros/humble/setup.bash
GAZEBO_ENV := IGN_IP=127.0.0.1 GZ_IP=127.0.0.1 IGN_PARTITION=inha_die_bonder GZ_PARTITION=inha_die_bonder

GPU_USER ?= team05
GPU_HOST ?= 165.246.170.53
LOCAL_DB_PORT ?= 54320
REMOTE_DB_PORT ?= 54320

BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

VISION_PROCESS ?= pick
PLACE_MODE ?= array
AUTO_COMMAND ?= true
BACKEND_LOG_URL ?= http://127.0.0.1:8000/robot-logs/vision-align
HISTORY_ID ?= 0
PIXEL_SIZE_X ?= 1.0
PIXEL_SIZE_Y ?= 1.0

MOVE_X ?= 0
MOVE_Y ?= 0
MOVE_Z ?= 80
MOVE_THETA_DEG ?= 0

CHIP_X ?= 0
CHIP_Y ?= 0

PICK_X ?= 0
PICK_Y ?= 0
PLACE_X ?= 200
PLACE_Y ?= 0
DEMO_SAFE_Z ?= 60
CONTACT_Z ?= 15
SETTLE_SEC ?= 3.0

.PHONY: help \
	install-backend install-frontend check-env db-tunnel init-db register-user backend frontend \
	ros-build gazebo gazebo-camera joint-bridge vision-bridge vision-bridge-auto \
	model-list safe chip-reset demo range-demo

help: ## Show available make targets.
	@awk 'BEGIN {FS = ":.*##"; printf "\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-28s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\nExamples:\n"
	@printf "  make ros-build\n"
	@printf "  make gazebo-camera\n"
	@printf "  make joint-bridge\n"
	@printf "  make vision-bridge VISION_PROCESS=pick\n"
	@printf "  make demo PICK_X=0 PICK_Y=0 PLACE_X=200 PLACE_Y=0\n\n"

.venv/bin/python:
	python3 -m venv .venv

check-env: ## Check that root .env exists.
	@test -f .env || (echo "Missing .env. Copy .env.example to .env and fill values first."; exit 1)

install-backend: .venv/bin/python ## Install Python backend dependencies.
	$(PIP) install -r requirements.txt

install-frontend: ## Install frontend dependencies.
	cd web_frontend && npm ci

db-tunnel: ## Open SSH tunnel to the shared PostgreSQL server.
	ssh -N -L $(LOCAL_DB_PORT):127.0.0.1:$(REMOTE_DB_PORT) $(GPU_USER)@$(GPU_HOST)

init-db: check-env ## Create backend database tables.
	$(PYTHON) -m web_backend.db.init_db

register-user: check-env ## Sync initial admin user from .env.
	$(PYTHON) -m web_backend.db.register_user

backend: check-env ## Run FastAPI backend.
	$(PYTHON) -m uvicorn web_backend.main:app --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

frontend: ## Run Vite frontend.
	cd web_frontend && npm run dev

ros-build: ## Build ROS2 workspace locally.
	source $(ROS_SETUP) && colcon build --symlink-install

gazebo: ## Run Gazebo without the camera-specific launch.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 launch robot_system_description gazebo.launch.py

gazebo-camera: ## Run Gazebo with camera topics for vision alignment.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 launch robot_system_description gazebo_camera.launch.py

joint-bridge: ## Run local joint command bridge.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 launch vision_core joint_bridge.launch.py

vision-bridge: ## Run local OpenCV camera vision alignment bridge.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 launch vision_core vision_alignment_bridge.launch.py alignment_process:=$(VISION_PROCESS) place_mode:=$(PLACE_MODE) auto_command:=$(AUTO_COMMAND) backend_log_url:=$(BACKEND_LOG_URL) history_id:=$(HISTORY_ID) pixel_size_x_mm:=$(PIXEL_SIZE_X) pixel_size_y_mm:=$(PIXEL_SIZE_Y)

vision-bridge-auto: ## Run local vision alignment bridge and publish correction commands.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 launch vision_core vision_alignment_bridge.launch.py alignment_process:=$(VISION_PROCESS) place_mode:=$(PLACE_MODE) auto_command:=true backend_log_url:=$(BACKEND_LOG_URL) history_id:=$(HISTORY_ID) pixel_size_x_mm:=$(PIXEL_SIZE_X) pixel_size_y_mm:=$(PIXEL_SIZE_Y)

model-list: ## List Ignition/Gazebo models locally.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ign model --list

safe: ## Move robot to a safe pose locally.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 run robot_control_pkg main_controller move $(MOVE_X) $(MOVE_Y) $(MOVE_Z) --theta-deg $(MOVE_THETA_DEG)

chip-reset: ## Reset chip pose locally.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 run robot_control_pkg main_controller chip_reset $(CHIP_X) $(CHIP_Y)

demo: ## Run local pick/place demo.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 run robot_control_pkg main_controller pick_place_demo --pick-x $(PICK_X) --pick-y $(PICK_Y) --place-x $(PLACE_X) --place-y $(PLACE_Y) --safe-z $(DEMO_SAFE_Z) --contact-z $(CONTACT_Z) --settle-sec $(SETTLE_SEC)

range-demo: ## Run local joint range demo.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 run robot_control_pkg main_controller range_demo --settle-sec $(SETTLE_SEC)
