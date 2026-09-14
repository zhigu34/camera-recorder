from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from app.services.motion_detection import SensitivityProfile, sensitivity_profile


_PIXEL_DELTA_THRESHOLD = 20
_GRID_SIZE = 4
_BLOCK_OCCUPANCY_THRESHOLD = 0.30


@dataclass(frozen=True, slots=True)
class MotionAnalysisResult:
    raw_score: float
    primary_zone_id: int | None
    matched_zone_ids: list[int]
    global_change: bool
    warming_up: bool
    stabilizing: bool
    moving_area_ratio: float
    global_change_ratio: float


@dataclass(frozen=True, slots=True)
class _ZoneMask:
    zone_id: int
    mask: np.ndarray
    area_pixels: int


class MotionFrameAnalyzer:
    """Analyze low-rate frames into motion evidence without deciding event policy."""

    def __init__(self, sensitivity: str, *, analysis_fps: int) -> None:
        if analysis_fps <= 0:
            raise ValueError("analysis_fps must be positive")
        self.profile: SensitivityProfile = sensitivity_profile(sensitivity)
        self.analysis_fps = analysis_fps
        self.warmup_frames = max(1, round(analysis_fps * 2.0))
        self.stabilization_frames = max(1, round(analysis_fps * 1.5))
        self.background = cv2.createBackgroundSubtractorMOG2(
            history=120,
            varThreshold=self.profile.var_threshold,
            detectShadows=False,
        )
        self.kernel = np.ones((3, 3), dtype=np.uint8)
        self._warmup_seen = 0
        self._stabilization_remaining = 0
        self._reference_gray: np.ndarray | None = None
        self._zone_signature: tuple[Any, ...] | None = None
        self._zone_masks: list[_ZoneMask] = []
        self._zone_union_mask: np.ndarray | None = None
        self._zone_union_area = 0
        self._frame_shape: tuple[int, int] | None = None

    def _empty_result(
        self,
        *,
        global_change: bool = False,
        warming_up: bool = False,
        stabilizing: bool = False,
        global_change_ratio: float = 0.0,
    ) -> MotionAnalysisResult:
        return MotionAnalysisResult(
            raw_score=0.0,
            primary_zone_id=None,
            matched_zone_ids=[],
            global_change=global_change,
            warming_up=warming_up,
            stabilizing=stabilizing,
            moving_area_ratio=0.0,
            global_change_ratio=global_change_ratio,
        )

    @staticmethod
    def _enabled_zone_signature(zones: list[dict[str, Any]]) -> tuple[Any, ...]:
        signature: list[Any] = []
        for zone in zones:
            if not bool(zone.get("enabled", True)):
                continue
            polygon = zone.get("polygon")
            polygon_signature: tuple[tuple[float, float], ...] = ()
            if isinstance(polygon, list):
                points: list[tuple[float, float]] = []
                for point in polygon:
                    if isinstance(point, (list, tuple)) and len(point) == 2:
                        points.append((float(point[0]), float(point[1])))
                polygon_signature = tuple(points)
            signature.append((zone.get("id"), polygon_signature))
        return tuple(signature)

    def _ensure_zone_masks(
        self,
        zones: list[dict[str, Any]],
        *,
        height: int,
        width: int,
    ) -> None:
        signature = self._enabled_zone_signature(zones)
        shape = (height, width)
        if signature == self._zone_signature and shape == self._frame_shape:
            return

        self._zone_signature = signature
        self._frame_shape = shape
        self._zone_masks = []
        self._zone_union_mask = None
        self._zone_union_area = 0

        union = np.zeros(shape, dtype=np.uint8)
        for zone in zones:
            if not bool(zone.get("enabled", True)):
                continue
            zone_id = zone.get("id")
            polygon = zone.get("polygon")
            if not isinstance(zone_id, int) or not isinstance(polygon, list) or len(polygon) < 3:
                continue

            points: list[list[int]] = []
            for point in polygon:
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    points = []
                    break
                x = min(1.0, max(0.0, float(point[0])))
                y = min(1.0, max(0.0, float(point[1])))
                points.append([
                    int(round(x * (width - 1))),
                    int(round(y * (height - 1))),
                ])
            if len(points) < 3:
                continue

            mask = np.zeros(shape, dtype=np.uint8)
            cv2.fillPoly(mask, [np.asarray(points, dtype=np.int32)], 255)
            area_pixels = int(np.count_nonzero(mask))
            if area_pixels <= 0:
                continue
            self._zone_masks.append(_ZoneMask(zone_id=zone_id, mask=mask, area_pixels=area_pixels))
            cv2.bitwise_or(union, mask, dst=union)

        if self._zone_masks:
            self._zone_union_mask = union
            self._zone_union_area = int(np.count_nonzero(union))

    @staticmethod
    def _changed_block_ratio(changed: np.ndarray) -> float:
        changed_blocks = 0
        total_blocks = 0
        for row in np.array_split(changed, _GRID_SIZE, axis=0):
            for block in np.array_split(row, _GRID_SIZE, axis=1):
                if block.size == 0:
                    continue
                total_blocks += 1
                if float(np.mean(block)) >= _BLOCK_OCCUPANCY_THRESHOLD:
                    changed_blocks += 1
        if total_blocks == 0:
            return 0.0
        return changed_blocks / total_blocks

    def _global_change_metrics(self, gray: np.ndarray) -> tuple[bool, float]:
        reference = self._reference_gray
        if reference is None or reference.shape != gray.shape:
            return False, 0.0
        delta = cv2.absdiff(reference, gray)
        changed = delta >= _PIXEL_DELTA_THRESHOLD
        changed_ratio = float(np.mean(changed)) if changed.size else 0.0
        block_ratio = self._changed_block_ratio(changed)
        global_change = (
            changed_ratio >= self.profile.global_change_ratio
            and block_ratio >= self.profile.global_block_ratio
        )
        return global_change, changed_ratio

    def _apply_background(self, gray: np.ndarray) -> np.ndarray:
        foreground = self.background.apply(gray)
        foreground = cv2.morphologyEx(
            foreground,
            cv2.MORPH_OPEN,
            self.kernel,
            iterations=1,
        )
        return cv2.morphologyEx(
            foreground,
            cv2.MORPH_CLOSE,
            self.kernel,
            iterations=2,
        )

    def analyze(self, frame: np.ndarray, zones: list[dict[str, Any]]) -> MotionAnalysisResult:
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("motion frames must use BGR channel layout")

        height, width = frame.shape[:2]
        self._ensure_zone_masks(zones, height=height, width=width)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if self._warmup_seen < self.warmup_frames:
            self._apply_background(gray)
            self._warmup_seen += 1
            self._reference_gray = gray.copy()
            return self._empty_result(warming_up=True)

        global_change, global_change_ratio = self._global_change_metrics(gray)

        if global_change:
            self._apply_background(gray)
            self._reference_gray = gray.copy()
            self._stabilization_remaining = self.stabilization_frames
            return self._empty_result(
                global_change=True,
                stabilizing=True,
                global_change_ratio=global_change_ratio,
            )

        if self._stabilization_remaining > 0:
            self._apply_background(gray)
            self._reference_gray = gray.copy()
            self._stabilization_remaining -= 1
            return self._empty_result(
                stabilizing=True,
                global_change_ratio=global_change_ratio,
            )

        foreground = self._apply_background(gray)
        self._reference_gray = gray.copy()

        contours, _ = cv2.findContours(
            foreground,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        frame_area = float(height * width)
        accepted_union = np.zeros((height, width), dtype=np.uint8)
        matched_zone_ids: list[int] = []
        zone_intersections: dict[int, int] = {}
        best_overlap_ratio = 0.0

        if not self._zone_masks:
            minimum_area = frame_area * self.profile.min_area_ratio
            for contour in contours:
                contour_mask = np.zeros((height, width), dtype=np.uint8)
                cv2.drawContours(contour_mask, [contour], -1, 255, thickness=-1)
                contour_pixels = int(np.count_nonzero(contour_mask))
                if contour_pixels < minimum_area:
                    continue
                cv2.bitwise_or(accepted_union, contour_mask, dst=accepted_union)

            accepted_pixels = int(np.count_nonzero(accepted_union))
            moving_area_ratio = accepted_pixels / frame_area if frame_area else 0.0
            if accepted_pixels == 0:
                return self._empty_result(global_change_ratio=global_change_ratio)
            area_score = min(
                1.0,
                moving_area_ratio / max(self.profile.min_area_ratio * 5.0, 1e-9),
            )
            return MotionAnalysisResult(
                raw_score=area_score,
                primary_zone_id=None,
                matched_zone_ids=[],
                global_change=False,
                warming_up=False,
                stabilizing=False,
                moving_area_ratio=moving_area_ratio,
                global_change_ratio=global_change_ratio,
            )

        for contour in contours:
            contour_mask = np.zeros((height, width), dtype=np.uint8)
            cv2.drawContours(contour_mask, [contour], -1, 255, thickness=-1)
            contour_pixels = int(np.count_nonzero(contour_mask))
            if contour_pixels <= 0:
                continue

            for zone in self._zone_masks:
                intersection = cv2.bitwise_and(contour_mask, zone.mask)
                intersection_pixels = int(np.count_nonzero(intersection))
                if intersection_pixels <= 0:
                    continue
                overlap_ratio = intersection_pixels / contour_pixels
                minimum_area = zone.area_pixels * self.profile.min_area_ratio
                if overlap_ratio < self.profile.min_zone_overlap_ratio:
                    continue
                if intersection_pixels < minimum_area:
                    continue

                cv2.bitwise_or(accepted_union, intersection, dst=accepted_union)
                zone_intersections[zone.zone_id] = (
                    zone_intersections.get(zone.zone_id, 0) + intersection_pixels
                )
                if zone.zone_id not in matched_zone_ids:
                    matched_zone_ids.append(zone.zone_id)
                best_overlap_ratio = max(best_overlap_ratio, overlap_ratio)

        accepted_pixels = int(np.count_nonzero(accepted_union))
        if accepted_pixels == 0:
            return self._empty_result(global_change_ratio=global_change_ratio)

        effective_area = float(self._zone_union_area or frame_area)
        moving_area_ratio = accepted_pixels / effective_area if effective_area else 0.0
        area_score = min(
            1.0,
            moving_area_ratio / max(self.profile.min_area_ratio * 5.0, 1e-9),
        )
        raw_score = min(1.0, area_score * min(1.0, best_overlap_ratio))
        primary_zone_id = max(
            zone_intersections,
            key=lambda zone_id: (zone_intersections[zone_id], zone_id),
        )

        return MotionAnalysisResult(
            raw_score=raw_score,
            primary_zone_id=primary_zone_id,
            matched_zone_ids=matched_zone_ids,
            global_change=False,
            warming_up=False,
            stabilizing=False,
            moving_area_ratio=moving_area_ratio,
            global_change_ratio=global_change_ratio,
        )
