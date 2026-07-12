import asyncio
import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from web_backend.schemas.common_schemas import CommonResponse
from web_backend.schemas.robot_control_schemas import (
    DEFAULT_STACK_COUNT,
    DemoStartRequest,
)


router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "log"

DEFAULT_GAZEBO_COMMAND = "make gazebo-camera"
DEFAULT_JOINT_BRIDGE_COMMAND = "make joint-bridge"
DEFAULT_DEMO_COMMAND = "make vision-stack-demo"
DEFAULT_GAZEBO_READY_TIMEOUT_SEC = 60.0

GAZEBO_TRANSPORT_ENV = {
    "IGN_IP": "127.0.0.1",
    "GZ_IP": "127.0.0.1",
    "IGN_PARTITION": "inha_die_bonder",
    "GZ_PARTITION": "inha_die_bonder",
}

_gazebo_process: subprocess.Popen | None = None
_joint_bridge_process: subprocess.Popen | None = None
_demo_process: subprocess.Popen | None = None
_demo_stack_count = DEFAULT_STACK_COUNT
_process_lock = asyncio.Lock()


def _command(environment_name: str, default: str) -> str:
    return os.environ.get(environment_name, default)


def _gazebo_command() -> str:
    return _command("ROBOT_GAZEBO_COMMAND", DEFAULT_GAZEBO_COMMAND)


def _joint_bridge_command() -> str:
    return _command("ROBOT_JOINT_BRIDGE_COMMAND", DEFAULT_JOINT_BRIDGE_COMMAND)


def _demo_command() -> str:
    return _command("ROBOT_DEMO_COMMAND", DEFAULT_DEMO_COMMAND)


def _is_running(process: subprocess.Popen | None) -> bool:
    return process is not None and process.poll() is None


def _command_argv(command_text: str, stack_count: int) -> list[str]:
    command = shlex.split(command_text)
    if not command:
        raise ValueError("실행 명령이 비어 있습니다.")

    # An explicit make assignment has precedence over Makefile defaults and
    # makes the effective value visible in the process command line. The same
    # value is also kept in the environment for custom command overrides.
    if Path(command[0]).name == "make":
        assignment = f"STACK_COUNT={stack_count}"
        replaced = False
        for index, part in enumerate(command[1:], start=1):
            if part.startswith("STACK_COUNT="):
                command[index] = assignment
                replaced = True
        if not replaced:
            command.append(assignment)
    return command


def _display_command(command_text: str) -> str:
    try:
        return shlex.join(_command_argv(command_text, _demo_stack_count))
    except ValueError:
        return command_text


def _process_data(process: subprocess.Popen | None, command: str) -> dict:
    if process is None:
        return {
            "running": False,
            "pid": None,
            "returncode": None,
            "command": command,
        }

    returncode = process.poll()
    return {
        "running": returncode is None,
        "pid": process.pid,
        "returncode": returncode,
        "command": command,
    }


def _process_snapshot() -> dict:
    gazebo = _process_data(
        _gazebo_process,
        _display_command(_gazebo_command()),
    )
    joint_bridge = _process_data(
        _joint_bridge_process,
        _display_command(_joint_bridge_command()),
    )
    demo = _process_data(_demo_process, _display_command(_demo_command()))

    return {
        # Keep the original top-level fields for existing API consumers.
        "running": demo["running"],
        "pid": demo["pid"],
        "returncode": demo["returncode"],
        "command": demo["command"],
        "stack_count": _demo_stack_count,
        "infrastructure_running": (
            gazebo["running"] and joint_bridge["running"]
        ),
        "processes": {
            "gazebo": gazebo,
            "joint_bridge": joint_bridge,
            "demo": demo,
        },
        "log_paths": {
            "gazebo": str(LOG_DIR / "web_gazebo.log"),
            "joint_bridge": str(LOG_DIR / "web_joint_bridge.log"),
            "demo": str(LOG_DIR / "robot_demo.log"),
        },
    }


