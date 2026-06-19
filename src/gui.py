from collections import OrderedDict
from dataclasses import dataclass
import math
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pygame

from car import Car
from car_loader import MAIN_OPTION, load_cars
from constants import ASSET_ROOT, PROJECT_ROOT
from simulation_profile import (
    FAILURE_COAST_DURATION_SECONDS,
    SimulationFrame,
    SimulationProfile,
    build_simulation_profile,
)
from track import Track
from track_loader import TrackAsset, load_tracks


BASE_WINDOW_SIZE = (1280, 800)
TRANSITION_DURATION_MS = 650
SOUND_FADE_OUT_MS = 180
ACTION_BUTTON_SCALE = 0.6
FOOTER_INSTRUCTION_SCALE = ACTION_BUTTON_SCALE * 1.5
SWITCH_ARROW_SCALE = 0.7
BOTTOM_BAR_MARGIN = 45
RACING_ARROW_WIDTH_METERS = 1.0
RACING_ARROW_SPACING_METERS = 1.15
FAILURE_SPIN_DEGREES_PER_SECOND = 220.0
REPORT_POPUP_SCALE = 0.85
MAX_SPEED_INPUT_DIGITS = 4
MAX_INPUT_SPEED_KMH = 9999.0
ASSET_DIR = ASSET_ROOT
GUI_DIR = ASSET_DIR / "GUI"
ROOT_DIR = PROJECT_ROOT


@dataclass
class CarFamily:
    name: str
    variants: List[Car]
    tire_options: List[str]
    spoiler_options: List[str]


@dataclass
class ButtonHitbox:
    kind: str
    value: str
    rect: pygame.Rect


@dataclass
class SlideTransition:
    from_family_index: int
    to_family_index: int
    from_car: Car
    to_car: Car
    step: int
    started_at: int
    duration_ms: int = TRANSITION_DURATION_MS


@dataclass
class TrackSlideTransition:
    from_track_index: int
    to_track_index: int
    step: int
    started_at: int
    duration_ms: int = TRANSITION_DURATION_MS


@dataclass(frozen=True)
class TrackSelectionResult:
    action: str
    asset: Optional[TrackAsset] = None

    @property
    def track(self) -> Optional[Track]:
        return self.asset.track if self.asset is not None else None


@dataclass(frozen=True)
class SimulationScreenResult:
    action: str


def choose_car_gui(cars: Optional[List[Car]] = None) -> Optional[Car]:
    selector = CarSelectionGUI(cars or load_cars())
    return selector.run()


def choose_track_gui(tracks: Optional[List[TrackAsset]] = None) -> Optional[TrackSelectionResult]:
    selector = TrackSelectionGUI(tracks or load_tracks())
    return selector.run()


def run_simulation_gui(car: Car, track_asset: TrackAsset) -> Optional[SimulationScreenResult]:
    screen = SimulationGUI(car, track_asset)
    return screen.run()


def close_gui() -> None:
    if pygame.get_init():
        pygame.quit()


