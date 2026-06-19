import math
from dataclasses import dataclass
from numbers import Real
from typing import Optional, Sequence

import numpy as np

from constants import EPSILON

Point = tuple[float, float]
PointInput = Sequence[Real]


def validate_points(points: Sequence[PointInput], min_points: int, name: str) -> list[Point]:
    """
    Memastikan points valid:
    - berupa list/tuple
    - panjang minimal min_points
    - setiap elemen berupa titik 2D
    - koordinat numeric
    - tidak ada duplicate consecutive points
    """
    if not isinstance(points, (list, tuple)):
        raise ValueError(f"{name} harus berupa list atau tuple titik.")

    if len(points) < min_points:
        raise ValueError(f"{name} minimal harus memiliki {min_points} titik.")

    validated_points: list[Point] = []

    for index, point in enumerate(points):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError(f"{name}[{index}] harus berupa titik 2D (x, y).")

        x_value, y_value = point
        if not _is_numeric_coordinate(x_value) or not _is_numeric_coordinate(y_value):
            raise ValueError(f"{name}[{index}] harus berisi koordinat numeric int atau float.")

        validated_point = (float(x_value), float(y_value))
        if not math.isfinite(validated_point[0]) or not math.isfinite(validated_point[1]):
            raise ValueError(f"{name}[{index}] berisi koordinat tidak valid.")

        if validated_points and validated_points[-1] == validated_point:
            raise ValueError(f"{name}[{index}] duplikat dengan titik sebelumnya.")

        validated_points.append(validated_point)

    return validated_points


def create_track_from_points(
    centerline_points: Sequence[PointInput],
    racing_line_points: Sequence[PointInput],
    road_width: float,
    name: Optional[str] = None,
    surface_grip: float = 1.0,
) -> "Track":
    """
    Membuat object Track langsung dari points setelah validasi.
    """
    return Track(
        centerline_points=centerline_points,
        racing_line_points=racing_line_points,
        road_width=road_width,
        name=name,
        surface_grip=surface_grip,
    )


@dataclass
class Track:
    centerline_points: Sequence[PointInput]
    racing_line_points: Sequence[PointInput]
    road_width: float
    name: Optional[str] = None
    surface_grip: float = 1.0

    def __post_init__(self) -> None:
        if not _is_numeric_coordinate(self.road_width) or not math.isfinite(float(self.road_width)):
            raise ValueError("road_width harus berupa angka valid.")
        if self.road_width <= 0:
            raise ValueError("road_width harus lebih besar dari 0.")
        if not _is_numeric_coordinate(self.surface_grip) or not math.isfinite(float(self.surface_grip)):
            raise ValueError("surface_grip harus berupa angka valid.")
        if self.surface_grip <= 0:
            raise ValueError("surface_grip harus lebih besar dari 0.")

        self.centerline_points = validate_points(self.centerline_points, 2, "centerline_points")
        self.racing_line_points = validate_points(self.racing_line_points, 3, "racing_line_points")
        self.road_width = float(self.road_width)
        self.surface_grip = float(self.surface_grip)

    def validate(self) -> None:
        if self.road_width <= 0:
            raise ValueError("road_width harus lebih besar dari 0.")
        if self.surface_grip <= 0:
            raise ValueError("surface_grip harus lebih besar dari 0.")
        validate_points(self.centerline_points, 2, "centerline_points")
        validate_points(self.racing_line_points, 3, "racing_line_points")

    def centerline_array(self) -> np.ndarray:
        return np.asarray(self.centerline_points, dtype=float)

    def racing_line_array(self) -> np.ndarray:
        return np.asarray(self.racing_line_points, dtype=float)

    def validate_racing_line_inside_track(self) -> None:
        self.validate()

        max_distance = self.road_width / 2.0
        for index, point in enumerate(self.racing_line_points):
            distance = _distance_point_to_polyline(point, self.centerline_points)
            if distance > max_distance + EPSILON:
                raise ValueError(
                    "Racing line keluar dari batas jalan pada "
                    f"index {index}, x={point[0]:.3f}, y={point[1]:.3f}, "
                    f"jarak_centerline={distance:.3f}, batas={max_distance:.3f}."
                )


def _is_numeric_coordinate(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _distance_point_to_polyline(point: Point, polyline: Sequence[Point]) -> float:
    distances = [
        _distance_point_to_segment(point, polyline[index], polyline[index + 1])
        for index in range(len(polyline) - 1)
    ]
    return min(distances)


def _distance_point_to_segment(point: Point, start: Point, end: Point) -> float:
    px, py = point
    ax, ay = start
    bx, by = end
    dx = bx - ax
    dy = by - ay
    length_squared = dx * dx + dy * dy

    if length_squared <= EPSILON:
        return math.hypot(px - ax, py - ay)

    t = ((px - ax) * dx + (py - ay) * dy) / length_squared
    t = max(0.0, min(1.0, t))
    nearest_x = ax + t * dx
    nearest_y = ay + t * dy
    return math.hypot(px - nearest_x, py - nearest_y)
