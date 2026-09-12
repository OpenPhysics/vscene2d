# vscene2d

VPython's ergonomics, in 2D, running natively inside a Jupyter cell — no GlowScript,
no WebGL, no separate browser tab.

Students write physics. The canvas, axes, scaling, redraws, and pacing are handled.

```python
from vscene2d import *

scene = Scene()
ball  = Ball(pos=vector(0, 0), radius=0.3, color=color.red, make_trail=True)
vel, g, dt = vector(12, 16), vector(0, -9.8), 0.01

while ball.pos.y >= 0:
    rate(100)
    ball.pos = ball.pos + vel*dt
    vel = vel + g*dt
```

## Install

```bash
pip install -e ".[live]"       # the [live] extra pulls in ipycanvas + ipywidgets
```

The library itself has no dependencies — `pip install -e .` is enough if you only ever
use `mode="record"`. You can also just put `vscene2d/` next to your notebook. Python 3.9+.

JupyterLab 4 and Notebook 7 pick up ipycanvas automatically. In Colab, run
`from google.colab import output; output.enable_custom_widget_manager()` first —
or skip the widget entirely and use `mode="record"`, which needs nothing but a browser.

---

## The two things this fixes about VPython in a physics course

### 1. Small `dt` no longer means slow motion

`rate(100)` renders one frame per integration step. With `dt = 1e-4`, one frame advances the
physics by 0.1 ms — a 10-second fall takes 17 real minutes, and the student concludes,
reasonably, that a smaller timestep "breaks" the animation. Accuracy and frame rate are
fighting each other, and accuracy loses.

`scene.run()` separates them. You ask for real-time playback; it works out how many
integration substeps belong between frames.

```python
def step(dt):
    global vel
    vel = vel + g*dt
    ball.pos = ball.pos + vel*dt

scene.run(step, dt=0.0001, until=lambda: ball.pos.y < 0, fps=30)
```

`until=` is checked every *integration* step, so the run stops at the ground crossing to
within `dt` rather than to within a frame.

| argument | |
|---|---|
| `dt` | integration timestep |
| `fps` | frames drawn per second (default 30) |
| `speed` | simulated seconds per real second — `0.25` for slow motion |
| `duration` | stop after this much simulated time |
| `until` | predicate; stop as soon as it's true |
| `realtime` | sleep between frames to hold `fps` (default: on in live mode, off when recording) |
| `max_frames` | frame cap for this run; overrides the scene's |

`step` is called as `step(dt)` or `step(dt, t)`, whichever you define.

### 2. Animations survive being saved

A live widget is a *kernel* artifact. Save the notebook, push it to GitHub, hand it to a
grader, open it on nbviewer — the animation is gone and all anyone sees is a blank
rectangle. For a course where students submit notebooks, that's disqualifying.

Every scene records its frames as it runs:

```python
scene = Scene(mode="record")     # no widget, no sleeping, full speed
...
scene.player()                   # scrubbable HTML animation
```

`player()` emits one self-contained HTML block — canvas, play/pause, scrub slider, frame data
inlined as JSON, zero external requests. It works in the notebook, in exported HTML, on
nbviewer, and in GitHub's preview, with no kernel and no widget extension.

It's also much faster to *produce*: a 12-second orbit that takes 12 seconds to watch live
records in about a fifth of a second, because nothing sleeps and nothing crosses the widget
comm channel.

`scene.save_html("orbit.html")` writes a standalone file for a course site.

| `mode=` | |
|---|---|
| `"live"` | draw to an ipycanvas widget as the loop runs |
| `"record"` | no widget, full speed, replay with `player()` |
| `"auto"` *(default)* | `live` in a notebook, `record` in a plain script |

---

## API

```python
vector(x, y)                    # immutable; .mag .mag2 .norm() .hat .dot() .cross()
                                #            .rotate(rad) .proj() .theta
dot(a, b)  cross(a, b)  mag(a)  norm(a)  hat(a)      # function forms of the same
```

`vector` is immutable on purpose. `ball.pos.x = 5` would silently bypass the position
setter, so it raises with an explanation instead of quietly doing nothing visible.