class CarSelectionGUI:
    def __init__(self, cars: List[Car]) -> None:
        os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        pygame.display.set_caption("Racing Line Car Selector")
        desktop_size = pygame.display.get_desktop_sizes()[0]
        self.screen = pygame.display.set_mode(desktop_size, pygame.NOFRAME)
        screen_rect = self.screen.get_rect()
        self.scale = min(
            screen_rect.width / BASE_WINDOW_SIZE[0],
            screen_rect.height / BASE_WINDOW_SIZE[1],
        )
        self.clock = pygame.time.Clock()

        self.families = _group_cars(cars)
        self.family_index = 0
        self.selected_tire = MAIN_OPTION
        self.selected_spoiler = MAIN_OPTION
        self.expanded_menu: Optional[str] = None
        self.transition: Optional[SlideTransition] = None
        self.hitboxes: List[ButtonHitbox] = []

        self.title_font = _font(["Century Gothic", "Segoe UI Light", "Segoe UI", "Arial"], self._scaled(52))
        self.option_font = _font(["Segoe UI", "Arial"], self._scaled(21), bold=False)
        self.option_bold_font = _font(["Segoe UI", "Arial"], self._scaled(21), bold=True)

        self.arrow_left = _load_image(GUI_DIR / "ArrowLeft.png")
        self.arrow_right = _load_image(GUI_DIR / "ArrowRight.png")
        self.footer = _load_image(GUI_DIR / "FooterInstruction.png")
        self.play = _load_image(GUI_DIR / "Play.png")
        self.image_cache: Dict[str, pygame.Surface] = {}
        self.scaled_background_cache: Dict[Tuple[str, Tuple[int, int]], pygame.Surface] = {}
        self.sound_cache: Dict[str, pygame.mixer.Sound] = {}
        self.rev_channel = pygame.mixer.Channel(0) if pygame.mixer.get_init() else None

    def run(self) -> Optional[Car]:
        while True:
            for event in pygame.event.get():
                result = self._handle_event(event)
                if result == "quit":
                    self._stop_rev_sound()
                    pygame.quit()
                    return None
                if result == "play":
                    selected_car = self.current_car
                    self._stop_rev_sound()
                    return selected_car

            self._draw()
            pygame.display.flip()
            self.clock.tick(60)

    @property
    def current_family(self) -> CarFamily:
        return self.families[self.family_index]

    @property
    def current_car(self) -> Car:
        for car in self.current_family.variants:
            if car.tire_option == self.selected_tire and car.spoiler_option == self.selected_spoiler:
                return car
        return self.current_family.variants[0]

    def _handle_event(self, event: pygame.event.Event) -> Optional[str]:
        if event.type == pygame.QUIT:
            return "quit"

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._stop_rev_sound()
                return "quit"
            if event.key in (pygame.K_LSHIFT, pygame.K_RSHIFT):
                if self.transition is None:
                    self._play_rev_sound()
                return None
            if self.transition is not None:
                return None
            if event.key in (pygame.K_a, pygame.K_LEFT):
                self._switch_family(-1)
            elif event.key in (pygame.K_d, pygame.K_RIGHT):
                self._switch_family(1)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return "play"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.transition is not None:
                return None
            mouse_pos = pygame.Vector2(event.pos)
            for hitbox in reversed(self.hitboxes):
                if hitbox.rect.collidepoint(mouse_pos):
                    return self._activate_hitbox(hitbox)
            self.expanded_menu = None

        return None

    def _scaled(self, value: int) -> int:
        return max(1, int(round(value * self.scale)))

    def _activate_hitbox(self, hitbox: ButtonHitbox) -> Optional[str]:
        if hitbox.kind == "previous":
            self._switch_family(-1)
        elif hitbox.kind == "next":
            self._switch_family(1)
        elif hitbox.kind == "play":
            return "play"
        elif hitbox.kind == "toggle_tires":
            self.expanded_menu = None if self.expanded_menu == "tires" else "tires"
        elif hitbox.kind == "toggle_spoiler":
            self.expanded_menu = None if self.expanded_menu == "spoiler" else "spoiler"
        elif hitbox.kind == "tire_option":
            self.selected_tire = hitbox.value
            self.expanded_menu = None
        elif hitbox.kind == "spoiler_option":
            self.selected_spoiler = hitbox.value
            self.expanded_menu = None

        return None

    def _switch_family(self, step: int) -> None:
        if self.transition is not None or len(self.families) <= 1:
            return

        self._stop_rev_sound()
        to_family_index = (self.family_index + step) % len(self.families)
        self.transition = SlideTransition(
            from_family_index=self.family_index,
            to_family_index=to_family_index,
            from_car=self.current_car,
            to_car=self._default_car_for_family(to_family_index),
            step=step,
            started_at=pygame.time.get_ticks(),
        )
        self.expanded_menu = None

    def _draw(self) -> None:
        self.hitboxes = []
        if self.transition is not None:
            if self._transition_finished(self.transition):
                self._finish_transition(self.transition)
            else:
                self._draw_transition(self.transition)
                self._draw_arrows()
                self._draw_footer()
                self._draw_play()
                return

        car = self.current_car
        background = self._get_scaled_background(car)

        background_rect = self._draw_background(background)
        self._draw_title(car.name)
        self._draw_arrows()
        self._draw_stats(car)
        self._draw_option_controls(car, background_rect)
        self._draw_footer()
        self._draw_play()

    def _transition_finished(self, transition: SlideTransition) -> bool:
        elapsed = pygame.time.get_ticks() - transition.started_at
        return elapsed >= transition.duration_ms

    def _finish_transition(self, transition: SlideTransition) -> None:
        self.family_index = transition.to_family_index
        self.selected_tire = MAIN_OPTION
        self.selected_spoiler = MAIN_OPTION
        self.expanded_menu = None
        self.transition = None

    def _draw_transition(self, transition: SlideTransition) -> None:
        screen_rect = self.screen.get_rect()
        self.screen.fill((205, 205, 205))

        elapsed = pygame.time.get_ticks() - transition.started_at
        progress = min(1.0, max(0.0, elapsed / transition.duration_ms))
        eased_progress = _ease_in_out_bezier(progress)
        slide_distance = int(round(screen_rect.width * eased_progress))

        from_background = self._get_scaled_background(transition.from_car)
        to_background = self._get_scaled_background(transition.to_car)

        from_rect = from_background.get_rect(center=screen_rect.center)
        to_rect = to_background.get_rect(center=screen_rect.center)

        from_offset = -transition.step * slide_distance
        to_offset = from_offset + transition.step * screen_rect.width

        self.screen.blit(from_background, from_rect.move(from_offset, 0))
        self.screen.blit(to_background, to_rect.move(to_offset, 0))

    def _draw_background(self, scaled_background: pygame.Surface) -> pygame.Rect:
        screen_rect = self.screen.get_rect()
        self.screen.fill((205, 205, 205))
        background_rect = scaled_background.get_rect(center=screen_rect.center)
        self.screen.blit(scaled_background, background_rect)
        return background_rect

    def _default_car_for_family(self, family_index: int) -> Car:
        family = self.families[family_index]
        for car in family.variants:
            if car.tire_option == MAIN_OPTION and car.spoiler_option == MAIN_OPTION:
                return car
        return family.variants[0]

    def _get_scaled_background(self, car: Car) -> pygame.Surface:
        screen_rect = self.screen.get_rect()
        cache_key = (car.imagePath, screen_rect.size)
        if cache_key not in self.scaled_background_cache:
            self.scaled_background_cache[cache_key] = self._scale_background(self._get_background(car))
        return self.scaled_background_cache[cache_key]

    def _scale_background(self, background: pygame.Surface) -> pygame.Surface:
        screen_rect = self.screen.get_rect()
        bg_width, bg_height = background.get_size()
        scale = max(screen_rect.width / bg_width, screen_rect.height / bg_height)
        scaled_size = (int(round(bg_width * scale)), int(round(bg_height * scale)))
        return pygame.transform.smoothscale(background, scaled_size)

    def _draw_title(self, title: str) -> None:
        screen_rect = self.screen.get_rect()
        text = self.title_font.render(title, True, (0, 0, 0))
        rect = text.get_rect(center=(screen_rect.centerx, self._scaled(125)))
        self.screen.blit(text, rect)

    def _draw_arrows(self) -> None:
        screen_rect = self.screen.get_rect()
        arrow_size = self._scaled(int(round(86 * SWITCH_ARROW_SCALE)))
        side_margin = self._scaled(80)
        left = pygame.transform.smoothscale(self.arrow_left, (arrow_size, arrow_size))
        right = pygame.transform.smoothscale(self.arrow_right, (arrow_size, arrow_size))
        left_rect = left.get_rect(center=(side_margin, screen_rect.centery))
        right_rect = right.get_rect(center=(screen_rect.width - side_margin, screen_rect.centery))

        self.screen.blit(left, left_rect)
        self.screen.blit(right, right_rect)
        self.hitboxes.append(ButtonHitbox("previous", "", left_rect))
        self.hitboxes.append(ButtonHitbox("next", "", right_rect))

    def _draw_stats(self, car: Car) -> None:
        screen_rect = self.screen.get_rect()
        stat_scale = 0.8
        stat_font = _font(["Segoe UI", "Arial"], max(1, int(round(self._scaled(23) * stat_scale))))
        stats = [
            ("Weight", f"{car.mass:.0f} kg"),
            ("Tire Grip", f"{car.tire_grip:.2f}"),
            ("Brake", f"{car.braking_deceleration:.0f} m/s2"),
            ("Acceleration", f"{car.acceleration:.0f} m/s2"),
            ("Downforce", f"{car.downforce_coeff:.2f} kg/m"),
        ]
        line_height = stat_font.get_linesize()
        row_gap = int(round(self._scaled(8) * stat_scale))
        vertical_padding = int(round(self._scaled(28) * stat_scale))
        content_height = len(stats) * line_height + (len(stats) - 1) * row_gap
        panel_height = content_height + vertical_padding * 2
        panel_rect = pygame.Rect(
            int(round(self._scaled(50) * stat_scale)),
            screen_rect.height - panel_height - int(round(self._scaled(50) * stat_scale)),
            int(round(self._scaled(300) * stat_scale)),
            panel_height,
        )
        panel = pygame.Surface(panel_rect.size, pygame.SRCALPHA)
        panel.fill((80, 80, 80, 165))
        self.screen.blit(panel, panel_rect)

        y = panel_rect.y + (panel_rect.height - content_height) // 2
        for label, value in stats:
            label_text = stat_font.render(label, True, (255, 255, 255))
            colon_text = stat_font.render(":", True, (255, 255, 255))
            value_text = stat_font.render(value, True, (255, 255, 255))

            self.screen.blit(label_text, (panel_rect.x + int(round(self._scaled(18) * stat_scale)), y))
            self.screen.blit(colon_text, (panel_rect.x + int(round(self._scaled(150) * stat_scale)), y))
            self.screen.blit(value_text, (panel_rect.x + int(round(self._scaled(172) * stat_scale)), y))
            y += line_height + row_gap

    def _draw_option_controls(self, car: Car, background_rect: pygame.Rect) -> None:
        self._draw_option_menu(
            label="Tires",
            toggle_kind="toggle_tires",
            option_kind="tire_option",
            options=self.current_family.tire_options,
            selected_value=self.selected_tire,
            expanded=self.expanded_menu == "tires",
            relative_position=car.tire_button_position,
            background_rect=background_rect,
        )

        if len(self.current_family.spoiler_options) > 1:
            self._draw_option_menu(
                label="Spoiler",
                toggle_kind="toggle_spoiler",
                option_kind="spoiler_option",
                options=self.current_family.spoiler_options,
                selected_value=self.selected_spoiler,
                expanded=self.expanded_menu == "spoiler",
                relative_position=car.spoiler_button_position,
                background_rect=background_rect,
            )

    def _draw_option_menu(
        self,
        label: str,
        toggle_kind: str,
        option_kind: str,
        options: List[str],
        selected_value: str,
        expanded: bool,
        relative_position: Tuple[float, float],
        background_rect: pygame.Rect,
    ) -> None:
        x = background_rect.x + int(background_rect.width * relative_position[0])
        y = background_rect.y + int(background_rect.height * relative_position[1])
        label_rect = self._draw_pill(label, (x, y), selected=False, anchor="center")
        self.hitboxes.append(ButtonHitbox(toggle_kind, "", label_rect))

        if not expanded:
            return

        gap = self._scaled(10)
        option_sizes = [self._pill_size(option, option == selected_value) for option in options]
        row_width = sum(width for width, _ in option_sizes) + gap * (len(options) - 1)
        screen_rect = self.screen.get_rect()
        next_x = max(
            self._scaled(16),
            min(label_rect.left, screen_rect.width - row_width - self._scaled(16)),
        )
        option_y = label_rect.bottom + gap

        for option in options:
            is_selected = option == selected_value
            rect = self._draw_pill(
                option,
                (next_x, option_y),
                selected=is_selected,
                anchor="topleft",
            )
            self.hitboxes.append(ButtonHitbox(option_kind, option, rect))
            next_x = rect.right + gap

    def _draw_pill(
        self,
        text: str,
        position: Tuple[int, int],
        selected: bool,
        anchor: str,
    ) -> pygame.Rect:
        font = self.option_bold_font if selected else self.option_font
        text_surface = font.render(text, True, (20, 20, 20))
        width = max(self._scaled(70), text_surface.get_width() + self._scaled(34))
        height = self._scaled(42)
        rect = pygame.Rect(0, 0, width, height)
        setattr(rect, anchor, position)

        shadow_rect = rect.move(self._scaled(2), self._scaled(3))
        shadow = pygame.Surface(shadow_rect.size, pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 45), shadow.get_rect(), border_radius=self._scaled(7))
        self.screen.blit(shadow, shadow_rect)
        fill = (255, 255, 255) if not selected else (235, 235, 235)
        pygame.draw.rect(self.screen, fill, rect, border_radius=self._scaled(7))

        text_rect = text_surface.get_rect(center=rect.center)
        self.screen.blit(text_surface, text_rect)
        return rect

    def _pill_size(self, text: str, selected: bool) -> Tuple[int, int]:
        font = self.option_bold_font if selected else self.option_font
        text_surface = font.render(text, True, (20, 20, 20))
        width = max(self._scaled(70), text_surface.get_width() + self._scaled(34))
        return width, self._scaled(42)

    def _draw_footer(self) -> None:
        screen_rect = self.screen.get_rect()
        bottom_y = _bottom_bar_baseline(screen_rect, self._scaled)
        footer = pygame.transform.smoothscale(
            self.footer,
            (
                self._scaled(int(round(430 * FOOTER_INSTRUCTION_SCALE))),
                self._scaled(int(round(35 * FOOTER_INSTRUCTION_SCALE))),
            ),
        )
        footer_rect = footer.get_rect(midbottom=(screen_rect.centerx, bottom_y))
        self.screen.blit(footer, footer_rect)

    def _draw_play(self) -> None:
        screen_rect = self.screen.get_rect()
        bottom_y = _bottom_bar_baseline(screen_rect, self._scaled)
        play = pygame.transform.smoothscale(
            self.play,
            (
                self._scaled(int(round(170 * ACTION_BUTTON_SCALE))),
                self._scaled(int(round(77 * ACTION_BUTTON_SCALE))),
            ),
        )
        play_rect = play.get_rect(
            bottomright=(screen_rect.width - self._scaled(BOTTOM_BAR_MARGIN), bottom_y)
        )
        self.screen.blit(play, play_rect)
        self.hitboxes.append(ButtonHitbox("play", "", play_rect))

    def _get_background(self, car: Car) -> pygame.Surface:
        if car.imagePath not in self.image_cache:
            self.image_cache[car.imagePath] = _load_image(ROOT_DIR / car.imagePath)
        return self.image_cache[car.imagePath]

    def _play_rev_sound(self) -> None:
        if self.rev_channel is None:
            return

        if self.rev_channel.get_busy():
            self._stop_rev_sound()
            return

        sound_path = self.current_car.SoundPath
        if not sound_path:
            return

        if sound_path not in self.sound_cache:
            absolute_sound_path = ROOT_DIR / sound_path
            try:
                self.sound_cache[sound_path] = pygame.mixer.Sound(absolute_sound_path)
            except pygame.error:
                return

        self.rev_channel.play(self.sound_cache[sound_path])

    def _stop_rev_sound(self) -> None:
        if self.rev_channel is not None and self.rev_channel.get_busy():
            self.rev_channel.fadeout(SOUND_FADE_OUT_MS)


