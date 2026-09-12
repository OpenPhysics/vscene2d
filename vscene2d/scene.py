"""The Scene -- canvas, axes, autoscale, and the animation loop.

Two ways to drive it:

``rate(fps)`` inside a ``while`` loop
    Byte-for-byte the VPython idiom.  Familiar, and fine when dt is coarse.

``scene.run(step, dt=...)``
    Separates the *integration* step from the *frame* rate.  This fixes the
    single most common complaint about VPython in a numerical-methods course:
    with ``rate(100)`` and ``dt = 1e-4``, one frame advances the physics by
    0.1 ms, so a 10-second fall takes 17 real minutes and the student
    concludes -- reasonably -- that a smaller timestep "breaks" the animation.
    Here you ask for real-time playback and the scene computes how many
    integration substeps belong between frames.  Accuracy and frame rate stop
    fighting each other.
"""

from __future__ import annotations

import inspect
import math
import time

from .backends import NullBackend, make_backend
from .camera import Camera
from .objects import Object2D, Trail, AttachedArrow, color
from .recorder import Recorder
from .vector import vector

_scene = None
_INF = float("inf")


def get_scene():
    global _scene
    if _scene is None:
        _scene = Scene()
    return _scene


class Mouse:
    def __init__(self):
        self.pos = vector(0, 0)
        self.pressed = False
        self.clicked = False


