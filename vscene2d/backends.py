"""Rendering backends.

A backend consumes display-list primitives and a Camera.  Two exist:

* ``IpycanvasBackend`` -- live widget in a running kernel.
* ``NullBackend``      -- no display at all; used for headless recording,
                          for CI, and for the fast "simulate now, scrub
                          later" workflow.

Splitting these apart is what makes the package testable.  A live-widget-only
design can only be verified by a human squinting at a notebook.
"""

from __future__ import annotations


class NullBackend:
    """Does nothing.  Frames are still captured by the Recorder upstream."""

    is_live = False

    def __init__(self, width=640, height=480, background="#ffffff"):
        self.width = width
        self.height = height
        self.background = background

    def display(self):
        return None

    def draw(self, prims, cam, camera_changed=True):
        pass

    def on_mouse_move(self, cb):
        pass

    def on_mouse_down(self, cb):
        pass

    def on_mouse_up(self, cb):
        pass


class IpycanvasBackend:
    """Two-layer canvas: static grid underneath, moving objects on top.

    The grid is only repainted when the camera actually changes, so a typical
    frame ships a few dozen drawing commands over the widget comm channel
    instead of a few hundred.  Everything for a frame is wrapped in
    ``hold_canvas`` so it arrives as one batch -- without that you get
    visible tearing, and it is by far the most common reason hand-rolled
    ipycanvas animations look bad.
    """

    is_live = True

    def __init__(self, width=640, height=480, background="#ffffff"):
        from ipycanvas import MultiCanvas

        self.width = width
        self.height = height
        self.background = background
        self.mc = MultiCanvas(2, width=width, height=height)
        self.bg = self.mc[0]
        self.fg = self.mc[1]
        self._grid_drawn = False

    def display(self):
        return self.mc

    # --- input --------------------------------------------------------
    def on_mouse_move(self, cb):
        self.fg.on_mouse_move(cb)

    def on_mouse_down(self, cb):
        self.fg.on_mouse_down(cb)

    def on_mouse_up(self, cb):
        self.fg.on_mouse_up(cb)

    # --- drawing ------------------------------------------------------
    def draw(self, prims, cam, camera_changed=True):
        from ipycanvas import hold_canvas

        grid = [p for p in prims if p.get("layer") == "grid"]
        objs = [p for p in prims if p.get("layer") != "grid"]

        if camera_changed or not self._grid_drawn:
            with hold_canvas(self.bg):
                self.bg.clear()
                self.bg.fill_style = self.background
                self.bg.fill_rect(0, 0, self.width, self.height)
                _paint(self.bg, grid, cam)
            self._grid_drawn = True

        with hold_canvas(self.fg):
            self.fg.clear()
            _paint(self.fg, objs, cam)


def _paint(cv, prims, cam):
    """Render a display list onto an ipycanvas Canvas."""
    import math

    for p in prims:
        t = p["t"]
        alpha = p.get("alpha", 1.0)
        if alpha != 1.0:
            cv.global_alpha = alpha

        if t == "circle":
            x, y = cam.to_px(p["x"], p["y"])
            r = max(cam.px_len(p["r"]), 1.0)
            if p.get("fill"):
                cv.fill_style = p["fill"]
                cv.fill_circle(x, y, r)
            if p.get("stroke"):
                cv.stroke_style = p["stroke"]
                cv.line_width = p.get("lw", 1)
                cv.stroke_circle(x, y, r)

        elif t == "rect":
            x, y = cam.to_px(p["x"], p["y"])
            w = cam.px_len(p["w"])
            h = cam.px_len(p["h"])
            ang = p.get("angle", 0.0)
            cv.save()
            cv.translate(x, y)
            if ang:
                cv.rotate(-ang)  # canvas y is down, so flip the sense
            if p.get("fill"):
                cv.fill_style = p["fill"]
                cv.fill_rect(-w / 2, -h / 2, w, h)
            if p.get("stroke"):
                cv.stroke_style = p["stroke"]
                cv.line_width = p.get("lw", 1)
                cv.stroke_rect(-w / 2, -h / 2, w, h)
            cv.restore()

        elif t == "poly":
            flat = p["pts"]
            pts = [list(cam.to_px(flat[i], flat[i + 1]))
                   for i in range(0, len(flat), 2)]
            if p.get("fill"):
                cv.fill_style = p["fill"]
                cv.fill_polygon(pts)
            if p.get("stroke"):
                cv.stroke_style = p["stroke"]
                cv.line_width = p.get("lw", 1)
                if p.get("closed"):
                    cv.stroke_polygon(pts)
                else:
                    cv.stroke_lines(pts)

        elif t == "arrow":
            x0, y0 = cam.to_px(p["x"], p["y"])
            x1, y1 = cam.to_px(p["x"] + p["dx"], p["y"] + p["dy"])
            dx, dy = x1 - x0, y1 - y0
            L = math.hypot(dx, dy)
            if L < 1e-9:
                continue
            ux, uy = dx / L, dy / L
            head = min(p.get("head", 10), L * 0.5)
            bx, by = x1 - ux * head, y1 - uy * head
            cv.stroke_style = p["stroke"]
            cv.line_width = p.get("lw", 2)
            cv.stroke_lines([[x0, y0], [bx, by]])
            cv.fill_style = p["stroke"]
            cv.fill_polygon([[x1, y1],
                             [bx - uy * head * 0.42, by + ux * head * 0.42],
                             [bx + uy * head * 0.42, by - ux * head * 0.42]])

        elif t == "text":
            x, y = cam.to_px(p["x"], p["y"])
            cv.fill_style = p.get("fill", "#111")
            cv.font = f"{p.get('size', 13)}px sans-serif"
            cv.text_align = p.get("align", "center")
            cv.text_baseline = p.get("baseline", "middle")
            cv.fill_text(p["s"], x, y)

        if alpha != 1.0:
            cv.global_alpha = 1.0


def in_notebook():
    """True only inside a real kernel with a widget-capable front end.

    Constructing an ipycanvas widget succeeds even in a plain ``python
    script.py`` run -- it just never displays.  Checking for the kernel
    instead means ``python demo.py`` silently falls back to recording and
    ``scene.save_html()`` still produces something you can open, rather than
    raising somewhere confusing.
    """
    try:
        from IPython import get_ipython
    except Exception:
        return False
    ip = get_ipython()
    return ip is not None and hasattr(ip, "kernel")


def make_backend(width, height, background, prefer_live=True):
    """Return a live backend if one can actually be shown, else the null one."""
    if prefer_live and in_notebook():
        try:
            return IpycanvasBackend(width, height, background)
        except Exception:
            pass
    return NullBackend(width, height, background)