class TrackSelectionGUI:
    def __init__(self, tracks: List[TrackAsset]) -> None:
        if not tracks:
            raise ValueError("Tidak ada track yang bisa dipilih.")

        os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
        pygame.init()
        pygame.display.set_caption("Racing Line Track Selector")
        desktop_size = pygame.display.get_desktop_sizes()[0]
        self.screen = pygame.display.set_mode(desktop_size, pygame.NOFRAME)
        screen_rect = self.screen.get_rect()
        self.scale = min(
            screen_rect.width / BASE_WINDOW_SIZE[0],
            screen_rect.height / BASE_WINDOW_SIZE[1],
        )
        self.clock = pygame.time.Clock()

        self.tracks = tracks
        self.track_index = 0
        self.transition: Optional[TrackSlideTransition] = None
        self.hitboxes: List[ButtonHitbox] = []

        self.title_font = _font(["Century Gothic", "Segoe UI Light", "Segoe UI", "Arial"], self._scaled(52))
        self.stat_font = _font(["Segoe UI", "Arial"], self._scaled(16))

        self.arrow_left = _load_image(GUI_DIR / "ArrowLeft.png")
        self.arrow_right = _load_image(GUI_DIR / "ArrowRight.png")
        self.footer = _load_image(GUI_DIR / "FooterInstruction2.png")
        self.play = _load_image(GUI_DIR / "Play.png")
        self.back = _load_image(GUI_DIR / "Back.png")
        self.cover_cache: Dict[Tuple[Path, Tuple[int, int]], pygame.Surface] = {}

    def run(self) -> Optional[TrackSelectionResult]:
        while True:
            for event in pygame.event.get():
                result = self._handle_event(event)
                if result == "quit":
                    pygame.quit()
                    return None
                if result == "back":
                    return TrackSelectionResult(action="back")
                if result == "play":
                    selected_asset = self.current_asset
                    return TrackSelectionResult(action="play", asset=selected_asset)

            self._draw()
            pygame.display.flip()
            self.clock.tick(60)

    @property
    def current_asset(self) -> TrackAsset:
        return self.tracks[self.track_index]

    @property
    def current_track(self) -> Track:
        return self.current_asset.track

    def _handle_event(self, event: pygame.event.Event) -> Optional[str]:
        if event.type == pygame.QUIT:
            return "quit"

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return "back"
            if self.transition is not None:
                return None
            if event.key in (pygame.K_a, pygame.K_LEFT):
                self._switch_track(-1)
            elif event.key in (pygame.K_d, pygame.K_RIGHT):
                self._switch_track(1)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return "play"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.transition is not None:
                return None
            mouse_pos = pygame.Vector2(event.pos)
            for hitbox in reversed(self.hitboxes):
                if hitbox.rect.collidepoint(mouse_pos):
                    return self._activate_hitbox(hitbox)

        return None

    def _scaled(self, value: int) -> int:
        return max(1, int(round(value * self.scale)))

    def _activate_hitbox(self, hitbox: ButtonHitbox) -> Optional[str]:
        if hitbox.kind == "previous":
            self._switch_track(-1)
        elif hitbox.kind == "next":
            self._switch_track(1)
        elif hitbox.kind == "play":
            return "play"
        elif hitbox.kind == "back":
            return "back"

        return None

    def _switch_track(self, step: int) -> None:
        if self.transition is not None or len(self.tracks) <= 1:
            return

        to_track_index = (self.track_index + step) % len(self.tracks)
        self.transition = TrackSlideTransition(
            from_track_index=self.track_index,
            to_track_index=to_track_index,
            step=step,
            started_at=pygame.time.get_ticks(),
        )

    def _draw(self) -> None:
        self.hitboxes = []
        if self.transition is not None:
            if self._transition_finished(self.transition):
                self._finish_transition(self.transition)
            else:
                self._draw_transition(self.transition)
                self._draw_arrows()
                self._draw_back()
                self._draw_footer()
                self._draw_play()
                return

        self.screen.fill((225, 225, 225))
        self._draw_track_card(self.current_asset, offset_x=0)
        self._draw_arrows()
        self._draw_back()
        self._draw_footer()
        self._draw_play()

    def _transition_finished(self, transition: TrackSlideTransition) -> bool:
        elapsed = pygame.time.get_ticks() - transition.started_at
        return elapsed >= transition.duration_ms

    def _finish_transition(self, transition: TrackSlideTransition) -> None:
        self.track_index = transition.to_track_index
        self.transition = None

    def _draw_transition(self, transition: TrackSlideTransition) -> None:
        screen_rect = self.screen.get_rect()
        self.screen.fill((225, 225, 225))

        elapsed = pygame.time.get_ticks() - transition.started_at
        progress = min(1.0, max(0.0, elapsed / transition.duration_ms))
        eased_progress = _ease_in_out_bezier(progress)
        slide_distance = int(round(screen_rect.width * eased_progress))

        from_offset = -transition.step * slide_distance
        to_offset = from_offset + transition.step * screen_rect.width
        self._draw_track_card(self.tracks[transition.from_track_index], offset_x=from_offset)
        self._draw_track_card(self.tracks[transition.to_track_index], offset_x=to_offset)

    def _draw_track_card(self, asset: TrackAsset, offset_x: int) -> pygame.Rect:
        screen_rect = self.screen.get_rect()
        track = asset.track

        title = track.name or asset.directory.name
        title_surface = self.title_font.render(title, True, (0, 0, 0))
        title_rect = title_surface.get_rect(
            center=(screen_rect.centerx + offset_x, self._scaled(125))
        )
        self.screen.blit(title_surface, title_rect)

        cover = self._get_scaled_cover(asset)
        cover_rect = cover.get_rect(
            center=(screen_rect.centerx + offset_x, screen_rect.centery)
        )
        self.screen.blit(cover, cover_rect)
        self._draw_track_stats(track, cover_rect)
        return cover_rect

    def _get_scaled_cover(self, asset: TrackAsset) -> pygame.Surface:
        screen_rect = self.screen.get_rect()
        cache_key = (asset.cover_path, screen_rect.size)
        if cache_key in self.cover_cache:
            return self.cover_cache[cache_key]

        cover = _load_image(asset.cover_path)
        max_width = self._scaled(570)
        max_height = self._scaled(320)
        scale = min(max_width / cover.get_width(), max_height / cover.get_height())
        scaled_size = (
            max(1, int(round(cover.get_width() * scale))),
            max(1, int(round(cover.get_height() * scale))),
        )
        scaled_cover = pygame.transform.smoothscale(cover, scaled_size)
        self.cover_cache[cache_key] = scaled_cover
        return scaled_cover

    def _draw_track_stats(self, track: Track, cover_rect: pygame.Rect) -> None:
        panel_height = min(self._scaled(56), cover_rect.height)
        panel_rect = pygame.Rect(
            cover_rect.x,
            cover_rect.bottom - panel_height,
            cover_rect.width,
            panel_height,
        )
        panel = pygame.Surface(panel_rect.size, pygame.SRCALPHA)
        panel.fill((35, 35, 35, 160))
        self.screen.blit(panel, panel_rect)

        stats = [
            ("Surface Grip", f"{track.surface_grip:g}"),
            ("Width", f"{track.road_width:g} m"),
        ]
        label_x = panel_rect.x + self._scaled(24)
        value_x = panel_rect.x + self._scaled(130)
        y = panel_rect.y + self._scaled(8)
        row_gap = self._scaled(24)

        for label, value in stats:
            label_text = self.stat_font.render(label, True, (255, 255, 255))
            value_text = self.stat_font.render(value, True, (255, 255, 255))
            self.screen.blit(label_text, (label_x, y))
            self.screen.blit(value_text, (value_x, y))
            y += row_gap

    def _draw_arrows(self) -> None:
        screen_rect = self.screen.get_rect()
        arrow_size = self._scaled(int(round(86 * SWITCH_ARROW_SCALE)))
        side_margin = self._scaled(80)
        left = pygame.transform.smoothscale(self.arrow_left, (arrow_size, arrow_size))
        right = pygame.transform.smoothscale(self.arrow_right, (arrow_size, arrow_size))
        left_rect = left.get_rect(center=(side_margin, screen_rect.centery))
        right_rect = right.get_rect(center=(screen_rect.width - side_margin, screen_rect.centery))

        self.screen.blit(left, left_rect)
        self.screen.blit(right, right_rect)
        self.hitboxes.append(ButtonHitbox("previous", "", left_rect))
        self.hitboxes.append(ButtonHitbox("next", "", right_rect))

    def _draw_back(self) -> None:
        screen_rect = self.screen.get_rect()
        bottom_y = _bottom_bar_baseline(screen_rect, self._scaled)
        back = pygame.transform.smoothscale(
            self.back,
            (
                self._scaled(int(round(155 * ACTION_BUTTON_SCALE))),
                self._scaled(int(round(77 * ACTION_BUTTON_SCALE))),
            ),
        )
        back_rect = back.get_rect(
            bottomleft=(self._scaled(BOTTOM_BAR_MARGIN), bottom_y)
        )
        self.screen.blit(back, back_rect)
        self.hitboxes.append(ButtonHitbox("back", "", back_rect))

    def _draw_footer(self) -> None:
        screen_rect = self.screen.get_rect()
        bottom_y = _bottom_bar_baseline(screen_rect, self._scaled)
        footer = pygame.transform.smoothscale(
            self.footer,
            (
                self._scaled(int(round(430 * FOOTER_INSTRUCTION_SCALE))),
                self._scaled(int(round(35 * FOOTER_INSTRUCTION_SCALE))),
            ),
        )
        footer_rect = footer.get_rect(midbottom=(screen_rect.centerx, bottom_y))
        self.screen.blit(footer, footer_rect)

    def _draw_play(self) -> None:
        screen_rect = self.screen.get_rect()
        bottom_y = _bottom_bar_baseline(screen_rect, self._scaled)
        play = pygame.transform.smoothscale(
            self.play,
            (
                self._scaled(int(round(170 * ACTION_BUTTON_SCALE))),
                self._scaled(int(round(77 * ACTION_BUTTON_SCALE))),
            ),
        )
        play_rect = play.get_rect(
            bottomright=(screen_rect.width - self._scaled(BOTTOM_BAR_MARGIN), bottom_y)
        )
        self.screen.blit(play, play_rect)
        self.hitboxes.append(ButtonHitbox("play", "", play_rect))


