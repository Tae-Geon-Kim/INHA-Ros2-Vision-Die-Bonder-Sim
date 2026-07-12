import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from pydantic import ValidationError

from web_backend.api import robot_control_api, robot_log_api
from web_backend.schemas.robot_log_schemas import (
    VisionAlignLogCreate,
    WorkHistoryCreate,
)
from web_backend.schemas.robot_control_schemas import DemoStartRequest


class FakeProcess:
    """Small Popen stand-in that never starts an operating-system process."""

    def __init__(self, pid: int, returncode: int | None = None):
        self.pid = pid
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self):
        return 0 if self.returncode is None else self.returncode


async def run_inline(function, *args, **kwargs):
    """Execute an asyncio.to_thread target without creating a worker thread."""

    return function(*args, **kwargs)


class RobotControlApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_state = (
            robot_control_api._gazebo_process,
            robot_control_api._joint_bridge_process,
            robot_control_api._demo_process,
            robot_control_api._demo_stack_count,
            robot_control_api._demo_history_id,
            robot_control_api._demo_monitor_task,
            robot_control_api._process_lock,
        )
        robot_control_api._gazebo_process = None
        robot_control_api._joint_bridge_process = None
        robot_control_api._demo_process = None
        robot_control_api._demo_stack_count = 4
        robot_control_api._demo_history_id = None
        robot_control_api._demo_monitor_task = None
        robot_control_api._process_lock = asyncio.Lock()
        self.db_pool = object()
        self.request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(db_pool=self.db_pool),
            ),
        )
        self.create_history = AsyncMock(return_value={"history_id": 901})
        self.finalize_history = AsyncMock()
        self.schedule_monitor = MagicMock()
        self.lifecycle_patchers = [
            patch.object(
                robot_control_api,
                "_create_managed_history",
                self.create_history,
            ),
            patch.object(
                robot_control_api,
                "_finalize_managed_history",
                self.finalize_history,
            ),
            patch.object(
                robot_control_api,
                "_schedule_demo_monitor",
                self.schedule_monitor,
            ),
        ]
        for patcher in self.lifecycle_patchers:
            patcher.start()

    async def asyncTearDown(self):
        (
            robot_control_api._gazebo_process,
            robot_control_api._joint_bridge_process,
            robot_control_api._demo_process,
            robot_control_api._demo_stack_count,
            robot_control_api._demo_history_id,
            robot_control_api._demo_monitor_task,
            robot_control_api._process_lock,
        ) = self.original_state
        for patcher in reversed(self.lifecycle_patchers):
            patcher.stop()

    async def test_start_passes_web_stack_count_to_all_three_processes(self):
        requested_count = 12
        fake_processes = iter(
            [FakeProcess(101), FakeProcess(102), FakeProcess(103)]
        )
        wait_for_gazebo = AsyncMock()
        wait_for_joint_bridge = AsyncMock()

        with (
            patch.object(
                robot_control_api,
                "_manual_simulator_running",
                return_value=False,
            ),
            patch.object(
                robot_control_api,
                "_wait_for_gazebo",
                wait_for_gazebo,
            ),
            patch.object(
                robot_control_api,
                "_wait_for_joint_bridge",
                wait_for_joint_bridge,
            ),
            patch.object(
                robot_control_api,
                "_spawn_process",
                side_effect=lambda *_args: next(fake_processes),
            ) as spawn_process,
            patch.object(
                robot_control_api.asyncio,
                "to_thread",
                run_inline,
            ),
            patch.object(robot_control_api.asyncio, "sleep", AsyncMock()),
        ):
            response = await robot_control_api.start_demo(
                self.request,
                DemoStartRequest(stack_count=requested_count)
            )

        self.assertEqual(spawn_process.call_count, 3)
        self.assertEqual(
            [spawn_call.args[2] for spawn_call in spawn_process.call_args_list],
            [requested_count, requested_count, requested_count],
        )
        self.assertEqual(
            [spawn_call.args[3] for spawn_call in spawn_process.call_args_list],
            [901, 901, 901],
        )
        self.assertEqual(
            [spawn_call.args[1] for spawn_call in spawn_process.call_args_list],
            ["web_gazebo.log", "web_joint_bridge.log", "robot_demo.log"],
        )
        wait_for_gazebo.assert_awaited_once_with(requested_count)
        wait_for_joint_bridge.assert_awaited_once_with()
        self.create_history.assert_awaited_once_with(
            self.db_pool,
            requested_count,
            None,
        )
        self.assertEqual(response.data["stack_count"], requested_count)
        self.assertTrue(response.data["infrastructure_running"])
        self.assertTrue(response.data["running"])
        self.assertEqual(response.data["history_id"], 901)
        self.schedule_monitor.assert_called_once_with(
            robot_control_api._demo_process,
            901,
            self.db_pool,
        )

    async def test_start_restarts_all_processes_for_a_different_count(self):
        old_gazebo = FakeProcess(201)
        old_joint_bridge = FakeProcess(202)
        old_demo = FakeProcess(203)
        robot_control_api._gazebo_process = old_gazebo
        robot_control_api._joint_bridge_process = old_joint_bridge
        robot_control_api._demo_process = old_demo
        robot_control_api._demo_stack_count = 4
        requested_count = 8
        fake_processes = iter(
            [FakeProcess(211), FakeProcess(212), FakeProcess(213)]
        )

        with (
            patch.object(
                robot_control_api,
                "_manual_simulator_running",
                return_value=False,
            ),
            patch.object(
                robot_control_api,
                "_wait_for_gazebo",
                AsyncMock(),
            ),
            patch.object(
                robot_control_api,
                "_wait_for_joint_bridge",
                AsyncMock(),
            ),
            patch.object(
                robot_control_api,
                "_terminate_process",
            ) as terminate_process,
            patch.object(
                robot_control_api,
                "_spawn_process",
                side_effect=lambda *_args: next(fake_processes),
            ) as spawn_process,
            patch.object(
                robot_control_api.asyncio,
                "to_thread",
                run_inline,
            ),
            patch.object(robot_control_api.asyncio, "sleep", AsyncMock()),
        ):
            response = await robot_control_api.start_demo(
                self.request,
                DemoStartRequest(stack_count=requested_count)
            )

        self.assertEqual(
            terminate_process.call_args_list,
            [call(old_demo), call(old_joint_bridge), call(old_gazebo)],
        )
        self.assertEqual(spawn_process.call_count, 3)
        self.assertEqual(
            [spawn_call.args[2] for spawn_call in spawn_process.call_args_list],
            [requested_count, requested_count, requested_count],
        )
        self.assertEqual(response.data["stack_count"], requested_count)
        self.assertTrue(response.data["infrastructure_running"])
        self.assertTrue(response.data["running"])

    async def test_start_repairs_missing_infrastructure_for_the_same_count(self):
        old_demo = FakeProcess(220)
        robot_control_api._gazebo_process = None
        robot_control_api._joint_bridge_process = None
        robot_control_api._demo_process = old_demo
        robot_control_api._demo_stack_count = 4
        fake_processes = iter(
            [FakeProcess(221), FakeProcess(222), FakeProcess(223)]
        )

        with (
            patch.object(
                robot_control_api,
                "_manual_simulator_running",
                return_value=False,
            ),
            patch.object(
                robot_control_api,
                "_wait_for_gazebo",
                AsyncMock(),
            ),
            patch.object(
                robot_control_api,
                "_wait_for_joint_bridge",
                AsyncMock(),
            ),
            patch.object(
                robot_control_api,
                "_terminate_process",
            ) as terminate_process,
            patch.object(
                robot_control_api,
                "_spawn_process",
                side_effect=lambda *_args: next(fake_processes),
            ) as spawn_process,
            patch.object(
                robot_control_api.asyncio,
                "to_thread",
                run_inline,
            ),
            patch.object(robot_control_api.asyncio, "sleep", AsyncMock()),
        ):
            response = await robot_control_api.start_demo(
                self.request,
                DemoStartRequest(stack_count=4)
            )

        self.assertEqual(
            terminate_process.call_args_list,
            [call(old_demo), call(None), call(None)],
        )
        self.assertEqual(spawn_process.call_count, 3)
        self.assertEqual(
            [spawn_call.args[2] for spawn_call in spawn_process.call_args_list],
            [4, 4, 4],
        )
        self.assertTrue(response.data["infrastructure_running"])
        self.assertTrue(response.data["running"])

    async def test_start_recreates_world_after_same_count_demo_completed(self):
        old_gazebo = FakeProcess(401)
        old_joint_bridge = FakeProcess(402)
        completed_demo = FakeProcess(403, returncode=0)
        robot_control_api._gazebo_process = old_gazebo
        robot_control_api._joint_bridge_process = old_joint_bridge
        robot_control_api._demo_process = completed_demo
        robot_control_api._demo_stack_count = 4
        fake_processes = iter(
            [FakeProcess(411), FakeProcess(412), FakeProcess(413)]
        )

        with (
            patch.object(
                robot_control_api,
                "_manual_simulator_running",
                return_value=False,
            ),
            patch.object(
                robot_control_api,
                "_wait_for_gazebo",
                AsyncMock(),
            ),
            patch.object(
                robot_control_api,
                "_wait_for_joint_bridge",
                AsyncMock(),
            ),
            patch.object(
                robot_control_api,
                "_terminate_process",
            ) as terminate_process,
            patch.object(
                robot_control_api,
                "_spawn_process",
                side_effect=lambda *_args: next(fake_processes),
            ) as spawn_process,
            patch.object(
                robot_control_api.asyncio,
                "to_thread",
                run_inline,
            ),
            patch.object(robot_control_api.asyncio, "sleep", AsyncMock()),
        ):
            response = await robot_control_api.start_demo(
                self.request,
                DemoStartRequest(stack_count=4)
            )

        self.assertEqual(
            terminate_process.call_args_list,
            [call(completed_demo), call(old_joint_bridge), call(old_gazebo)],
        )
        self.assertEqual(spawn_process.call_count, 3)
        self.assertTrue(response.data["running"])

    async def test_stop_terminates_demo_bridge_and_gazebo(self):
        gazebo = FakeProcess(301)
        joint_bridge = FakeProcess(302)
        demo = FakeProcess(303)
        robot_control_api._gazebo_process = gazebo
        robot_control_api._joint_bridge_process = joint_bridge
        robot_control_api._demo_process = demo
        robot_control_api._demo_stack_count = 16
        robot_control_api._demo_history_id = 77

        with (
            patch.object(
                robot_control_api,
                "_terminate_process",
            ) as terminate_process,
            patch.object(
                robot_control_api.asyncio,
                "to_thread",
                run_inline,
            ),
        ):
            response = await robot_control_api.stop_demo(self.request)

        self.assertEqual(
            terminate_process.call_args_list,
            [call(demo), call(joint_bridge), call(gazebo)],
        )
        self.assertFalse(response.data["running"])
        self.assertFalse(response.data["infrastructure_running"])
        self.assertIsNone(robot_control_api._demo_process)
        self.assertIsNone(robot_control_api._joint_bridge_process)
        self.assertIsNone(robot_control_api._gazebo_process)
        self.finalize_history.assert_awaited_once_with(
            self.db_pool,
            77,
            "STOP",
        )

    async def test_completed_demo_finalizes_history_and_stops_infrastructure(self):
        demo = FakeProcess(501, returncode=0)
        robot_control_api._demo_process = demo
        robot_control_api._demo_history_id = 88

        with (
            patch.object(
                robot_control_api.asyncio,
                "to_thread",
                run_inline,
            ),
            patch.object(
                robot_control_api,
                "_stop_infrastructure_sync",
            ) as stop_infrastructure,
        ):
            await robot_control_api._monitor_demo_completion(
                demo,
                88,
                self.db_pool,
            )

        self.finalize_history.assert_awaited_once_with(
            self.db_pool,
            88,
            "DONE",
            error_detail=None,
        )
        stop_infrastructure.assert_called_once_with()
        self.assertIsNone(robot_control_api._demo_history_id)


