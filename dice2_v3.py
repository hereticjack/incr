"""
Dice Poker Game using Pygame.

Five dice roll with a chunky little gravity-and-bounce animation. After the
first roll you may hold any dice and roll the rest once more.

Changes in this version:
  - Credits are always shown in a top HUD.
  - Betting controls and buttons live in the bottom panel.
  - Wager adjusts with +/-10 and +/-100 buttons.
  - Five "hold slots" appear at the top. Holding a die slides it into its
    slot, and after the second roll the final dice slide up for a clean
    presentation.

The player's credit balance is stored on disk in ``dice_save.json``.

Controls:
  - Use +/-10 and +/-100 to change your wager.
  - Click the checkboxes to toggle side bets.
  - Click Roll to start. After the first roll, click dice to hold/unhold.
  - Click Roll Again to finish the round.
"""

import json
import math
import os
import random
import sys
from typing import Dict, List, Tuple

import pygame

############################
# Configuration
############################
W, H = 1000, 650
FPS = 60

# Colours
BG = (20, 22, 28)
TABLE = (45, 50, 65)
WHITE = (240, 240, 245)
BLACK = (15, 15, 15)
RED_PIP = (220, 60, 70)
BLACK_PIP = (25, 25, 30)
BUTTON_COLOUR = (90, 140, 255)
BUTTON_HOVER = (120, 165, 255)
TOGGLE_OFF = (80, 80, 100)
TOGGLE_ON = (120, 180, 100)
SHADOW = (0, 0, 0, 80)

PANEL_BG = (35, 38, 50)
PANEL_LINE = (70, 75, 95)
SLOT_BORDER = (120, 130, 160)
SLOT_FILL = (28, 30, 40)

TABLE_Y = 470
DIE_SIZE = 80

GRAVITY = 2200.0          # px/s^2
BOUNCE = 0.35             # coefficient of restitution
FRICTION = 0.86           # velocity damping per bounce
AIR_DRAG = 0.995          # per frame
SPIN_DRAG = 0.99          # per frame
REST_EPS = 35.0           # threshold for "resting" (px/s)
REST_FRAMES_REQUIRED = 18 # frames below eps to count as resting

SAVE_FILE = os.path.join(os.path.dirname(__file__), "dice_save.json")
STARTING_CREDIT = 250

# Saved, user-facing prefs live alongside credits.
DEFAULT_SETTINGS: Dict[str, object] = {
    # If False, the Options panel still shows the key legend, but we won't
    # surface extra key hints elsewhere.
    "show_key_legend": True,
}

############################
# Payout Table
############################
PAYOUTS: Dict[str, int] = {
    "three_kind": 1,   # returns your wager
    "straight": 3,
    "full_house": 5,
    "four_kind": 7,
    "five_kind": 10,
}

############################
# Helper Functions
############################
def rounded_rect(
    surf: pygame.Surface,
    rect: pygame.Rect,
    colour: Tuple[int, int, int],
    radius: int = 14,
    width: int = 0,
) -> None:
    pygame.draw.rect(surf, colour, rect, width=width, border_radius=radius)


def draw_shadowed_rect(
    surf: pygame.Surface,
    rect: pygame.Rect,
    colour: Tuple[int, int, int],
    radius: int = 16,
    shadow_offset: Tuple[int, int] = (0, 6),
) -> None:
    shadow = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    rounded_rect(shadow, shadow.get_rect(), SHADOW, radius)
    surf.blit(shadow, (rect.x + shadow_offset[0], rect.y + shadow_offset[1]))
    rounded_rect(surf, rect, colour, radius)


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def ease_out_cubic(t: float) -> float:
    # 0..1 -> 0..1
    t = clamp(t, 0.0, 1.0)
    return 1.0 - (1.0 - t) ** 3


############################
# Die Drawing Utilities
############################
def pip_positions(size: int) -> Tuple[List[float], List[float]]:
    margin = size * 0.22
    centre = size / 2
    right = size - margin
    xs = [margin, centre, right]
    ys = [margin, centre, right]
    return xs, ys


def pips_for_face(face: int) -> List[Tuple[int, int]]:
    if face == 1:
        return [(1, 1)]
    if face == 2:
        return [(0, 0), (2, 2)]
    if face == 3:
        return [(0, 0), (1, 1), (2, 2)]
    if face == 4:
        return [(0, 0), (2, 0), (0, 2), (2, 2)]
    if face == 5:
        return [(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)]
    if face == 6:
        return [(0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)]
    return [(1, 1)]