def _process_environment(stack_count: int) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(GAZEBO_TRANSPORT_ENV)
    environment["STACK_COUNT"] = str(stack_count)
    return environment


def _spawn_process(
    command_text: str,
    log_name: str,
    stack_count: int,
) -> subprocess.Popen:
    command = _command_argv(command_text, stack_count)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / log_name
    with log_path.open("ab") as log_file:
        return subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=_process_environment(stack_count),
        )


def _terminate_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return

    process_group_id = process.pid
    process.poll()
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return

    for stop_signal, timeout_sec in (
        (signal.SIGINT, 5.0),
        (signal.SIGTERM, 3.0),
        (signal.SIGKILL, 2.0),
    ):
        try:
            os.killpg(process_group_id, stop_signal)
        except ProcessLookupError:
            return
        if _wait_for_process_group_exit(
            process,
            process_group_id,
            timeout_sec,
        ):
            return


def _wait_for_process_group_exit(
    process: subprocess.Popen,
    process_group_id: int,
    timeout_sec: float,
) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        process.poll()
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        time.sleep(0.05)

    process.poll()
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _any_process_running() -> bool:
    return any(
        _is_running(process)
        for process in (_gazebo_process, _joint_bridge_process, _demo_process)
    )


def _stop_all_processes_sync() -> None:
    global _gazebo_process, _joint_bridge_process, _demo_process

    # Stop command producers before disconnecting the bridge and simulator.
    _terminate_process(_demo_process)
    _terminate_process(_joint_bridge_process)
    _terminate_process(_gazebo_process)
    _demo_process = None
    _joint_bridge_process = None
    _gazebo_process = None


