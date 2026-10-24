"""
Neon Seeker - a glowing number-guessing game for Windows.

The game picks a secret number from 1 to 100 and you have 7 tries to find it.
After every guess it tells you to go higher or lower and how hot or cold you are.
Your best score (fewest tries) is saved in a small file in your user folder.
"""

import ctypes
import json
import math
import random
import re
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QFont, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout, QWidget)

APP_NAME = "Neon Seeker"
LOWEST, HIGHEST = 1, 100
MAX_TRIES = 7
BEST_SCORE_FILE = Path.home() / ".neon_seeker_best.json"
FONT = "Segoe UI"

CYAN = QColor("#00e5ff")
PURPLE = QColor("#a855f7")
PINK = QColor("#ff2e88")
GOLD = QColor("#ffd54a")
AMBER = QColor("#ffb74d")
RED = QColor("#ff3355")
WHITE = QColor("#ffffff")
SOFT_TEXT = QColor("#c9d3ff")

# Cold -> hot colours used by the dial, the heat bar and the history.
HEAT_STOPS = [
    (0.00, QColor("#3d5afe")),
    (0.45, QColor("#00e5ff")),
    (0.70, QColor("#a855f7")),
    (0.88, QColor("#ff2e88")),
    (1.00, QColor("#ff9100")),
]

ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
NO_PEN = Qt.PenStyle.NoPen
NO_BRUSH = Qt.BrushStyle.NoBrush
ANTIALIAS = QPainter.RenderHint.Antialiasing
Ease = QEasingCurve.Type


# ----------------------------------------------------------------------------- game rules

def parse_guess(text):
    """Turn what the player typed into a number.

    Returns (number, None) when it is fine, or (None, friendly message) when it is not.
    """
    text = text.strip()
    if not text:
        return None, f"Type a number from {LOWEST} to {HIGHEST} first."
    if re.fullmatch(r"[+-]?\d+", text, re.ASCII):
        try:
            number = int(text)
        except ValueError:  # absurdly long digit strings
            number = HIGHEST + 1
        if LOWEST <= number <= HIGHEST:
            return number, None
        return None, f"That's outside the range. Pick a number from {LOWEST} to {HIGHEST}."
    if re.fullmatch(r"[+-]?\d*[.,]\d+", text, re.ASCII):
        return None, "Whole numbers only, please (no decimals)."
    return None, "That doesn't look like a number. Try something like 42."


class Game:
    """One round: the secret number and the guesses made so far."""

    def __init__(self, secret=None):
        self.secret = secret if secret is not None else random.randint(LOWEST, HIGHEST)
        self.guesses = []  # (number, hint) where hint is "higher", "lower" or "correct"

    @property
    def tries_used(self):
        return len(self.guesses)

    @property
    def tries_left(self):
        return MAX_TRIES - len(self.guesses)

    @property
    def won(self):
        return bool(self.guesses) and self.guesses[-1][1] == "correct"

    @property
    def over(self):
        return self.won or self.tries_left == 0

    @property
    def low(self):
        """Smallest number that is still possible."""
        return max([n + 1 for n, hint in self.guesses if hint == "higher"], default=LOWEST)

    @property
    def high(self):
        """Biggest number that is still possible."""
        return min([n - 1 for n, hint in self.guesses if hint == "lower"], default=HIGHEST)

    def already_tried(self, number):
        return any(n == number for n, _ in self.guesses)

    def guess(self, number):
        if self.over:
            raise ValueError("The round is already over.")
        if number == self.secret:
            hint = "correct"
        else:
            hint = "higher" if number < self.secret else "lower"
        self.guesses.append((number, hint))
        return hint


def heat_of(number, secret):
    """0 = as far away as possible, 1 = spot on. Squared so colours change faster near the target."""
    closeness = 1 - abs(number - secret) / (HIGHEST - LOWEST)
    return closeness ** 2


def heat_word(number, secret):
    distance = abs(number - secret)
    for limit, word in ((0, "BULLSEYE!"), (3, "ON FIRE"), (7, "HOT"), (15, "WARM"), (25, "COOL"), (45, "COLD")):
        if distance <= limit:
            return word
    return "FREEZING"


def heat_color(heat):
    heat = max(0.0, min(1.0, heat))
    for (p1, c1), (p2, c2) in zip(HEAT_STOPS, HEAT_STOPS[1:]):
        if heat <= p2:
            f = (heat - p1) / (p2 - p1)
            return QColor.fromRgbF(c1.redF() + (c2.redF() - c1.redF()) * f,
                                   c1.greenF() + (c2.greenF() - c1.greenF()) * f,
                                   c1.blueF() + (c2.blueF() - c1.blueF()) * f)
    return QColor(HEAT_STOPS[-1][1])


