"""Scene objects.

Objects never touch a canvas.  They emit a small *display list* of primitives
in world coordinates, and a backend turns that into pixels.  That indirection
is what lets the identical scene render live to a widget, replay as a
standalone HTML animation in an exported notebook, or run headless in a test
with no display at all.

Primitive dicts (world coordinates; line widths and text sizes in pixels):
    {"t":"circle", "x","y","r", "fill","stroke","lw"}
    {"t":"rect",   "x","y","w","h","angle", "fill","stroke","lw"}
    {"t":"poly",   "pts":[x0,y0,x1,y1,...], "stroke","fill","lw","closed"}
    {"t":"arrow",  "x","y","dx","dy", "stroke","lw","head"}
    {"t":"text",   "x","y","s", "fill","size","align"}
"""

from __future__ import annotations

import math

from .vector import vector

_INF = float("inf")


class color:
    """VPython-style palette.  Any CSS color string also works."""

    red = "#e34a33"
    orange = "#f07c1e"
    yellow = "#f2c14e"
    green = "#3fa34d"
    blue = "#2b6cb0"
    cyan = "#2aa8b0"
    magenta = "#b0399b"
    purple = "#7b52ab"
    white = "#ffffff"
    black = "#111111"
    gray = "#8a8f98"


class Object2D:
    """Base class: registers with the scene, tracks visibility."""

    def __init__(self, scene=None, color=color.blue, opacity=1.0, visible=True):
        from .scene import get_scene
        self.scene = scene if scene is not None else get_scene()
        self.color = color
        self.opacity = opacity
        self.visible = visible
        self.scene._add(self)

    def bounds(self):
        """(xmin, ymin, xmax, ymax) in world units, for autoscale."""
        return (_INF, _INF, -_INF, -_INF)

    def emit(self, out, cam):
        """Append primitives to the list `out`."""

    def remove(self):
        self.scene._remove(self)


class Ball(Object2D):
    """A disc.  ``Ball(pos=vector(0,0), radius=0.2, color=color.red)``"""

    def __init__(self, pos=None, radius=0.2, color=color.red,
                 make_trail=False, retain=None, **kw):
        self.pos = pos if pos is not None else vector(0, 0)
        self.radius = radius
        super().__init__(color=color, **kw)
        self.trail = Trail(self, retain=retain, color=color, scene=self.scene) if make_trail else None

    def bounds(self):
        r = self.radius
        return (self.pos.x - r, self.pos.y - r, self.pos.x + r, self.pos.y + r)

    def emit(self, out, cam):
        if not self.visible:
            return
        out.append({"t": "circle", "x": self.pos.x, "y": self.pos.y,
                    "r": self.radius, "fill": self.color, "stroke": None, "lw": 0})


class Box(Object2D):
    """An axis-aligned (or rotated) rectangle.  ``angle`` in radians."""

    def __init__(self, pos=None, size=None, angle=0.0, color=color.gray,
                 filled=True, **kw):
        self.pos = pos if pos is not None else vector(0, 0)
        self.size = size if size is not None else vector(1, 1)
        self.angle = angle
        self.filled = filled
        super().__init__(color=color, **kw)

    def bounds(self):
        hx, hy = self.size.x / 2, self.size.y / 2
        c, s = abs(math.cos(self.angle)), abs(math.sin(self.angle))
        ex, ey = hx * c + hy * s, hx * s + hy * c
        return (self.pos.x - ex, self.pos.y - ey, self.pos.x + ex, self.pos.y + ey)

    def emit(self, out, cam):
        if not self.visible:
            return
        out.append({"t": "rect", "x": self.pos.x, "y": self.pos.y,
                    "w": self.size.x, "h": self.size.y, "angle": self.angle,
                    "fill": self.color if self.filled else None,
                    "stroke": None if self.filled else self.color, "lw": 2})


class Arrow(Object2D):
    """A vector drawn from ``pos`` along ``axis``.

    ``scale`` converts physical units to world length, so a velocity in m/s
    can be drawn in a scene measured in metres without distorting anything.
    """

    def __init__(self, pos=None, axis=None, color=color.green, scale=1.0,
                 lw=3, **kw):
        self.pos = pos if pos is not None else vector(0, 0)
        self.axis = axis if axis is not None else vector(1, 0)
        self.scale = scale
        self.lw = lw
        super().__init__(color=color, **kw)

    @property
    def tip(self):
        return self.pos + self.axis * self.scale

    def bounds(self):
        p, q = self.pos, self.tip
        return (min(p.x, q.x), min(p.y, q.y), max(p.x, q.x), max(p.y, q.y))

    def emit(self, out, cam):
        if not self.visible:
            return
        d = self.axis * self.scale
        if d.mag == 0:
            return
        out.append({"t": "arrow", "x": self.pos.x, "y": self.pos.y,
                    "dx": d.x, "dy": d.y, "stroke": self.color,
                    "lw": self.lw, "head": 10})


class Segment(Object2D):
    """A straight line between two points -- rods, strings, ramps, walls."""

    def __init__(self, start=None, end=None, color=color.black, lw=2, **kw):
        self.start = start if start is not None else vector(0, 0)
        self.end = end if end is not None else vector(1, 0)
        self.lw = lw
        super().__init__(color=color, **kw)

    def bounds(self):
        a, b = self.start, self.end
        return (min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))

    def emit(self, out, cam):
        if not self.visible:
            return
        out.append({"t": "poly",
                    "pts": [self.start.x, self.start.y, self.end.x, self.end.y],
                    "stroke": self.color, "fill": None, "lw": self.lw,
                    "closed": False})


