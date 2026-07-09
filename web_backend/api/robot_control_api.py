import os
import shlex
import signal
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from web_backend.schemas.common_schemas import CommonResponse


router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEMO_COMMAND = (
    "bash -lc '"
    "source /opt/ros/humble/setup.bash && "
    "source install/setup.bash && "
    "ros2 run robot_control_pkg main_controller pick_place_demo"
    "'"
)

_demo_process: subprocess.Popen | None = None


def _demo_command() -> str:
    return os.environ.get("ROBOT_DEMO_COMMAND", DEFAULT_DEMO_COMMAND)


def _process_snapshot():
    if _demo_process is None:
        return {
            "running": False,
            "pid": None,
            "returncode": None,
            "command": _demo_command(),
        }

    returncode = _demo_process.poll()
    return {
        "running": returncode is None,
        "pid": _demo_process.pid,
        "returncode": returncode,
        "command": _demo_command(),
    }


@router.get(
    "/demo/status",
    response_model=CommonResponse,
    status_code=status.HTTP_200_OK,
    summary="[로봇 제어] Gazebo 데모 실행 상태 조회",
)
async def get_demo_status():
    return CommonResponse(data=_process_snapshot())


@router.post(
    "/demo/start",
    response_model=CommonResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="[로봇 제어] Gazebo Pick/Place 데모 시작",
    description=(
        "FastAPI가 실행 중인 환경에서 ROS2 main_controller pick_place_demo 명령을 "
        "별도 프로세스로 실행합니다. Gazebo와 ROS bridge가 먼저 켜져 있어야 합니다."
    ),
)
async def start_demo():
    global _demo_process

    snapshot = _process_snapshot()
    if snapshot["running"]:
        return CommonResponse(message="Gazebo 데모가 이미 실행 중입니다.", data=snapshot)

    command_text = _demo_command()
    command = shlex.split(command_text)
    log_dir = PROJECT_ROOT / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "robot_demo.log"

    try:
        with log_path.open("ab") as log_file:
            _demo_process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"로봇 데모 명령을 찾을 수 없습니다: {command[0]}. "
                "백엔드를 실행한 터미널에서 ROS2/workspace 환경을 source 했는지 확인하세요."
            ),
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"로봇 데모를 시작하지 못했습니다: {exc}",
        ) from exc

    return CommonResponse(
        message="Gazebo Pick/Place 데모를 시작했습니다.",
        data={**_process_snapshot(), "log_path": str(log_path)},
    )


@router.post(
    "/demo/stop",
    response_model=CommonResponse,
    status_code=status.HTTP_200_OK,
    summary="[로봇 제어] Gazebo 데모 중지",
)
async def stop_demo():
    if _demo_process is None or _demo_process.poll() is not None:
        return CommonResponse(message="실행 중인 Gazebo 데모가 없습니다.", data=_process_snapshot())

    os.killpg(_demo_process.pid, signal.SIGTERM)
    return CommonResponse(message="Gazebo 데모 중지 신호를 보냈습니다.", data=_process_snapshot())
