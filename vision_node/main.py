import argparse
from pathlib import Path

import cv2

from vision_aligner import VisionAligner


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_IMAGE_DIR = WORKSPACE_ROOT / "src" / "robot_system_description" / "test_images"
DEFAULT_MACRO_IMAGE = DEFAULT_TEST_IMAGE_DIR / "answer_macro.jpg"
DEFAULT_MICRO_IMAGES = [
    DEFAULT_TEST_IMAGE_DIR / f"answer_micro_{index}.jpg"
    for index in range(1, 5)
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Macro/Micro 카메라 이미지로 비전 정렬 오차를 계산합니다."
    )
    parser.add_argument(
        "--process",
        choices=("macro", "pick", "place"),
        required=True,
        help="실행할 정렬 공정입니다.",
    )
    parser.add_argument(
        "--mode",
        choices=("array", "stacking"),
        default="array",
        help="place 공정에서 사용할 기준 타겟 선택 모드입니다.",
    )
    parser.add_argument(
        "--image",
        default=str(DEFAULT_MACRO_IMAGE),
        help="macro 공정에서 사용할 이미지 1장 경로입니다. 기본값은 answer_macro.jpg입니다.",
    )
    parser.add_argument(
        "--micro-images",
        nargs=4,
        default=[str(path) for path in DEFAULT_MICRO_IMAGES],
        metavar=("MICRO_1", "MICRO_2", "MICRO_3", "MICRO_4"),
        help="pick/place 공정에서 사용할 micro 이미지 4장 경로입니다. 기본값은 answer_micro_1~4.jpg입니다.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="검출 위치와 계산 결과가 그려진 디버그 이미지를 생성합니다.",
    )
    parser.add_argument(
        "--show-debug",
        action="store_true",
        help="OpenCV 창으로 디버그 이미지를 표시합니다.",
    )
    parser.add_argument(
        "--debug-dir",
        default="vision_debug",
        help="디버그 이미지를 저장할 폴더입니다.",
    )
    return parser.parse_args()


def save_debug_frames(aligner: VisionAligner, debug_dir: str):
    output_dir = Path(debug_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for name, frame in aligner.last_debug_frames.items():
        cv2.imwrite(str(output_dir / f"{name}.png"), frame)


def main():
    args = parse_args()
    aligner = VisionAligner(
        debug_mode=args.debug,
        show_debug_windows=args.show_debug,
    )

    if args.process == "macro":
        if not args.image:
            raise ValueError("macro 공정은 --image가 필요합니다.")
        result = aligner.align_macro(args.image)
    elif args.process == "pick":
        if not args.micro_images:
            raise ValueError("pick 공정은 --micro-images 이미지 4장이 필요합니다.")
        result = aligner.align_pick(args.micro_images)
    else:
        if not args.micro_images:
            raise ValueError("place 공정은 --micro-images 이미지 4장이 필요합니다.")
        result = aligner.align_place(args.micro_images, mode=args.mode)

    print(result)

    if args.debug:
        save_debug_frames(aligner, args.debug_dir)

    if args.show_debug:
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
