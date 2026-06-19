from dataclasses import dataclass, field
from typing import Tuple

from constants import EPSILON
from spoiler import Spoiler
from tires import Tires


@dataclass
class Car:
    name: str
    imagePath: str
    simImagePath: str
    SoundPath: str
    width: float
    mass: float
    base_tire_grip: float
    braking_deceleration: float
    acceleration: float
    base_downforce_coeff: float
    tire_option: str = "Main"
    spoiler_option: str = "Main"
    tire_button_position: Tuple[float, float] = (0.5, 0.75)
    spoiler_button_position: Tuple[float, float] = (0.3, 0.45)
    spoiler: Spoiler = field(default_factory=Spoiler)
    tires: Tires = field(default_factory=lambda: Tires(0.0))

    @property
    def tire_grip(self) -> float:
        return self.base_tire_grip + self.tires.tire_grip

    @property
    def downforce_coeff(self) -> float:
        return self.base_downforce_coeff + self.spoiler.downforce

    def install_spoiler(self, spoiler: Spoiler) -> None:
        spoiler.validate()
        self.spoiler = spoiler

    def install_tires(self, tires: Tires) -> None:
        tires.validate()
        self.tires = tires

    def validate(self) -> None:
        if self.width <= 0:
            raise ValueError("width mobil harus lebih besar dari 0.")
        if self.mass <= 0:
            raise ValueError("mass harus lebih besar dari 0.")
        if self.base_tire_grip < 0:
            raise ValueError("base tire grip mobil tidak boleh negatif.")
        if self.braking_deceleration < 0:
            raise ValueError("braking_deceleration tidak boleh negatif.")
        if self.acceleration < 0:
            raise ValueError("acceleration tidak boleh negatif.")
        if self.base_downforce_coeff < 0:
            raise ValueError("base downforce coefficient mobil tidak boleh negatif.")

        self.spoiler.validate()
        self.tires.validate()

        if self.tire_grip <= EPSILON:
            raise ValueError("total tire grip mobil harus lebih besar dari 0.")
        if self.downforce_coeff < 0:
            raise ValueError("total downforce coefficient mobil tidak boleh negatif.")
