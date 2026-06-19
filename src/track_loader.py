from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from constants import ASSET_ROOT, PROJECT_ROOT
from track import Point, Track, create_track_from_points


ROOT_DIR = PROJECT_ROOT
TRACKS_DIR = ASSET_ROOT / "Tracks"


@dataclass(frozen=True)
class TrackAsset:
    track: Track
    cover_path: Path
    image_path: Path
    directory: Path
    image_start_anchor: Point
    image_end_anchor: Point


def load_tracks(tracks_dir: Optional[Path] = None) -> List[TrackAsset]:
    base_dir = tracks_dir or TRACKS_DIR
    if not base_dir.exists():
        raise ValueError(f"Folder track tidak ditemukan: {base_dir}")

    track_assets: List[TrackAsset] = []
    for track_dir in sorted((path for path in base_dir.iterdir() if path.is_dir()), key=_sort_key):
        track_assets.append(_load_track_asset(track_dir))

    if not track_assets:
        raise ValueError(f"Tidak ada track valid di folder: {base_dir}")

    return track_assets


def _load_track_asset(track_dir: Path) -> TrackAsset:
    spec_path = track_dir / "TrackSpec.txt"
    racing_points_path = track_dir / "RacingPoints.txt"
    cover_path = track_dir / "Cover.png"
    image_path = track_dir / "Image.png"

    if not spec_path.exists():
        raise ValueError(f"TrackSpec.txt tidak ditemukan di {track_dir}")
    if not racing_points_path.exists():
        raise ValueError(f"RacingPoints.txt tidak ditemukan di {track_dir}")
    if not cover_path.exists():
        raise ValueError(f"Cover.png tidak ditemukan di {track_dir}")
    if not image_path.exists():
        image_path = cover_path

    spec_lines = _read_non_empty_lines(spec_path)
    if len(spec_lines) < 5:
        raise ValueError(
            f"TrackSpec.txt di {track_dir} minimal berisi nama, width, surface grip, "
            "dan dua titik centerline."
        )

    name = spec_lines[0]
    road_width = _parse_float(spec_lines[1], "road_width", spec_path, line_number=2)
    surface_grip, image_start_anchor, image_end_anchor, centerline_start_index = _parse_spec_metadata(
        spec_lines,
        spec_path,
    )
    centerline_points = _parse_points(
        spec_lines[centerline_start_index:],
        spec_path,
        first_line_number=centerline_start_index + 1,
    )
    racing_line_points = _parse_points(
        _read_non_empty_lines(racing_points_path),
        racing_points_path,
        first_line_number=1,
    )

    track = create_track_from_points(
        centerline_points=centerline_points,
        racing_line_points=racing_line_points,
        road_width=road_width,
        name=name,
        surface_grip=surface_grip,
    )
    return TrackAsset(
        track=track,
        cover_path=cover_path,
        image_path=image_path,
        directory=track_dir,
        image_start_anchor=image_start_anchor,
        image_end_anchor=image_end_anchor,
    )


def _read_non_empty_lines(path: Path) -> List[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _parse_points(lines: List[str], path: Path, first_line_number: int) -> List[Point]:
    points: List[Point] = []
    for offset, line in enumerate(lines):
        line_number = first_line_number + offset
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f"{path} line {line_number} harus berformat: x y")

        x_value = _parse_float(parts[0], "x", path, line_number)
        y_value = _parse_float(parts[1], "y", path, line_number)
        points.append((x_value, y_value))

    return points


def _parse_spec_metadata(lines: List[str], path: Path) -> tuple[float, Point, Point, int]:
    line3_anchor = _try_parse_point(lines[2])
    line4_anchor = _try_parse_point(lines[3]) if len(lines) > 3 else None
    if (
        line3_anchor is not None
        and line4_anchor is not None
        and _is_relative_anchor(line3_anchor)
        and _is_relative_anchor(line4_anchor)
    ):
        surface_grip, centerline_start_index = _parse_surface_after_anchor(lines, path)
        return surface_grip, line3_anchor, line4_anchor, centerline_start_index

    surface_grip = _parse_float(lines[2], "surface_grip", path, line_number=3)
    image_start_anchor, image_end_anchor, centerline_start_index = _parse_optional_image_anchors(lines)
    return surface_grip, image_start_anchor, image_end_anchor, centerline_start_index


def _parse_surface_after_anchor(lines: List[str], path: Path) -> tuple[float, int]:
    if len(lines) > 4 and _try_parse_point(lines[4]) is None:
        return _parse_float(lines[4], "surface_grip", path, line_number=5), 5

    return 1.0, 4


def _parse_optional_image_anchors(lines: List[str]) -> tuple[Point, Point, int]:
    if len(lines) < 7:
        return (0.0, 0.0), (1.0, 0.0), 3

    start_anchor = _try_parse_point(lines[3])
    end_anchor = _try_parse_point(lines[4])
    if (
        start_anchor is None
        or end_anchor is None
        or not _is_relative_anchor(start_anchor)
        or not _is_relative_anchor(end_anchor)
    ):
        return (0.0, 0.0), (1.0, 0.0), 3

    return start_anchor, end_anchor, 5


def _try_parse_point(line: str) -> Optional[Point]:
    parts = line.split()
    if len(parts) != 2:
        return None

    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        return None


def _is_relative_anchor(point: Point) -> bool:
    return 0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0


def _parse_float(raw_value: str, field_name: str, path: Path, line_number: int) -> float:
    try:
        return float(raw_value)
    except ValueError as error:
        raise ValueError(f"{path} line {line_number}: {field_name} harus berupa angka.") from error


def _sort_key(path: Path) -> tuple[int, str]:
    try:
        return (0, f"{int(path.name):08d}")
    except ValueError:
        return (1, path.name.lower())
