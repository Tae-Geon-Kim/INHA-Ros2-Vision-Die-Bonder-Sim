from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Mapping, Sequence

import cv2
import numpy as np


AlignmentMode = Literal["array", "stacking"]
TargetKind = Literal["chip", "base_plate"]
ImageInput = str | Path | np.ndarray
Roi = tuple[int, int, int, int]


@dataclass(frozen=True)
class MacroCalibration:
    """Macro 카메라 1장으로 중앙 사각 마커를 볼 때 쓰는 보정값."""

    # None이면 입력 이미지의 정중앙을 기준점으로 사용합니다.
    expected_center: tuple[float, float] | None = None
    # 장비 기준에서 중앙 마커가 가져야 하는 각도입니다. 기본은 수평 0도입니다.
    expected_angle_deg: float = 0.0
    # 기본 출력 단위는 pixel입니다. mm 출력이 필요하면 mm/pixel 값을 넣습니다.
    pixel_size: tuple[float, float] = (1.0, 1.0)
    # 중앙 마커를 찾을 영역을 제한하고 싶을 때 사용합니다. (x, y, w, h)
    marker_roi: Roi | None = None


@dataclass(frozen=True)
class MicroCameraSpec:
    """Micro 카메라 1대가 담당하는 십자선 마커의 기하 정보."""

    name: str
    # 기준 좌표계에서 이 카메라가 봐야 하는 이상적인 마커 좌표입니다.
    # 실제 장비에서는 칩/베이스 마커 간 거리(mm)를 넣는 것이 가장 좋습니다.
    reference_point: tuple[float, float]
    # 해당 카메라 이미지 안에서 마커가 정렬되어 있어야 하는 픽셀 위치입니다.
    # None이면 각 이미지의 정중앙을 사용합니다.
    expected_pixel: tuple[float, float] | None = None
    # x, y 방향 pixel -> 장비 좌표 변환 비율입니다. 기본은 pixel 그대로입니다.
    pixel_size: tuple[float, float] = (1.0, 1.0)
    # 카메라 설치 방향이 뒤집힌 경우 축 부호를 바꿉니다.
    # 예: 이미지 y+와 로봇 y+가 반대면 axis_sign=(1.0, -1.0)
    axis_sign: tuple[float, float] = (1.0, 1.0)
    # Pick/Place 기준 타겟별 탐색 ROI입니다.
    # 같은 이미지에 칩 마커와 베이스 마커가 같이 잡힐 때, 여기서 분리합니다.
    target_rois: Mapping[TargetKind, Roi] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionConfig:
    """마커 검출 알고리즘의 민감도와 탐색 스케일."""

    # 십자선 템플릿 크기 후보입니다. 실제 마커가 크게 보이면 더 큰 홀수를 추가합니다.
    cross_template_sizes: tuple[int, ...] = (19, 25, 31, 41, 55, 71)
    # 템플릿 매칭 점수가 이 값보다 낮으면 검출 실패로 판단합니다.
    min_cross_score: float = 0.22
    # 템플릿 매칭 후 sub-pixel 중심을 다시 구할 때 사용할 지역 창 배율입니다.
    refine_window_scale: float = 1.7
    # Macro 사각 마커 contour의 최소/최대 면적 비율입니다.
    macro_min_area_ratio: float = 0.0003
    macro_max_area_ratio: float = 0.25


@dataclass(frozen=True)
class ReferenceRegistrationConfig:
    """기준 영상과 현재 영상의 4축 정합 설정."""

    max_width: int = 960
    max_iterations: int = 60
    epsilon: float = 1e-5
    min_correlation: float = 0.20
    macro_roi_fraction: float = 1.0
    micro_roi_fraction: float = 1.0


@dataclass(frozen=True)
class MarkerDetection:
    """검출된 마커 중심과 디버깅용 부가 정보."""

    center: tuple[float, float]
    score: float
    size: int
    polarity: Literal["bright", "dark"]
    angle_deg: float = 0.0
    box_points: tuple[tuple[float, float], ...] | None = None


