import math
from dataclasses import dataclass
from typing import List, Optional

from car import Car
from constants import EPSILON
from physics_model import PhysicsModel
from track import Point, Track


FAILURE_COAST_DURATION_SECONDS = 2.0
SPEED_LIMIT_TOLERANCE = 0.1 / 3.6
CONTROL_SPEED_EPSILON = 1e-6


@dataclass(frozen=True)
class SimulationFrame:
    index: int
    position: Point
    speed: float
    local_speed_limit: float
    optimal_speed: float
    curvature: float
    acceleration_value: float
    acceleration_state: str
    elapsed_time: float
    lateral_acceleration: float
    downforce: float


@dataclass(frozen=True)
class SimulationProfile:
    frames: List[SimulationFrame]
    optimal_initial_speed: float
    total_time: float
    failed_index: Optional[int]
    failed_message: Optional[str]


def build_simulation_profile(
    car: Car,
    track: Track,
    initial_speed: float,
    physics_model: Optional[PhysicsModel] = None,
    validate_boundary: bool = True,
) -> SimulationProfile:
    if initial_speed < 0:
        raise ValueError("initial_speed tidak boleh negatif.")

    car.validate()
    if validate_boundary:
        track.validate_racing_line_inside_track()
    else:
        track.validate()

    model = physics_model or PhysicsModel()
    points = track.racing_line_array()
    distances = model.compute_distances(points)
    curvatures = model.compute_curvature(track.racing_line_points)
    speed_limits = model.compute_speed_limits(car, track, curvatures)
    dp = model.compute_backward_dp(car, speed_limits, distances)

    current_speed = float(initial_speed)
    elapsed_time = 0.0
    frames: List[SimulationFrame] = []
    failed_index: Optional[int] = None
    failed_message: Optional[str] = None

    for index, point in enumerate(points):
        acceleration_value = 0.0
        acceleration_state = "Coasting"
        local_speed_limit = float(speed_limits[index])

        if current_speed > local_speed_limit + SPEED_LIMIT_TOLERANCE:
            failed_index = index
            failed_message = "Mobil gagal mengikuti racing line."
            acceleration_state = "Failed"
        elif current_speed > local_speed_limit:
            current_speed = local_speed_limit

        if failed_index is None and index < len(points) - 1:
            next_target_speed = float(dp[index + 1])
            if current_speed > next_target_speed + CONTROL_SPEED_EPSILON:
                acceleration_value = _required_acceleration(
                    current_speed,
                    next_target_speed,
                    float(distances[index]),
                    min_acceleration=-car.braking_deceleration,
                    max_acceleration=0.0,
                )
                acceleration_state = "Braking"
            elif current_speed < next_target_speed - CONTROL_SPEED_EPSILON:
                acceleration_value = _required_acceleration(
                    current_speed,
                    next_target_speed,
                    float(distances[index]),
                    min_acceleration=0.0,
                    max_acceleration=car.acceleration,
                )
                acceleration_state = "Accelerating"

        frames.append(
            SimulationFrame(
                index=index,
                position=(float(point[0]), float(point[1])),
                speed=current_speed,
                local_speed_limit=local_speed_limit,
                optimal_speed=float(dp[index]),
                curvature=float(curvatures[index]),
                acceleration_value=acceleration_value,
                acceleration_state=acceleration_state,
                elapsed_time=elapsed_time,
                lateral_acceleration=current_speed * current_speed * float(curvatures[index]),
                downforce=car.downforce_coeff * current_speed * current_speed,
            )
        )

        if failed_index is not None or index == len(points) - 1:
            break

        next_speed = _next_speed(current_speed, acceleration_value, distances[index], dp[index + 1])
        elapsed_time += _segment_time(float(distances[index]), current_speed, next_speed)
        current_speed = next_speed

    total_time = frames[-1].elapsed_time if frames else 0.0
    if failed_index is not None:
        total_time += FAILURE_COAST_DURATION_SECONDS

    return SimulationProfile(
        frames=frames,
        optimal_initial_speed=float(dp[0]),
        total_time=total_time,
        failed_index=failed_index,
        failed_message=failed_message,
    )


def _next_speed(current_speed: float, acceleration_value: float, distance: float, next_target_speed: float) -> float:
    if acceleration_value < 0:
        return math.sqrt(max(0.0, current_speed * current_speed + 2.0 * acceleration_value * distance))

    if acceleration_value > 0:
        accelerated_speed = math.sqrt(current_speed * current_speed + 2.0 * acceleration_value * distance)
        return min(accelerated_speed, float(next_target_speed))

    return current_speed


def _required_acceleration(
    current_speed: float,
    target_speed: float,
    distance: float,
    min_acceleration: float,
    max_acceleration: float,
) -> float:
    if distance <= EPSILON:
        return 0.0

    acceleration = (target_speed * target_speed - current_speed * current_speed) / (2.0 * distance)
    return max(min_acceleration, min(max_acceleration, acceleration))


def _segment_time(distance: float, start_speed: float, end_speed: float) -> float:
    average_speed = (start_speed + end_speed) / 2.0
    if average_speed <= EPSILON:
        return 0.0

    return distance / average_speed
