from pathlib import Path
from typing import Iterable, List, Optional

from car import Car
from constants import ASSET_ROOT, PROJECT_ROOT
from spoiler import Spoiler
from tires import Tires


MAIN_OPTION = "Main"
NONE_OPTION = "None"
SLICK_TOTAL_GRIP = 2.0
ADDITIONAL_SPOILER_DOWNFORCE = 1.0


def load_cars(cars_dir: Optional[Path] = None) -> List[Car]:
    base_dir = cars_dir or _default_cars_dir()
    if not base_dir.exists():
        raise ValueError(f"Folder cars tidak ditemukan: {base_dir}")

    cars: List[Car] = []
    for car_dir in sorted(_iter_car_dirs(base_dir)):
        spec_path = car_dir / "spec.txt"
        if not spec_path.exists():
            raise ValueError(f"File spec.txt tidak ditemukan di folder {car_dir}")

        cars.extend(_load_car_variants(car_dir))

    if not cars:
        raise ValueError(f"Tidak ada mobil yang berhasil dimuat dari {base_dir}")

    return cars


def _default_cars_dir() -> Path:
    asset_cars_dir = ASSET_ROOT / "Cars"
    if asset_cars_dir.exists():
        return asset_cars_dir
    return PROJECT_ROOT / "Cars"


def _iter_car_dirs(base_dir: Path) -> Iterable[Path]:
    return (path for path in base_dir.iterdir() if path.is_dir())


def _load_car_variants(car_dir: Path) -> List[Car]:
    lines = (car_dir / "spec.txt").read_text(encoding="utf-8").splitlines()
    if len(lines) < 11:
        raise ValueError(f"Format spec.txt tidak lengkap: {car_dir / 'spec.txt'}")

    tire_options = _build_options(lines[0])
    spoiler_options = _build_options(lines[2])
    tire_button_position = _parse_position(lines[1], "tire button", car_dir)
    spoiler_button_position = _parse_position(
        lines[3],
        "spoiler button",
        car_dir,
        allow_hidden=lines[2].strip().lower() == NONE_OPTION.lower(),
    )

    data_lines = [line.strip() for line in lines if line.strip()]
    if len(data_lines) < 11:
        raise ValueError(f"Format spec.txt tidak lengkap: {car_dir / 'spec.txt'}")

    width = _parse_float(data_lines[4], "width", car_dir)
    name = data_lines[5]
    mass = _parse_float(data_lines[6], "mass", car_dir)
    base_tire_grip = _parse_float(data_lines[7], "base_tire_grip", car_dir)
    braking_deceleration = _parse_float(data_lines[8], "braking_deceleration", car_dir)
    acceleration = _parse_float(data_lines[9], "acceleration", car_dir)
    base_downforce_coeff = _parse_float(data_lines[10], "base_downforce_coeff", car_dir)

    cars: List[Car] = []
    sound_path = _find_sound_path(car_dir)
    sim_image_path = _find_sim_image_path(car_dir)
    for tire_option in tire_options:
        for spoiler_option in spoiler_options:
            image_path = _find_image_path(car_dir, tire_option, spoiler_option)
            car = Car(
                name=name,
                imagePath=image_path,
                simImagePath=sim_image_path,
                SoundPath=sound_path,
                width=width,
                mass=mass,
                base_tire_grip=base_tire_grip,
                braking_deceleration=braking_deceleration,
                acceleration=acceleration,
                base_downforce_coeff=base_downforce_coeff,
                tire_option=tire_option,
                spoiler_option=spoiler_option,
                tire_button_position=tire_button_position,
                spoiler_button_position=spoiler_button_position,
            )

            if tire_option != MAIN_OPTION:
                car.install_tires(Tires(tire_grip=max(0.0, SLICK_TOTAL_GRIP - base_tire_grip)))
            if spoiler_option != MAIN_OPTION:
                car.install_spoiler(Spoiler(downforce=ADDITIONAL_SPOILER_DOWNFORCE))

            car.validate()
            cars.append(car)

    return cars


def _build_options(raw_option: str) -> List[str]:
    option = raw_option.strip()
    options = [MAIN_OPTION]
    if option and option.lower() != NONE_OPTION.lower():
        options.append(option)
    return options


def _parse_float(raw_value: str, field_name: str, car_dir: Path) -> float:
    try:
        return float(raw_value)
    except ValueError as error:
        raise ValueError(f"Nilai {field_name} tidak valid di {car_dir / 'spec.txt'}") from error


def _parse_position(
    raw_value: str,
    field_name: str,
    car_dir: Path,
    allow_hidden: bool = False,
) -> tuple[float, float]:
    try:
        x_raw, y_raw = raw_value.split()
        x = float(x_raw)
        y = float(y_raw)
    except ValueError as error:
        raise ValueError(f"Posisi {field_name} tidak valid di {car_dir / 'spec.txt'}") from error

    if allow_hidden and x < 0 and y < 0:
        return (0.0, 0.0)

    if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
        raise ValueError(
            f"Posisi {field_name} harus berada di interval 0 sampai 1 "
            f"di {car_dir / 'spec.txt'}"
        )

    return (x, y)


def _find_image_path(car_dir: Path, tire_option: str, spoiler_option: str) -> str:
    file_name = f"{tire_option}_{spoiler_option}.png"
    exact_path = car_dir / file_name
    if exact_path.exists():
        return _relative_asset_path(exact_path)

    target_stem = Path(file_name).stem.lower()
    for image_path in car_dir.glob("*.png"):
        if image_path.stem.lower() == target_stem:
            return _relative_asset_path(image_path)

    if tire_option == MAIN_OPTION and spoiler_option == MAIN_OPTION:
        for image_path in car_dir.glob("*.png"):
            if image_path.stem.lower() == "main":
                return _relative_asset_path(image_path)

    raise ValueError(
        "Gambar mobil tidak ditemukan untuk kombinasi "
        f"ban {tire_option} dan spoiler {spoiler_option} di {car_dir}"
    )


def _find_sound_path(car_dir: Path) -> str:
    exact_path = car_dir / "Sound.wav"
    if exact_path.exists():
        return _relative_asset_path(exact_path)

    for sound_path in car_dir.iterdir():
        if sound_path.is_file() and sound_path.name.lower() == "sound.wav":
            return _relative_asset_path(sound_path)

    return ""


def _find_sim_image_path(car_dir: Path) -> str:
    exact_path = car_dir / "Sim.png"
    if exact_path.exists():
        return _relative_asset_path(exact_path)

    for image_path in car_dir.glob("*.png"):
        if image_path.stem.lower() == "sim":
            return _relative_asset_path(image_path)

    raise ValueError(f"Sim.png tidak ditemukan di folder mobil {car_dir}")


def _relative_asset_path(image_path: Path) -> str:
    return image_path.relative_to(PROJECT_ROOT).as_posix()