def _manual_simulator_running() -> bool:
    """Return true when a ROS/Gazebo stack exists outside this manager."""

    if _is_running(_gazebo_process):
        return False

    try:
        result = subprocess.run(
            [
                "pgrep",
                "-u",
                str(os.getuid()),
                "-f",
                (
                    "ign gazebo|ign-gazebo-server|gazebo_camera.launch.py|"
                    "joint_bridge.launch.py|vision_stack_demo"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _expected_model_names(stack_count: int) -> tuple[str, ...]:
    chip_names = tuple(
        "check_chip" if index == 1 else f"check_chip_{index}"
        for index in range(1, stack_count + 1)
    )
    return ("robot_system", *chip_names)


def _gazebo_models_ready(stack_count: int) -> bool:
    environment = os.environ.copy()
    environment.update(GAZEBO_TRANSPORT_ENV)
    try:
        result = subprocess.run(
            ["ign", "model", "--list"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False

    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        return False

    return all(
        re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(model_name)}(?![A-Za-z0-9_])",
            output,
        )
        for model_name in _expected_model_names(stack_count)
    )


async def _wait_for_gazebo(stack_count: int) -> None:
    # 16 chips finish their nominal staggered spawn at about 13 seconds, but
    # software rendering and the create service can be much slower locally.
    configured_timeout = float(
        os.environ.get(
            "ROBOT_GAZEBO_READY_TIMEOUT_SEC",
            DEFAULT_GAZEBO_READY_TIMEOUT_SEC,
        )
    )
    timeout_sec = max(configured_timeout, 12.0 + stack_count * 0.7)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_sec

    while loop.time() < deadline:
        if not _is_running(_gazebo_process):
            raise RuntimeError("Gazebo 프로세스가 준비 중 종료되었습니다.")

        models_ready = await asyncio.to_thread(
            _gazebo_models_ready,
            stack_count,
        )
        if models_ready:
            return
        await asyncio.sleep(0.5)

    raise RuntimeError(
        f"Gazebo에서 {stack_count}개 칩 모델 준비를 확인하지 못했습니다."
    )


async def _wait_for_joint_bridge() -> None:
    # A launch process that survives this grace period has created the bridge
    # and adapter nodes; the controller itself still performs topic waits.
    await asyncio.sleep(1.0)
    if not _is_running(_joint_bridge_process):
        raise RuntimeError("joint bridge 프로세스가 준비 중 종료되었습니다.")


async def shutdown_managed_demo() -> None:
    """Stop every process started through the web API."""

    async with _process_lock:
        await asyncio.to_thread(_stop_all_processes_sync)


@router.get(
    "/demo/status",
    response_model=CommonResponse,
    status_code=status.HTTP_200_OK,
    summary="[로봇 제어] 비전 적층 데모 실행 상태 조회",
)
async def get_demo_status():
    return CommonResponse(data=_process_snapshot())


@router.post(
    "/demo/start",
    response_model=CommonResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="[로봇 제어] 비전 적층 시스템 자동 시작",
    description=(
        "웹에서 받은 4~16개의 stack_count 하나로 Gazebo, joint bridge, "
        "vision-stack-demo를 같은 값으로 순서대로 실행합니다."
    ),
)
async def start_demo(data: DemoStartRequest | None = None):
    global _gazebo_process, _joint_bridge_process, _demo_process
    global _demo_stack_count

    requested_stack_count = (
        data.stack_count if data is not None else DEFAULT_STACK_COUNT
    )

    async with _process_lock:
        snapshot = _process_snapshot()
        if (
            snapshot["running"]
            and snapshot["infrastructure_running"]
            and snapshot["stack_count"] == requested_stack_count
        ):
            return CommonResponse(
                message=(
                    f'{snapshot["stack_count"]}개 칩 적층 데모가 이미 '
                    "실행 중입니다."
                ),
                data=snapshot,
            )

        try:
            # A completed/failed demo leaves moved chips in Gazebo. Recreate
            # the whole world for every non-idempotent Start so the requested
            # run always begins from its declared spawn layout.
            await asyncio.to_thread(_stop_all_processes_sync)
            if _manual_simulator_running():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "터미널에서 실행한 Gazebo 또는 ROS 데모가 "
                        "감지되었습니다. 기존 프로세스를 Ctrl+C로 종료한 "
                        "뒤 Start를 다시 누르세요."
                    ),
                )

            _demo_stack_count = requested_stack_count
            _gazebo_process = _spawn_process(
                _gazebo_command(),
                "web_gazebo.log",
                requested_stack_count,
            )
            await _wait_for_gazebo(requested_stack_count)
            _joint_bridge_process = _spawn_process(
                _joint_bridge_command(),
                "web_joint_bridge.log",
                requested_stack_count,
            )
            await _wait_for_joint_bridge()

            _demo_process = _spawn_process(
                _demo_command(),
                "robot_demo.log",
                requested_stack_count,
            )
            await asyncio.sleep(0.3)
            if not _is_running(_demo_process):
                raise RuntimeError("비전 적층 데모 프로세스가 즉시 종료되었습니다.")
        except asyncio.CancelledError:
            await asyncio.to_thread(_stop_all_processes_sync)
            raise
        except HTTPException:
            raise
        except (FileNotFoundError, OSError, ValueError, RuntimeError) as exc:
            await asyncio.to_thread(_stop_all_processes_sync)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"비전 적층 시스템을 시작하지 못했습니다: {exc} "
                    f"로그 경로: {LOG_DIR}"
                ),
            ) from exc

        return CommonResponse(
            message=(
                f"웹 설정값 {requested_stack_count}개로 Gazebo, joint bridge, "
                "비전 적층 데모를 시작했습니다."
            ),
            data=_process_snapshot(),
        )


@router.post(
    "/demo/stop",
    response_model=CommonResponse,
    status_code=status.HTTP_200_OK,
    summary="[로봇 제어] 비전 적층 시스템 전체 중지",
)
async def stop_demo():
    async with _process_lock:
        snapshot = _process_snapshot()
        if not _any_process_running():
            return CommonResponse(
                message="웹에서 실행한 비전 적층 시스템이 없습니다.",
                data=snapshot,
            )

        await asyncio.to_thread(_stop_all_processes_sync)
        return CommonResponse(
            message="Gazebo, joint bridge, 비전 적층 데모를 모두 중지했습니다.",
            data=_process_snapshot(),
        )
