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

import inspect


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
            r = p.get("rpx") or max(cam.px_len(p["r"]), 1.0)
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


_pump_unsupported = False
_ui_poll = None  # jupyter_ui_poll's poll function, held for the current cell
_UI_EVENTS_PER_PUMP = 20


def _ui_poller(ip):
    """Return a jupyter-ui-poll ``poll(n)`` for this cell, or None.

    ``ui_events()`` drives the async ``do_one_iteration`` on a helper thread
    and holds back ``execute_request`` messages (cells queued below) until
    this cell finishes. Entering it starts a thread, so the context is opened
    once per cell and closed from IPython's ``post_run_cell`` event.
    """
    global _ui_poll
    if _ui_poll is not None:
        return _ui_poll
    try:
        from jupyter_ui_poll import ui_events
    except Exception:
        return None
    try:
        ctx = ui_events()
        poll = ctx.__enter__()
    except Exception:
        return None

    def _finish(*args, **kwargs):
        global _ui_poll
        ip.events.unregister("post_run_cell", _finish)
        _ui_poll = None
        ctx.__exit__(None, None, None)

    ip.events.register("post_run_cell", _finish)
    _ui_poll = poll
    return poll


_COMM_MSG_TYPES = (b"comm_open", b"comm_msg", b"comm_close")
_held = None  # ipykernel 7: non-comm shell messages held until the cell ends


def _main_shell_stream(kernel):
    """ipykernel 7: the ZMQStream that feeds the main shell, or None.

    With subshells (the default) that is the inproc pair from the shell
    channel thread; ``kernel.shell_stream`` then belongs to that thread and
    must not be read from here.
    """
    if getattr(kernel, "_supports_kernel_subshells", False):
        try:
            manager = kernel.shell_channel_thread.manager
            return manager.get_shell_channel_to_subshell_pair(None).to_stream
        except Exception:
            return None
    return getattr(kernel, "shell_stream", None)


def _is_comm(kernel, frames):
    """True if a raw shell message is a widget (comm) message."""
    if len(frames) < 2:
        return False
    try:
        _, rest = kernel.session.feed_identities(frames, copy=False)
        header = kernel.session.deserialize(rest, content=False, copy=False)["header"]
    except Exception:
        return False
    return header.get("msg_type", "").encode() in _COMM_MSG_TYPES


def _dispatch_comm_now(kernel, frames):
    """Run a comm message through ``dispatch_shell`` without the event loop.

    ipykernel 7.4's own ``shell_main`` dispatches comm messages that arrive
    during a busy cell with ``concurrent=True``. For comm handlers
    ``dispatch_shell`` has no real awaits, so the coroutine finishes on its
    first step. The cell's
    parent is restored afterwards so its output stays in its own cell.
    """
    parent = kernel.get_parent("shell")
    lookup = getattr(kernel, "_get_shell_context_var", None)
    ident = (lookup(kernel._shell_parent_ident) if lookup is not None
             else kernel._shell_parent_ident.get())
    if "concurrent" in inspect.signature(kernel.dispatch_shell).parameters:
        coro = kernel.dispatch_shell(frames, subshell_id=None, concurrent=True)
    else:  # ipykernel < 7.4 also publishes busy/idle for the comm message
        coro = kernel.dispatch_shell(frames, subshell_id=None)
    try:
        coro.send(None)
    except StopIteration:
        pass
    except Exception:
        pass
    else:
        coro.close()  # suspended on a real await: cannot finish it here
    finally:
        kernel.set_parent(ident, parent, channel="shell")


def _replay_held(kernel, held):
    """Hand held messages back to the kernel, in order, once the cell ends."""
    import asyncio

    for frames in held:
        asyncio.ensure_future(kernel.shell_main(None, frames))


def _drain_shell(ip, kernel):
    """ipykernel 7: read the main shell socket between frames.

    Comm messages (mouse events) are dispatched at once. Everything else --
    cells queued below, completion requests -- is held and replayed when this
    cell finishes, so nothing runs in the middle of the animation loop.
    Returns False if this kernel does not look like ipykernel 7.
    """
    global _held
    import zmq

    stream = _main_shell_stream(kernel)
    if stream is None or not hasattr(kernel, "shell_main"):
        return False
    if _held is None:
        held = []

        def _finish(*args, **kwargs):
            global _held
            ip.events.unregister("post_run_cell", _finish)
            _held = None
            _replay_held(kernel, held)

        ip.events.register("post_run_cell", _finish)
        _held = held
    sock = stream.socket
    while True:
        try:
            frames = sock.recv_multipart(zmq.NOBLOCK, copy=False)
        except zmq.Again:
            return True
        if _is_comm(kernel, frames):
            _dispatch_comm_now(kernel, frames)
        else:
            _held.append(frames)


def pump_kernel():
    """Process pending IPython kernel messages so widget events can land.

    ``rate`` / ``run`` call this in live mode between frames. ``time.sleep``
    blocks the kernel, which freezes ``scene.mouse`` for the whole loop.
    IPython is optional: with no kernel this returns and the caller blocks
    as before.

    Since ipykernel 5 (Jupyter, Colab) ``do_one_iteration`` is a coroutine
    that waits on the running event loop, which a synchronous loop cannot
    drive itself. When ``jupyter-ui-poll`` is installed (the ``[live]`` extra)
    it does the driving. Without it the coroutine is closed unawaited (no
    "never awaited" warning) and pumping is switched off for the session.

    ipykernel 7 routes shell messages through a separate thread, which
    ``do_one_iteration`` (gone in 7.1) does not see; there the main shell
    socket is read directly (``_drain_shell``), with no extra dependency.
    """
    global _pump_unsupported
    if _pump_unsupported:
        return
    try:
        from IPython import get_ipython
    except Exception:
        return
    ip = get_ipython()
    if ip is None:
        return
    kernel = getattr(ip, "kernel", None)
    if kernel is None:
        return
    if hasattr(kernel, "shell_main"):  # ipykernel 7
        try:
            if not _drain_shell(ip, kernel):
                _pump_unsupported = True
        except Exception:
            _pump_unsupported = True
        return
    step = getattr(kernel, "do_one_iteration", None)
    if step is None:
        return
    if inspect.iscoroutinefunction(step):
        poll = _ui_poller(ip)
        if poll is None:
            _pump_unsupported = True
            return
        try:
            poll(_UI_EVENTS_PER_PUMP)
        except Exception:
            return
        return
    try:
        result = step()
    except Exception:
        return
    if inspect.isawaitable(result):
        _pump_unsupported = True
        close = getattr(result, "close", None)
        if close is not None:
            close()


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