def make_die_surface(size: int, face: int) -> pygame.Surface:
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    body = (245, 245, 248)
    edge = (210, 210, 220)
    pygame.draw.rect(surf, body, (0, 0, size, size), border_radius=int(size * 0.18))
    pygame.draw.rect(surf, edge, (0, 0, size, size), width=4, border_radius=int(size * 0.18))

    highlight = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.circle(highlight, (255, 255, 255, 70), (int(size * 0.28), int(size * 0.28)), int(size * 0.46))
    surf.blit(highlight, (0, 0))

    pip_colour = RED_PIP if face in (1, 4) else BLACK_PIP
    xs, ys = pip_positions(size)
    pip_r = int(size * 0.06)
    for (cx, cy) in pips_for_face(face):
        pygame.draw.circle(surf, pip_colour, (int(xs[cx]), int(ys[cy])), pip_r)

    return surf


############################
# Button Classes
############################
class Button:
    def __init__(self, rect: Tuple[int, int, int, int], text: str, font: pygame.font.Font):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.font = font

    def draw(self, screen: pygame.Surface, mouse_pos: Tuple[int, int]) -> None:
        hover = self.rect.collidepoint(mouse_pos)
        colour = BUTTON_HOVER if hover else BUTTON_COLOUR
        draw_shadowed_rect(screen, self.rect, colour, radius=18)
        label = self.font.render(self.text, True, WHITE)
        screen.blit(label, label.get_rect(center=self.rect.center))

    def clicked(self, event: pygame.event.Event) -> bool:
        return (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.rect.collidepoint(event.pos)
        )


class Toggle:
    def __init__(self, rect: Tuple[int, int, int, int], label: str, font: pygame.font.Font):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.font = font
        self.active = False

        # Click target includes the label text as well as the box.
        self.hit_rect = self.rect.copy()

    def draw(self, screen: pygame.Surface, mouse_pos: Tuple[int, int]) -> None:
        # Box
        box_fill = (55, 58, 72)
        rounded_rect(screen, self.rect, box_fill, radius=6)
        border_col = TOGGLE_ON if self.active else TOGGLE_OFF
        rounded_rect(screen, self.rect, border_col, radius=6, width=2)

        # Check mark
        if self.active:
            cx, cy = self.rect.center
            size = self.rect.w * 0.45
            pts = [
                (cx - size * 0.55, cy + size * 0.05),
                (cx - size * 0.15, cy + size * 0.45),
                (cx + size * 0.65, cy - size * 0.45),
            ]
            pygame.draw.lines(screen, WHITE, False, pts, 4)

        # Label
        label_surf = self.font.render(self.label, True, WHITE)
        label_pos = (self.rect.right + 10, self.rect.centery - label_surf.get_height() / 2)
        screen.blit(label_surf, label_pos)

        # Expand hit rect to include the label too (helps usability)
        label_rect = label_surf.get_rect(topleft=label_pos)
        self.hit_rect = self.rect.union(label_rect)

    def handle_event(self, event: pygame.event.Event) -> None:
        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.hit_rect.collidepoint(event.pos)
        ):
            self.active = not self.active


class WagerControl:
    """
    +/-10 and +/-100 control with a centered value display.
    """

    def __init__(
        self,
        rect: Tuple[int, int, int, int],
        font: pygame.font.Font,
        font_small: pygame.font.Font,
        min_value: int = 10,
        max_value: int = 9999,
        initial: int = 10,
    ):
        self.rect = pygame.Rect(rect)
        self.font = font
        self.font_small = font_small
        self.min = min_value
        self.max = max_value
        self.value = initial

        h = self.rect.h
        btn_w = int(h * 1.25)
        gap = 10

        self.btn_m100 = pygame.Rect(self.rect.x, self.rect.y, btn_w, h)
        self.btn_m10 = pygame.Rect(self.btn_m100.right + gap, self.rect.y, btn_w, h)
        self.btn_p10 = pygame.Rect(self.rect.right - btn_w - gap - btn_w, self.rect.y, btn_w, h)
        self.btn_p100 = pygame.Rect(self.rect.right - btn_w, self.rect.y, btn_w, h)

        mid_x = self.btn_m10.right + gap
        mid_w = self.btn_p10.x - gap - mid_x
        self.value_rect = pygame.Rect(mid_x, self.rect.y, mid_w, h)

        self._buttons = [
            (self.btn_m100, "-100", -100),
            (self.btn_m10, "-10", -10),
            (self.btn_p10, "+10", +10),
            (self.btn_p100, "+100", +100),
        ]

    def draw(self, screen: pygame.Surface, mouse_pos: Tuple[int, int]) -> None:
        # label
        label = self.font_small.render("WAGER", True, (200, 205, 220))
        screen.blit(label, (self.rect.x, self.rect.y - 18))

        for r, txt, _delta in self._buttons:
            hover = r.collidepoint(mouse_pos)
            colour = BUTTON_HOVER if hover else BUTTON_COLOUR
            draw_shadowed_rect(screen, r, colour, radius=12, shadow_offset=(0, 4))
            t = self.font.render(txt, True, WHITE)
            screen.blit(t, t.get_rect(center=r.center))

        rounded_rect(screen, self.value_rect, (60, 65, 80), radius=12)
        value_surf = self.font.render(str(self.value), True, WHITE)
        screen.blit(value_surf, value_surf.get_rect(center=self.value_rect.center))

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for r, _txt, delta in self._buttons:
                if r.collidepoint(event.pos):
                    self.value = int(clamp(self.value + delta, self.min, self.max))
                    break


