"""A 2D vector, mirroring VPython's `vector()` ergonomics.

Deliberately supports in-place `+=` by *rebinding* rather than mutating, so
that `ball.pos += v*dt` goes through the property setter on the object and
triggers the usual bookkeeping (trail points, autoscale).  This is why
`vector` is immutable: mutation would silently bypass the setter, which is
the single most confusing failure mode a student can hit.
"""

from __future__ import annotations

import math


class vector:
    """Immutable 2D vector.  ``vector(x, y)``."""

    __slots__ = ("_x", "_y")

    def __init__(self, x=0.0, y=0.0):
        object.__setattr__(self, "_x", float(x))
        object.__setattr__(self, "_y", float(y))

    # --- immutability -------------------------------------------------
    @property
    def x(self):
        return self._x

    @property
    def y(self):
        return self._y

    def __setattr__(self, name, value):
        raise AttributeError(
            "vector is immutable -- build a new one, e.g. "
            "`ball.pos = vector(ball.pos.x + 1, ball.pos.y)`. "
            "Mutating in place would skip the redraw."
        )

    # --- arithmetic ---------------------------------------------------
    def __add__(self, o):
        return vector(self._x + o.x, self._y + o.y)

    def __sub__(self, o):
        return vector(self._x - o.x, self._y - o.y)

    def __mul__(self, s):
        return vector(self._x * s, self._y * s)

    __rmul__ = __mul__

    def __truediv__(self, s):
        return vector(self._x / s, self._y / s)

    def __neg__(self):
        return vector(-self._x, -self._y)

    def __eq__(self, o):
        return isinstance(o, vector) and self._x == o.x and self._y == o.y

    def __hash__(self):
        return hash((self._x, self._y))

    def __iter__(self):
        yield self._x
        yield self._y

    def __getitem__(self, i):
        return (self._x, self._y)[i]

    def __repr__(self):
        return f"vector({self._x:.6g}, {self._y:.6g})"

    # --- geometry -----------------------------------------------------
    @property
    def mag(self):
        return math.hypot(self._x, self._y)

    @property
    def mag2(self):
        return self._x * self._x + self._y * self._y

    def norm(self):
        m = self.mag
        return vector(0.0, 0.0) if m == 0.0 else vector(self._x / m, self._y / m)

    hat = property(lambda self: self.norm())

    def dot(self, o):
        return self._x * o.x + self._y * o.y

    def cross(self, o):
        """z-component of the 3D cross product (a scalar in 2D)."""
        return self._x * o.y - self._y * o.x

    def rotate(self, angle):
        """Rotate counterclockwise by ``angle`` radians."""
        c, s = math.cos(angle), math.sin(angle)
        return vector(self._x * c - self._y * s, self._x * s + self._y * c)

    def proj(self, o):
        """Component of self along o, as a vector."""
        n = o.norm()
        return n * self.dot(n)

    @property
    def theta(self):
        """Angle from +x axis, in radians, in (-pi, pi]."""
        return math.atan2(self._y, self._x)

    def as_tuple(self):
        return (self._x, self._y)


def dot(a, b):
    return a.dot(b)


def cross(a, b):
    return a.cross(b)


def mag(a):
    return a.mag


def norm(a):
    return a.norm()


def hat(a):
    return a.norm()