class Spring(Object2D):
    """A zigzag between two points.  Coils stay fixed in number as it stretches,
    which is exactly the visual cue students need for SHM demos."""

    def __init__(self, start=None, end=None, coils=10, amplitude=0.15,
                 color=color.gray, lw=2, **kw):
        self.start = start if start is not None else vector(0, 0)
        self.end = end if end is not None else vector(1, 0)
        self.coils = coils
        self.amplitude = amplitude
        self.lw = lw
        super().__init__(color=color, **kw)

    def bounds(self):
        a, b = self.start, self.end
        m = self.amplitude
        return (min(a.x, b.x) - m, min(a.y, b.y) - m,
                max(a.x, b.x) + m, max(a.y, b.y) + m)

    def emit(self, out, cam):
        if not self.visible:
            return
        d = self.end - self.start
        L = d.mag
        if L == 0:
            return
        u = d / L
        n = vector(-u.y, u.x)
        pts = []
        steps = self.coils * 4
        for i in range(steps + 1):
            f = i / steps
            # flat lead-ins at both ends
            env = 0.0 if (f < 0.1 or f > 0.9) else 1.0
            off = self.amplitude * env * (1 if (i % 4 == 1) else (-1 if i % 4 == 3 else 0))
            p = self.start + u * (L * f) + n * off
            pts += [p.x, p.y]
        out.append({"t": "poly", "pts": pts, "stroke": self.color,
                    "fill": None, "lw": self.lw, "closed": False})


class Label(Object2D):
    """Text pinned to a world position.  Size is in pixels, so it stays legible
    no matter how far the scene autoscales out."""

    def __init__(self, pos=None, text="", color=color.black, size=13,
                 align="center", **kw):
        self.pos = pos if pos is not None else vector(0, 0)
        self.text = text
        self.size = size
        self.align = align
        super().__init__(color=color, **kw)

    def emit(self, out, cam):
        if not self.visible:
            return
        out.append({"t": "text", "x": self.pos.x, "y": self.pos.y,
                    "s": str(self.text), "fill": self.color,
                    "size": self.size, "align": self.align})


class Curve(Object2D):
    """An explicit polyline the student appends to -- for plotting a computed
    path, a field line, or a potential contour."""

    def __init__(self, points=None, color=color.purple, lw=2, **kw):
        self.points = list(points) if points else []
        self.lw = lw
        super().__init__(color=color, **kw)

    def append(self, p):
        self.points.append(p)

    def clear(self):
        self.points.clear()

    def bounds(self):
        if not self.points:
            return (_INF, _INF, -_INF, -_INF)
        xs = [p.x for p in self.points]
        ys = [p.y for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))

    def emit(self, out, cam):
        if not self.visible or len(self.points) < 2:
            return
        pts = []
        for p in self.points:
            pts += [p.x, p.y]
        out.append({"t": "poly", "pts": pts, "stroke": self.color,
                    "fill": None, "lw": self.lw, "closed": False})


class Trail(Object2D):
    """A path that samples its target **once per rendered frame**, not on every
    assignment to ``pos``.

    This matters: with dt = 1e-4 a per-assignment trail accumulates 10,000
    points per simulated second and the animation grinds to a halt.  Sampling
    at frame rate keeps trail density constant no matter how fine the
    integration step is.
    """

    def __init__(self, target, retain=None, color=color.red, lw=2, **kw):
        self.target = target
        self.retain = retain
        self.lw = lw
        self.points = []
        super().__init__(color=color, **kw)

    def sample(self):
        p = self.target.pos
        if self.points and self.points[-1] == p:
            return
        self.points.append(p)
        if self.retain and len(self.points) > self.retain:
            del self.points[: len(self.points) - self.retain]

    def clear(self):
        self.points.clear()

    def bounds(self):
        if not self.points:
            return (_INF, _INF, -_INF, -_INF)
        xs = [p.x for p in self.points]
        ys = [p.y for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))

    def emit(self, out, cam):
        if not self.visible or len(self.points) < 2:
            return
        pts = []
        for p in self.points:
            pts += [p.x, p.y]
        out.append({"t": "poly", "pts": pts, "stroke": self.color,
                    "fill": None, "lw": self.lw, "closed": False})


class AttachedArrow(Arrow):
    """An arrow that reads an attribute off another object every frame.

    ``attach_arrow(ball, "vel")`` then just works -- the student never has to
    remember to update the arrow inside the loop, which is where hand-written
    versions always drift out of sync with the physics.
    """

    def __init__(self, target, attr, owner=None, **kw):
        self.target = target
        self.attr = attr
        self._owner = owner
        super().__init__(pos=target.pos, axis=vector(1, 0), **kw)

    def refresh(self):
        self.pos = self.target.pos
        src = self._owner if self._owner is not None else self.target
        # `owner=globals()` is the natural thing to write when the velocity is
        # a module-level variable rather than an attribute, so accept a mapping.
        if isinstance(src, dict):
            v = src.get(self.attr)
        else:
            v = getattr(src, self.attr, None)
        if isinstance(v, vector):
            self.axis = v
            self.visible = True
        else:
            self.visible = False


def attach_trail(obj, retain=None, color=None, lw=2):
    """Give an existing object a trail."""
    t = Trail(obj, retain=retain, color=color or getattr(obj, "color", "#e34a33"),
              lw=lw, scene=obj.scene)
    obj.trail = t
    return t


def attach_arrow(obj, attr, scale=1.0, color=color.green, lw=3, owner=None):
    """Draw ``getattr(owner or obj, attr)`` as an arrow anchored at ``obj.pos``.

    ``owner`` lets you point at a plain variable held elsewhere, e.g. a module
    or a small state object, when the velocity isn't stored on the ball.
    """
    return AttachedArrow(obj, attr, owner=owner, scale=scale, color=color,
                         lw=lw, scene=obj.scene)