class SimulationGUI:
    def __init__(self, car: Car, track_asset: TrackAsset) -> None:
        os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
        pygame.init()
        pygame.display.set_caption("Racing Line Simulation")
        desktop_size = pygame.display.get_desktop_sizes()[0]
        self.screen = pygame.display.set_mode(desktop_size, pygame.NOFRAME)
        screen_rect = self.screen.get_rect()
        self.scale = min(
            screen_rect.width / BASE_WINDOW_SIZE[0],
            screen_rect.height / BASE_WINDOW_SIZE[1],
        )
        self.clock = pygame.time.Clock()

        self.car = car
        self.track_asset = track_asset
        self.track = track_asset.track
        self.input_speed = 0.0
        self.input_speed_text = ""
        self.input_field_active = False
        self.dragging_timeline = False
        self.timeline_bar_rect: Optional[pygame.Rect] = None
        self.report_dismissed = False
        self.running = False
        self.started_at = 0
        self.paused_elapsed = 0.0
        self.profile_error: Optional[str] = None
        self.reference_profile: Optional[SimulationProfile] = None
        self.profile: Optional[SimulationProfile] = None
        self.hitboxes: List[ButtonHitbox] = []

        self.title_font = _font(["Century Gothic", "Segoe UI Light", "Segoe UI", "Arial"], self._scaled(48))
        self.panel_title_font = _font(["Segoe UI", "Arial"], self._scaled(25), bold=True)
        self.panel_subtitle_font = _font(["Segoe UI", "Arial"], self._scaled(18))
        self.info_font = _font(["Segoe UI", "Arial"], self._scaled(15))
        self.card_title_font = _font(["Segoe UI", "Arial"], self._scaled(28))
        self.card_unit_font = _font(["Segoe UI", "Arial"], self._scaled(30))
        self.card_hint_font = _font(["Segoe UI", "Arial"], self._scaled(14))
        self.popup_title_font = _font(["Segoe UI", "Arial"], self._report_scaled(36), bold=True)
        self.popup_subtitle_font = _font(["Segoe UI", "Arial"], self._report_scaled(20))
        self.popup_body_font = _font(["Segoe UI", "Arial"], self._report_scaled(21))

        self.back = _load_image(GUI_DIR / "Back.png")
        self.play = _load_image(GUI_DIR / "Play.png")
        self.try_again = _load_image(GUI_DIR / "TryAgain.png")
        self.close = _load_image(GUI_DIR / "Close.png")
        self.simulation_image = _load_image(track_asset.image_path)
        self.car_image = _load_image(ROOT_DIR / car.simImagePath)
        self.racing_arrow_images = {
            index: _load_image(GUI_DIR / "Arrow" / f"{index}.png")
            for index in range(1, 8)
        }
        self.racing_arrow_cache: Dict[Tuple[int, int], pygame.Surface] = {}

        self._build_reference_profile()
        self._rebuild_profile()

    def run(self) -> Optional[SimulationScreenResult]:
        while True:
            for event in pygame.event.get():
                result = self._handle_event(event)
                if result == "quit":
                    pygame.quit()
                    return None
                if result == "back":
                    return SimulationScreenResult(action="back")

            self._draw()
            pygame.display.flip()
            self.clock.tick(60)

    def _handle_event(self, event: pygame.event.Event) -> Optional[str]:
        if event.type == pygame.QUIT:
            return "quit"

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging_timeline = False
            return None

        if event.type == pygame.MOUSEMOTION and self.dragging_timeline:
            self._seek_timeline(float(event.pos[0]))
            return None

        if event.type == pygame.KEYDOWN:
            if self._should_draw_report_popup():
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._try_again_after_report()
                    return None
                if event.key == pygame.K_ESCAPE:
                    self.report_dismissed = True
                return None

            if event.key == pygame.K_ESCAPE:
                return "back"

            if self.input_field_active:
                self._handle_speed_input_key(event)
                return None

            if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._toggle_play()
            elif event.key in (pygame.K_UP, pygame.K_w):
                self._adjust_input_speed(10.0 if event.mod & pygame.KMOD_SHIFT else 1.0)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self._adjust_input_speed(-10.0 if event.mod & pygame.KMOD_SHIFT else -1.0)

        if event.type == pygame.MOUSEWHEEL:
            if self._should_draw_report_popup():
                return None
            self._adjust_input_speed(float(event.y))

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mouse_pos = pygame.Vector2(event.pos)
            self.input_field_active = False
            for hitbox in reversed(self.hitboxes):
                if hitbox.rect.collidepoint(mouse_pos):
                    if hitbox.kind == "report_try_again":
                        self._try_again_after_report()
                        return None
                    if hitbox.kind == "report_close":
                        self.report_dismissed = True
                        return None
                    if hitbox.kind == "back":
                        return "back"
                    if hitbox.kind == "play":
                        self._toggle_play()
                        return None
                    elif hitbox.kind == "speed_input":
                        self.running = False
                        self.input_field_active = True
                        return None
                    elif hitbox.kind == "timeline":
                        self.running = False
                        self.dragging_timeline = True
                        self._seek_timeline(float(mouse_pos.x))
                        return None

            if self._should_draw_report_popup():
                return None

        return None

    def _scaled(self, value: int) -> int:
        return max(1, int(round(value * self.scale)))

    def _report_scaled(self, value: int) -> int:
        return max(1, int(round(self._scaled(value) * REPORT_POPUP_SCALE)))

    def _stage_rect(self) -> pygame.Rect:
        return _virtual_stage_rect(self.screen.get_rect(), self.scale)

    def _stage_x(self, value: int) -> int:
        return self._stage_rect().x + self._scaled(value)

    def _stage_y(self, value: int) -> int:
        return self._stage_rect().y + self._scaled(value)

    def _build_reference_profile(self) -> None:
        try:
            self.reference_profile = build_simulation_profile(
                self.car,
                self.track,
                0.0,
                validate_boundary=False,
            )
            self.profile_error = None
        except ValueError as error:
            self.reference_profile = None
            self.profile_error = str(error)

    def _rebuild_profile(self) -> None:
        if not self._has_speed_input():
            self.input_speed = 0.0
            self.profile = None
            self.profile_error = None
            self.running = False
            self.paused_elapsed = 0.0
            self.report_dismissed = False
            return

        try:
            self.input_speed = self._input_speed_mps()
            self.profile = build_simulation_profile(
                self.car,
                self.track,
                self.input_speed,
                validate_boundary=False,
            )
            self.profile_error = None
            self.report_dismissed = False
        except ValueError as error:
            self.profile = None
            self.profile_error = str(error)
            self.running = False
            self.paused_elapsed = 0.0
            self.report_dismissed = False

    def _has_speed_input(self) -> bool:
        text = self.input_speed_text.strip()
        if text in ("", "."):
            return False

        try:
            if not self._is_valid_speed_input_text(text):
                return False
            float(text)
            return True
        except ValueError:
            return False

    def _input_speed_mps(self) -> float:
        return float(self.input_speed_text) / 3.6

    def _input_speed_kmh(self, default: float = 0.0) -> float:
        if not self._has_speed_input():
            return default
        return float(self.input_speed_text)

    def _set_input_speed_text(self, text: str) -> None:
        if not self._is_valid_speed_input_text(text):
            return
        self.input_speed_text = text
        self.paused_elapsed = 0.0
        self.running = False
        self._rebuild_profile()

    def _is_valid_speed_input_text(self, text: str) -> bool:
        if text == "":
            return True
        if text.count(".") > 1:
            return False
        if any(character != "." and not character.isdigit() for character in text):
            return False
        digit_count = sum(1 for character in text if character.isdigit())
        return digit_count <= MAX_SPEED_INPUT_DIGITS

    def _handle_speed_input_key(self, event: pygame.event.Event) -> None:
        if event.key == pygame.K_RETURN:
            self.input_field_active = False
            self._toggle_play()
            return
        if event.key == pygame.K_TAB:
            self.input_field_active = False
            return
        if event.key == pygame.K_BACKSPACE:
            self._set_input_speed_text(self.input_speed_text[:-1])
            return
        if event.key == pygame.K_DELETE:
            self._set_input_speed_text("")
            return

        character = event.unicode
        if character.isdigit() or character == ".":
            self._set_input_speed_text(self.input_speed_text + character)
            return

    def _adjust_input_speed(self, delta_kmh: float) -> None:
        if self.running:
            return

        new_speed = min(MAX_INPUT_SPEED_KMH, max(0.0, self._input_speed_kmh(default=0.0) + delta_kmh))
        if abs(new_speed - round(new_speed)) < 1e-9:
            self._set_input_speed_text(str(int(round(new_speed))))
        else:
            self._set_input_speed_text(f"{new_speed:.1f}")

    def _toggle_play(self) -> None:
        if self.profile is None:
            self.input_field_active = True
            return

        if self.running:
            self.paused_elapsed = self._current_elapsed()
            self.running = False
            return

        if self.profile.total_time > 0 and self.paused_elapsed >= self.profile.total_time:
            self.paused_elapsed = 0.0
            self.report_dismissed = False

        self.started_at = pygame.time.get_ticks() - int(round(self.paused_elapsed * 1000.0))
        self.running = True

    def _seek_timeline(self, x_position: float) -> None:
        if self.profile is None or self.profile.total_time <= 0 or self.timeline_bar_rect is None:
            return

        progress = (x_position - self.timeline_bar_rect.x) / self.timeline_bar_rect.width
        progress = min(1.0, max(0.0, progress))
        self.paused_elapsed = progress * self.profile.total_time
        self.running = False
        if self.paused_elapsed < self.profile.total_time - 1e-6:
            self.report_dismissed = False

    def _current_elapsed(self) -> float:
        if self.profile is None:
            return 0.0

        if self.running:
            elapsed = (pygame.time.get_ticks() - self.started_at) / 1000.0
            if elapsed >= self.profile.total_time:
                self.running = False
                self.paused_elapsed = self.profile.total_time
                return self.profile.total_time
            return elapsed

        return min(self.paused_elapsed, self.profile.total_time)

    def _current_frame(self) -> Optional[SimulationFrame]:
        if self.profile is None:
            if self.reference_profile is not None and self.reference_profile.frames:
                return self.reference_profile.frames[0]
            return None

        if not self.profile.frames:
            return None

        elapsed = self._current_elapsed()
        selected_frame = self.profile.frames[0]
        for frame in self.profile.frames:
            if frame.elapsed_time <= elapsed:
                selected_frame = frame
            else:
                break

        return selected_frame

    def _draw(self) -> None:
        self.hitboxes = []
        self.screen.fill((225, 225, 225))

        screen_rect = self.screen.get_rect()
        title = self.title_font.render("Simulation Time!", True, (0, 0, 0))
        title_rect = title.get_rect(center=(screen_rect.centerx, self._stage_y(90)))
        self.screen.blit(title, title_rect)

        image_rect = self._draw_simulation_image()
        frame = self._current_frame()
        if frame is not None:
            self._draw_racing_line(frame, image_rect)
        if frame is not None:
            self._draw_car(frame, image_rect)

        self._draw_info_panel(frame)
        self._draw_speed_card(frame)
        self._draw_progress_slider(image_rect)
        self._draw_back()
        self._draw_play()
        if self._should_draw_report_popup():
            self._draw_report_popup()

    def _draw_simulation_image(self) -> pygame.Rect:
        max_width = self._scaled(630)
        max_height = self._scaled(470)
        scale = min(max_width / self.simulation_image.get_width(), max_height / self.simulation_image.get_height())
        scaled_size = (
            max(1, int(round(self.simulation_image.get_width() * scale))),
            max(1, int(round(self.simulation_image.get_height() * scale))),
        )
        scaled_image = pygame.transform.smoothscale(self.simulation_image, scaled_size)
        image_rect = scaled_image.get_rect(center=(self._stage_x(640), self._stage_y(390)))
        self.screen.blit(scaled_image, image_rect)
        return image_rect

    def _draw_racing_line(self, current_frame: SimulationFrame, image_rect: pygame.Rect) -> None:
        if self.profile is None or not self.profile.frames:
            return
        arrow_frames = self._racing_line_arrow_frames()
        if not arrow_frames:
            return

        world_scale = self._world_to_image_scale(image_rect)
        arrow_width = max(1, int(round(RACING_ARROW_WIDTH_METERS * world_scale)))
        min_spacing = max(1, int(round(RACING_ARROW_SPACING_METERS * world_scale)))
        passed_index = min(current_frame.index, len(arrow_frames) - 1)
        current_speed = current_frame.speed
        last_position: Optional[pygame.Vector2] = None

        old_clip = self.screen.get_clip()
        self.screen.set_clip(image_rect)
        for frame in arrow_frames:
            position = self._world_to_image(frame.position, image_rect)
            if last_position is not None and (position - last_position).length() < min_spacing:
                continue
            last_position = position

            if frame.index <= passed_index:
                continue

            direction = self._frame_direction(frame, image_rect, arrow_frames)
            if direction.length_squared() <= 1e-6:
                continue

            arrow = self._scaled_racing_arrow(
                self._racing_arrow_index(frame, current_speed),
                arrow_width,
            )
            direction_angle = math.degrees(math.atan2(direction.y, direction.x))
            rotated_arrow = pygame.transform.rotate(arrow, -(direction_angle + 90.0))
            arrow_rect = rotated_arrow.get_rect(center=(int(round(position.x)), int(round(position.y))))
            self.screen.blit(rotated_arrow, arrow_rect)
        self.screen.set_clip(old_clip)

    def _racing_line_arrow_frames(self) -> List[SimulationFrame]:
        if self.reference_profile is not None and self.reference_profile.frames:
            return self.reference_profile.frames
        if self.profile is not None:
            return self.profile.frames
        return []

    def _frame_direction(
        self,
        frame: SimulationFrame,
        image_rect: pygame.Rect,
        frames: Optional[List[SimulationFrame]] = None,
    ) -> pygame.Vector2:
        source_frames = frames or (self.profile.frames if self.profile is not None else [])
        if not source_frames:
            return pygame.Vector2()

        frame_index = min(frame.index, len(source_frames) - 1)
        next_frame = source_frames[min(frame_index + 1, len(source_frames) - 1)]
        previous_frame = source_frames[max(frame_index - 1, 0)]
        return self._world_to_image(next_frame.position, image_rect) - self._world_to_image(previous_frame.position, image_rect)

    def _racing_arrow_index(self, frame: SimulationFrame, current_speed: float) -> int:
        max_speed_at_point = frame.local_speed_limit
        if max_speed_at_point <= 1e-9:
            return 4

        speed_delta = max_speed_at_point - current_speed
        clamped_delta = max(-max_speed_at_point, min(max_speed_at_point, speed_delta))
        bin_width = (2.0 * max_speed_at_point) / 7.0
        index = int(math.floor((clamped_delta + max_speed_at_point) / bin_width)) + 1
        return max(1, min(7, index))

    def _scaled_racing_arrow(self, index: int, target_width: int) -> pygame.Surface:
        cache_key = (index, target_width)
        if cache_key not in self.racing_arrow_cache:
            arrow = self.racing_arrow_images[index]
            image_scale = target_width / arrow.get_width()
            size = (
                max(1, int(round(arrow.get_width() * image_scale))),
                max(1, int(round(arrow.get_height() * image_scale))),
            )
            self.racing_arrow_cache[cache_key] = pygame.transform.smoothscale(arrow, size)
        return self.racing_arrow_cache[cache_key]

    def _draw_car(self, frame: SimulationFrame, image_rect: pygame.Rect) -> None:
        if self.profile is None:
            return

        position, angle = self._car_visual_state(frame, image_rect)

        world_scale = self._world_to_image_scale(image_rect)
        target_height = max(1, int(round(self.car.width * world_scale)))
        image_scale = target_height / self.car_image.get_height()
        car_size = (
            max(1, int(round(self.car_image.get_width() * image_scale))),
            max(1, int(round(self.car_image.get_height() * image_scale))),
        )
        scaled_car = pygame.transform.smoothscale(self.car_image, car_size)
        rotated_car = pygame.transform.rotate(scaled_car, angle)
        car_rect = rotated_car.get_rect(center=(int(round(position.x)), int(round(position.y))))
        old_clip = self.screen.get_clip()
        self.screen.set_clip(image_rect)
        self.screen.blit(rotated_car, car_rect)
        self.screen.set_clip(old_clip)

    def _car_visual_state(self, frame: SimulationFrame, image_rect: pygame.Rect) -> Tuple[pygame.Vector2, float]:
        if self.profile is not None and self.profile.failed_index is not None and frame.index >= self.profile.failed_index:
            return self._failed_car_visual_state(frame, image_rect)

        position = self._world_to_image(frame.position, image_rect)
        next_frame = self.profile.frames[min(frame.index + 1, len(self.profile.frames) - 1)]
        previous_frame = self.profile.frames[max(frame.index - 1, 0)]
        direction_start = self._world_to_image(previous_frame.position, image_rect)
        direction_end = self._world_to_image(next_frame.position, image_rect)
        direction = direction_end - direction_start
        angle = 0.0 if direction.length_squared() == 0 else -math.degrees(math.atan2(direction.y, direction.x))
        return position, angle

    def _failed_car_visual_state(self, frame: SimulationFrame, image_rect: pygame.Rect) -> Tuple[pygame.Vector2, float]:
        if self.profile is None:
            return self._world_to_image(frame.position, image_rect), 0.0

        failed_index = self.profile.failed_index if self.profile.failed_index is not None else frame.index
        failed_frame = self.profile.frames[min(failed_index, len(self.profile.frames) - 1)]
        direction_world = self._failure_heading_world(failed_index)
        fail_elapsed = max(0.0, self._current_elapsed() - failed_frame.elapsed_time)
        fail_elapsed = min(FAILURE_COAST_DURATION_SECONDS, fail_elapsed)
        failed_position = pygame.Vector2(failed_frame.position)
        visual_position_world = failed_position + direction_world * failed_frame.speed * fail_elapsed
        visual_position = self._world_to_image((visual_position_world.x, visual_position_world.y), image_rect)

        direction_start = self._world_to_image((0.0, 0.0), image_rect)
        direction_end = self._world_to_image((direction_world.x, direction_world.y), image_rect)
        direction_screen = direction_end - direction_start
        base_angle = 0.0 if direction_screen.length_squared() == 0 else -math.degrees(math.atan2(direction_screen.y, direction_screen.x))
        spin_direction = self._failure_spin_direction(failed_index)
        return visual_position, base_angle + spin_direction * FAILURE_SPIN_DEGREES_PER_SECOND * fail_elapsed

    def _failure_heading_world(self, failed_index: int) -> pygame.Vector2:
        points = self.track.racing_line_points
        if len(points) < 2:
            return pygame.Vector2(1.0, 0.0)

        if failed_index >= 1:
            start = pygame.Vector2(points[failed_index - 1])
            end = pygame.Vector2(points[min(failed_index, len(points) - 1)])
        else:
            start = pygame.Vector2(points[0])
            end = pygame.Vector2(points[1])

        direction = end - start
        if direction.length_squared() <= 1e-9 and len(points) >= 2:
            direction = pygame.Vector2(points[1]) - pygame.Vector2(points[0])
        if direction.length_squared() <= 1e-9:
            return pygame.Vector2(1.0, 0.0)
        return direction.normalize()

    def _failure_spin_direction(self, failed_index: int) -> float:
        points = self.track.racing_line_points
        if len(points) < 3:
            return 1.0

        middle_index = min(max(1, failed_index - 1), len(points) - 2)
        previous_point = pygame.Vector2(points[middle_index - 1])
        middle_point = pygame.Vector2(points[middle_index])
        next_point = pygame.Vector2(points[middle_index + 1])
        incoming = middle_point - previous_point
        outgoing = next_point - middle_point
        cross = incoming.x * outgoing.y - incoming.y * outgoing.x
        if abs(cross) <= 1e-9:
            return 1.0
        return 1.0 if cross > 0 else -1.0

    def _draw_info_panel(self, frame: Optional[SimulationFrame]) -> None:
        panel_rect = pygame.Rect(
            self._stage_x(70),
            self._stage_y(170),
            self._scaled(220),
            self._scaled(470),
        )
        pygame.draw.rect(self.screen, (95, 95, 95), panel_rect)

        title_y = panel_rect.y + self._scaled(28)
        for line in self._wrap_text(self.car.name, self.panel_title_font, panel_rect.width - self._scaled(28)):
            name_text = self.panel_title_font.render(line, True, (255, 255, 255))
            name_rect = name_text.get_rect(center=(panel_rect.centerx, title_y))
            self.screen.blit(name_text, name_rect)
            title_y += self.panel_title_font.get_linesize()

        track_text = self.panel_subtitle_font.render(self.track.name or "Track", True, (245, 245, 245))
        track_rect = track_text.get_rect(center=(panel_rect.centerx, title_y + self._scaled(10)))
        self.screen.blit(track_text, track_rect)

        if self.profile_error is not None:
            self._draw_multiline(
                self.profile_error,
                self.info_font,
                (255, 255, 255),
                pygame.Rect(panel_rect.x + self._scaled(18), panel_rect.y + self._scaled(150), panel_rect.width - self._scaled(36), panel_rect.height),
            )
            return

        if frame is None:
            return

        info_rows = [
            ("Time", f"{frame.elapsed_time:.2f} s"),
            ("Speed", f"{_mps_to_kmh(frame.speed):.1f} km/h"),
            ("State", frame.acceleration_state),
            ("Accel", f"{frame.acceleration_value:+.2f} m/s2"),
            ("Limit", f"{_mps_to_kmh(frame.local_speed_limit):.1f} km/h"),
            ("Target", f"{_mps_to_kmh(frame.optimal_speed):.1f} km/h"),
            ("Curvature", f"{frame.curvature:.4f}"),
            ("Lat Accel", f"{frame.lateral_acceleration:.2f} m/s2"),
            ("Downforce", f"{frame.downforce:.1f}"),
        ]

        y = max(panel_rect.y + self._scaled(132), track_rect.bottom + self._scaled(42))
        no_speed_input = not self._has_speed_input()
        for label, value in info_rows:
            if no_speed_input and label in ("Time", "Speed", "State", "Accel"):
                value = "Waiting" if label == "State" else "--"
            label_surface = self.info_font.render(label, True, (245, 245, 245))
            value_surface = self.info_font.render(value, True, (255, 255, 255))
            self.screen.blit(label_surface, (panel_rect.x + self._scaled(18), y))
            self.screen.blit(value_surface, (panel_rect.x + self._scaled(104), y))
            y += self._scaled(31)

    def _draw_speed_card(self, frame: Optional[SimulationFrame]) -> None:
        card_rect = pygame.Rect(
            self._stage_rect().right - self._scaled(290),
            self._stage_y(280),
            self._scaled(220),
            self._scaled(255),
        )
        shadow = pygame.Surface(card_rect.size, pygame.SRCALPHA)
        shadow.fill((0, 0, 0, 28))
        self.screen.blit(shadow, card_rect.move(self._scaled(7), self._scaled(7)))
        pygame.draw.rect(self.screen, (255, 255, 255), card_rect)

        title = self.card_title_font.render("Input Speed", True, (30, 30, 30))
        self.screen.blit(title, (card_rect.x + self._scaled(30), card_rect.y + self._scaled(48)))

        input_text = self.input_speed_text if self.input_speed_text else "0"
        value_color = (0, 0, 0) if self.input_speed_text else (150, 150, 150)
        pill_rect = pygame.Rect(
            card_rect.x + self._scaled(28),
            card_rect.y + self._scaled(111),
            self._scaled(98),
            self._scaled(44),
        )
        pygame.draw.rect(self.screen, (220, 220, 220), pill_rect, border_radius=self._scaled(20))
        if self.input_field_active:
            pygame.draw.rect(
                self.screen,
                (255, 105, 0),
                pill_rect,
                width=self._scaled(3),
                border_radius=self._scaled(20),
            )
        value_text = self._render_speed_input_text(input_text, value_color, pill_rect.width - self._scaled(12))
        self.screen.blit(value_text, value_text.get_rect(center=pill_rect.center))
        self.hitboxes.append(ButtonHitbox("speed_input", "", pill_rect.inflate(self._scaled(12), self._scaled(12))))

        unit_text = self.card_unit_font.render("km/h", True, (0, 0, 0))
        self.screen.blit(unit_text, (pill_rect.right + self._scaled(14), pill_rect.y + self._scaled(3)))

        optimal_profile = self.profile or self.reference_profile
        optimal = 0.0 if optimal_profile is None else _mps_to_kmh(optimal_profile.optimal_initial_speed)
        hint = self.card_hint_font.render(f"Optimal = {self._format_speed_kmh(optimal)}", True, (155, 155, 155))
        self.screen.blit(hint, (card_rect.x + self._scaled(40), card_rect.y + self._scaled(176)))

        if not self._has_speed_input():
            current = self.card_hint_font.render("Enter speed to start", True, (155, 155, 155))
            self.screen.blit(current, (card_rect.x + self._scaled(40), card_rect.y + self._scaled(202)))

    def _render_speed_input_text(self, text: str, color: Tuple[int, int, int], max_width: int) -> pygame.Surface:
        for size in range(28, 17, -2):
            font = _font(["Segoe UI", "Arial"], self._scaled(size), bold=True)
            surface = font.render(text, True, color)
            if surface.get_width() <= max_width:
                return surface
        return _font(["Segoe UI", "Arial"], self._scaled(18), bold=True).render(text, True, color)

    def _should_draw_report_popup(self) -> bool:
        if self.profile is None or self.report_dismissed or self.profile.total_time <= 0:
            return False
        return self._current_elapsed() >= self.profile.total_time - 1e-6

    def _draw_report_popup(self) -> None:
        if self.profile is None:
            return

        failed = self.profile.failed_index is not None
        screen_rect = self.screen.get_rect()
        overlay = pygame.Surface(screen_rect.size, pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 105))
        self.screen.blit(overlay, (0, 0))

        card_rect = pygame.Rect(0, 0, self._report_scaled(560), self._report_scaled(350))
        card_rect.center = screen_rect.center
        pygame.draw.rect(self.screen, (255, 255, 255), card_rect)

        close_size = self._report_scaled(19)
        close_image = pygame.transform.smoothscale(self.close, (close_size, close_size))
        close_rect = close_image.get_rect(topright=(card_rect.right - self._report_scaled(18), card_rect.y + self._report_scaled(18)))
        self.screen.blit(close_image, close_rect)
        self.hitboxes.append(ButtonHitbox("report_close", "", close_rect.inflate(self._report_scaled(12), self._report_scaled(12))))

        title_text = "Car Crashed !" if failed else "Car Go Fast !"
        title = self.popup_title_font.render(title_text, True, (0, 0, 0))
        self.screen.blit(title, title.get_rect(center=(card_rect.centerx, card_rect.y + self._report_scaled(62))))

        subtitle_text = "Initial speed too fast!" if failed else "Car successfully passed all corners!"
        subtitle_color = (255, 25, 25) if failed else (88, 150, 45)
        subtitle = self.popup_subtitle_font.render(subtitle_text, True, subtitle_color)
        self.screen.blit(subtitle, subtitle.get_rect(center=(card_rect.centerx, card_rect.y + self._report_scaled(112))))

        optimal_kmh = _mps_to_kmh(self.profile.optimal_initial_speed)
        input_kmh = _mps_to_kmh(self.input_speed)
        optimal_percentage = self._optimal_speed_percentage(input_kmh, optimal_kmh)
        rows = [
            ("Optimal Speed", self._format_speed_kmh(optimal_kmh)),
            ("Your Input", self._format_speed_kmh(input_kmh)),
            ("Optimality", "Nope" if failed else self._format_percentage(optimal_percentage)),
        ]

        y = card_rect.y + self._report_scaled(160)
        label_x = card_rect.x + self._report_scaled(92)
        value_x = card_rect.x + self._report_scaled(380)
        for label, value in rows:
            label_surface = self.popup_body_font.render(label, True, (20, 20, 20))
            value_surface = self.popup_body_font.render(value, True, (20, 20, 20))
            self.screen.blit(label_surface, (label_x, y))
            self.screen.blit(value_surface, (value_x, y))
            y += self._report_scaled(42)

        try_again_size = (self._report_scaled(148), self._report_scaled(42))
        try_again_image = pygame.transform.smoothscale(self.try_again, try_again_size)
        try_again_rect = try_again_image.get_rect(center=(card_rect.centerx, card_rect.y + self._report_scaled(302)))
        self.screen.blit(try_again_image, try_again_rect)
        self.hitboxes.append(ButtonHitbox("report_try_again", "", try_again_rect))

    def _optimal_speed_percentage(self, input_kmh: float, optimal_kmh: float) -> float:
        if optimal_kmh <= 1e-9:
            return 100.0 if input_kmh <= 1e-9 else 0.0
        if math.isclose(input_kmh, optimal_kmh, rel_tol=1e-9, abs_tol=1e-6):
            return 100.0
        return (input_kmh / optimal_kmh) * 100.0

    def _format_speed_kmh(self, speed: float) -> str:
        if abs(speed - round(speed)) < 0.05:
            return f"{int(round(speed))} km/h"
        formatted = f"{speed:.2f}".rstrip("0").rstrip(".")
        return f"{formatted} km/h"

    def _format_percentage(self, percentage: float) -> str:
        if abs(percentage - round(percentage)) < 0.05:
            return f"{int(round(percentage))}%"
        return f"{percentage:.1f}%"

    def _try_again_after_report(self) -> None:
        self.running = False
        self.paused_elapsed = 0.0
        self.input_speed = 0.0
        self.input_speed_text = ""
        self.profile = None
        self.profile_error = None
        self.report_dismissed = False
        self.input_field_active = True

    def _draw_progress_slider(self, image_rect: pygame.Rect) -> None:
        if self.profile is None or self.profile.total_time <= 0:
            progress = 0.0
        else:
            progress = min(1.0, max(0.0, self._current_elapsed() / self.profile.total_time))

        play_rect = self._play_rect()
        bar_rect = pygame.Rect(
            image_rect.x,
            play_rect.top - self._scaled(34),
            image_rect.width,
            self._scaled(10),
        )
        self.timeline_bar_rect = bar_rect
        pygame.draw.rect(self.screen, (205, 205, 205), bar_rect, border_radius=self._scaled(5))
        filled_rect = pygame.Rect(bar_rect.x, bar_rect.y, int(round(bar_rect.width * progress)), bar_rect.height)
        pygame.draw.rect(self.screen, (255, 105, 0), filled_rect, border_radius=self._scaled(5))
        knob_x = bar_rect.x + int(round(bar_rect.width * progress))
        pygame.draw.circle(
            self.screen,
            (255, 105, 0),
            (knob_x, bar_rect.centery),
            self._scaled(17),
        )
        self.hitboxes.append(
            ButtonHitbox(
                "timeline",
                "",
                bar_rect.inflate(self._scaled(34), self._scaled(38)),
            )
        )

    def _draw_back(self) -> None:
        back = pygame.transform.smoothscale(
            self.back,
            (
                self._scaled(int(round(155 * ACTION_BUTTON_SCALE))),
                self._scaled(int(round(77 * ACTION_BUTTON_SCALE))),
            ),
        )
        back_rect = self._back_rect(back.get_size())
        self.screen.blit(back, back_rect)
        self.hitboxes.append(ButtonHitbox("back", "", back_rect))

    def _draw_play(self) -> None:
        play = pygame.transform.smoothscale(
            self.play,
            (
                self._scaled(int(round(170 * ACTION_BUTTON_SCALE))),
                self._scaled(int(round(77 * ACTION_BUTTON_SCALE))),
            ),
        )
        play_rect = self._play_rect(play.get_size())
        self.screen.blit(play, play_rect)
        self.hitboxes.append(ButtonHitbox("play", "", play_rect))

    def _play_rect(self, size: Optional[Tuple[int, int]] = None) -> pygame.Rect:
        screen_rect = self.screen.get_rect()
        bottom_y = _bottom_bar_baseline(screen_rect, self._scaled)
        if size is None:
            size = (
                self._scaled(int(round(170 * ACTION_BUTTON_SCALE))),
                self._scaled(int(round(77 * ACTION_BUTTON_SCALE))),
            )
        rect = pygame.Rect(0, 0, size[0], size[1])
        rect.midbottom = (screen_rect.centerx, bottom_y)
        return rect

    def _back_rect(self, size: Tuple[int, int]) -> pygame.Rect:
        screen_rect = self.screen.get_rect()
        bottom_y = _bottom_bar_baseline(screen_rect, self._scaled)
        rect = pygame.Rect(0, 0, size[0], size[1])
        rect.bottomleft = (self._scaled(70), bottom_y)
        return rect

    def _world_to_image(self, point: Tuple[float, float], image_rect: pygame.Rect) -> pygame.Vector2:
        start_world = pygame.Vector2(self.track.racing_line_points[0])
        start_image = self._relative_anchor_to_screen(self.track_asset.image_start_anchor, image_rect)

        delta = pygame.Vector2(point) - start_world
        converted_delta = pygame.Vector2(delta.x, -delta.y)
        transform = self._world_to_image_transform(image_rect)
        rotated = pygame.Vector2(
            converted_delta.x * math.cos(transform[1]) - converted_delta.y * math.sin(transform[1]),
            converted_delta.x * math.sin(transform[1]) + converted_delta.y * math.cos(transform[1]),
        )
        return start_image + rotated * transform[0]

    def _world_to_image_scale(self, image_rect: pygame.Rect) -> float:
        return self._world_to_image_transform(image_rect)[0]

    def _world_to_image_transform(self, image_rect: pygame.Rect) -> Tuple[float, float]:
        start_world = pygame.Vector2(self.track.racing_line_points[0])
        end_world = pygame.Vector2(self.track.racing_line_points[-1])
        start_image = self._relative_anchor_to_screen(self.track_asset.image_start_anchor, image_rect)
        end_image = self._relative_anchor_to_screen(self.track_asset.image_end_anchor, image_rect)
        world_delta = end_world - start_world
        converted_world_delta = pygame.Vector2(world_delta.x, -world_delta.y)
        image_delta = end_image - start_image

        world_length = max(converted_world_delta.length(), 1.0)
        image_length = max(image_delta.length(), 1.0)
        scale = image_length / world_length
        angle = math.atan2(image_delta.y, image_delta.x) - math.atan2(
            converted_world_delta.y,
            converted_world_delta.x,
        )
        return scale, angle

    def _relative_anchor_to_screen(self, anchor: Tuple[float, float], image_rect: pygame.Rect) -> pygame.Vector2:
        return pygame.Vector2(
            image_rect.x + anchor[0] * image_rect.width,
            image_rect.y + anchor[1] * image_rect.height,
        )

    def _draw_multiline(
        self,
        text: str,
        font: pygame.font.Font,
        color: Tuple[int, int, int],
        rect: pygame.Rect,
    ) -> None:
        lines = self._wrap_text(text, font, rect.width)
        y = rect.y
        for line in lines:
            surface = font.render(line, True, color)
            self.screen.blit(surface, (rect.x, y))
            y += font.get_linesize()

    def _wrap_text(self, text: str, font: pygame.font.Font, max_width: int) -> List[str]:
        words = text.split()
        lines: List[str] = []
        current_line = ""
        for word in words:
            candidate = word if not current_line else f"{current_line} {word}"
            if font.size(candidate)[0] <= max_width:
                current_line = candidate
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines or [text]


