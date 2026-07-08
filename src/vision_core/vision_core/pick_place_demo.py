from vision_core.joint_commander import JointCommander
from vision_core.motion_profile import PRESETS

import rclpy


def main() -> int:
    rclpy.init()
    commander = JointCommander()

    try:
        sequence = (
            PRESETS["home"],
            PRESETS["pick"],
            PRESETS["pick_down"],
            PRESETS["pick"],
            PRESETS["place"],
            PRESETS["place_down"],
            PRESETS["place"],
            PRESETS["home"],
        )
        commander.run_sequence(sequence, steps=140, period=0.02, dwell=0.8)
    finally:
        commander.destroy_node()
        rclpy.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