class VisionAligner:
    """
    Pick / Place 공정의 비전 정렬 오차(dx, dy, dtheta)를 계산합니다.

    기본 반환 단위는 pixel 기반입니다. 실제 로봇 보정값(mm, deg)이 필요하면
    MicroCameraSpec.pixel_size와 reference_point를 장비 캘리브레이션 값으로
    바꿔서 생성하면 됩니다.
    """

    DEFAULT_CAMERA_ORDER = ("micro_1", "micro_2", "micro_3", "micro_4")

    def __init__(
        self,
        *,
        macro_calibration: MacroCalibration | None = None,
        micro_camera_specs: Mapping[str, MicroCameraSpec] | None = None,
        detection_config: DetectionConfig | None = None,
        reference_registration_config: ReferenceRegistrationConfig | None = None,
        debug_mode: bool = False,
        show_debug_windows: bool = False,
    ):
        self.macro_calibration = macro_calibration or MacroCalibration()
        self.micro_camera_specs = (
            dict(micro_camera_specs)
            if micro_camera_specs is not None
            else self.create_default_micro_camera_specs()
        )
        self.micro_camera_order = tuple(self.micro_camera_specs.keys())
        if len(self.micro_camera_order) != 4:
            raise ValueError("Micro 카메라 spec은 정확히 4개가 필요합니다.")

        self.detection_config = detection_config or DetectionConfig()
        self.reference_registration_config = (
            reference_registration_config or ReferenceRegistrationConfig()
        )
        self.debug_mode = debug_mode
        self.show_debug_windows = show_debug_windows

        # FastAPI 같은 서버 환경에서는 cv2.imshow를 띄우지 않고,
        # 마지막 디버그 프레임만 보관해서 API 응답/파일 저장 등에 활용할 수 있게 합니다.
        self.last_debug_frames: dict[str, np.ndarray] = {}
        self._template_cache: dict[int, np.ndarray] = {}

    @classmethod
    def create_default_micro_camera_specs(
        cls,
        *,
        marker_span_x: float = 100.0,
        marker_span_y: float = 100.0,
        pixel_size: tuple[float, float] = (1.0, 1.0),
    ) -> dict[str, MicroCameraSpec]:
        """
        4대 Micro 카메라의 기본 배치를 만듭니다.

        기본 순서는 좌상, 우상, 우하, 좌하입니다. 실제 배선 순서가 다르면
        이 메서드를 쓰지 말고 MicroCameraSpec을 직접 만들어 전달하세요.
        """

        half_x = marker_span_x / 2.0
        half_y = marker_span_y / 2.0

        return {
            "micro_1": MicroCameraSpec(
                name="micro_1",
                reference_point=(-half_x, half_y),
                pixel_size=pixel_size,
            ),
            "micro_2": MicroCameraSpec(
                name="micro_2",
                reference_point=(half_x, half_y),
                pixel_size=pixel_size,
            ),
            "micro_3": MicroCameraSpec(
                name="micro_3",
                reference_point=(half_x, -half_y),
                pixel_size=pixel_size,
            ),
            "micro_4": MicroCameraSpec(
                name="micro_4",
                reference_point=(-half_x, -half_y),
                pixel_size=pixel_size,
            ),
        }

    def align_macro(self, image: ImageInput) -> dict[str, float]:
        """
        Macro 이미지 1장에서 중앙 사각 마커를 검출해 Coarse 오차를 계산합니다.

        dx, dy는 "마커 중심을 기준 위치로 보내기 위한 보정량"입니다.
        dtheta도 동일하게 현재 각도를 기준 각도로 맞추기 위한 보정각입니다.
        """

        self.last_debug_frames.clear()
        frame = self._load_image(image)
        calibration = self.macro_calibration
        detection = self._detect_square_marker(frame, calibration.marker_roi)

        height, width = frame.shape[:2]
        expected_center = calibration.expected_center or (width / 2.0, height / 2.0)
        dx = (expected_center[0] - detection.center[0]) * calibration.pixel_size[0]
        dy = (expected_center[1] - detection.center[1]) * calibration.pixel_size[1]
        dtheta = self._normalize_angle_deg(
            calibration.expected_angle_deg - detection.angle_deg
        )

        result = self._result(dx, dy, dtheta)

        if self.debug_mode:
            debug_frame = self._draw_macro_debug(frame, detection, expected_center, result)
            self._publish_debug_frame("macro_alignment", debug_frame)

        return result

    def align_pick(self, micro_images: Sequence[ImageInput] | Mapping[str, ImageInput]):
        """
        Pick 공정 정렬입니다.

        명세에 따라 무조건 "칩 내부 4개 십자선 마커"를 기준으로 오차를 계산합니다.
        """

        return self._align_micro(
            micro_images=micro_images,
            target_kind="chip",
            debug_prefix="pick_chip",
        )

    def align_place(
        self,
        micro_images: Sequence[ImageInput] | Mapping[str, ImageInput],
        *,
        mode: AlignmentMode | str = "array",
        base_plate_empty: bool = False,
    ) -> dict[str, float]:
        """
        Place 공정 정렬입니다.

        - array 모드 또는 바닥 판이 비어 있는 경우: 베이스 플레이트 마커만 사용합니다.
        - stacking 모드: 바로 아래 기존 칩의 내부 마커만 사용합니다.
        """

        normalized_mode = mode.strip().lower()

        if base_plate_empty or normalized_mode in {"array", "base", "base_plate"}:
            target_kind: TargetKind = "base_plate"
        elif normalized_mode in {"stacking", "stack"}:
            target_kind = "chip"
        else:
            raise ValueError(
                "mode는 'array' 또는 'stacking' 중 하나여야 합니다. "
                f"입력값: {mode!r}"
            )

        return self._align_micro(
            micro_images=micro_images,
            target_kind=target_kind,
            debug_prefix=f"place_{target_kind}",
        )

    def align_reference_image(
        self,
        *,
        reference_image: ImageInput,
        current_image: ImageInput,
        pixel_size: tuple[float, float],
        reference_distance_mm: float,
        roi_fraction: float | None = None,
        axis_sign: tuple[float, float] = (1.0, 1.0),
        motion_model: Literal["translation", "affine"] = "affine",
    ) -> dict[str, float]:
        """기준 영상으로 돌아가기 위한 dx, dy, dz, dtheta를 계산합니다."""

        reference = self._load_image(reference_image)
        current = self._load_image(current_image)
        if current.shape[:2] != reference.shape[:2]:
            current = cv2.resize(
                current,
                (reference.shape[1], reference.shape[0]),
                interpolation=cv2.INTER_AREA,
            )

        fraction = (
            self.reference_registration_config.micro_roi_fraction
            if roi_fraction is None
            else float(roi_fraction)
        )
        reference_crop = self._center_crop_fraction(reference, fraction)
        current_crop = self._center_crop_fraction(current, fraction)
        reference_gray = self._registration_gray(reference_crop)
        current_gray = self._registration_gray(current_crop)

        resize_scale = min(
            1.0,
            self.reference_registration_config.max_width
            / max(1.0, float(reference_gray.shape[1])),
        )
        if resize_scale < 1.0:
            output_size = (
                max(32, int(round(reference_gray.shape[1] * resize_scale))),
                max(32, int(round(reference_gray.shape[0] * resize_scale))),
            )
            reference_work = cv2.resize(
                reference_gray,
                output_size,
                interpolation=cv2.INTER_AREA,
            )
            current_work = cv2.resize(
                current_gray,
                output_size,
                interpolation=cv2.INTER_AREA,
            )
        else:
            reference_work = reference_gray
            current_work = current_gray

        if motion_model not in {"translation", "affine"}:
            raise ValueError(f"unsupported registration motion model: {motion_model}")

        shift, phase_score = cv2.phaseCorrelate(reference_work, current_work)
        warp = np.array(
            [[1.0, 0.0, shift[0]], [0.0, 1.0, shift[1]]],
            dtype=np.float32,
        )
        cv_motion_model = (
            cv2.MOTION_TRANSLATION
            if motion_model == "translation"
            else cv2.MOTION_AFFINE
        )
        criteria = (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            self.reference_registration_config.max_iterations,
            self.reference_registration_config.epsilon,
        )

        try:
            correlation, warp = cv2.findTransformECC(
                reference_work,
                current_work,
                warp,
                cv_motion_model,
                criteria,
                None,
                5,
            )
        except cv2.error:
            correlation = float(phase_score)

        if correlation < self.reference_registration_config.min_correlation:
            raise ValueError(
                "기준 영상 정합 신뢰도가 낮습니다: "
                f"correlation={correlation:.3f}"
            )

        affine = warp[:, :2].astype(np.float64)
        translation = warp[:, 2].astype(np.float64) / resize_scale
        center = np.array(
            [reference_gray.shape[1] / 2.0, reference_gray.shape[0] / 2.0],
            dtype=np.float64,
        )
        current_center = affine @ center + translation
        image_offset = current_center - center

        scale = math.sqrt(max(abs(float(np.linalg.det(affine))), 1e-12))
        image_rotation_deg = math.degrees(math.atan2(affine[1, 0], affine[0, 0]))
        dx = -image_offset[0] * float(pixel_size[0]) * float(axis_sign[0])
        dy = -image_offset[1] * float(pixel_size[1]) * float(axis_sign[1])
        dz = float(reference_distance_mm) * (1.0 - 1.0 / scale)
        # ECC's affine angle is the current-to-reference warp. With the moving
        # downward camera, the joint command follows this warp's numeric sign.
        dtheta = self._normalize_angle_deg(image_rotation_deg)

        return {
            "dx": float(dx),
            "dy": float(dy),
            "dz": float(dz),
            "dtheta": float(dtheta),
            "score": float(correlation),
            "scale": float(scale),
        }

    def align_reference_square_marker(
        self,
        *,
        reference_image: ImageInput,
        current_image: ImageInput,
        pixel_size: tuple[float, float],
        reference_distance_mm: float,
        axis_sign: tuple[float, float] = (1.0, 1.0),
        theta_axis_sign: float = 1.0,
    ) -> dict[str, float | str]:
        """Fast Macro registration from the visible chip or substrate outline."""

        reference = self._load_image(reference_image)
        current = self._load_image(current_image)
        if current.shape[:2] != reference.shape[:2]:
            current = cv2.resize(
                current,
                (reference.shape[1], reference.shape[0]),
                interpolation=cv2.INTER_AREA,
            )

        reference_marker = self._detect_square_marker(reference, None)
        current_marker = self._detect_square_marker(current, None)
        image_offset_x = current_marker.center[0] - reference_marker.center[0]
        image_offset_y = current_marker.center[1] - reference_marker.center[1]
        dx = -image_offset_x * float(pixel_size[0]) * float(axis_sign[0])
        dy = -image_offset_y * float(pixel_size[1]) * float(axis_sign[1])

        # A rotated square gains roughly one raster pixel at its contour edge,
        # which is too noisy for height estimation. Micro ECC retains Z control.
        scale = 1.0
        dz = 0.0

        # The camera looks down while joint_theta rotates around -Z. In this
        # setup the marker angle measured in image coordinates has the same
        # sign as the required joint command correction.
        image_angle_delta = self._normalize_square_angle_deg(
            current_marker.angle_deg - reference_marker.angle_deg
        )
        dtheta = image_angle_delta * float(theta_axis_sign)
        score = min(1.0, min(reference_marker.score, current_marker.score) / 5.0)
        return {
            "dx": float(dx),
            "dy": float(dy),
            "dz": float(dz),
            "dtheta": float(dtheta),
            "score": float(score),
            "scale": float(scale),
            "source": "macro_square_marker",
        }

    def align_reference_substrate_outline(
        self,
        *,
        reference_image: ImageInput,
        current_image: ImageInput,
        pixel_size: tuple[float, float],
        reference_distance_mm: float,
        axis_sign: tuple[float, float] = (1.0, 1.0),
        theta_axis_sign: float = 1.0,
    ) -> dict[str, float | str]:
        """Align to the saturated substrate outline while ignoring gray chips."""

        reference = self._load_image(reference_image)
        current = self._load_image(current_image)
        if current.shape[:2] != reference.shape[:2]:
            current = cv2.resize(
                current,
                (reference.shape[1], reference.shape[0]),
                interpolation=cv2.INTER_AREA,
            )

        reference_marker, reference_area = self._detect_saturated_surface(reference)
        current_marker, current_area = self._detect_saturated_surface(current)
        image_offset_x = current_marker.center[0] - reference_marker.center[0]
        image_offset_y = current_marker.center[1] - reference_marker.center[1]
        dx = -image_offset_x * float(pixel_size[0]) * float(axis_sign[0])
        dy = -image_offset_y * float(pixel_size[1]) * float(axis_sign[1])
        dtheta = self._normalize_square_angle_deg(
            current_marker.angle_deg - reference_marker.angle_deg
        ) * float(theta_axis_sign)

        area_scale = math.sqrt(max(current_area / reference_area, 1e-12))
        area_score = min(reference_area, current_area) / max(
            reference_area,
            current_area,
        )
        return {
            "dx": float(dx),
            "dy": float(dy),
            # Macro scale is sensitive to rendered contour edges. Micro ECC owns Z.
            "dz": 0.0,
            "dtheta": float(dtheta),
            "score": float(area_score),
            "scale": float(area_scale),
            "source": "macro_substrate_outline",
        }

    def align_reference_micro_set(
        self,
        *,
        reference_images: Sequence[ImageInput],
        current_images: Sequence[ImageInput],
        pixel_size: tuple[float, float],
        reference_distance_mm: float,
        axis_sign: tuple[float, float] = (1.0, 1.0),
        normalized_rois: Sequence[tuple[float, float, float, float]] | None = None,
        registration_roi_fraction: float | None = None,
    ) -> dict[str, object]:
        """Micro 카메라 4대의 기준 영상 정합 결과를 강건하게 결합합니다."""

        if len(reference_images) != 4 or len(current_images) != 4:
            raise ValueError("Micro 기준 영상과 현재 영상은 각각 정확히 4장이 필요합니다.")
        if normalized_rois is not None and len(normalized_rois) != 4:
            raise ValueError("Micro 정합 ROI는 카메라별로 정확히 4개가 필요합니다.")

        def align_camera(camera_args):
            index, reference, current = camera_args
            if normalized_rois is not None:
                roi = normalized_rois[index - 1]
                reference = self._crop_normalized_roi(
                    self._load_image(reference),
                    roi,
                )
                current = self._crop_normalized_roi(
                    self._load_image(current),
                    roi,
                )
            result = self.align_reference_image(
                reference_image=reference,
                current_image=current,
                pixel_size=pixel_size,
                reference_distance_mm=reference_distance_mm,
                roi_fraction=registration_roi_fraction,
                axis_sign=axis_sign,
            )
            if (
                abs(float(result["dx"])) > 5.0
                or abs(float(result["dy"])) > 5.0
                or abs(float(result["dz"])) > 2.0
                or abs(float(result["dtheta"])) > 10.0
            ):
                raise ValueError(
                    "Micro ECC produced an implausible correction: "
                    f"dx={result['dx']:.3f}mm, dy={result['dy']:.3f}mm, "
                    f"dz={result['dz']:.3f}mm, "
                    f"dtheta={result['dtheta']:.3f}deg"
                )
            result["camera_index"] = index
            return result

        camera_args = [
            (index, reference, current)
            for index, (reference, current) in enumerate(
                zip(reference_images, current_images),
                start=1,
            )
        ]
        results = []
        failures = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(align_camera, args) for args in camera_args]
            for index, future in enumerate(futures, start=1):
                try:
                    results.append(future.result())
                except (ValueError, cv2.error) as exc:
                    failures.append({"camera_index": index, "error": str(exc)})

        if len(results) < 3:
            raise ValueError(
                "Micro 기준 영상 정합에 성공한 카메라가 3대 미만입니다: "
                f"success={len(results)}, failures={failures}"
            )

        combined = {
            key: float(np.median([result[key] for result in results]))
            for key in ("dx", "dy", "dz", "dtheta", "score", "scale")
        }
        combined["per_camera"] = results
        combined["failed_cameras"] = failures
        combined["valid_camera_count"] = len(results)
        combined["source"] = "micro_reference_ecc_marker_roi"
        return combined

    def _crop_normalized_roi(
        self,
        frame: np.ndarray,
        roi: tuple[float, float, float, float],
    ) -> np.ndarray:
        x0, y0, x1, y1 = roi
        if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
            raise ValueError(f"normalized ROI 범위가 잘못되었습니다: {roi}")
        height, width = frame.shape[:2]
        left = int(round(x0 * width))
        top = int(round(y0 * height))
        right = int(round(x1 * width))
        bottom = int(round(y1 * height))
        return frame[top:bottom, left:right]

    def _center_crop_fraction(
        self,
        frame: np.ndarray,
        fraction: float,
    ) -> np.ndarray:
        fraction = min(1.0, max(0.2, float(fraction)))
        height, width = frame.shape[:2]
        crop_width = max(32, int(round(width * fraction)))
        crop_height = max(32, int(round(height * fraction)))
        x0 = max(0, (width - crop_width) // 2)
        y0 = max(0, (height - crop_height) // 2)
        return frame[y0:y0 + crop_height, x0:x0 + crop_width]

    def _registration_gray(self, frame: np.ndarray) -> np.ndarray:
        if frame.ndim == 2:
            gray = frame
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        return cv2.normalize(
            gray.astype(np.float32),
            None,
            0.0,
            1.0,
            cv2.NORM_MINMAX,
        )

    def _align_micro(
        self,
        *,
        micro_images: Sequence[ImageInput] | Mapping[str, ImageInput],
        target_kind: TargetKind,
        debug_prefix: str,
    ) -> dict[str, float]:
        self.last_debug_frames.clear()

        image_map = self._normalize_micro_images(micro_images)
        measured_points: list[tuple[float, float]] = []
        reference_points: list[tuple[float, float]] = []

        for camera_name in self.micro_camera_order:
            spec = self.micro_camera_specs[camera_name]
            frame = self._load_image(image_map[camera_name])
            roi = spec.target_rois.get(target_kind)
            detection = self._detect_cross_marker(frame, roi)
            expected_pixel = self._expected_pixel_for(frame, spec)

            measured_point = self._camera_measurement_to_world_point(
                detection=detection,
                expected_pixel=expected_pixel,
                spec=spec,
            )

            measured_points.append(measured_point)
            reference_points.append(spec.reference_point)

            if self.debug_mode:
                debug_frame = self._draw_cross_debug(
                    frame=frame,
                    detection=detection,
                    expected_pixel=expected_pixel,
                    roi=roi,
                    camera_name=camera_name,
                    target_kind=target_kind,
                )
                self._publish_debug_frame(f"{debug_prefix}_{camera_name}", debug_frame)

        result = self._solve_rigid_alignment(
            measured_points=measured_points,
            reference_points=reference_points,
        )

        if self.debug_mode:
            overview = self._draw_micro_overview(
                measured_points=measured_points,
                reference_points=reference_points,
                result=result,
            )
            self._publish_debug_frame(f"{debug_prefix}_overview", overview)

        return result

    def _normalize_micro_images(
        self,
        micro_images: Sequence[ImageInput] | Mapping[str, ImageInput],
    ) -> dict[str, ImageInput]:
        if isinstance(micro_images, Mapping):
            missing = [
                name for name in self.micro_camera_order if name not in micro_images
            ]
            if missing:
                raise ValueError(f"Micro 이미지가 부족합니다. 누락: {missing}")
            return {name: micro_images[name] for name in self.micro_camera_order}

        if len(micro_images) != len(self.micro_camera_order):
            raise ValueError(
                "Micro 이미지는 4장이 필요합니다. "
                f"입력 개수: {len(micro_images)}"
            )

        return dict(zip(self.micro_camera_order, micro_images))

    def _detect_square_marker(
        self,
        frame: np.ndarray,
        roi: Roi | None,
    ) -> MarkerDetection:
        crop, offset = self._crop(frame, roi)
        gray = self._preprocess_gray(crop)
        image_area = gray.shape[0] * gray.shape[1]
        min_area = image_area * self.detection_config.macro_min_area_ratio
        max_area = image_area * self.detection_config.macro_max_area_ratio
        roi_center = np.array([gray.shape[1] / 2.0, gray.shape[0] / 2.0])
        roi_diag = math.hypot(gray.shape[1], gray.shape[0])

        best: tuple[float, MarkerDetection] | None = None

        # 마커가 검은색/흰색 어느 쪽이어도 찾을 수 있게 양쪽 이진화를 모두 시도합니다.
        for threshold_type, polarity in (
            (cv2.THRESH_BINARY, "bright"),
            (cv2.THRESH_BINARY_INV, "dark"),
        ):
            _, mask = cv2.threshold(gray, 0, 255, threshold_type | cv2.THRESH_OTSU)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            contours, _ = cv2.findContours(
                mask,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )

            for contour in contours:
                area = cv2.contourArea(contour)
                if area < min_area or area > max_area:
                    continue

                rect = cv2.minAreaRect(contour)
                (center_x, center_y), (width, height), _ = rect
                if width <= 1.0 or height <= 1.0:
                    continue

                long_side = max(width, height)
                short_side = min(width, height)
                square_score = short_side / long_side
                if square_score < 0.55:
                    continue

                center = np.array([center_x, center_y])
                center_score = 1.0 - min(
                    1.0,
                    np.linalg.norm(center - roi_center) / max(roi_diag / 2.0, 1.0),
                )
                extent = area / max(width * height, 1.0)
                size_score = min(1.0, area / max(image_area * 0.03, 1.0))
                score = square_score * 2.0 + center_score * 2.0 + extent + size_score

                box = cv2.boxPoints(rect)
                detection = MarkerDetection(
                    center=(center_x + offset[0], center_y + offset[1]),
                    score=float(score),
                    size=int(round(long_side)),
                    polarity=polarity,
                    angle_deg=self._rect_angle_deg(rect),
                    box_points=tuple(
                        (float(point[0] + offset[0]), float(point[1] + offset[1]))
                        for point in box
                    ),
                )

                if best is None or score > best[0]:
                    best = (score, detection)

        if best is None:
            raise ValueError("Macro 이미지에서 중앙 사각 마커를 찾지 못했습니다.")

        return best[1]

    def _detect_saturated_surface(
        self,
        frame: np.ndarray,
    ) -> tuple[MarkerDetection, float]:
        hsv = cv2.cvtColor(self._ensure_bgr(frame), cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(
            hsv,
            np.array((0, 60, 40), dtype=np.uint8),
            np.array((179, 255, 255), dtype=np.uint8),
        )
        kernel = np.ones((5, 5), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        image_area = float(frame.shape[0] * frame.shape[1])
        candidates: list[tuple[float, MarkerDetection]] = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < image_area * 0.002 or area > image_area * 0.5:
                continue
            rect = cv2.minAreaRect(contour)
            (center_x, center_y), (width, height), _ = rect
            if width <= 1.0 or height <= 1.0:
                continue
            long_side = max(width, height)
            short_side = min(width, height)
            square_score = short_side / long_side
            if square_score < 0.5:
                continue
            box = cv2.boxPoints(rect)
            candidates.append((
                area,
                MarkerDetection(
                    center=(float(center_x), float(center_y)),
                    score=float(square_score),
                    size=int(round(long_side)),
                    polarity="bright",
                    angle_deg=self._rect_angle_deg(rect),
                    box_points=tuple(
                        (float(point[0]), float(point[1])) for point in box
                    ),
                ),
            ))

        if not candidates:
            raise ValueError("Macro 이미지에서 substrate 외곽을 찾지 못했습니다.")

        area, detection = max(candidates, key=lambda candidate: candidate[0])
        return detection, area

    def _detect_cross_marker(
        self,
        frame: np.ndarray,
        roi: Roi | None,
    ) -> MarkerDetection:
        crop, offset = self._crop(frame, roi)
        gray = self._preprocess_gray(crop)

        best: MarkerDetection | None = None

        for size in self.detection_config.cross_template_sizes:
            if gray.shape[0] < size or gray.shape[1] < size:
                continue

            bright_template = self._cross_template(size)
            dark_template = 255 - bright_template

            for polarity, template in (
                ("bright", bright_template),
                ("dark", dark_template),
            ):
                response = cv2.matchTemplate(
                    gray,
                    template,
                    cv2.TM_CCOEFF_NORMED,
                )
                _, score, _, max_location = cv2.minMaxLoc(response)
                if best is not None and score <= best.score:
                    continue

                rough_center = (
                    max_location[0] + size / 2.0,
                    max_location[1] + size / 2.0,
                )
                refined_center = self._refine_cross_center(
                    gray=gray,
                    rough_center=rough_center,
                    template_size=size,
                    polarity=polarity,
                )
                best = MarkerDetection(
                    center=(
                        refined_center[0] + offset[0],
                        refined_center[1] + offset[1],
                    ),
                    score=float(score),
                    size=size,
                    polarity=polarity,
                )

        if best is None or best.score < self.detection_config.min_cross_score:
            score = "None" if best is None else f"{best.score:.3f}"
            raise ValueError(
                "Micro 이미지에서 십자선 마커를 안정적으로 찾지 못했습니다. "
                f"best_score={score}"
            )

        return best

    def _refine_cross_center(
        self,
        *,
        gray: np.ndarray,
        rough_center: tuple[float, float],
        template_size: int,
        polarity: Literal["bright", "dark"],
    ) -> tuple[float, float]:
        # 템플릿 매칭은 정수 픽셀 위치가 기본이므로, 주변 패치의 foreground 중심을
        # 모멘트로 다시 계산해 sub-pixel 중심 좌표를 얻습니다.
        radius = max(8, int(round(
            template_size * self.detection_config.refine_window_scale / 2.0
        )))
        center_x, center_y = rough_center
        x0 = max(0, int(math.floor(center_x - radius)))
        y0 = max(0, int(math.floor(center_y - radius)))
        x1 = min(gray.shape[1], int(math.ceil(center_x + radius)))
        y1 = min(gray.shape[0], int(math.ceil(center_y + radius)))

        patch = gray[y0:y1, x0:x1]
        if patch.size == 0:
            return rough_center

        threshold_type = cv2.THRESH_BINARY if polarity == "bright" else cv2.THRESH_BINARY_INV
        _, mask = cv2.threshold(patch, 0, 255, threshold_type | cv2.THRESH_OTSU)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

        label_count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
        if label_count <= 1:
            return rough_center

        local_center = np.array([center_x - x0, center_y - y0])
        selected_label = self._select_component_near_center(
            labels=labels,
            stats=stats,
            centroids=centroids,
            local_center=local_center,
        )
        if selected_label is None:
            return rough_center

        component_mask = np.where(labels == selected_label, 255, 0).astype(np.uint8)
        moments = cv2.moments(component_mask)
        if moments["m00"] == 0:
            return rough_center

        refined_x = x0 + moments["m10"] / moments["m00"]
        refined_y = y0 + moments["m01"] / moments["m00"]
        return float(refined_x), float(refined_y)

    def _select_component_near_center(
        self,
        *,
        labels: np.ndarray,
        stats: np.ndarray,
        centroids: np.ndarray,
        local_center: np.ndarray,
    ) -> int | None:
        center_x = int(round(local_center[0]))
        center_y = int(round(local_center[1]))
        if 0 <= center_x < labels.shape[1] and 0 <= center_y < labels.shape[0]:
            label_at_center = int(labels[center_y, center_x])
            if label_at_center != 0:
                return label_at_center

        best_label: int | None = None
        best_distance = float("inf")
        for label in range(1, len(centroids)):
            area = stats[label, cv2.CC_STAT_AREA]
            if area < 5:
                continue
            distance = float(np.linalg.norm(centroids[label] - local_center))
            if distance < best_distance:
                best_distance = distance
                best_label = label

        return best_label

    def _camera_measurement_to_world_point(
        self,
        *,
        detection: MarkerDetection,
        expected_pixel: tuple[float, float],
        spec: MicroCameraSpec,
    ) -> tuple[float, float]:
        # 이미지 안에서 기대 위치 대비 얼마나 밀렸는지 계산합니다.
        # 이후 카메라별 pixel_size, axis_sign을 적용해 장비 좌표계 오프셋으로 바꿉니다.
        offset_px_x = detection.center[0] - expected_pixel[0]
        offset_px_y = detection.center[1] - expected_pixel[1]
        offset_world_x = offset_px_x * spec.pixel_size[0] * spec.axis_sign[0]
        offset_world_y = offset_px_y * spec.pixel_size[1] * spec.axis_sign[1]

        return (
            spec.reference_point[0] + offset_world_x,
            spec.reference_point[1] + offset_world_y,
        )

    def _solve_rigid_alignment(
        self,
        *,
        measured_points: Sequence[tuple[float, float]],
        reference_points: Sequence[tuple[float, float]],
    ) -> dict[str, float]:
        if len(measured_points) != len(reference_points) or len(measured_points) < 2:
            raise ValueError("정렬 계산에는 같은 개수의 측정점/기준점이 2개 이상 필요합니다.")

        measured = np.asarray(measured_points, dtype=np.float64)
        reference = np.asarray(reference_points, dtype=np.float64)

        measured_center = measured.mean(axis=0)
        reference_center = reference.mean(axis=0)
        measured_centered = measured - measured_center
        reference_centered = reference - reference_center

        if np.linalg.norm(measured_centered) < 1e-9:
            raise ValueError("측정점들이 한 점에 모여 있어 회전각을 계산할 수 없습니다.")

        # 2D Kabsch/Procrustes 방식으로 measured -> reference 변환을 구합니다.
        # 반환되는 t가 로봇/스테이지에 적용할 병진 보정량(dx, dy)입니다.
        covariance = measured_centered.T @ reference_centered
        u_matrix, _, vt_matrix = np.linalg.svd(covariance)
        rotation = vt_matrix.T @ u_matrix.T

        # 반사 변환이 섞이는 예외를 제거합니다.
        if np.linalg.det(rotation) < 0:
            vt_matrix[-1, :] *= -1
            rotation = vt_matrix.T @ u_matrix.T

        theta = math.degrees(math.atan2(rotation[1, 0], rotation[0, 0]))
        translation = reference_center - rotation @ measured_center

        return self._result(translation[0], translation[1], theta)

    def _expected_pixel_for(
        self,
        frame: np.ndarray,
        spec: MicroCameraSpec,
    ) -> tuple[float, float]:
        if spec.expected_pixel is not None:
            return spec.expected_pixel

        height, width = frame.shape[:2]
        return width / 2.0, height / 2.0

    def _cross_template(self, size: int) -> np.ndarray:
        if size in self._template_cache:
            return self._template_cache[size]

        if size % 2 == 0:
            raise ValueError("cross_template_sizes는 홀수만 사용할 수 있습니다.")

        template = np.zeros((size, size), dtype=np.uint8)
        center = size // 2
        thickness = max(3, int(round(size * 0.22)))
        half_thickness = thickness // 2
        margin = max(1, int(round(size * 0.12)))

        # 밝은 십자선 템플릿입니다. 어두운 십자선은 255 - template으로 처리합니다.
        cv2.rectangle(
            template,
            (center - half_thickness, margin),
            (center + half_thickness, size - margin - 1),
            255,
            -1,
        )
        cv2.rectangle(
            template,
            (margin, center - half_thickness),
            (size - margin - 1, center + half_thickness),
            255,
            -1,
        )

        self._template_cache[size] = template
        return template

    def _preprocess_gray(self, frame: np.ndarray) -> np.ndarray:
        if frame.ndim == 2:
            gray = frame
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        return cv2.GaussianBlur(gray, (3, 3), 0)

    def _crop(self, frame: np.ndarray, roi: Roi | None) -> tuple[np.ndarray, tuple[int, int]]:
        if roi is None:
            return frame, (0, 0)

        x, y, width, height = roi
        image_height, image_width = frame.shape[:2]
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(image_width, x + width)
        y1 = min(image_height, y + height)

        if x0 >= x1 or y0 >= y1:
            raise ValueError(f"ROI가 이미지 범위를 벗어났습니다: {roi}")

        return frame[y0:y1, x0:x1], (x0, y0)

    def _load_image(self, image: ImageInput) -> np.ndarray:
        if isinstance(image, np.ndarray):
            return image.copy()

        frame = cv2.imread(str(image), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"이미지를 읽을 수 없습니다: {image}")

        return frame

    def _draw_macro_debug(
        self,
        frame: np.ndarray,
        detection: MarkerDetection,
        expected_center: tuple[float, float],
        result: dict[str, float],
    ) -> np.ndarray:
        debug = self._ensure_bgr(frame)

        if detection.box_points is not None:
            box = np.asarray(detection.box_points, dtype=np.int32)
            cv2.polylines(debug, [box], True, (0, 180, 255), 2)

        self._draw_crosshair(debug, detection.center, (0, 255, 0), "detected")
        self._draw_crosshair(debug, expected_center, (255, 80, 80), "expected")
        self._draw_result_text(debug, result)
        return debug

    def _draw_cross_debug(
        self,
        *,
        frame: np.ndarray,
        detection: MarkerDetection,
        expected_pixel: tuple[float, float],
        roi: Roi | None,
        camera_name: str,
        target_kind: TargetKind,
    ) -> np.ndarray:
        debug = self._ensure_bgr(frame)

        if roi is not None:
            x, y, width, height = roi
            cv2.rectangle(debug, (x, y), (x + width, y + height), (255, 180, 0), 1)

        self._draw_crosshair(debug, detection.center, (0, 255, 0), "detected")
        self._draw_crosshair(debug, expected_pixel, (255, 80, 80), "expected")
        cv2.putText(
            debug,
            f"{camera_name} / {target_kind} / score={detection.score:.3f}",
            (12, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (30, 220, 30),
            2,
            cv2.LINE_AA,
        )
        return debug

    def _draw_micro_overview(
        self,
        *,
        measured_points: Sequence[tuple[float, float]],
        reference_points: Sequence[tuple[float, float]],
        result: dict[str, float],
    ) -> np.ndarray:
        canvas = np.full((520, 520, 3), 245, dtype=np.uint8)
        all_points = np.asarray([*measured_points, *reference_points], dtype=np.float64)
        min_xy = all_points.min(axis=0)
        max_xy = all_points.max(axis=0)
        span = np.maximum(max_xy - min_xy, 1.0)
        scale = 400.0 / float(max(span[0], span[1]))

        def to_canvas(point: tuple[float, float]) -> tuple[int, int]:
            x = int(round((point[0] - min_xy[0]) * scale + 60))
            y = int(round(460 - (point[1] - min_xy[1]) * scale))
            return x, y

        point_pairs = zip(reference_points, measured_points)
        for index, (reference, measured) in enumerate(point_pairs, start=1):
            ref_px = to_canvas(reference)
            meas_px = to_canvas(measured)
            cv2.circle(canvas, ref_px, 7, (255, 80, 80), -1)
            cv2.circle(canvas, meas_px, 7, (0, 160, 0), -1)
            cv2.line(canvas, meas_px, ref_px, (80, 80, 80), 1)
            cv2.putText(
                canvas,
                str(index),
                (ref_px[0] + 9, ref_px[1] - 9),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (40, 40, 40),
                1,
                cv2.LINE_AA,
            )

        self._draw_result_text(canvas, result)
        cv2.putText(
            canvas,
            "blue=reference, green=measured",
            (12, 500),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (70, 70, 70),
            1,
            cv2.LINE_AA,
        )
        return canvas

    def _draw_crosshair(
        self,
        frame: np.ndarray,
        center: tuple[float, float],
        color: tuple[int, int, int],
        label: str,
    ) -> None:
        x = int(round(center[0]))
        y = int(round(center[1]))
        cv2.line(frame, (x - 14, y), (x + 14, y), color, 2)
        cv2.line(frame, (x, y - 14), (x, y + 14), color, 2)
        cv2.circle(frame, (x, y), 4, color, -1)
        cv2.putText(
            frame,
            label,
            (x + 8, y - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )

    def _draw_result_text(self, frame: np.ndarray, result: dict[str, float]) -> None:
        text = f"dx={result['dx']:.3f}, dy={result['dy']:.3f}, dtheta={result['dtheta']:.4f}"
        cv2.rectangle(frame, (8, 36), (510, 70), (255, 255, 255), -1)
        cv2.putText(
            frame,
            text,
            (14, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (20, 20, 20),
            2,
            cv2.LINE_AA,
        )

    def _publish_debug_frame(self, name: str, frame: np.ndarray) -> None:
        self.last_debug_frames[name] = frame

        if not self.show_debug_windows:
            return

        try:
            cv2.imshow(name, frame)
            cv2.waitKey(1)
        except cv2.error:
            # 서버/WSL/headless OpenCV 환경에서는 imshow가 실패할 수 있습니다.
            # 정렬 계산 자체는 계속 진행하고 last_debug_frames에만 남깁니다.
            pass

    def _ensure_bgr(self, frame: np.ndarray) -> np.ndarray:
        if frame.ndim == 2:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        return frame.copy()

    def _rect_angle_deg(self, rect) -> float:
        (_, _), (width, height), angle = rect
        if width < height:
            angle += 90.0
        return self._normalize_square_angle_deg(angle)

    def _normalize_square_angle_deg(self, angle: float) -> float:
        # 중앙 마커가 사각형이면 0도와 90도는 시각적으로 같은 상태입니다.
        # OpenCV minAreaRect가 같은 사각형을 0도 또는 90도로 번갈아 반환할 수 있어
        # 사각 마커 기준 오차는 -45~45도 범위로 접어 안정화합니다.
        # 정확히 45도인 경계는 -45도로 통일해 0->45도 칩 보정 부호가
        # 15도 / 30도 칩과 같은 방향을 유지하게 합니다.
        while angle <= -45.0:
            angle += 90.0
        while angle >= 45.0:
            angle -= 90.0
        return angle

    def _normalize_angle_deg(self, angle: float) -> float:
        while angle <= -180.0:
            angle += 360.0
        while angle > 180.0:
            angle -= 360.0
        return angle

    def _result(self, dx: float, dy: float, dtheta: float) -> dict[str, float]:
        return {
            "dx": float(dx),
            "dy": float(dy),
            "dtheta": float(dtheta),
        }


__all__ = [
    "DetectionConfig",
    "MacroCalibration",
    "MicroCameraSpec",
    "ReferenceRegistrationConfig",
    "VisionAligner",
]