def _group_cars(cars: List[Car]) -> List[CarFamily]:
    grouped: "OrderedDict[str, List[Car]]" = OrderedDict()
    for car in cars:
        grouped.setdefault(car.name, []).append(car)

    families: List[CarFamily] = []
    for name, variants in grouped.items():
        tire_options = _unique([car.tire_option for car in variants])
        spoiler_options = _unique([car.spoiler_option for car in variants])
        families.append(CarFamily(name, variants, tire_options, spoiler_options))

    return families


def _unique(values: List[str]) -> List[str]:
    ordered: List[str] = []
    for value in values:
        if value not in ordered:
            ordered.append(value)
    return ordered


def _mps_to_kmh(speed: float) -> float:
    return speed * 3.6


def _font(names: List[str], size: int, bold: bool = False) -> pygame.font.Font:
    for name in names:
        font_path = pygame.font.match_font(name, bold=bold)
        if font_path:
            return pygame.font.Font(font_path, size)
    return pygame.font.SysFont(None, size, bold=bold)


def _load_image(path: Path) -> pygame.Surface:
    if not path.exists():
        raise ValueError(f"Asset GUI tidak ditemukan: {path}")
    return pygame.image.load(path).convert_alpha()


def _bottom_bar_baseline(screen_rect: pygame.Rect, scaled: Callable[[int], int]) -> int:
    return screen_rect.bottom - scaled(BOTTOM_BAR_MARGIN)


