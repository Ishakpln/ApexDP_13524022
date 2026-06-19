from dataclasses import dataclass


@dataclass
class Spoiler:
    downforce: float = 0.0

    def validate(self) -> None:
        if self.downforce < 0:
            raise ValueError("downforce spoiler tidak boleh negatif.")
