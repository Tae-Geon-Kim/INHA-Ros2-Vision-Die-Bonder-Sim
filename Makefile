SHELL := /bin/bash

ROS_SETUP ?= /opt/ros/humble/setup.bash
GAZEBO_ENV := IGN_IP=127.0.0.1 GZ_IP=127.0.0.1 IGN_PARTITION=inha_die_bonder GZ_PARTITION=inha_die_bonder
GAZEBO_RENDER_MODE ?= auto
GAZEBO_RENDER_ENGINE ?= ogre
GAZEBO_GPU_ADAPTER ?=

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
VISION_REFERENCE_DIR ?= $(CURDIR)/src/robot_system_description/test_images/vision_references
VISION_PLACE_REFERENCE ?= place_empty
VISION_MAX_MICRO_ITERATIONS ?= 20
VISION_REQUEST_TIMEOUT_SEC ?= 45.0
VISION_SETTLE_SEC ?= 0.25
VISION_STACK_SETTLE_SEC ?= 0.25
VISION_MOTION_TIMEOUT_SEC ?= 60.0
VISION_XY_THETA_TOLERANCE_UM ?= 1.0
VISION_Z_TOLERANCE_UM ?= 100.0
VISION_BRIDGE_STARTUP_SEC ?= 3.0
VISION_OPENCV_THREADS ?= 2
MACRO_PIXEL_SIZE_X ?= 0.075
MACRO_PIXEL_SIZE_Y ?= 0.075
MICRO_PIXEL_SIZE_X ?= 0.0068
MICRO_PIXEL_SIZE_Y ?= 0.0068
VISION_AXIS_SIGN_X ?= -1.0
VISION_AXIS_SIGN_Y ?= 1.0

MOVE_X ?= 0
MOVE_Y ?= 0
MOVE_Z ?= 100
MOVE_THETA_DEG ?= 0

CHIP_X ?= 500
CHIP_Y ?= 400

PICK_X ?= 500
PICK_Y ?= 400
STACK_COUNT ?= 4
STACK_FIRST_PICK_Y ?= 400
STACK_LAST_PICK_Y ?= -400
STACK_FIRST_CHIP_THETA_DEG ?= 0
STACK_LAST_CHIP_THETA_DEG ?= 45
SUBSTRATE_X ?= 140
SUBSTRATE_Y ?= 0
PLACE_X ?= $(SUBSTRATE_X)
PLACE_Y ?= $(SUBSTRATE_Y)
DEMO_SAFE_Z ?= 100
CONTACT_Z ?= 50.1
SETTLE_SEC ?= 3.0

.PHONY: help \
	install-backend install-frontend check-env db-tunnel init-db register-user backend frontend \
	ros-build gazebo gazebo-camera joint-bridge vision-bridge vision-bridge-auto \
	gazebo-render-check \
	model-list safe chip-reset demo range-demo vision-ref-pick vision-ref-place-empty \
	vision-ref-place-stacked vision-ref-all vision-demo vision-stack-demo

.NOTPARALLEL: vision-ref-all

help: ## Show available make targets.
	@awk 'BEGIN {FS = ":.*##"; printf "\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-28s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\nExamples:\n"
	@printf "  make ros-build\n"
	@printf "  make gazebo-render-check\n"
	@printf "  make gazebo-camera\n"
	@printf "  make gazebo-camera GAZEBO_RENDER_MODE=software\n"
	@printf "  make joint-bridge STACK_COUNT=4\n"
	@printf "  make vision-bridge VISION_PROCESS=pick\n"
	@printf "  make vision-ref-all\n"
	@printf "  make vision-demo VISION_PLACE_REFERENCE=place_empty\n"
	@printf "  make gazebo-camera STACK_COUNT=4\n"
	@printf "  make vision-stack-demo STACK_COUNT=4\n"
	@printf "  make demo PICK_X=500 PICK_Y=400 PLACE_X=140 PLACE_Y=0\n\n"

