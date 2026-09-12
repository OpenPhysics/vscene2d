"""Live graphs -- the ``graph`` / ``gcurve`` half of VPython.

Watching a ball move is only half of a physics demo.  The moment that lands is
the energy trace going flat while the ball oscillates, or the phase-space
ellipse closing on itself.  In VPython that's ``gcurve``, and it's the single
most-used feature after ``sphere``.

A ``Graph`` is a second canvas driven by the same loop: create it, call
``.plot()`` inside the loop, and it repaints on the same frames the scene does.
Axes autoscale independently in x and y, which is what a plot needs and what
the scene must never do.
"""

from __future__ import annotations

import math

from .backends import NullBackend, make_backend
from .camera import PlotCamera
from .objects import color
from .recorder import Recorder

_INF = float("inf")


class Graph:
    """A live 2D plot.  Attaches to the current scene and repaints with it."""

    def __init__(self, width=640, height=260, title="", xtitle="t", ytitle="",
                 background="#ffffff", mode=None, scene=None, max_frames=2000):
        from .scene import get_scene

        self.scene = scene if scene is not None else get_scene()
        self.width = width
        self.height = height
        self.title = title
        self.xtitle = xtitle
        self.ytitle = ytitle
        self.background = background
        self.curves = []
        self.camera = PlotCamera(width, height)

        live = self.scene.mode == "live" if mode is None else (mode == "live")
        self.backend = (make_backend(width, height, background, prefer_live=True)
                        if live else NullBackend(width, height, background))
        self.recorder = Recorder(max_frames=max_frames)
        self._cam_key = None
        self._displayed = False
        self.scene._graphs.append(self)
        if self.backend.is_live:
            self.show()

    def show(self):
        w = self.backend.display()
        if w is not None and not self._displayed:
            from IPython.display import display
            display(w)
            self._displayed = True
        return w

    def _add(self, c):
        self.curves.append(c)

    # --- drawing ------------------------------------------------------
    def _autoscale(self):
        xmin = ymin = _INF
        xmax = ymax = -_INF
        for c in self.curves:
            if not c.xs:
                continue
            xmin = min(xmin, min(c.xs))
            xmax = max(xmax, max(c.xs))
            ymin = min(ymin, min(c.ys))
            ymax = max(ymax, max(c.ys))
        if xmin is _INF:
            return
        if xmax - xmin < 1e-12:
            xmin, xmax = xmin - 0.5, xmax + 0.5
        if ymax - ymin < 1e-12:
            pad = max(abs(ymin), 1.0) * 0.1
            ymin, ymax = ymin - pad, ymax + pad
        self.camera.include(xmin, ymin, xmax, ymax)

    def _display_list(self):
        cam = self.camera
        out = []
        x0, y0, x1, y1 = cam.bounds
        xs, ys, xstep, ystep = cam.ticks()
        for x in xs:
            out.append({"t": "poly", "pts": [x, y0, x, y1], "layer": "grid",
                        "stroke": "#eceef2", "fill": None, "lw": 1, "closed": False})
        for y in ys:
            axis = abs(y) < ystep * 1e-6
            out.append({"t": "poly", "pts": [x0, y, x1, y], "layer": "grid",
                        "stroke": "#c9ccd4" if axis else "#eceef2",
                        "fill": None, "lw": 1.5 if axis else 1, "closed": False})
        pad_x, pad_y = 0.02 * (x1 - x0), 0.04 * (y1 - y0)
        for y in ys:
            out.append({"t": "text", "x": x0 + pad_x, "y": y, "s": f"{y:.3g}",
                        "layer": "grid", "fill": "#8a8f98", "size": 11,
                        "align": "left"})
        for x in xs[1:]:
            out.append({"t": "text", "x": x, "y": y0 + pad_y, "s": f"{x:.3g}",
                        "layer": "grid", "fill": "#8a8f98", "size": 11,
                        "align": "center"})
        if self.xtitle:
            out.append({"t": "text", "x": x1 - pad_x, "y": y0 + pad_y,
                        "s": self.xtitle, "layer": "grid", "fill": "#6b7280",
                        "size": 12, "align": "right"})

        for c in self.curves:
            c.emit(out)

        # Legend runs down from the top-*right*: the y-axis tick labels own the
        # left gutter, and a legend on top of them is unreadable exactly when
        # the trace is interesting.
        lx, ly = x1 - pad_x, y1 - pad_y
        row = 0.075 * (y1 - y0)
        if self.title:
            out.append({"t": "text", "x": x0 + pad_x, "y": y1 - pad_y,
                        "s": self.title, "fill": "#374151", "size": 13,
                        "align": "left"})
        for c in self.curves:
            if c.label:
                out.append({"t": "text", "x": lx, "y": ly, "s": c.label + " —",
                            "fill": c.color, "size": 12, "align": "right"})
                ly -= row
        return out

    def render(self):
        self._autoscale()
        prims = self._display_list()
        key = self.camera.key
        changed = key != self._cam_key
        self._cam_key = key
        self.backend.draw(prims, self.camera, camera_changed=changed)
        self.recorder.capture(prims, self.camera, self.scene.t)

    def player(self, fps=None):
        from IPython.display import HTML

        if len(self.recorder) == 0:
            return HTML("<em>vscene2d: graph has no data.</em>")
        return HTML(self.recorder.html(self.width, self.height, self.background,
                                       fps or self.scene._fps_hint, self.title))

    def clear(self):
        for c in self.curves:
            c.clear()
        self.recorder.clear()


class gcurve:
    """A single trace on a Graph.  ``curve.plot(x, y)`` appends a point.

    ``every`` thins the trace: ``gcurve(every=5)`` keeps one point in five,
    which matters when the integration step is fine.  A 10-second run at
    dt = 1e-4 is a million points; nobody can see more than a few thousand,
    and the browser certainly can't draw them 30 times a second.
    """

    def __init__(self, graph=None, color=color.blue, label="", lw=2, every=1,
                 dot=False):
        self.graph = graph if graph is not None else _current_graph()
        self.color = color
        self.label = label
        self.lw = lw
        self.every = max(int(every), 1)
        self.dot = dot
        self.xs = []
        self.ys = []
        self._n = 0
        self.graph._add(self)

    def plot(self, x, y=None):
        """``plot(x, y)`` or ``plot((x, y))``."""
        if y is None:
            x, y = x
        self._n += 1
        if (self._n - 1) % self.every:
            return
        if not (math.isfinite(x) and math.isfinite(y)):
            return
        self.xs.append(float(x))
        self.ys.append(float(y))

    def clear(self):
        self.xs.clear()
        self.ys.clear()
        self._n = 0

    def emit(self, out):
        if len(self.xs) < 2:
            return
        pts = []
        for x, y in zip(self.xs, self.ys):
            pts += [x, y]
        out.append({"t": "poly", "pts": pts, "stroke": self.color,
                    "fill": None, "lw": self.lw, "closed": False})
        if self.dot:
            out.append({"t": "circle", "x": self.xs[-1], "y": self.ys[-1],
                        "r": 0.0, "fill": self.color, "stroke": None, "lw": 0})


def _current_graph():
    from .scene import get_scene

    s = get_scene()
    if not s._graphs:
        return Graph()
    return s._graphs[-1]