def _virtual_stage_rect(screen_rect: pygame.Rect, scale: float) -> pygame.Rect:
    stage_size = (
        int(round(BASE_WINDOW_SIZE[0] * scale)),
        int(round(BASE_WINDOW_SIZE[1] * scale)),
    )
    return pygame.Rect(0, 0, *stage_size).move(
        int(round((screen_rect.width - stage_size[0]) / 2)),
        int(round((screen_rect.height - stage_size[1]) / 2)),
    )


def _ease_in_out_bezier(progress: float) -> float:
    return _cubic_bezier(progress, 0.42, 0.0, 0.58, 1.0)


def _cubic_bezier(progress: float, p1x: float, p1y: float, p2x: float, p2y: float) -> float:
    lower = 0.0
    upper = 1.0
    for _ in range(16):
        midpoint = (lower + upper) / 2.0
        x = _cubic(midpoint, 0.0, p1x, p2x, 1.0)
        if x < progress:
            lower = midpoint
        else:
            upper = midpoint

    t = (lower + upper) / 2.0
    return _cubic(t, 0.0, p1y, p2y, 1.0)


def _cubic(t: float, p0: float, p1: float, p2: float, p3: float) -> float:
    one_minus_t = 1.0 - t
    return (
        one_minus_t**3 * p0
        + 3.0 * one_minus_t**2 * t * p1
        + 3.0 * one_minus_t * t**2 * p2
        + t**3 * p3
    )


if __name__ == "__main__":
    selected = choose_car_gui()
    if selected is not None:
        print(
            f"{selected.name} | Ban: {selected.tire_option} | "
            f"Spoiler: {selected.spoiler_option}"
        )