define run_with_reference_vision_bridge
	@export $(GAZEBO_ENV); \
	source $(ROS_SETUP); \
	source install/setup.bash; \
	vision_session="make_$${BASHPID}"; \
	vision_request_topic="/vision/$${vision_session}/alignment_request"; \
	vision_result_topic="/vision/$${vision_session}/alignment_result"; \
	export ROBOT_CONTROL_VISION_REQUEST_TOPIC="$$vision_request_topic"; \
	export ROBOT_CONTROL_VISION_RESULT_TOPIC="$$vision_result_topic"; \
	setsid ros2 launch vision_core vision_alignment_bridge.launch.py \
		request_only:=true direct_gz_images:=true auto_command:=false \
		request_topic:="$$vision_request_topic" \
		result_topic:="$$vision_result_topic" \
		request_timeout_sec:=$(VISION_REQUEST_TIMEOUT_SEC) \
		opencv_threads:=$(VISION_OPENCV_THREADS) \
		reference_dir:="$(VISION_REFERENCE_DIR)" \
		macro_pixel_size_x_mm:=$(MACRO_PIXEL_SIZE_X) \
		macro_pixel_size_y_mm:=$(MACRO_PIXEL_SIZE_Y) \
		micro_pixel_size_x_mm:=$(MICRO_PIXEL_SIZE_X) \
		micro_pixel_size_y_mm:=$(MICRO_PIXEL_SIZE_Y) \
		macro_axis_sign_x:=$(VISION_AXIS_SIGN_X) macro_axis_sign_y:=$(VISION_AXIS_SIGN_Y) \
		micro_axis_sign_x:=$(VISION_AXIS_SIGN_X) micro_axis_sign_y:=$(VISION_AXIS_SIGN_Y) & \
	vision_pid=$$!; \
	trap 'kill -TERM -- "-$$vision_pid" 2>/dev/null || true; wait "$$vision_pid" 2>/dev/null || true' EXIT; \
	sleep $(VISION_BRIDGE_STARTUP_SEC); \
	$(1); \
	status=$$?; \
	exit $$status
endef

define configure_gazebo_rendering
	render_mode="$(GAZEBO_RENDER_MODE)"; \
	render_engine="$(GAZEBO_RENDER_ENGINE)"; \
	gpu_backend=""; \
	gpu_adapter="$(GAZEBO_GPU_ADAPTER)"; \
	case "$$render_mode" in auto|gpu|software) ;; *) \
		echo "GAZEBO_RENDER_MODE must be auto, gpu, or software: $$render_mode"; exit 2 ;; \
	esac; \
	if [ "$$render_mode" != "software" ]; then \
		if [ -e /dev/dxg ] && [ -f /usr/lib/x86_64-linux-gnu/dri/d3d12_dri.so ]; then \
			gpu_backend="WSLg-D3D12"; \
			if [ -z "$$gpu_adapter" ] && command -v powershell.exe >/dev/null 2>&1; then \
				gpu_names="$$(powershell.exe -NoProfile -NonInteractive -Command "Get-CimInstance Win32_VideoController | ForEach-Object { \$$_.Name }" 2>/dev/null | tr -d '\r')"; \
				gpu_count="$$(printf '%s\n' "$$gpu_names" | awk 'NF { count++ } END { print count + 0 }')"; \
				if [ "$$gpu_count" -eq 1 ]; then \
					case "$$gpu_names" in *Intel*) gpu_adapter="Intel" ;; *NVIDIA*) gpu_adapter="NVIDIA" ;; *AMD*|*Radeon*) gpu_adapter="AMD" ;; esac; \
				fi; \
			fi; \
			export GALLIUM_DRIVER=d3d12; \
			if [ -n "$$gpu_adapter" ]; then export MESA_D3D12_DEFAULT_ADAPTER_NAME="$$gpu_adapter"; fi; \
		elif compgen -G '/dev/dri/renderD*' >/dev/null || compgen -G '/dev/nvidia[0-9]*' >/dev/null; then \
			gpu_backend="native-DRI"; \
		fi; \
	fi; \
	if [ "$$render_mode" = "software" ] || [ -z "$$gpu_backend" ]; then \
		if [ "$$render_mode" = "gpu" ]; then \
			echo "Gazebo GPU mode requested, but no supported GPU device was detected."; exit 2; \
		fi; \
		gpu_backend="software-fallback"; \
		export LIBGL_ALWAYS_SOFTWARE=1; \
		unset GALLIUM_DRIVER MESA_D3D12_DEFAULT_ADAPTER_NAME; \
	else \
		unset LIBGL_ALWAYS_SOFTWARE; \
	fi; \
	export GAZEBO_SELECTED_RENDER_ENGINE="$$render_engine"; \
	printf '[Gazebo render] mode=%s backend=%s adapter=%s engine=%s\n' \
		"$$render_mode" "$$gpu_backend" "$${gpu_adapter:-default}" "$$render_engine"
