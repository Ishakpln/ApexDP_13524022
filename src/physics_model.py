import math
from typing import Sequence

import numpy as np

from car import Car
from constants import EPSILON, G, STRAIGHT_SPEED_LIMIT
from track import PointInput, Track, validate_points


def calculate_curvature_from_three_points(
    A: Sequence[float],
    B: Sequence[float],
    C: Sequence[float],
) -> float:
    ax, ay = float(A[0]), float(A[1])
    bx, by = float(B[0]), float(B[1])
    cx, cy = float(C[0]), float(C[1])

    a = math.hypot(cx - bx, cy - by)
    b = math.hypot(cx - ax, cy - ay)
    c = math.hypot(bx - ax, by - ay)
    if a <= EPSILON or b <= EPSILON or c <= EPSILON:
        return 0.0

    area = abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) / 2.0
    if area <= EPSILON:
        return 0.0

    return 4.0 * area / (a * b * c)


def calculate_curvatures(points: Sequence[PointInput]) -> list[float]:
    """
    Input:
    - points: list titik racing line

    Output:
    - list curvature dengan panjang sama seperti points

    Titik pertama dan terakhir diberi curvature 0 karena tidak memiliki
    tetangga lengkap untuk membentuk tiga titik lokal.
    """
    validated_points = validate_points(points, 3, "racing_line_points")
    curvatures = [0.0] * len(validated_points)

    for index in range(1, len(validated_points) - 1):
        curvatures[index] = calculate_curvature_from_three_points(
            validated_points[index - 1],
            validated_points[index],
            validated_points[index + 1],
        )

    return curvatures


class PhysicsModel:
    def compute_distances(self, points: Sequence[PointInput]) -> np.ndarray:
        point_array = np.asarray(points, dtype=float)
        deltas = np.diff(point_array, axis=0)
        return np.sqrt(deltas[:, 0] ** 2 + deltas[:, 1] ** 2)

    def compute_curvature(self, points: Sequence[PointInput]) -> np.ndarray:
        return np.asarray(calculate_curvatures(points), dtype=float)

    def compute_speed_limits(self, car: Car, track: Track, curvature: np.ndarray) -> np.ndarray:
        effective_grip = car.tire_grip * track.surface_grip
        denominator = curvature - (effective_grip * car.downforce_coeff / car.mass)

        speed_limits = np.full_like(curvature, STRAIGHT_SPEED_LIMIT, dtype=float)
        cornering_mask = (curvature > EPSILON) & (denominator > EPSILON)
        speed_limits[cornering_mask] = np.sqrt((effective_grip * G) / denominator[cornering_mask])
        return speed_limits

    def compute_backward_dp(
        self,
        car: Car,
        speed_limits: np.ndarray,
        distances: np.ndarray,
    ) -> np.ndarray:
        if len(distances) != len(speed_limits) - 1:
            raise ValueError("Jumlah distances harus N - 1 dari jumlah speed_limits.")

        dp = np.zeros_like(speed_limits, dtype=float)
        dp[-1] = speed_limits[-1]

        for i in range(len(speed_limits) - 2, -1, -1):
            max_speed_before_braking = math.sqrt(
                max(0.0, dp[i + 1] ** 2 + 2.0 * car.braking_deceleration * distances[i])
            )
            dp[i] = min(speed_limits[i], max_speed_before_braking)

        return dp
