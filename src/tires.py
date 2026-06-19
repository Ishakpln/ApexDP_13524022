from dataclasses import dataclass


@dataclass
class Tires:
    tire_grip: float

    def validate(self) -> None:
        if self.tire_grip < 0:
            raise ValueError("tire grip dari ban tidak boleh negatif.")