############################
# Die Physics Object (with optional slot animation)
############################
class Die:
    def __init__(self, x: float, y: float):
        self.pos = pygame.Vector2(x, y)
        self.vel = pygame.Vector2(random.uniform(-220, 220), random.uniform(0, 80))
        self.angle = random.uniform(0, 360)
        self.spin = random.uniform(-520, 520)
        self.face = random.randint(1, 6)
        self.revealed = False
        self.rest_counter = 0
        self.hold = False
        self.radius = (DIE_SIZE / 2) * math.sqrt(2)
        self.base_surfaces = {i: make_die_surface(DIE_SIZE, i) for i in range(1, 7)}

        # presentation/slot animation (does not change roll physics)
        self.parked = False         # True when sitting in a top slot
        self.anim_active = False
        self.anim_t = 0.0
        self.anim_dur = 0.0
        self.anim_start = pygame.Vector2(self.pos)
        self.anim_end = pygame.Vector2(self.pos)
        self.anim_parked_end = None  # type: ignore

        # set by Game
        self.home_pos = pygame.Vector2(x, TABLE_Y - DIE_SIZE / 2)
        self.slot_pos = pygame.Vector2(x, 110)

    def reset_roll(self, x: float, y: float) -> None:
        self.pos.update(x, y)
        self.vel.update(random.uniform(-240, 240), random.uniform(0, 90))
        self.angle = random.uniform(0, 360)
        self.spin = random.uniform(-600, 600)
        self.revealed = False
        self.rest_counter = 0
        self.face = random.randint(1, 6)

        self.anim_active = False
        self.parked = False

    def start_anim(self, target: pygame.Vector2, dur: float = 0.22, parked_end=None) -> None:
        self.anim_active = True
        self.anim_t = 0.0
        self.anim_dur = max(0.001, dur)
        self.anim_start = pygame.Vector2(self.pos)
        self.anim_end = pygame.Vector2(target)
        self.anim_parked_end = parked_end

    def update_anim(self, dt: float) -> None:
        if not self.anim_active:
            return
        self.anim_t += dt
        t = self.anim_t / self.anim_dur
        k = ease_out_cubic(t)
        self.pos = self.anim_start.lerp(self.anim_end, k)
        if t >= 1.0:
            self.pos = pygame.Vector2(self.anim_end)
            self.anim_active = False
            if self.anim_parked_end is not None:
                self.parked = bool(self.anim_parked_end)
            self.anim_parked_end = None

    def update(self, dt: float) -> None:
        # parked dice only animate (their face stays)
        if self.anim_active:
            self.update_anim(dt)
            return
        if self.parked:
            return

        # gravity
        self.vel.y += GRAVITY * dt
        self.pos += self.vel * dt

        # wall bounces
        left_wall = DIE_SIZE / 2
        right_wall = W - DIE_SIZE / 2
        if self.pos.x < left_wall:
            self.pos.x = left_wall
            if self.vel.x < 0:
                self.vel.x = -self.vel.x * BOUNCE
                self.vel.y *= FRICTION
                self.spin *= 0.75
        elif self.pos.x > right_wall:
            self.pos.x = right_wall
            if self.vel.x > 0:
                self.vel.x = -self.vel.x * BOUNCE
                self.vel.y *= FRICTION
                self.spin *= 0.75

        # drag
        self.vel *= AIR_DRAG
        self.spin *= SPIN_DRAG
        self.angle += self.spin * dt

        # bounce off table
        ground_y = TABLE_Y - DIE_SIZE / 2
        if self.pos.y > ground_y:
            self.pos.y = ground_y
            if self.vel.y > 0:
                self.vel.y = -self.vel.y * BOUNCE
                self.vel.x *= FRICTION
                self.spin *= 0.75

        # rest detection
        if (
            abs(self.vel.y) < REST_EPS
            and abs(self.vel.x) < REST_EPS
            and self.pos.y >= ground_y - 0.1
        ):
            self.rest_counter += 1
        else:
            self.rest_counter = 0

        if not self.revealed and self.rest_counter >= REST_FRAMES_REQUIRED:
            self.revealed = True
            self.face = random.randint(1, 6)
            self.spin = 0
            self.angle = random.choice([0, 90, 180, 270])

        if not self.revealed:
            if random.random() < 0.07:
                self.face = random.randint(1, 6)

    def draw(self, screen: pygame.Surface) -> None:
        surf = self.base_surfaces[self.face]
        rotated = pygame.transform.rotozoom(surf, -self.angle, 1.0)
        rect = rotated.get_rect(center=(int(self.pos.x), int(self.pos.y)))

        # shadow (only when not parked)
        if not self.parked:
            shadow_strength = 90
            height = clamp((TABLE_Y - self.pos.y) / 320.0, 0.0, 1.0)
            shadow_alpha = int((1.0 - height) * shadow_strength)
            shadow_w = int(DIE_SIZE * (1.2 + (1.0 - height) * 0.2))
            shadow_h = int(DIE_SIZE * (0.35 + (1.0 - height) * 0.15))
            shadow = pygame.Surface((shadow_w, shadow_h), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (0, 0, 0, shadow_alpha), shadow.get_rect())
            screen.blit(shadow, shadow.get_rect(center=(int(self.pos.x), TABLE_Y - 6)))

        screen.blit(rotated, rect)

        # hold overlay
        if self.hold and not self.parked:
            overlay = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            overlay.fill((255, 255, 0, 60))
            screen.blit(overlay, rect)
            hold_font = pygame.font.SysFont(None, 20)
            hold_label = hold_font.render("HOLD", True, BLACK)
            screen.blit(hold_label, hold_label.get_rect(center=rect.center))

    def hit_test(self, pos: Tuple[int, int]) -> bool:
        surf = self.base_surfaces[self.face]
        rotated = pygame.transform.rotozoom(surf, -self.angle, 1.0)
        rect = rotated.get_rect(center=(int(self.pos.x), int(self.pos.y)))
        return rect.collidepoint(pos)