| object | |
|---|---|
| `Ball(pos, radius, color, make_trail=, retain=)` | disc |
| `Box(pos, size, angle, filled=)` | rectangle, rotatable |
| `Arrow(pos, axis, scale=, color)` | vector; `scale` converts units to world length |
| `Segment(start, end, lw=)` | rod, string, ramp, wall |
| `Spring(start, end, coils=, amplitude=)` | zigzag with a fixed coil count as it stretches |
| `Label(pos, text, size=)` | text; size in **pixels**, so it stays legible through autoscale |
| `Curve(points)` | polyline you append to with `.append(p)` |

Every object also takes `color=`, `opacity=`, `visible=`, and has `.remove()`. Objects
register with the current scene on construction, so you never pass one explicitly.

| helper | |
|---|---|
| `attach_trail(obj, retain=)` | add a trail to an existing object |
| `attach_arrow(obj, "vel", owner=globals(), scale=)` | arrow that re-reads the variable every frame, so it can't drift out of sync with the physics |

| graphing | |
|---|---|
| `Graph(title, xtitle, ytitle)` | second canvas, repaints on the same frames |
| `gcurve(color, label, every=, dot=)` | one trace; `.plot(x, y)` or `.plot((x, y))` |

`every=20` thins a trace. 20 000 integration steps is more points than a 560-pixel plot can
show, and drawing them all 30 times a second is what makes browser plots stutter.

A `Graph` exports independently of the scene: `graph.player()` gives the plot its own
scrubbable HTML block.

| scene | |
|---|---|
| `scene.t` / `scene.frame` | simulated time; frames rendered so far |
| `scene.set_view(center=, range=)` | pin the view, stop autoscaling |
| `Scene(center=, range=)` | same, at construction |
| `scene.mouse.pos` | cursor in world coordinates (live mode) |
| `scene.player(fps=)` / `scene.save_html(path)` | export |
| `scene.clear()` | delete objects, reset the clock (keeps the camera) |

`Scene` also takes `width=640`, `height=480`, `title=`, `background=`, `grid=True`,
`autoscale=` (defaults to off once you give a `range`), and `max_frames=2000`.

---

## Design notes

**Objects never touch a canvas.** They emit a display list of primitives in world
coordinates; a backend turns that into pixels. That indirection is why the same scene can
render to a live widget, replay as standalone HTML, and run headless in a test with no
display — and why the geometry is testable at all, instead of only verifiable by a human
squinting at a notebook.

**Equal aspect, always.** In a scene, x and y are drawn at the same scale, so a circle is a
circle and a 45° launch looks like 45°. `Graph` deliberately does the opposite, because a
plot needs independent axes. Same camera class, one flag.

**Autoscale that settles.** Fitting the bounding box every frame makes the world visibly
breathe and makes a straight trail appear to curve. Here the view only ever grows, it grows
with headroom, and it snaps onto a 1/2/5 ladder — a projectile going from a 0.3 m ball to a
44 m range rescales 8 times over 400 frames instead of 400, and gridlines land on the same
round numbers at every zoom level.

**Trails sample once per rendered frame**, not on every assignment to `pos`. At `dt = 1e-4`
a per-assignment trail accumulates 10 000 points per simulated second and the animation
dies. Frame-rate sampling keeps trail density constant no matter how fine the integration.

**Frames are prefix-delta encoded.** A trail re-emits its whole polyline every frame, which
is quadratic in storage; since trails only append, storing just the new points makes it
linear. A 124-frame projectile with a trail exports as 51 KB of HTML.

**Batched drawing.** The live backend uses two canvas layers — grid underneath, redrawn only
when the camera actually changes; objects on top — and wraps each frame in `hold_canvas`.
Without that batching, ipycanvas animations tear visibly; it's the most common reason
hand-rolled ones look bad.

---

## Limitations

- 2D only, by design. If you need 3D, VPython in a separate tab is still the answer.
- The live loop blocks the kernel, exactly as VPython's does. Interrupt with the stop button;
  `mode="record"` avoids the issue entirely.
- Mouse input needs the live widget.
- `max_frames` defaults to 2000; longer runs record the first 2000 and say so.

## Tests

```bash
python3 test_vscene2d.py
```

No test framework and no display needed — it runs against the headless backend and
prints a line per check. Covers vector algebra, the camera transform and its round-trip, autoscale stability,
substepping against analytic projectile range and flight time, energy conservation, the
delta encoding round-trip against a fresh render, and the exported HTML's structure.