def load_best():
    """Fewest tries ever needed, or None if there is no saved score yet."""
    try:
        best = int(json.loads(BEST_SCORE_FILE.read_text(encoding="utf-8"))["best_tries"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return best if 1 <= best <= MAX_TRIES else None


def save_best(tries):
    try:
        BEST_SCORE_FILE.write_text(json.dumps({"best_tries": tries}), encoding="utf-8")
    except OSError:
        pass  # not being able to save a score should never stop the game


# ----------------------------------------------------------------------------- drawing helpers

def with_alpha(color, alpha):
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def pen(paint, width):
    p = QPen(QBrush(paint), float(width))
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return p


def make_font(px, weight=QFont.Weight.Bold, spacing=0):
    f = QFont(FONT)
    f.setPixelSize(max(1, int(px)))
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def text_path(text, font, center):
    path = QPainterPath()
    path.addText(0, 0, font, text)
    return path.translated(center - path.boundingRect().center())


def paint_glow(p, path, color, strength=1.0, spread=14.0, fill=None):
    """Draw a shape with a soft neon glow around it."""
    p.save()
    p.setBrush(NO_BRUSH)
    for i in range(6):
        p.setPen(pen(with_alpha(color, 0.07 * strength), spread * (1 - i / 6)))
        p.drawPath(path)
    p.setPen(NO_PEN)
    p.setBrush(fill if fill is not None else color)
    p.drawPath(path)
    p.restore()


_path_cache = {}
_glow_cache = {}


def cached_text_path(text, px, weight=QFont.Weight.Black, spacing=0):
    """Outline of a piece of text, centred on (0, 0). Kept for reuse because building it is slow."""
    key = (text, int(px), weight, spacing)
    if key not in _path_cache:
        _path_cache[key] = text_path(text, make_font(px, weight, spacing), QPointF(0, 0))
    return _path_cache[key]


def render_glow(path, color, spread, dpr):
    """Pre-draw the soft glow around a shape into an image, so each frame only has to copy it."""
    box = path.boundingRect().adjusted(-spread, -spread, spread, spread)
    pm = QPixmap(max(1, math.ceil(box.width() * dpr)), max(1, math.ceil(box.height() * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(ANTIALIAS)
    p.translate(-box.topLeft())
    paint_glow(p, path, color, 2.0, spread, fill=QColor(0, 0, 0, 0))
    p.end()
    return pm, box.topLeft()


def draw_glow_text(p, text, px, center, color, strength=1.0, spread=14.0, fill=None,
                   weight=QFont.Weight.Black, spacing=0):
    """Glowing text centred on a point. Strength 2 is the brightest glow."""
    path = cached_text_path(text, px, weight, spacing)
    dpr = p.device().devicePixelRatioF()
    key = (text, int(px), weight, spacing, QColor(color).rgba(), int(spread), dpr)
    if key not in _glow_cache:
        if len(_glow_cache) > 300:
            _glow_cache.clear()
        _glow_cache[key] = render_glow(path, color, int(spread), dpr)
    pm, offset = _glow_cache[key]
    p.save()
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.translate(center)
    opacity = p.opacity()
    p.setOpacity(opacity * max(0.0, min(1.0, strength / 2)))
    p.drawPixmap(offset, pm)
    p.setOpacity(opacity)
    p.fillPath(path, QBrush(fill if fill is not None else color))
    p.restore()
    return path


def heart_path(size):
    s = size
    path = QPainterPath()
    path.moveTo(0, 0.42 * s)
    path.cubicTo(-0.62 * s, 0.02 * s, -0.48 * s, -0.50 * s, 0, -0.20 * s)
    path.cubicTo(0.48 * s, -0.50 * s, 0.62 * s, 0.02 * s, 0, 0.42 * s)
    return path.translated(0, -0.05 * s)


def make_anim(owner, setter, duration, easing=Ease.OutCubic):
    anim = QVariantAnimation(owner)
    anim.setDuration(duration)
    anim.setEasingCurve(easing)
    anim.valueChanged.connect(setter)
    return anim


def run_anim(anim, start, end):
    anim.stop()
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.start()


def eased(kind, progress):
    return QEasingCurve(kind).valueForProgress(max(0.0, min(1.0, progress)))


def make_icon(size=256):
    """The app icon: a glowing question mark in a neon ring."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(ANTIALIAS)
    c = QPointF(size / 2, size / 2)
    r = size * 0.46
    bg = QRadialGradient(c - QPointF(0, size * 0.12), r * 1.3)
    bg.setColorAt(0, QColor("#24206b"))
    bg.setColorAt(1, QColor("#070818"))
    p.setPen(NO_PEN)
    p.setBrush(bg)
    p.drawEllipse(c, r, r)
    ring = QConicalGradient(c, 90)
    for pos, color in ((0, CYAN), (0.33, PURPLE), (0.66, PINK), (1, CYAN)):
        ring.setColorAt(pos, color)
    p.setBrush(NO_BRUSH)
    p.setPen(pen(ring, size * 0.06))
    p.drawEllipse(c, r * 0.86, r * 0.86)
    path = text_path("?", make_font(size * 0.55, QFont.Weight.Black), c + QPointF(0, size * 0.01))
    paint_glow(p, path, CYAN, 1.4, size * 0.08, fill=QColor("#e9fdff"))
    p.end()
    return pm


# ----------------------------------------------------------------------------- screen pieces

class Title(QWidget):
    """The game name with a gradient and a light sheen sweeping across it."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(62)
        self.setMinimumWidth(380)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(ANTIALIAS)
        text = APP_NAME.upper()
        box = cached_text_path(text, 40, QFont.Weight.Black, 8).boundingRect()
        grad = QLinearGradient(box.left(), 0, box.right(), 0)
        grad.setColorAt(0, CYAN)
        grad.setColorAt(0.5, PURPLE)
        grad.setColorAt(1, PINK)
        sheen = (time.monotonic() * 0.3) % 2.0 - 0.4
        if 0 < sheen < 1:
            grad.setColorAt(sheen, QColor("#eafcff"))
        draw_glow_text(p, text, 40, QPointF(12 + box.width() / 2, self.height() / 2), PURPLE, 1.0, 18,
                       fill=grad, spacing=8)


class Dial(QWidget):
    """The big round display. Its glowing arc glides to each new guess."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(400, 400)
        self.value = 0.0  # 0 means "no guess yet"
        self.color = QColor(CYAN)
        self.caption = "MAKE A GUESS"
        self.low, self.high = LOWEST, HIGHEST
        self.marks = []  # earlier guesses as (number, colour)
        self.pulse = 0.0
        self._move = make_anim(self, self._set_value, 900)
        self._pulse = make_anim(self, self._set_pulse, 800, Ease.OutQuad)
        self._move.finished.connect(lambda: run_anim(self._pulse, 1, 0))

    def _set_value(self, v):
        self.value = v
        self.update()

    def _set_pulse(self, v):
        self.pulse = v
        self.update()

    def show_guess(self, number, color, caption, low, high, marks):
        self.color, self.caption, self.low, self.high, self.marks = QColor(color), caption, low, high, marks
        run_anim(self._move, max(self.value, LOWEST), number)

    def reset(self):
        self._move.stop()
        self._pulse.stop()
        self.value, self.pulse = 0.0, 0.0
        self.color = QColor(CYAN)
        self.caption = "MAKE A GUESS"
        self.low, self.high = LOWEST, HIGHEST
        self.marks = []
        self.update()

    @staticmethod
    def _degrees(v):
        return 225 - 270 * (v - LOWEST) / (HIGHEST - LOWEST)

    def _point(self, center, radius, v):
        a = math.radians(self._degrees(v))
        return QPointF(center.x() + radius * math.cos(a), center.y() - radius * math.sin(a))

    def _arc(self, p, rect, v1, v2):
        start = self._degrees(v1)
        span = self._degrees(v2) - start
        p.drawArc(rect, int(start * 16), int(span * 16))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(ANTIALIAS)
        side = min(self.width(), self.height())
        c = QPointF(self.width() / 2, self.height() / 2)
        r = side / 2 - 46
        has_guess = self.value >= LOWEST
        idle = 0.5 + 0.5 * math.sin(time.monotonic() * 2.2)

        halo = QRadialGradient(c, side / 2)
        halo.setColorAt(0, with_alpha(self.color, 0.20 + 0.15 * self.pulse))
        halo.setColorAt(0.6, with_alpha(self.color, 0.06))
        halo.setColorAt(1, with_alpha(self.color, 0))
        p.setPen(NO_PEN)
        p.setBrush(halo)
        p.drawEllipse(c, side / 2, side / 2)

        face = QRadialGradient(c - QPointF(0, r * 0.3), r * 1.2)
        face.setColorAt(0, QColor("#1b2050"))
        face.setColorAt(1, QColor("#080a1c"))
        p.setBrush(face)
        p.setPen(pen(with_alpha(self.color, 0.35), 1.5))
        p.drawEllipse(c, r - 20, r - 20)

        # track, plus the part of it that can still hold the secret number
        ring = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        p.setBrush(NO_BRUSH)
        p.setPen(pen(QColor(255, 255, 255, 20), 14))
        self._arc(p, ring, LOWEST, HIGHEST)
        if self.marks:
            p.setPen(pen(QColor(255, 255, 255, 55), 14))
            self._arc(p, ring, self.low - 0.45, self.high + 0.45)

        for v in range(LOWEST, HIGHEST + 1):
            major = v == LOWEST or v % 10 == 0
            if not major and v % 2:
                continue
            p.setPen(pen(QColor(255, 255, 255, 110 if major else 40), 2 if major else 1))
            p.drawLine(self._point(c, r + 13, v), self._point(c, r + (25 if major else 19), v))

        p.setFont(make_font(max(10, r * 0.065)))
        p.setPen(QColor(255, 255, 255, 90))
        for v in (1, 25, 50, 75, 100):
            pt = self._point(c, r - 40, v)
            p.drawText(QRectF(pt.x() - 22, pt.y() - 11, 44, 22), ALIGN_CENTER, str(v))

        if has_guess:
            for width, alpha in ((38, 0.06), (28, 0.09), (20, 0.15)):
                p.setPen(pen(with_alpha(self.color, alpha * (1 + self.pulse)), width))
                self._arc(p, ring, LOWEST, self.value)
            p.setPen(pen(self.color, 12))
            self._arc(p, ring, LOWEST, self.value)
            p.setPen(pen(with_alpha(WHITE, 0.55), 3))
            self._arc(p, ring, LOWEST, self.value)
            tip = self._point(c, r, self.value)
            glow = QRadialGradient(tip, 26)
            glow.setColorAt(0, with_alpha(self.color, 0.9))
            glow.setColorAt(1, with_alpha(self.color, 0))
            p.setPen(NO_PEN)
            p.setBrush(glow)
            p.drawEllipse(tip, 26, 26)
            p.setBrush(WHITE)
            p.drawEllipse(tip, 6, 6)

        for number, color in self.marks:
            dot = self._point(c, r + 35, number)
            p.setPen(NO_PEN)
            p.setBrush(with_alpha(color, 0.35))
            p.drawEllipse(dot, 8, 8)
            p.setBrush(color)
            p.drawEllipse(dot, 4, 4)

        text = str(round(self.value)) if has_guess else "?"
        strength = 1.2 + 1.5 * self.pulse if has_guess else 0.7 + 0.7 * idle
        draw_glow_text(p, text, r * 0.58, c - QPointF(0, r * 0.06), self.color, strength, r * 0.11,
                       fill=QColor(self.color).lighter(135))

        p.setFont(make_font(r * 0.075, QFont.Weight.Bold, 3))
        p.setPen(with_alpha(self.color, 0.95))
        p.drawText(QRectF(c.x() - r, c.y() + r * 0.30, 2 * r, r * 0.2), ALIGN_CENTER, self.caption)


class HeatBar(QWidget):
    """Cold-to-hot bar. A marker springs to how close the guess was, then sends out a ripple."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(58)
        self.level = 0.0
        self.color = QColor(CYAN)
        self.active = False
        self.ripple = 1.0
        self._move = make_anim(self, self._set_level, 1000, Ease.OutBack)
        self._ripple = make_anim(self, self._set_ripple, 900)
        self._move.finished.connect(lambda: run_anim(self._ripple, 0, 1))

    def _set_level(self, v):
        self.level = v
        self.update()

    def _set_ripple(self, v):
        self.ripple = v
        self.update()

    def set_heat(self, heat, color):
        self.active = True
        self.color = QColor(color)
        run_anim(self._move, self.level, heat)

    def reset(self):
        self._move.stop()
        self._ripple.stop()
        self.level, self.ripple, self.active = 0.0, 1.0, False
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(ANTIALIAS)
        left, right = 14, self.width() - 14
        y, bh = self.height() / 2 + 6, 12
        bar = QRectF(left, y - bh / 2, right - left, bh)
        grad = QLinearGradient(left, 0, right, 0)
        for pos, color in HEAT_STOPS:
            grad.setColorAt(pos, color)

        p.setFont(make_font(10, QFont.Weight.Bold, 2))
        label_box = QRectF(left, 0, right - left, y - bh / 2 - 5)
        p.setPen(with_alpha(HEAT_STOPS[0][1], 0.9))
        p.drawText(label_box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, "COLD")
        p.setPen(with_alpha(HEAT_STOPS[-1][1], 0.9))
        p.drawText(label_box, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, "HOT")

        p.setPen(NO_PEN)
        p.setBrush(grad)
        p.setOpacity(0.2)
        p.drawRoundedRect(bar, bh / 2, bh / 2)
        p.setOpacity(1)
        if not self.active:
            return

        x = left + (right - left) * max(0.0, min(1.0, self.level))
        p.save()
        p.setClipRect(QRectF(0, 0, x, self.height()))
        for grow, alpha in ((9, 0.10), (5, 0.18)):
            p.setOpacity(alpha)
            p.drawRoundedRect(bar.adjusted(-grow, -grow, grow, grow), bh, bh)
        p.setOpacity(1)
        p.drawRoundedRect(bar, bh / 2, bh / 2)
        p.restore()

        center = QPointF(x, y)
        if self.ripple < 1:
            p.setBrush(NO_BRUSH)
            p.setPen(pen(with_alpha(self.color, 1 - self.ripple), 2.5))
            radius = 10 + 13 * self.ripple
            p.drawEllipse(center, radius, radius)
        halo = QRadialGradient(center, 22)
        halo.setColorAt(0, with_alpha(self.color, 0.8))
        halo.setColorAt(1, with_alpha(self.color, 0))
        p.setPen(NO_PEN)
        p.setBrush(halo)
        p.drawEllipse(center, 22, 22)
        p.setBrush(WHITE)
        p.setPen(pen(self.color, 3))
        p.drawEllipse(center, 8, 8)


class Lives(QWidget):
    """Seven glowing hearts. One fades away for every try used."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(54)
        self.alive = [1.0] * MAX_TRIES
        self._anims = [make_anim(self, lambda v, i=i: self._set(i, v), 800, Ease.InOutCubic)
                       for i in range(MAX_TRIES)]

    def _set(self, i, v):
        self.alive[i] = v
        self.update()

    def set_lives(self, left):
        for i in range(MAX_TRIES):
            target = 1.0 if i < left else 0.0
            if self.alive[i] != target:
                run_anim(self._anims[i], self.alive[i], target)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(ANTIALIAS)
        slot = self.width() / MAX_TRIES
        s = min(self.height() * 0.8, slot * 0.8)
        breath = 0.5 + 0.5 * math.sin(time.monotonic() * 3)
        for i, a in enumerate(self.alive):
            c = QPointF(slot * (i + 0.5), self.height() / 2)
            p.setBrush(NO_BRUSH)
            p.setPen(pen(QColor(255, 255, 255, 35), 1.4))
            p.drawPath(heart_path(s * 0.9).translated(c))
            if a <= 0.01:
                continue
            scale = 0.55 + 0.45 * a
            glow_radius = self.height() / 2
            halo = QRadialGradient(c, glow_radius)
            halo.setColorAt(0, with_alpha(PINK, (0.45 + 0.2 * breath) * a))
            halo.setColorAt(1, with_alpha(PINK, 0))
            p.setPen(NO_PEN)
            p.setBrush(halo)
            p.drawEllipse(c, glow_radius, glow_radius)
            fill = QLinearGradient(c.x(), c.y() - s / 2, c.x(), c.y() + s / 2)
            fill.setColorAt(0, with_alpha(QColor("#ff8ad8"), a))
            fill.setColorAt(1, with_alpha(PINK, a))
            p.setBrush(fill)
            p.setPen(pen(with_alpha(QColor("#ffd1f0"), 0.8 * a), 1.2))
            p.drawPath(heart_path(s * 0.9 * scale).translated(c))
            p.setPen(NO_PEN)
            p.setBrush(with_alpha(WHITE, 0.45 * a))
            p.drawEllipse(QPointF(c.x() - s * 0.17 * scale, c.y() - s * 0.14 * scale), s * 0.07 * scale, s * 0.05 * scale)


class HistoryStrip(QWidget):
    """Seven slots that fill up with your guesses, coloured hot or cold."""

    ARROWS = {"higher": "▲", "lower": "▼", "correct": "★"}

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(88)
        self.entries = []  # (number, hint, colour)
        self.pop = 1.0
        self._pop = make_anim(self, self._set_pop, 550, Ease.OutBack)

    def _set_pop(self, v):
        self.pop = v
        self.update()

    def add(self, number, hint, color):
        self.entries.append((number, hint, QColor(color)))
        run_anim(self._pop, 0, 1)

    def reset(self):
        self._pop.stop()
        self.entries, self.pop = [], 1.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(ANTIALIAS)
        gap = 8
        w = (self.width() - gap * (MAX_TRIES - 1)) / MAX_TRIES
        for i in range(MAX_TRIES):
            rect = QRectF(i * (w + gap), 3, w, self.height() - 6)
            if i >= len(self.entries):
                dashed = pen(QColor(255, 255, 255, 40), 1.2)
                dashed.setStyle(Qt.PenStyle.DashLine)
                p.setPen(dashed)
                p.setBrush(QColor(255, 255, 255, 8))
                p.drawRoundedRect(rect, 12, 12)
                p.setPen(QColor(255, 255, 255, 50))
                p.setFont(make_font(11))
                p.drawText(rect, ALIGN_CENTER, f"#{i + 1}")
                continue
            number, hint, color = self.entries[i]
            k = max(0.01, self.pop) if i == len(self.entries) - 1 else 1.0
            p.save()
            p.translate(rect.center())
            p.scale(k, k)
            p.translate(-rect.center())
            p.setOpacity(min(1.0, k))
            bg = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            bg.setColorAt(0, with_alpha(color, 0.30))
            bg.setColorAt(1, with_alpha(color, 0.08))
            p.setBrush(bg)
            p.setPen(pen(with_alpha(color, 0.9), 1.6))
            p.drawRoundedRect(rect, 12, 12)
            p.setPen(QColor(255, 255, 255, 120))
            p.setFont(make_font(10))
            p.drawText(rect.adjusted(0, 6, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f"#{i + 1}")
            p.setPen(WHITE)
            p.setFont(make_font(min(24, w * 0.38), QFont.Weight.Black))
            p.drawText(rect, ALIGN_CENTER, str(number))
            p.setPen(QColor(color).lighter(130))
            p.setFont(make_font(13))
            p.drawText(rect.adjusted(0, 0, 0, -6), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       self.ARROWS[hint])
            p.restore()


class _Bit:
    __slots__ = ("x", "y", "vx", "vy", "angle", "spin", "flip", "flip_speed", "color", "size", "round")


class Confetti:
    """Confetti shot from both bottom corners, plus some falling from the top. Drawn by the win screen."""

    COLORS = [CYAN, PINK, GOLD, PURPLE, QColor("#7cff6b"), QColor("#ff9100")]

    def __init__(self):
        self.bits = []

    def _bit(self, x, y, vx, vy):
        b = _Bit()
        b.x, b.y, b.vx, b.vy = x, y, vx, vy
        b.angle, b.spin = random.uniform(0, 360), random.uniform(-12, 12)
        b.flip, b.flip_speed = random.uniform(0, 6.28), random.uniform(0.08, 0.25)
        b.color, b.size, b.round = random.choice(self.COLORS), random.uniform(7, 13), random.random() < 0.3
        return b

    def burst(self, w, h):
        k = h / 700
        self.bits = []
        for direction, x in ((1, 0), (-1, w)):
            for _ in range(110):
                self.bits.append(self._bit(x, h, direction * random.uniform(4, 14) * k, -random.uniform(16, 27) * k))
        for _ in range(90):
            self.bits.append(self._bit(random.uniform(0, w), random.uniform(-h * 0.6, -10),
                                       random.uniform(-1.5, 1.5) * k, random.uniform(1, 4) * k))

    def step(self, frames, h):
        """Move every piece on; `frames` is the time passed, counted in 1/60ths of a second."""
        gravity = 0.32 * h / 700
        drag = 0.975 ** frames
        alive = []
        for b in self.bits:
            b.vy = (b.vy + gravity * frames) * drag
            b.vx = b.vx * drag + math.sin(b.flip) * 0.12 * frames
            b.x += b.vx * frames
            b.y += b.vy * frames
            b.angle += b.spin * frames
            b.flip += b.flip_speed * frames
            if b.y < h + 30:
                alive.append(b)
        self.bits = alive

    def paint(self, p):
        p.save()
        p.setPen(NO_PEN)
        for b in self.bits:
            turn = math.cos(b.flip)
            p.save()
            p.translate(b.x, b.y)
            p.rotate(b.angle)
            p.scale(1, max(0.05, abs(turn)))
            p.setBrush(b.color if turn > 0 else b.color.darker(140))
            if b.round:
                p.drawEllipse(QPointF(0, 0), b.size / 2.6, b.size / 2.6)
            else:
                p.drawRect(QRectF(-b.size / 2, -b.size / 4, b.size, b.size / 2))
            p.restore()
        p.restore()


class ResultOverlay(QWidget):
    """The win screen and the game-over screen, drawn over the whole window."""

    play_again = Signal()
    closed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hide()
        self.mode, self.secret, self.tries, self.best, self.new_best = "win", 0, 0, None, False
        self.fade, self.intro, self.t, self.glitch = 0.0, 0.0, 0.0, 0.0
        self._fading_out = False

        self.button = QPushButton("PLAY AGAIN", self)
        self.button.setObjectName("again")
        self.button.setFont(make_font(18, QFont.Weight.Black, 3))
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button.clicked.connect(self._request_new_game)
        self._button_glow = QGraphicsDropShadowEffect(self.button)
        self._button_glow.setOffset(0, 0)
        self.button.setGraphicsEffect(self._button_glow)
        self._layout = QVBoxLayout(self)
        self._layout.addStretch(1)
        self._layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)

        self._fade = make_anim(self, lambda v: self._set("fade", v), 400)
        self._fade.finished.connect(self._after_fade)
        self._intro = make_anim(self, lambda v: self._set("intro", v), 1500, Ease.Linear)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._last_tick = time.monotonic()
        self.confetti = Confetti()
        self._backdrop = None  # picture of the game behind, so it doesn't have to be redrawn every frame

    def _set(self, name, value):
        setattr(self, name, value)
        self.update()

    def _use_backdrop(self, picture):
        self._backdrop = picture
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, picture is not None)

    def show_result(self, mode, secret, tries, best, new_best):
        self.mode, self.secret, self.tries, self.best, self.new_best = mode, secret, tries, best, new_best
        self._fading_out = False
        self.fade, self.intro, self.t = 0.0, 0.0, 0.0
        self._button_glow.setColor(GOLD if mode == "win" else RED)
        self.hide()
        self.setGeometry(self.parentWidget().rect())
        self._use_backdrop(self.parentWidget().grab())
        self.confetti.bits = []
        if mode == "win":
            self.confetti.burst(self.width(), self.height())
        self.button.hide()
        self.show()
        self.raise_()
        self.setFocus()
        run_anim(self._fade, 0, 1)
        run_anim(self._intro, 0, 1)
        self._last_tick = time.monotonic()
        self._timer.start()

    def hide_result(self):
        if self.isVisible() and not self._fading_out:
            self._fading_out = True
            self._use_backdrop(None)  # let the fresh game show through while fading out
            run_anim(self._fade, self.fade, 0)

    def _after_fade(self):
        if self._fading_out:
            self.hide()
            self._timer.stop()
            self.confetti.bits = []
            self.closed.emit()

    def _request_new_game(self):
        if not self._fading_out and self.intro >= 0.5:
            self.play_again.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._request_new_game()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        self._layout.setContentsMargins(0, 0, 0, int(self.height() * 0.11))
        if self._backdrop is not None and self._backdrop.deviceIndependentSize().toSize() != self.size():
            self._use_backdrop(None)

    def _tick(self):
        now = time.monotonic()
        elapsed = min(0.1, now - self._last_tick)
        self._last_tick = now
        self.t += elapsed
        self.confetti.step(elapsed * 60, self.height())
        self.glitch = random.random() if random.random() < 0.06 else 0.0
        self._button_glow.setBlurRadius(28 + 22 * (0.5 + 0.5 * math.sin(self.t * 4)))
        if self.intro > 0.6 and not self._fading_out and not self.button.isVisible():
            self.button.show()
        self.update()

    def _line(self, p, text, y, font, color):
        p.setFont(font)
        p.setPen(color)
        p.drawText(QRectF(0, y - 40, self.width(), 80), ALIGN_CENTER, text)

    def _paint_rays(self, p, c, color):
        # The rays are soft, so they are drawn on a small image and stretched: much faster.
        small = QPixmap(max(1, self.width() // 4), max(1, self.height() // 4))
        small.fill(Qt.GlobalColor.transparent)
        q = QPainter(small)
        q.scale(0.25, 0.25)
        rays = QConicalGradient(c, self.t * 12)
        for i in range(12):
            rays.setColorAt(i / 12, with_alpha(color, 0))
            rays.setColorAt((i + 0.5) / 12, with_alpha(color, 0.12))
        rays.setColorAt(1, with_alpha(color, 0))
        q.fillRect(self.rect(), QBrush(rays))
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        fade = QRadialGradient(c, max(self.width(), self.height()) * 0.7)
        fade.setColorAt(0, QColor(0, 0, 0, 255))
        fade.setColorAt(1, QColor(0, 0, 0, 0))
        q.fillRect(self.rect(), QBrush(fade))
        q.end()
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(self.rect(), small)
        p.restore()

    def _paint_scanlines(self, p):
        w, h = self.width(), self.height()
        p.save()
        p.setRenderHint(ANTIALIAS, False)
        p.setPen(QColor(255, 40, 70, 16))
        for y in range(0, h, 4):
            p.drawLine(0, y, w, y)
        p.restore()
        band = (self.t * 160) % (h + 200) - 100
        g = QLinearGradient(0, band - 60, 0, band + 60)
        g.setColorAt(0, with_alpha(RED, 0))
        g.setColorAt(0.5, with_alpha(RED, 0.09))
        g.setColorAt(1, with_alpha(RED, 0))
        p.fillRect(QRectF(0, band - 60, w, 120), QBrush(g))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(ANTIALIAS)
        w, h = self.width(), self.height()
        c = QPointF(w / 2, h * 0.38)
        win = self.mode == "win"
        accent = GOLD if win else RED
        if self._backdrop is not None:
            p.drawPixmap(0, 0, self._backdrop)
        p.setOpacity(self.fade)
        p.fillRect(self.rect(), QColor(4, 5, 16, 228))
        vignette = QRadialGradient(c, max(w, h) * 0.6)
        vignette.setColorAt(0, with_alpha(accent, 0.22))
        vignette.setColorAt(1, with_alpha(accent, 0))
        p.fillRect(self.rect(), QBrush(vignette))

        if win:
            self._paint_rays(p, c, accent)
            size = min(w * 0.085, 86)
            k = max(0.01, eased(Ease.OutBack, self.intro / 0.4))
            fill = QLinearGradient(0, -size / 2, 0, size / 2)
            fill.setColorAt(0, QColor("#fff6cf"))
            fill.setColorAt(1, GOLD)
            p.save()
            p.translate(c)
            p.scale(k, k)
            draw_glow_text(p, "YOU FOUND IT!", size, QPointF(0, 0), accent, 1.6, size * 0.28, fill=fill, spacing=4)
            p.restore()
        else:
            self._paint_scanlines(p)
            size = min(w * 0.12, 120)
            title = cached_text_path("GAME OVER", size, QFont.Weight.Black, 6)
            slam = min(1.0, self.intro / 0.22)
            k = 2.4 - 1.4 * eased(Ease.OutCubic, slam)
            shake_t = (self.intro - 0.22) / 0.45
            shake = math.sin(shake_t * math.pi * 9) * 18 * (1 - shake_t) if 0 < shake_t < 1 else 0
            split = 4 + 14 * self.glitch
            p.save()
            p.translate(c.x() + shake, c.y())
            p.scale(k, k)
            p.setOpacity(self.fade * min(1.0, slam * 1.6))
            p.fillPath(title.translated(-split, 0), QBrush(with_alpha(CYAN, 0.55)))
            p.fillPath(title.translated(split, 2), QBrush(with_alpha(QColor("#ff0040"), 0.55)))
            draw_glow_text(p, "GAME OVER", size, QPointF(0, 0), accent, 1.5, size * 0.25,
                           fill=QColor("#ffe3e8"), spacing=6)
            if self.glitch:
                # a slice of the title jumps sideways now and then
                p.setClipRect(QRectF(-w, -size * 0.1 + self.glitch * size * 0.3 - size * 0.2, 2 * w, size * 0.12))
                p.fillPath(title.translated(30 * (self.glitch - 0.5), 0), QBrush(QColor("#ffe3e8")))
            p.restore()

        p.setOpacity(self.fade * max(0.0, min(1.0, (self.intro - 0.35) / 0.3)))
        y = c.y() + size * 0.95
        if win:
            self._line(p, f"The secret number was {self.secret}", y, make_font(24, QFont.Weight.DemiBold), WHITE)
            word = "try" if self.tries == 1 else "tries"
            self._line(p, f"You found it in {self.tries} {word}", y + 40, make_font(19), accent)
            if self.new_best:
                draw_glow_text(p, "★  NEW BEST SCORE  ★", 22, QPointF(w / 2, y + 92), GOLD,
                               1.0 + 0.8 * math.sin(self.t * 5) ** 2, 16, fill=QColor("#fff6cf"), spacing=3)
            elif self.best:
                word = "try" if self.best == 1 else "tries"
                self._line(p, f"Your best score is {self.best} {word}", y + 88, make_font(16, QFont.Weight.DemiBold),
                           SOFT_TEXT)
        else:
            self._line(p, "THE SECRET NUMBER WAS", y - 6, make_font(15, QFont.Weight.Bold, 4), SOFT_TEXT)
            progress = eased(Ease.OutCubic, (self.intro - 0.35) / 0.6)
            shown = round(LOWEST + (self.secret - LOWEST) * progress)
            draw_glow_text(p, str(shown), size * 0.62, QPointF(w / 2, y + size * 0.5), CYAN, 1.5, size * 0.12,
                           fill=QColor("#e9fdff"))
            self._line(p, "Out of tries. Better luck next time!", y + size * 1.05, make_font(17, QFont.Weight.DemiBold),
                       SOFT_TEXT)

        p.setOpacity(self.fade)
        self.confetti.paint(p)


# ----------------------------------------------------------------------------- main window

STYLE = """
QWidget { color: #e6eaff; font-family: "Segoe UI"; }
QLabel#subtitle { color: #8e97c9; font-size: 14px; }
QLabel#best { color: #ffd54a; background: rgba(255, 213, 74, 22); border: 1px solid rgba(255, 213, 74, 110);
              border-radius: 17px; padding: 8px 18px; }
QFrame#card { background: rgba(255, 255, 255, 9); border: 1px solid rgba(255, 255, 255, 26); border-radius: 22px; }
QLabel#caption { color: #7f88bd; }
QLabel#tries { color: #ff8ad8; font-size: 13px; font-weight: 800; }
QLabel#heat { color: #8e97c9; }
QLabel#message { font-size: 15px; font-weight: 600; }
QLabel#tip { color: #5d6699; font-size: 12px; }
QLineEdit { background: rgba(5, 8, 25, 220); border: 2px solid rgba(0, 229, 255, 90); border-radius: 14px;
            padding: 8px 16px; font-size: 26px; font-weight: 700; color: white; selection-background-color: #a855f7; }
QLineEdit:focus { border: 2px solid #00e5ff; }
QLineEdit:disabled { color: rgba(255, 255, 255, 70); border: 2px solid rgba(255, 255, 255, 25); }
QLineEdit[error="true"] { border: 2px solid #ffb74d; }
QPushButton#guess { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00e5ff, stop:1 #a855f7);
                    color: #0a0420; border: none; border-radius: 14px; padding: 14px 28px; font-size: 18px; font-weight: 900; }
QPushButton#guess:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5ff0ff, stop:1 #c084fc); }
QPushButton#guess:pressed { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00b8cc, stop:1 #8b3fd9); }
QPushButton#guess:disabled { background: rgba(255, 255, 255, 20); color: rgba(255, 255, 255, 70); }
QPushButton#again { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00e5ff, stop:1 #ff2e88);
                    color: #0a0420; border: none; border-radius: 26px; padding: 14px 48px; }
QPushButton#again:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5ff0ff, stop:1 #ff6bab); }
"""

# Slowly drifting coloured lights in the background: (x, y, size, colour, speed, phase)
ORBS = [
    (0.12, 0.25, 0.35, CYAN, 0.21, 0.0),
    (0.85, 0.20, 0.30, PINK, 0.17, 1.7),
    (0.55, 0.85, 0.40, PURPLE, 0.13, 3.1),
    (0.30, 0.70, 0.22, QColor("#3d5afe"), 0.25, 4.4),
    (0.75, 0.60, 0.20, CYAN, 0.19, 5.2),
]


def caption(text):
    label = QLabel(text)
    label.setObjectName("caption")
    label.setFont(make_font(11, QFont.Weight.ExtraBold, 3))
    return label


def glow_effect(widget, color, blur):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setOffset(0, 0)
    effect.setBlurRadius(blur)
    effect.setColor(color)
    widget.setGraphicsEffect(effect)
    return effect


class GameWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 700)
        self.resize(1140, 760)
        self.setStyleSheet(STYLE)
        self.game = Game()
        self._backdrop = None
        self._build_ui()
        self.overlay = ResultOverlay(self)
        self.overlay.play_again.connect(self.new_game)
        self.overlay.closed.connect(self._update_ticker)
        self._error_timer = QTimer(self)
        self._error_timer.setSingleShot(True)
        self._error_timer.timeout.connect(lambda: self._set_error(False))
        self._ticker = QTimer(self)  # keeps the background and glows gently moving
        self._ticker.timeout.connect(self.update)
        self.new_game()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 20, 32, 26)
        root.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(Title())
        subtitle = QLabel(f"Find the secret number from {LOWEST} to {HIGHEST}. You have {MAX_TRIES} tries.")
        subtitle.setObjectName("subtitle")
        subtitle.setContentsMargins(10, 0, 0, 0)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.best_label = QLabel()
        self.best_label.setObjectName("best")
        self.best_label.setFont(make_font(14, QFont.Weight.ExtraBold, 2))
        glow_effect(self.best_label, with_alpha(GOLD, 0.6), 24)
        header.addWidget(self.best_label, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(26)
        self.dial = Dial()
        body.addWidget(self.dial, 11)

        card = QFrame()
        card.setObjectName("card")
        card.setMinimumWidth(430)
        col = QVBoxLayout(card)
        col.setContentsMargins(26, 20, 26, 18)
        col.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(caption("LIVES"))
        row.addStretch(1)
        self.tries_label = QLabel()
        self.tries_label.setObjectName("tries")
        row.addWidget(self.tries_label)
        col.addLayout(row)
        self.lives = Lives()
        col.addWidget(self.lives)
        col.addSpacing(6)

        row = QHBoxLayout()
        row.addWidget(caption("HOT OR COLD"))
        row.addStretch(1)
        self.heat_label = QLabel()
        self.heat_label.setObjectName("heat")
        self.heat_label.setFont(make_font(13, QFont.Weight.Black, 2))
        row.addWidget(self.heat_label)
        col.addLayout(row)
        self.heat_bar = HeatBar()
        col.addWidget(self.heat_bar)
        col.addSpacing(8)

        col.addWidget(caption("YOUR GUESS"))
        row = QHBoxLayout()
        row.setSpacing(12)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText(f"{LOWEST} – {HIGHEST}")
        self.entry.setMaxLength(12)
        self.entry.returnPressed.connect(self.submit)
        self._entry_glow = glow_effect(self.entry, with_alpha(CYAN, 0.55), 26)
        self.guess_button = QPushButton("GUESS")
        self.guess_button.setObjectName("guess")
        self.guess_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.guess_button.clicked.connect(self.submit)
        row.addWidget(self.entry, 1)
        row.addWidget(self.guess_button)
        col.addLayout(row)
        self.message = QLabel()
        self.message.setObjectName("message")
        self.message.setWordWrap(True)
        self.message.setMinimumHeight(46)
        col.addWidget(self.message)

        col.addWidget(caption("YOUR GUESSES"))
        self.history = HistoryStrip()
        col.addWidget(self.history)
        col.addStretch(1)
        tip = QLabel("Tip: press Enter to submit a guess.")
        tip.setObjectName("tip")
        col.addWidget(tip)
        body.addWidget(card, 9)
        root.addLayout(body, 1)

    # --- background -----------------------------------------------------------------------

    def _make_backdrop(self):
        """The still part of the background: a deep gradient and a neon perspective grid."""
        dpr = self.devicePixelRatioF()
        w, h = self.width(), self.height()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        p = QPainter(pm)
        p.setRenderHint(ANTIALIAS)
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor("#05061a"))
        bg.setColorAt(0.6, QColor("#0b0826"))
        bg.setColorAt(1, QColor("#16072c"))
        p.fillRect(QRectF(0, 0, w, h), QBrush(bg))
        horizon = h * 0.70
        glow = QLinearGradient(0, horizon - 90, 0, horizon + 10)
        glow.setColorAt(0, with_alpha(PINK, 0))
        glow.setColorAt(0.85, with_alpha(PINK, 0.10))
        glow.setColorAt(1, with_alpha(PINK, 0))
        p.fillRect(QRectF(0, horizon - 90, w, 100), QBrush(glow))
        p.setPen(pen(QColor(168, 85, 247, 34), 1))
        for i in range(1, 14):
            y = horizon + (h - horizon) * (i / 13) ** 2
            p.drawLine(QPointF(0, y), QPointF(w, y))
        for k in range(-16, 17):
            p.drawLine(QPointF(w / 2 + k * w * 0.02, horizon), QPointF(w / 2 + k * w * 0.16, h))
        p.end()
        return pm

    def paintEvent(self, event):
        p = QPainter(self)
        if self._backdrop is None or self._backdrop.deviceIndependentSize().toSize() != self.size():
            self._backdrop = self._make_backdrop()
        p.drawPixmap(0, 0, self._backdrop)
        # The lights are blurry anyway, so draw them on a small image and stretch it: much faster.
        w, h = self.width(), self.height()
        lights = QPixmap(max(1, w // 6), max(1, h // 6))
        lights.fill(Qt.GlobalColor.transparent)
        q = QPainter(lights)
        q.scale(1 / 6, 1 / 6)
        q.setPen(NO_PEN)
        t = time.monotonic()
        for fx, fy, size, color, speed, phase in ORBS:
            center = QPointF(fx * w + math.sin(t * speed + phase) * w * 0.06,
                             fy * h + math.cos(t * speed * 0.8 + phase) * h * 0.06)
            radius = size * min(w, h)
            g = QRadialGradient(center, radius)
            g.setColorAt(0, with_alpha(color, 0.13))
            g.setColorAt(1, with_alpha(color, 0))
            q.setBrush(g)
            q.drawEllipse(center, radius, radius)
        q.end()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(self.rect(), lights)

    def resizeEvent(self, event):
        self.overlay.setGeometry(self.rect())

    def changeEvent(self, event):
        # Rest the background animation while you are using another window.
        if event.type() in (QEvent.Type.ActivationChange, QEvent.Type.WindowStateChange):
            self._update_ticker()
        super().changeEvent(event)

    def _update_ticker(self):
        awake = self.isActiveWindow() and not self.isMinimized() and not self.overlay.isVisible()
        if awake and not self._ticker.isActive():
            self._ticker.start(60)
        elif not awake:
            self._ticker.stop()

    # --- game flow ------------------------------------------------------------------------

    def new_game(self):
        self.game = Game()
        self.overlay.hide_result()
        self.dial.reset()
        self.heat_bar.reset()
        self.history.reset()
        self.lives.set_lives(MAX_TRIES)
        self.heat_label.setText("—")
        self.heat_label.setStyleSheet("")
        self._update_tries()
        self._update_best()
        self._say(f"I'm thinking of a number from {LOWEST} to {HIGHEST}. Take your first guess!", SOFT_TEXT)
        self._set_error(False)
        self.entry.setEnabled(True)
        self.guess_button.setEnabled(True)
        self.entry.clear()
        self.entry.setFocus()

    def submit(self):
        if self.game.over:
            return
        number, problem = parse_guess(self.entry.text())
        if problem is None and self.game.already_tried(number):
            problem = f"You already tried {number}. Pick a different number."
        if problem:
            self._say(problem, AMBER)
            self._set_error(True)
            self._error_timer.start(1400)
            self.entry.selectAll()
            self.entry.setFocus()
            return

        self._set_error(False)
        self.entry.clear()
        secret = self.game.secret
        hint = self.game.guess(number)
        heat = heat_of(number, secret)
        color = heat_color(heat)
        caption_text = {"higher": "GO HIGHER  ▲", "lower": "GO LOWER  ▼", "correct": "BULLSEYE!"}[hint]
        marks = [(n, heat_color(heat_of(n, secret))) for n, _ in self.game.guesses]
        self.dial.show_guess(number, color, caption_text, self.game.low, self.game.high, marks)
        self.heat_bar.set_heat(heat, color)
        self.heat_label.setText(heat_word(number, secret))
        self.heat_label.setStyleSheet(f"color: {color.lighter(120).name()};")
        self.lives.set_lives(self.game.tries_left)
        self.history.add(number, hint, color)
        self._update_tries()

        if self.game.won:
            self._say(f"{number} is the secret number!", GOLD)
        elif self.game.over:
            self._say("That was your last try...", PINK)
        else:
            text = f"{number} is too low. Go higher!" if hint == "higher" else f"{number} is too high. Go lower!"
            if self.game.tries_left == 1:
                text += " Last try, make it count!"
            self._say(text, color.lighter(140))
        if self.game.over:
            self.entry.setEnabled(False)
            self.guess_button.setEnabled(False)
            finished = self.game
            QTimer.singleShot(1000, lambda: self._show_result(finished))

    def _show_result(self, finished):
        if finished is not self.game:
            return
        if finished.won:
            best = load_best()
            new_best = best is None or finished.tries_used < best
            if new_best:
                save_best(finished.tries_used)
                best = finished.tries_used
            self._update_best()
            self.layout().activate()  # resize the best-score badge before the end screen snapshots the window
            self.overlay.show_result("win", finished.secret, finished.tries_used, best, new_best)
        else:
            self.overlay.show_result("lose", finished.secret, finished.tries_used, load_best(), False)
        self._update_ticker()  # the end screen covers the window, so the background can rest

    def _say(self, text, color):
        self.message.setText(text)
        self.message.setStyleSheet(f"color: {QColor(color).name()};")

    def _set_error(self, on):
        self.entry.setProperty("error", on)
        self.entry.style().unpolish(self.entry)
        self.entry.style().polish(self.entry)
        self._entry_glow.setColor(with_alpha(AMBER if on else CYAN, 0.6))

    def _update_tries(self):
        self.tries_label.setText(f"{self.game.tries_left} / {MAX_TRIES} tries left")

    def _update_best(self):
        best = load_best()
        if best:
            self.best_label.setText(f"★  BEST  {best} {'TRY' if best == 1 else 'TRIES'}")
        else:
            self.best_label.setText("★  BEST  —")


def main():
    if sys.platform == "win32":
        try:  # lets Windows show the game's own icon in the taskbar
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NeonSeeker.Game")
        except (AttributeError, OSError):
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(make_icon(256)))
    window = GameWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