############################
# Game Logic
############################
def compute_hand(dice_faces: List[int]) -> Tuple[str, int]:
    counts: Dict[int, int] = {}
    for face in dice_faces:
        counts[face] = counts.get(face, 0) + 1

    sorted_counts = sorted(counts.values(), reverse=True)

    if sorted_counts[0] == 5:
        return "five_kind", PAYOUTS.get("five_kind", 0)
    if sorted_counts[0] == 4:
        return "four_kind", PAYOUTS.get("four_kind", 0)
    if sorted_counts[0] == 3 and sorted_counts[1] == 2:
        return "full_house", PAYOUTS.get("full_house", 0)

    if len(counts) == 5:
        sorted_faces = sorted(dice_faces)
        if sorted_faces == [1, 2, 3, 4, 5] or sorted_faces == [2, 3, 4, 5, 6]:
            return "straight", PAYOUTS.get("straight", 0)

    if sorted_counts[0] == 3:
        return "three_kind", PAYOUTS.get("three_kind", 0)

    return "none", 0


def is_all_red(dice_faces: List[int]) -> bool:
    return all(face in (1, 4) for face in dice_faces)


def load_save() -> Tuple[int, Dict[str, object], bool]:
    """Load credits + settings from disk.

    Returns (credit, settings, loaded_from_save). If no save exists or it is
    invalid, returns STARTING_CREDIT, DEFAULT_SETTINGS, and False.
    """
    settings = dict(DEFAULT_SETTINGS)
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Back-compat: older saves were just {"credit": int}.
            if isinstance(data, dict) and isinstance(data.get("credit"), int):
                credit = int(data["credit"])
                if isinstance(data.get("settings"), dict):
                    for k, v in data["settings"].items():
                        settings[k] = v
                return credit, settings, True
        except Exception:
            pass

    return STARTING_CREDIT, settings, False


def save_save(credit: int, settings: Dict[str, object]) -> None:
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump({"credit": int(credit), "settings": settings}, f)
    except Exception:
        pass


