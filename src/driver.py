from car_loader import load_cars
from gui import close_gui, run_simulation_gui
from track_loader import TrackAsset, load_tracks


class BackToCarSelection(Exception):
    pass


def choose_car():
    from gui import choose_car_gui

    selected_car = choose_car_gui(load_cars())
    if selected_car is None:
        raise KeyboardInterrupt
    return selected_car


def choose_track() -> TrackAsset:
    from gui import choose_track_gui

    selected_track = choose_track_gui(load_tracks())
    if selected_track is None:
        raise KeyboardInterrupt
    if selected_track.action == "back":
        raise BackToCarSelection
    if selected_track.asset is None:
        raise KeyboardInterrupt
    return selected_track.asset


def main() -> None:
    try:
        while True:
            car = choose_car()
            while True:
                try:
                    track_asset = choose_track()
                except BackToCarSelection:
                    break

                screen_result = run_simulation_gui(car, track_asset)
                if screen_result is None:
                    raise KeyboardInterrupt
                if screen_result.action == "back":
                    continue
    except ValueError as error:
        close_gui()
        print()
        print("=" * 60)
        print("SIMULASI TIDAK DAPAT DIJALANKAN")
        print("=" * 60)
        print(f"Error: {error}")
        print("=" * 60)
    except KeyboardInterrupt:
        close_gui()


if __name__ == "__main__":
    main()
