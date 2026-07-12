import asyncio
import unittest
from unittest.mock import AsyncMock, call, patch

from pydantic import ValidationError

from web_backend.api import robot_control_api
from web_backend.schemas.robot_control_schemas import DemoStartRequest


class FakeProcess:
    """Small Popen stand-in that never starts an operating-system process."""

    def __init__(self, pid: int, returncode: int | None = None):
        self.pid = pid
        self.returncode = returncode

    def poll(self):
        return self.returncode


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
            robot_control_api._process_lock,
        )
        robot_control_api._gazebo_process = None
        robot_control_api._joint_bridge_process = None
        robot_control_api._demo_process = None
        robot_control_api._demo_stack_count = 4
        robot_control_api._process_lock = asyncio.Lock()

    async def asyncTearDown(self):
        (
            robot_control_api._gazebo_process,
            robot_control_api._joint_bridge_process,
            robot_control_api._demo_process,
            robot_control_api._demo_stack_count,
            robot_control_api._process_lock,
        ) = self.original_state

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
                DemoStartRequest(stack_count=requested_count)
            )

        self.assertEqual(spawn_process.call_count, 3)
        self.assertEqual(
            [spawn_call.args[2] for spawn_call in spawn_process.call_args_list],
            [requested_count, requested_count, requested_count],
        )
        self.assertEqual(
            [spawn_call.args[1] for spawn_call in spawn_process.call_args_list],
            ["web_gazebo.log", "web_joint_bridge.log", "robot_demo.log"],
        )
        wait_for_gazebo.assert_awaited_once_with(requested_count)
        wait_for_joint_bridge.assert_awaited_once_with()
        self.assertEqual(response.data["stack_count"], requested_count)
        self.assertTrue(response.data["infrastructure_running"])
        self.assertTrue(response.data["running"])

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
            response = await robot_control_api.stop_demo()

        self.assertEqual(
            terminate_process.call_args_list,
            [call(demo), call(joint_bridge), call(gazebo)],
        )
        self.assertFalse(response.data["running"])
        self.assertFalse(response.data["infrastructure_running"])
        self.assertIsNone(robot_control_api._demo_process)
        self.assertIsNone(robot_control_api._joint_bridge_process)
        self.assertIsNone(robot_control_api._gazebo_process)


class DemoStartRequestTests(unittest.TestCase):
    def test_stack_count_accepts_full_web_range(self):
        self.assertEqual(DemoStartRequest(stack_count=4).stack_count, 4)
        self.assertEqual(DemoStartRequest(stack_count=16).stack_count, 16)

    def test_stack_count_rejects_values_outside_web_range(self):
        for invalid_count in (3, 17):
            with self.subTest(stack_count=invalid_count):
                with self.assertRaises(ValidationError):
                    DemoStartRequest(stack_count=invalid_count)


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

        environment = robot_control_api._process_environment(requested_count)
        self.assertEqual(environment["STACK_COUNT"], "16")

    def test_requested_count_overrides_stale_make_assignment(self):
        argv = robot_control_api._command_argv(
            "make gazebo-camera STACK_COUNT=4",
            12,
        )

        self.assertIn("STACK_COUNT=12", argv)
        self.assertNotIn("STACK_COUNT=4", argv)


if __name__ == "__main__":
    unittest.main()