class Game:
    def __init__(self) -> None:
        pygame.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("D6 Dice Poker")
        self.clock = pygame.time.Clock()

        self.font_title = pygame.font.SysFont(None, 56)
        self.font = pygame.font.SysFont(None, 30)
        self.font_small = pygame.font.SysFont(None, 22)
        self.font_big = pygame.font.SysFont(None, 48)

        # Save data
        self.credit, self.settings, loaded = load_save()
        if not loaded:
            save_save(self.credit, self.settings)

        # Layout
        self.panel_y = TABLE_Y + 10
        self.panel_h = H - self.panel_y - 10

        # UI components (bottom panel)
        self.roll_button = Button((30, self.panel_y + 18, 220, 72), "Roll", self.font_big)
        self.reroll_button = Button((30, self.panel_y + 18, 220, 72), "Roll Again", self.font_big)

        self.wager = WagerControl(
            rect=(280, self.panel_y + 26, 420, 58),
            font=self.font,
            font_small=self.font_small,
            min_value=10,
            max_value=9999,
            initial=10,
        )

        self.side1_toggle = Toggle((740, self.panel_y + 28, 24, 24), "One Roll", self.font)
        self.side2_toggle = Toggle((740, self.panel_y + 66, 24, 24), "All Red", self.font)

        # Top-right options (future-ready)
        self.options_button = Button((W - 150, 20, 130, 42), "Options", self.font_small)
        self.options_open = False
        self.options_rect = pygame.Rect(W // 2 - 290, 110, 580, 370)
        self.options_close_rect = pygame.Rect(self.options_rect.right - 44, self.options_rect.y + 18, 26, 26)
        self.options_legend_toggle = Toggle(
            (self.options_rect.x + 26, self.options_rect.y + 86, 24, 24),
            "Show key legend",  # saved
            self.font,
        )
        self.options_legend_toggle.active = bool(self.settings.get("show_key_legend", True))

        # game state
        self.dice: List[Die] = []
        self.state = "betting"  # betting, rolling1, hold, rolling2, presenting, finished
        self.message = ""
        self.result_message = ""  # sticky during presenting/finished
        self.side1_stake = 0
        self.side2_stake = 0

        # Dice positions (physics start x positions)
        xs = [220 + i * 120 for i in range(5)]
        self.dice_positions = [(x, 160) for x in xs]  # y isn't used for ground, kept for compatibility

        # Hold/presentation slots (top row)
        self.slot_rects: List[pygame.Rect] = []
        self.slot_centers: List[pygame.Vector2] = []
        slot_size = DIE_SIZE + 14
        gap = 18
        total_w = 5 * slot_size + 4 * gap
        x0 = int((W - total_w) / 2)
        y0 = 110
        for i in range(5):
            r = pygame.Rect(x0 + i * (slot_size + gap), y0, slot_size, slot_size)
            self.slot_rects.append(r)
            self.slot_centers.append(pygame.Vector2(r.centerx, r.centery))

        for i, pos in enumerate(self.dice_positions):
            die = Die(pos[0], pos[1])
            die.home_pos = pygame.Vector2(pos[0], TABLE_Y - DIE_SIZE / 2)
            die.slot_pos = pygame.Vector2(self.slot_centers[i])
            die.pos = pygame.Vector2(die.home_pos)  # start on the table
            die.revealed = True
            self.dice.append(die)

    def start_round(self) -> None:
        bet = self.wager.value
        if bet > self.credit:
            self.message = "Insufficient credit for wager."
            return

        side_base = max(5, math.ceil(bet * 0.10))
        self.side1_stake = side_base if self.side1_toggle.active else 0
        self.side2_stake = side_base if self.side2_toggle.active else 0
        total_cost = bet + self.side1_stake + self.side2_stake

        if total_cost > self.credit:
            self.message = "Insufficient credit for wager and side bets."
            return

        self.credit -= total_cost

        for i, die in enumerate(self.dice):
            die.hold = False
            die.parked = False
            die.anim_active = False
            x, _y = self.dice_positions[i]
            die.reset_roll(x, 100)

        self.result_message = ""
        self.state = "rolling1"
        self.message = "Rolling..."

    def all_dice_revealed(self) -> bool:
        return all(die.revealed for die in self.dice)

    def all_anims_done(self) -> bool:
        return all(not d.anim_active for d in self.dice)

    def update(self, dt: float) -> None:
        if self.state in ("rolling1", "rolling2"):
            # update physics dice (held dice may be parked in slots)
            for die in self.dice:
                die.update(dt)

            # collisions only among non-parked dice
            active = [d for d in self.dice if (not d.parked and not d.anim_active)]
            for i in range(len(active)):
                for j in range(i + 1, len(active)):
                    di = active[i]
                    dj = active[j]
                    vec = dj.pos - di.pos
                    dist = vec.length()
                    if dist == 0:
                        continue
                    d_min = di.radius + dj.radius
                    if dist < d_min:
                        n = vec.normalize()
                        overlap = d_min - dist
                        correction = overlap / 2
                        di.pos -= n * correction
                        dj.pos += n * correction

                        rel_vel = di.vel - dj.vel
                        rel_vn = rel_vel.dot(n)
                        if rel_vn < 0:
                            adjust = (1 + BOUNCE) / 2 * rel_vn
                            di.vel += adjust * n
                            dj.vel -= adjust * n

            if self.all_dice_revealed():
                faces = [d.face for d in self.dice]

                if self.state == "rolling1":
                    hand_name, multiplier = compute_hand(faces)
                    if self.side1_stake > 0 and multiplier > 0:
                        pay = self.side1_stake * 5
                        self.credit += pay
                        self.message = f"Opening hand {hand_name.replace('_', ' ')}! One Roll pays {pay}."
                    elif self.side1_stake > 0:
                        self.message = "Opening hand misses One Roll side bet."
                    else:
                        self.message = "Click dice to hold, then Roll Again."
                    self.state = "hold"

                elif self.state == "rolling2":
                    # final evaluation, then presentation slide-up
                    hand_name, multiplier = compute_hand(faces)
                    bet = self.wager.value
                    payout = 0
                    if multiplier > 0:
                        payout = bet * multiplier
                        self.credit += payout
                        self.result_message = f"Final hand: {hand_name.replace('_', ' ')}! Payout {payout}."
                    else:
                        self.result_message = "No winning hand."

                    if self.side2_stake > 0:
                        if is_all_red(faces):
                            ar_pay = self.side2_stake * 15
                            self.credit += ar_pay
                            self.result_message += f" All Red pays {ar_pay}."
                        else:
                            self.result_message += " All Red side bet lost."

                    save_save(self.credit, self.settings)

                    # slide all dice into the top slots for the finish
                    for die in self.dice:
                        die.start_anim(die.slot_pos, dur=0.26, parked_end=True)

                    self.state = "presenting"
                    self.message = "Resolving..."

        elif self.state == "presenting":
            for die in self.dice:
                die.update_anim(dt)
            if self.all_anims_done():
                self.state = "finished"
                self.message = ""

        else:
            # still let any lingering anim finish (hold/unhold)
            for die in self.dice:
                die.update_anim(dt)

    # ----------------------------
    # Input helpers
    # ----------------------------
    def adjust_wager(self, delta: int) -> None:
        """Adjust wager by delta (only meaningful in betting/finished)."""
        self.wager.value = int(clamp(self.wager.value + delta, self.wager.min, self.wager.max))

    def toggle_hold_index(self, idx: int) -> None:
        if not (0 <= idx < len(self.dice)):
            return
        die = self.dice[idx]
        if die.anim_active:
            return
        die.hold = not die.hold
        if die.hold:
            die.start_anim(die.slot_pos, dur=0.22, parked_end=True)
        else:
            die.parked = False
            die.start_anim(die.home_pos, dur=0.22, parked_end=False)

    def commit_reroll(self) -> None:
        """Second roll: reroll non-held dice."""
        for i, die in enumerate(self.dice):
            if die.hold:
                die.revealed = True
                die.vel.update(0, 0)
                die.spin = 0
                die.angle = random.choice([0, 90, 180, 270])
                if not die.anim_active:
                    die.parked = True
            else:
                x, _y = self.dice_positions[i]
                die.reset_roll(x, 100)

        self.state = "rolling2"
        self.message = "Rolling final..."

    def do_primary_action(self) -> None:
        """Spacebar action: Roll / Roll Again / New Round."""
        if self.options_open:
            return
        if self.state in ("betting", "finished"):
            # Start round
            if self.state == "finished":
                for die in self.dice:
                    die.hold = False
                    die.parked = False
                    die.anim_active = False
                self.message = ""
                self.result_message = ""
            self.start_round()
        elif self.state == "hold":
            self.commit_reroll()

        # Other states: ignore

    def handle_event(self, event: pygame.event.Event) -> None:
        """Handle mouse + keyboard input.

        Key map:
          Space: Roll / Roll Again
          1-5:   Toggle hold dice 1-5 (during hold)
          ,/. :  Decrease/Increase wager (Shift = bigger step)
        """

        # ----------------------------
        # Options modal (blocks game input)
        # ----------------------------
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.options_open:
                if self.options_close_rect.collidepoint(event.pos) or not self.options_rect.collidepoint(event.pos):
                    self.options_open = False
                    save_save(self.credit, self.settings)
                    return
                # In-panel clicks
                self.options_legend_toggle.handle_event(event)
                self.settings["show_key_legend"] = bool(self.options_legend_toggle.active)
                save_save(self.credit, self.settings)
                return
            else:
                if self.options_button.clicked(event):
                    self.options_legend_toggle.active = bool(self.settings.get("show_key_legend", True))
                    self.options_open = True
                    return

        if event.type == pygame.KEYDOWN:
            if self.options_open:
                if event.key == pygame.K_ESCAPE:
                    self.options_open = False
                    save_save(self.credit, self.settings)
                return

            # Spacebar: primary action
            if event.key == pygame.K_SPACE:
                self.do_primary_action()
                return

            # 1-5: hold toggles
            if self.state == "hold" and pygame.K_1 <= event.key <= pygame.K_5:
                idx = int(event.key - pygame.K_1)
                self.toggle_hold_index(idx)
                return

            # ,/. wager changes
            if self.state in ("betting", "finished") and event.key in (pygame.K_COMMA, pygame.K_PERIOD):
                big = bool(event.mod & pygame.KMOD_SHIFT)
                step = 100 if big else 10
                delta = -step if event.key == pygame.K_COMMA else +step
                self.adjust_wager(delta)
                return

            # Escape: quit (when not in options)
            if event.key == pygame.K_ESCAPE:
                save_save(self.credit, self.settings)
                pygame.quit()
                sys.exit()

        # ----------------------------
        # Game input (mouse)
        # ----------------------------
        if self.options_open:
            return

        if self.state == "betting":
            self.wager.handle_event(event)
            self.side1_toggle.handle_event(event)
            self.side2_toggle.handle_event(event)
            if self.roll_button.clicked(event):
                self.start_round()

        elif self.state == "hold":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for i, die in enumerate(self.dice):
                    if die.hit_test(event.pos):
                        self.toggle_hold_index(i)
                        break

            if self.reroll_button.clicked(event):
                self.commit_reroll()

        elif self.state == "finished":
            self.wager.handle_event(event)
            self.side1_toggle.handle_event(event)
            self.side2_toggle.handle_event(event)
            if self.roll_button.clicked(event):
                self.do_primary_action()

    def draw_hold_slots(self) -> None:
        # Slot backgrounds and borders (drawn under dice)
        for r in self.slot_rects:
            rounded_rect(self.screen, r, SLOT_FILL, radius=16)
            rounded_rect(self.screen, r, SLOT_BORDER, radius=16, width=2)

    def draw_hold_slots_label(self) -> None:
        # Label centered above the slot row (prevents overlap with the credits HUD)
        label = self.font_small.render("HOLD SLOTS", True, (200, 205, 220))
        x_left = self.slot_rects[0].left
        x_right = self.slot_rects[-1].right
        x_mid = (x_left + x_right) / 2
        y = self.slot_rects[0].top - 6
        self.screen.blit(label, label.get_rect(midbottom=(x_mid, y)))

    def draw_hud(self) -> None:
        # Top HUD pill for credits and wager
        hud_rect = pygame.Rect(20, 18, 240, 54)
        rounded_rect(self.screen, hud_rect, PANEL_BG, radius=18)
        rounded_rect(self.screen, hud_rect, PANEL_LINE, radius=18, width=2)

        credit_surf = self.font.render(f"Credits: {self.credit}", True, WHITE)
        self.screen.blit(credit_surf, (hud_rect.x + 14, hud_rect.y + 8))

        wager_surf = self.font_small.render(f"Wager: {self.wager.value}", True, (200, 205, 220))
        self.screen.blit(wager_surf, (hud_rect.x + 14, hud_rect.y + 32))

        # Title
        title = self.font_title.render("D6 Dice Poker", True, WHITE)
        self.screen.blit(title, title.get_rect(midtop=(W / 2, 16)))

    def draw_options_overlay(self, mouse_pos: Tuple[int, int]) -> None:
        if not self.options_open:
            return

        # Dim the world
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 150))
        self.screen.blit(veil, (0, 0))

        # Panel
        rounded_rect(self.screen, self.options_rect, (30, 34, 46), radius=18)
        rounded_rect(self.screen, self.options_rect, PANEL_LINE, radius=18, width=2)

        # Title
        title = self.font.render("Options", True, WHITE)
        self.screen.blit(title, (self.options_rect.x + 22, self.options_rect.y + 18))

        # Close button
        rounded_rect(self.screen, self.options_close_rect, (55, 58, 72), radius=10)
        rounded_rect(self.screen, self.options_close_rect, PANEL_LINE, radius=10, width=2)
        x_surf = self.font_small.render("X", True, WHITE)
        self.screen.blit(x_surf, x_surf.get_rect(center=self.options_close_rect.center))

        # Keyboard legend
        section = self.font_small.render("Keyboard", True, (200, 205, 220))
        self.screen.blit(section, (self.options_rect.x + 26, self.options_rect.y + 58))

        # Toggle
        self.options_legend_toggle.draw(self.screen, mouse_pos)

        lines = [
            ("Space", "Roll / Roll Again"),
            ("1 2 3 4 5", "Toggle hold on dice 1-5"),
            (",  .", "Wager down / up"),
            ("Shift + ,/.", "Bigger wager steps"),
            ("Esc", "Close Options"),
        ]

        x0 = self.options_rect.x + 38
        y0 = self.options_rect.y + 130
        col1_w = 140
        for k, desc in lines:
            key_s = self.font.render(k, True, WHITE)
            desc_s = self.font.render(desc, True, (210, 215, 230))
            self.screen.blit(key_s, (x0, y0))
            self.screen.blit(desc_s, (x0 + col1_w, y0))
            y0 += 34

        foot = self.font_small.render("Click outside the panel to close.", True, (200, 205, 220))
        self.screen.blit(foot, (self.options_rect.x + 26, self.options_rect.bottom - 34))

    def draw_bottom_panel(self, mouse_pos: Tuple[int, int]) -> None:
        panel_rect = pygame.Rect(10, self.panel_y, W - 20, self.panel_h)
        rounded_rect(self.screen, panel_rect, PANEL_BG, radius=18)
        rounded_rect(self.screen, panel_rect, PANEL_LINE, radius=18, width=2)

        if self.state == "betting":
            self.roll_button.draw(self.screen, mouse_pos)
        elif self.state == "hold":
            self.reroll_button.draw(self.screen, mouse_pos)
        elif self.state == "finished":
            self.roll_button.draw(self.screen, mouse_pos)

        # Wager and toggles should still be visible in betting and finished
        if self.state in ("betting", "finished"):
            self.wager.draw(self.screen, mouse_pos)

            bet = self.wager.value
            side_base = max(5, math.ceil(bet * 0.10))

            self.side1_toggle.draw(self.screen, mouse_pos)
            c1 = self.font_small.render(f"Cost: {side_base}", True, (200, 205, 220))
            self.screen.blit(c1, (self.side1_toggle.rect.right + 130, self.side1_toggle.rect.y + 4))

            self.side2_toggle.draw(self.screen, mouse_pos)
            c2 = self.font_small.render(f"Cost: {side_base}", True, (200, 205, 220))
            self.screen.blit(c2, (self.side2_toggle.rect.right + 130, self.side2_toggle.rect.y + 4))

            hint = self.font_small.render("Toggle side bets, pick a wager, then roll.", True, (200, 205, 220))
            self.screen.blit(hint, (280, self.panel_y + 98))

            if bool(self.settings.get("show_key_legend", True)):
                keys = self.font_small.render("Keys: Space roll  |  ,/. wager (Shift = big)", True, (200, 205, 220))
                self.screen.blit(keys, keys.get_rect(midbottom=(W / 2, self.panel_y + self.panel_h - 18)))

        elif self.state == "hold":
            hint = self.font_small.render("Click dice to hold. Held dice slide into the top slots.", True, (200, 205, 220))
            self.screen.blit(hint, (280, self.panel_y + 100))

            if bool(self.settings.get("show_key_legend", True)):
                keys = self.font_small.render("Keys: 1-5 hold dice  |  Space Roll Again", True, (200, 205, 220))
                self.screen.blit(keys, keys.get_rect(midbottom=(W / 2, self.panel_y + self.panel_h - 18)))
    def draw_message(self) -> None:
        """Top-level status messages (kept out of the dice landing zone)."""
        if not (self.message or self.result_message):
            return

        # Reserve a "safe" strip above the dice so text never gets hidden by the row.
        safe_y = int(TABLE_Y - DIE_SIZE - 44)

        def pill(text_surf: pygame.Surface, midtop: Tuple[int, int]) -> pygame.Rect:
            r = text_surf.get_rect(midtop=midtop)
            bg = r.inflate(28, 16)
            bg_s = pygame.Surface((bg.w, bg.h), pygame.SRCALPHA)
            pygame.draw.rect(bg_s, (25, 28, 38, 210), bg_s.get_rect(), border_radius=14)
            pygame.draw.rect(bg_s, (80, 85, 105, 220), bg_s.get_rect(), width=2, border_radius=14)
            self.screen.blit(bg_s, bg.topleft)
            self.screen.blit(text_surf, r)
            return bg

        if self.message:
            msg = self.font.render(self.message, True, WHITE)
            pill(msg, (W // 2, safe_y))

        if self.result_message:
            parts = [p.strip() for p in self.result_message.split(". ") if p.strip()]
            y = safe_y - 30
            for p in parts[:3]:
                line = self.font_small.render(p, True, WHITE)
                pill(line, (W // 2, y))
                y -= 26


    def draw(self) -> None:
        self.screen.fill(BG)

        # Slot UI sits under the dice (dice can fly through without covering the slots).
        self.draw_hold_slots()

        # play surface
        pygame.draw.rect(self.screen, TABLE, (0, TABLE_Y, W, H - TABLE_Y))

        # dice
        for die in self.dice:
            die.draw(self.screen)

        mouse_pos = pygame.mouse.get_pos()

        # UI
        self.draw_hud()
        self.options_button.draw(self.screen, mouse_pos)
        self.draw_hold_slots_label()

        # bottom controls
        self.draw_bottom_panel(mouse_pos)

        # messages are drawn last so they never get hidden (unless the Options overlay is up)
        self.draw_message()

        # options overlay sits above everything
        self.draw_options_overlay(mouse_pos)

        pygame.display.flip()





def main() -> None:
    game = Game()
    running = True
    while running:
        dt = game.clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break
            game.handle_event(event)

        game.update(dt)
        game.draw()

    save_save(game.credit, game.settings)
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
