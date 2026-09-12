"""World <-> pixel mapping.

Two properties matter pedagogically and are easy to get wrong:

1.  **Equal aspect ratio.**  In a *scene*, x and y are drawn at the same
    scale, so a circle is a circle and a 45-degree launch looks like 45
    degrees.  Almost every hand-rolled matplotlib animation gets this wrong
    by default.

2.  **Autoscale that does not jitter.**  A naive "fit the bounding box every
    frame" rescales on every step, so the world visibly breathes and a
    straight trail appears to curve.  Here the view only ever *grows*, and it
    grows in discrete jumps with headroom, so it settles after a moment and
    then stays put -- which is what VPython does and why VPython looks calm.

``Camera`` keeps half-ranges in x and y separately.  For a scene they are
locked to the pixel aspect ratio; for a ``Graph`` they float independently.
One transform, two behaviours, one backend.
"""

from __future__ import annotations

import math

_GROW = 1.30   # headroom when growing, so rescales are rare
_PAD = 0.08    # margin as a fraction of the visible range


def nice_step(raw):
    """Round a raw tick spacing to the nearest 1/2/5 x 10^n."""
    if raw <= 0 or not math.isfinite(raw):
        return 1.0
    exp = math.floor(math.log10(raw))
    frac = raw / 10.0**exp
    for cut, val in ((1.5, 1.0), (3.5, 2.0), (7.5, 5.0)):
        if frac < cut:
            return val * 10.0**exp
    return 10.0 * 10.0**exp


def nice_ceil(v):
    """Smallest 1/2/5 x 10^n value that is at least ``v``."""
    if v <= 0 or not math.isfinite(v):
        return 1.0
    exp = math.floor(math.log10(v))
    frac = v / 10.0**exp
    for m in (1.0, 2.0, 5.0, 10.0):
        if frac <= m * (1 + 1e-12):
            return m * 10.0**exp
    return 10.0 * 10.0**exp


class Camera:
    """Maps world coordinates to canvas pixels, y-up.  Equal aspect."""

    equal_aspect = True

    def __init__(self, width, height, center=(0.0, 0.0), range_=1.0,
                 autoscale=True):
        self.width = width
        self.height = height
        self.cx, self.cy = center
        self.ry = float(range_)
        self.rx = self.ry * width / height if self.equal_aspect else float(range_)
        self.autoscale = autoscale
        self._seeded = False

    # --- transform ----------------------------------------------------
    @property
    def range(self):
        return self.ry

    @range.setter
    def range(self, v):
        self.ry = float(v)
        if self.equal_aspect:
            self.rx = self.ry * self.width / self.height

    @property
    def sx(self):
        return self.width / (2.0 * self.rx)

    @property
    def sy(self):
        return self.height / (2.0 * self.ry)

    def to_px(self, x, y):
        return (self.width * 0.5 + (x - self.cx) * self.sx,
                self.height * 0.5 - (y - self.cy) * self.sy)

    def to_world(self, px, py):
        return (self.cx + (px - self.width * 0.5) / self.sx,
                self.cy - (py - self.height * 0.5) / self.sy)

    def px_len(self, world_len):
        """Pixel length of a world length (min axis, so discs never clip)."""
        return world_len * min(self.sx, self.sy)

    @property
    def bounds(self):
        return (self.cx - self.rx, self.cy - self.ry,
                self.cx + self.rx, self.cy + self.ry)

    @property
    def key(self):
        return (self.cx, self.cy, self.rx, self.ry)

    # --- autoscale ----------------------------------------------------
    def include(self, xmin, ymin, xmax, ymax):
        """Grow the view (never shrink) so this box fits.  True if it changed."""
        if not self.autoscale:
            return False
        if not all(map(math.isfinite, (xmin, ymin, xmax, ymax))):
            return False

        if not self._seeded:
            self._seeded = True
            self._fit(xmin, ymin, xmax, ymax)
            return True

        vx0, vy0, vx1, vy1 = self.bounds
        px, py = _PAD * 2 * self.rx, _PAD * 2 * self.ry
        if (xmin >= vx0 + px and xmax <= vx1 - px
                and ymin >= vy0 + py and ymax <= vy1 - py):
            return False

        self._fit(min(vx0, xmin), min(vy0, ymin), max(vx1, xmax), max(vy1, ymax))
        return True

    def _fit(self, xmin, ymin, xmax, ymax):
        self.cx = 0.5 * (xmin + xmax)
        self.cy = 0.5 * (ymin + ymax)
        hx = max(0.5 * (xmax - xmin), 1e-12)
        hy = max(0.5 * (ymax - ymin), 1e-12)
        k = 1 + 2 * _PAD
        if self.equal_aspect:
            # One scale for both axes: whichever axis is more demanding wins.
            # Snapping the half-range onto a 1/2/5 ladder means a run zooms out
            # through a handful of discrete levels instead of creeping outward
            # every few frames, and gridlines land on the same round numbers
            # at every level instead of shuffling.
            s = max(hx / (self.width * 0.5), hy / (self.height * 0.5))
            self.ry = nice_ceil(s * self.height * 0.5 * k)
            self.rx = self.ry * self.width / self.height
        else:
            self.rx = nice_ceil(hx * k)
            self.ry = nice_ceil(hy * k)

    # --- gridlines ----------------------------------------------------
    def ticks(self, target_count=8):
        """Nice gridline positions: (xs, ys, xstep, ystep)."""
        x0, y0, x1, y1 = self.bounds
        if self.equal_aspect:
            step = nice_step(max(x1 - x0, y1 - y0) / target_count)
            xstep = ystep = step
        else:
            xstep = nice_step((x1 - x0) / target_count)
            ystep = nice_step((y1 - y0) / max(target_count // 2, 3))
        return (_seq(x0, x1, xstep), _seq(y0, y1, ystep), xstep, ystep)


class PlotCamera(Camera):
    """Independent x and y scaling, for graphs."""

    equal_aspect = False

    def __init__(self, width, height):
        super().__init__(width, height, range_=1.0, autoscale=True)
        self.rx = 1.0
        self.ry = 1.0


def _seq(lo, hi, step):
    out = []
    if step <= 0 or not math.isfinite(step):
        return out
    k = math.ceil(lo / step)
    while k * step <= hi and len(out) < 200:
        out.append(k * step)
        k += 1
    return out