class DemoStartRequestTests(unittest.TestCase):
    def test_stack_count_accepts_full_web_range(self):
        self.assertEqual(DemoStartRequest(stack_count=4).stack_count, 4)
        self.assertEqual(DemoStartRequest(stack_count=16).stack_count, 16)

    def test_stack_count_rejects_values_outside_web_range(self):
        for invalid_count in (3, 17):
            with self.subTest(stack_count=invalid_count):
                with self.assertRaises(ValidationError):
                    DemoStartRequest(stack_count=invalid_count)

    def test_work_history_records_stack_count(self):
        self.assertEqual(
            WorkHistoryCreate(die_serial_number="HBM-DEFAULT").stack_count,
            4,
        )
        self.assertEqual(
            WorkHistoryCreate(
                die_serial_number="HBM-16L",
                stack_count=16,
            ).stack_count,
            16,
        )
        with self.assertRaises(ValidationError):
            WorkHistoryCreate(
                die_serial_number="HBM-3L",
                stack_count=3,
            )


class VisionLogApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_micro_camera_batch_is_saved_as_four_rows(self):
        entries = [
            VisionAlignLogCreate(
                history_id=42,
                process_step="PICK",
                camera_type=camera_type,
                offset_x=index * 0.001,
            )
            for index, camera_type in enumerate(
                ("MICRO_TL", "MICRO_TR", "MICRO_BL", "MICRO_BR"),
                start=1,
            )
        ]
        save_log = AsyncMock(
            side_effect=[
                {"align_id": index, "camera_type": entry.camera_type}
                for index, entry in enumerate(entries, start=1)
            ]
        )

        with patch.object(
            robot_log_api,
            "create_vision_align_log_service",
            save_log,
        ):
            response = await robot_log_api.create_vision_align_log(
                entries,
                conn=object(),
            )

        self.assertEqual(save_log.await_count, 4)
        self.assertEqual(len(response.data), 4)
        self.assertEqual(
            [row["camera_type"] for row in response.data],
            [entry.camera_type for entry in entries],
        )


class ProcessConfigurationTests(unittest.TestCase):
    def test_requested_count_reaches_make_arguments_and_environment(self):
        requested_count = 16

        for command in (
            robot_control_api.DEFAULT_GAZEBO_COMMAND,
            robot_control_api.DEFAULT_JOINT_BRIDGE_COMMAND,
            robot_control_api.DEFAULT_DEMO_COMMAND,
        ):
            with self.subTest(command=command):
                argv = robot_control_api._command_argv(
                    command,
                    requested_count,
                )
                self.assertEqual(argv[-1], "STACK_COUNT=16")

        environment = robot_control_api._process_environment(
            requested_count,
            history_id=42,
        )
        self.assertEqual(environment["STACK_COUNT"], "16")
        self.assertEqual(environment["HISTORY_ID"], "42")

    def test_requested_count_overrides_stale_make_assignment(self):
        argv = robot_control_api._command_argv(
            "make gazebo-camera STACK_COUNT=4",
            12,
        )

        self.assertIn("STACK_COUNT=12", argv)
        self.assertNotIn("STACK_COUNT=4", argv)


if __name__ == "__main__":
    unittest.main()