class Scene:
    """An auto-configured 2D world.

    Parameters
    ----------
    mode : "live" | "record" | "auto"
        ``live`` draws to an ipycanvas widget as the loop runs.
        ``record`` skips the widget entirely, runs at full speed, and is
        played back afterwards with ``scene.player()``.
        ``auto`` uses ``live`` if ipycanvas is importable, else ``record``.
    """

    def __init__(self, width=640, height=480, title="", background="#fbfbfd",
                 center=None, range=None, autoscale=None, grid=True,
                 mode="auto", max_frames=2000):
        global _scene
        _scene = self

        self.width = width
        self.height = height
        self.title = title
        self.background = background
        self.grid = grid
        self.objects = []
        self._graphs = []
        self.t = 0.0
        self.mouse = Mouse()
        self.frame = 0

        if autoscale is None:
            autoscale = range is None
        self.camera = Camera(width, height,
                             center=(center.x, center.y) if center else (0.0, 0.0),
                             range_=range if range else 1.0,
                             autoscale=autoscale)
        if range is not None:
            self.camera._seeded = True

        live = (mode == "live") or (mode == "auto")
        self.backend = make_backend(width, height, background, prefer_live=live)
        if mode == "record":
            self.backend = NullBackend(width, height, background)
        self.mode = "live" if self.backend.is_live else "record"

        self.recorder = Recorder(max_frames=max_frames)
        self.record = True
        self._cam_key = None
        self._displayed = False
        self._lag_warned = False
        self._fps_hint = 30

        if self.backend.is_live:
            self.backend.on_mouse_move(self._on_move)
            self.backend.on_mouse_down(self._on_down)
            self.show()

    # --- registry -----------------------------------------------------
    def _add(self, obj):
        self.objects.append(obj)

    def _remove(self, obj):
        if obj in self.objects:
            self.objects.remove(obj)

    def clear(self):
        """Delete every object and reset the clock (keeps the camera)."""
        self.objects.clear()
        self.recorder.clear()
        self.t = 0.0
        self.frame = 0

    # --- display ------------------------------------------------------
    def show(self):
        w = self.backend.display()
        if w is not None and not self._displayed:
            from IPython.display import display
            display(w)
            self._displayed = True
        return w

    def _on_move(self, px, py):
        x, y = self.camera.to_world(px, py)
        self.mouse.pos = vector(x, y)

    def _on_down(self, px, py):
        self._on_move(px, py)
        self.mouse.clicked = True
        self.mouse.pressed = True

    # --- drawing ------------------------------------------------------
    def _autoscale(self):
        xmin = ymin = _INF
        xmax = ymax = -_INF
        for o in self.objects:
            a, b, c, d = o.bounds()
            if a < xmin:
                xmin = a
            if b < ymin:
                ymin = b
            if c > xmax:
                xmax = c
            if d > ymax:
                ymax = d
        if xmin is _INF or xmin > xmax:
            return
        if xmax - xmin < 1e-12 and ymax - ymin < 1e-12:
            pad = max(abs(xmin), abs(ymin), 1.0) * 0.5
            xmin, xmax, ymin, ymax = xmin - pad, xmax + pad, ymin - pad, ymax + pad
        self.camera.include(xmin, ymin, xmax, ymax)

    def _emit_grid(self, out):
        cam = self.camera
        x0, y0, x1, y1 = cam.bounds
        xs, ys, xstep, ystep = cam.ticks()
        for x in xs:
            axis = abs(x) < xstep * 1e-6
            out.append({"t": "poly", "pts": [x, y0, x, y1], "layer": "grid",
                        "stroke": "#c9ccd4" if axis else "#e8eaee",
                        "fill": None, "lw": 1.5 if axis else 1, "closed": False})
        for y in ys:
            axis = abs(y) < ystep * 1e-6
            out.append({"t": "poly", "pts": [x0, y, x1, y], "layer": "grid",
                        "stroke": "#c9ccd4" if axis else "#e8eaee",
                        "fill": None, "lw": 1.5 if axis else 1, "closed": False})
        # tick labels along the axes, clamped into view
        lx = min(max(0.0, x0 + 0.04 * (x1 - x0)), x1 - 0.02 * (x1 - x0))
        ly = min(max(0.0, y0 + 0.05 * (y1 - y0)), y1 - 0.02 * (y1 - y0))
        fmt = (lambda v: f"{v:.3g}")
        for x in xs:
            if abs(x) < xstep * 1e-6:
                continue
            out.append({"t": "text", "x": x, "y": ly, "s": fmt(x), "layer": "grid",
                        "fill": "#8a8f98", "size": 11, "align": "center"})
        for y in ys:
            if abs(y) < ystep * 1e-6:
                continue
            out.append({"t": "text", "x": lx, "y": y, "s": fmt(y), "layer": "grid",
                        "fill": "#8a8f98", "size": 11, "align": "left"})

    def _display_list(self):
        out = []
        if self.grid:
            self._emit_grid(out)
        for o in self.objects:
            o.emit(out, self.camera)
        return out

    def render(self):
        """Sample trails, autoscale, draw one frame, and record it."""
        for o in self.objects:
            if isinstance(o, AttachedArrow):
                o.refresh()
            elif isinstance(o, Trail):
                o.sample()
        self._autoscale()

        prims = self._display_list()
        key = self.camera.key
        changed = key != self._cam_key
        self._cam_key = key

        self.backend.draw(prims, self.camera, camera_changed=changed)
        if self.record:
            self.recorder.capture(prims, self.camera, self.t)
        for g in self._graphs:
            g.render()
        self.frame += 1

    # --- animation loops ----------------------------------------------
    def rate(self, fps):
        """VPython-compatible: render a frame and pace the loop to ``fps``."""
        self._fps_hint = fps
        now = time.perf_counter()
        target = getattr(self, "_next_tick", None)
        self.render()
        if self.mode == "live":
            if target is None:
                self._next_tick = now + 1.0 / fps
            else:
                delay = target - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -1.0 and not self._lag_warned:
                    self._lag_warned = True
                    print("vscene2d: the loop can't keep up with rate(%g). "
                          "Try Scene(mode='record') and scene.player(), or "
                          "scene.run(step, dt=..., fps=30)." % fps)
                self._next_tick = max(target + 1.0 / fps, time.perf_counter())
        self.t += 1.0 / fps

    def run(self, step, dt, duration=None, until=None, fps=30, speed=1.0,
            realtime=None, max_frames=None):
        """Advance ``step`` with timestep ``dt`` while rendering at ``fps``.

        ``step`` is called as ``step(dt)`` or ``step(dt, t)``.
        ``speed`` is simulated seconds per real second (0.25 = slow motion).
        ``until`` is a predicate; the run stops as soon as it returns True.
        """
        if realtime is None:
            realtime = (self.mode == "live")
        try:
            nargs = len(inspect.signature(step).parameters)
        except (TypeError, ValueError):
            nargs = 1
        call = (lambda: step(dt, self.t)) if nargs >= 2 else (lambda: step(dt))

        per_frame = speed / fps
        nsub = max(1, int(round(per_frame / dt)))
        t_end = None if duration is None else self.t + duration
        cap = max_frames if max_frames is not None else self.recorder.max_frames
        budget = 1.0 / fps
        wall = time.perf_counter()

        self.render()
        while True:
            for _ in range(nsub):
                call()
                self.t += dt
                if until is not None and until():
                    self.render()
                    return self
                if t_end is not None and self.t >= t_end:
                    break
            self.render()
            if t_end is not None and self.t >= t_end:
                return self
            if self.frame >= cap:
                return self
            if realtime:
                wall += budget
                delay = wall - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    wall = time.perf_counter()
                    if delay < -1.0 and not self._lag_warned:
                        self._lag_warned = True
                        print("vscene2d: rendering slower than %g fps. "
                              "Use Scene(mode='record') for full speed." % fps)
        return self

    # --- playback -----------------------------------------------------
    def player(self, fps=None, title=None):
        """Return a self-contained HTML animation of everything recorded.

        Display it as the last line of a cell.  It keeps working after the
        kernel dies, after the notebook is exported, and on nbviewer.
        """
        from IPython.display import HTML

        if len(self.recorder) == 0:
            return HTML("<em>vscene2d: nothing recorded yet.</em>")
        note = title if title is not None else self.title
        if self.recorder.dropped:
            note = (note + "  ") if note else ""
            note += (f"(showing first {len(self.recorder)} frames; "
                     f"{self.recorder.dropped} more were dropped -- raise "
                     f"Scene(max_frames=...) if you need them)")
        return HTML(self.recorder.html(self.width, self.height,
                                       self.background,
                                       fps or self._fps_hint, note))

    def save_html(self, path, fps=None, title=None):
        """Write the recorded animation to a standalone .html file."""
        html = self.recorder.html(self.width, self.height, self.background,
                                  fps or self._fps_hint,
                                  title if title is not None else self.title)
        doc = ("<!doctype html><meta charset='utf-8'>"
               "<body style=\"font-family:system-ui,sans-serif;margin:24px\">"
               + html + "</body>")
        with open(path, "w") as f:
            f.write(doc)
        return path

    # --- camera controls ----------------------------------------------
    def set_view(self, center=None, range=None):
        """Pin the view manually and stop autoscaling."""
        if center is not None:
            self.camera.cx, self.camera.cy = center.x, center.y
        if range is not None:
            self.camera.range = float(range)
        self.camera.autoscale = False
        self.camera._seeded = True
        return self


def rate(fps):
    """Module-level ``rate()`` -- paces the current scene, exactly like VPython."""
    get_scene().rate(fps)