endef

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

gazebo-render-check: ## Show the Gazebo GPU / software renderer selected for this PC.
	@$(call configure_gazebo_rendering); \
	if command -v glxinfo >/dev/null 2>&1; then \
		glxinfo -B 2>/dev/null | awk -F: '/OpenGL renderer string/ { sub(/^[[:space:]]+/, "", $$2); print "[OpenGL renderer] " $$2 }'; \
	else \
		printf '%s\n' '[OpenGL renderer] glxinfo unavailable; device-based selection shown above.'; \
	fi

gazebo: ## Run Gazebo without the camera-specific launch.
	@$(call configure_gazebo_rendering); \
	export $(GAZEBO_ENV); \
	source $(ROS_SETUP); \
	source install/setup.bash; \
	ros2 launch robot_system_description gazebo.launch.py \
		stack_count:=$(STACK_COUNT) render_engine:="$$GAZEBO_SELECTED_RENDER_ENGINE"

gazebo-camera: ## Run Gazebo with camera topics for vision alignment.
	@$(call configure_gazebo_rendering); \
	export $(GAZEBO_ENV); \
	source $(ROS_SETUP); \
	source install/setup.bash; \
	ros2 launch robot_system_description gazebo_camera.launch.py \
		stack_count:=$(STACK_COUNT) render_engine:="$$GAZEBO_SELECTED_RENDER_ENGINE"

joint-bridge: ## Run local joint command bridge.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 launch vision_core joint_bridge.launch.py stack_count:=$(STACK_COUNT)

vision-bridge: ## Run local OpenCV camera vision alignment bridge.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 launch vision_core vision_alignment_bridge.launch.py alignment_process:=$(VISION_PROCESS) place_mode:=$(PLACE_MODE) auto_command:=$(AUTO_COMMAND) backend_log_url:=$(BACKEND_LOG_URL) history_id:=$(HISTORY_ID) pixel_size_x_mm:=$(PIXEL_SIZE_X) pixel_size_y_mm:=$(PIXEL_SIZE_Y) opencv_threads:=$(VISION_OPENCV_THREADS)

vision-bridge-auto: ## Run local vision alignment bridge and publish correction commands.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 launch vision_core vision_alignment_bridge.launch.py alignment_process:=$(VISION_PROCESS) place_mode:=$(PLACE_MODE) auto_command:=true backend_log_url:=$(BACKEND_LOG_URL) history_id:=$(HISTORY_ID) pixel_size_x_mm:=$(PIXEL_SIZE_X) pixel_size_y_mm:=$(PIXEL_SIZE_Y) opencv_threads:=$(VISION_OPENCV_THREADS)

model-list: ## List Ignition/Gazebo models locally.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ign model --list

safe: ## Move robot to a safe pose locally.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 run robot_control_pkg main_controller move $(MOVE_X) $(MOVE_Y) $(MOVE_Z) --theta-deg $(MOVE_THETA_DEG)

chip-reset: ## Reset chip pose locally.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 run robot_control_pkg main_controller chip_reset $(CHIP_X) $(CHIP_Y)

demo: ## Run local pick/place demo.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 run robot_control_pkg main_controller pick_place_demo --pick-x $(PICK_X) --pick-y $(PICK_Y) --place-x $(PLACE_X) --place-y $(PLACE_Y) --safe-z $(DEMO_SAFE_Z) --contact-z $(CONTACT_Z) --settle-sec $(SETTLE_SEC)

vision-ref-pick: ## Capture one macro and four micro pick reference images.
	$(call run_with_reference_vision_bridge,ros2 run robot_control_pkg main_controller vision_reference_capture pick --settle-sec $(SETTLE_SEC) --vision-timeout-sec $(VISION_REQUEST_TIMEOUT_SEC) --motion-timeout-sec $(VISION_MOTION_TIMEOUT_SEC))

vision-ref-place-empty: ## Capture the empty-substrate place reference set.
	$(call run_with_reference_vision_bridge,ros2 run robot_control_pkg main_controller vision_reference_capture place_empty --settle-sec $(SETTLE_SEC) --vision-timeout-sec $(VISION_REQUEST_TIMEOUT_SEC) --motion-timeout-sec $(VISION_MOTION_TIMEOUT_SEC))

vision-ref-place-stacked: ## Capture the substrate-with-chip place reference set.
	$(call run_with_reference_vision_bridge,ros2 run robot_control_pkg main_controller vision_reference_capture place_stacked --settle-sec $(SETTLE_SEC) --vision-timeout-sec $(VISION_REQUEST_TIMEOUT_SEC) --motion-timeout-sec $(VISION_MOTION_TIMEOUT_SEC))

vision-ref-all: vision-ref-pick vision-ref-place-empty vision-ref-place-stacked ## Capture all 15 reference images.

vision-demo: ## Run vision-aligned pick/place without changing the original demo.
	$(call run_with_reference_vision_bridge,ros2 run robot_control_pkg main_controller vision_pick_place_demo --pick-x $(PICK_X) --pick-y $(PICK_Y) --place-x $(PLACE_X) --place-y $(PLACE_Y) --contact-z $(CONTACT_Z) --place-reference $(VISION_PLACE_REFERENCE) --max-micro-iterations $(VISION_MAX_MICRO_ITERATIONS) --settle-sec $(SETTLE_SEC) --vision-settle-sec $(VISION_SETTLE_SEC) --vision-timeout-sec $(VISION_REQUEST_TIMEOUT_SEC) --motion-timeout-sec $(VISION_MOTION_TIMEOUT_SEC) --xy-theta-tolerance-um $(VISION_XY_THETA_TOLERANCE_UM) --z-tolerance-um $(VISION_Z_TOLERANCE_UM))

vision-stack-demo: ## Vision-align and stack 2-16 chips (default 4) using physical contact.
	$(call run_with_reference_vision_bridge,ros2 run robot_control_pkg main_controller vision_stack_demo --stack-count $(STACK_COUNT) --pick-x $(PICK_X) --first-pick-y $(STACK_FIRST_PICK_Y) --last-pick-y $(STACK_LAST_PICK_Y) --first-chip-theta-deg $(STACK_FIRST_CHIP_THETA_DEG) --last-chip-theta-deg $(STACK_LAST_CHIP_THETA_DEG) --place-x $(PLACE_X) --place-y $(PLACE_Y) --contact-z $(CONTACT_Z) --max-micro-iterations $(VISION_MAX_MICRO_ITERATIONS) --settle-sec $(VISION_STACK_SETTLE_SEC) --vision-settle-sec $(VISION_SETTLE_SEC) --vision-timeout-sec $(VISION_REQUEST_TIMEOUT_SEC) --motion-timeout-sec $(VISION_MOTION_TIMEOUT_SEC) --xy-theta-tolerance-um $(VISION_XY_THETA_TOLERANCE_UM) --z-tolerance-um $(VISION_Z_TOLERANCE_UM))

range-demo: ## Run local joint range demo.
	export $(GAZEBO_ENV) && source $(ROS_SETUP) && source install/setup.bash && ros2 run robot_control_pkg main_controller range_demo --settle-sec $(SETTLE_SEC)
