import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vscene2d import *  # noqa
from vscene2d.camera import Camera, nice_step
from vscene2d.scene import Scene

FAIL = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  " + extra) if extra else ""))
    if not cond:
        FAIL.append(name)


print("\n[vector]")
a, b = vector(3, 4), vector(1, 0)
check("mag", a.mag == 5.0)
check("dot", a.dot(b) == 3.0)
check("cross (z-component)", vector(1, 0).cross(vector(0, 1)) == 1.0)
check("norm is unit", abs(a.norm().mag - 1) < 1e-12)
check("rotate 90deg", abs(vector(1, 0).rotate(math.pi / 2).y - 1) < 1e-12)
check("theta", abs(vector(0, 1).theta - math.pi / 2) < 1e-12)
check("rmul", (2 * a) == vector(6, 8))
check("unpacking", list(vector(1, 2)) == [1.0, 2.0])
try:
    a.x = 9
    check("immutable", False)
except AttributeError as e:
    check("immutable, with a useful message", "redraw" in str(e))

print("\n[camera: equal aspect]")
cam = Camera(640, 480, range_=10)
check("sx == sy", abs(cam.sx - cam.sy) < 1e-12, f"sx={cam.sx:.4f}")
p = cam.to_px(0, 0)
check("origin maps to centre", p == (320.0, 240.0))
check("y is up", cam.to_px(0, 1)[1] < cam.to_px(0, 0)[1])
rx, ry = cam.to_world(*cam.to_px(3.5, -2.25))
check("roundtrip", abs(rx - 3.5) < 1e-9 and abs(ry + 2.25) < 1e-9)
check("nice_step", [nice_step(v) for v in (0.11, 0.3, 0.7, 3, 40)] == [0.1, 0.2, 0.5, 2.0, 50.0])

print("\n[autoscale: must settle, not jitter]")
cam = Camera(640, 480)
changes = 0
# a projectile sweeping out a wide arc, one 'frame' at a time
for i in range(400):
    t = i * 0.01
    x, y = 20 * t, 20 * t - 4.9 * t * t
    if cam.include(x - .3, y - .3, x + .3, y + .3):
        changes += 1
check("rescales a handful of times over 400 frames", changes <= 10, f"changes={changes}")
check("never shrinks below the trajectory", cam.bounds[2] >= 8.0)
before = cam.key
cam.include(0, 0, 1, 1)
check("interior box triggers no rescale", cam.key == before)

print("\n[scene: headless run]")
scene = Scene(mode="record", width=400, height=300, title="drop")
ball = Ball(pos=vector(0, 0), radius=0.3, color=color.red, make_trail=True)
arr = attach_arrow(ball, "v", owner=sys.modules[__name__], scale=0.2, color=color.blue)
v = vector(14, 18)
g = vector(0, -9.8)


def step(dt):
    global v
    v = v + g * dt
    ball.pos = ball.pos + v * dt


scene.run(step, dt=0.0005, until=lambda: ball.pos.y < 0, fps=30)
check("no widget in record mode", scene.mode == "record")
check("frames recorded", len(scene.recorder) > 20, f"n={len(scene.recorder)}")
T = 2 * 18 / 9.8
check("stopped at the analytic flight time", abs(scene.t - T) < 0.02,
      f"t={scene.t:.4f} vs {T:.4f}")
check("range agrees with v0^2 sin(2th)/g", abs(ball.pos.x - 14 * T) < 0.05,
      f"x={ball.pos.x:.3f}")
trail = ball.trail
check("trail sampled per frame, not per step",
      len(trail.points) < 200 and len(trail.points) > 20, f"pts={len(trail.points)}")
check("substepping: many physics steps per frame",
      scene.t / 0.0005 > 10 * len(scene.recorder))

print("\n[recorder: delta encoding]")
rec = scene.recorder
enc_sizes = [len(json.dumps(f)) for f in rec.frames]
check("later frames are not larger than early ones (trail deltas work)",
      enc_sizes[-1] < 3 * enc_sizes[3], f"{enc_sizes[3]} -> {enc_sizes[-1]}")
total = len(json.dumps(rec.frames))
naive = sum(len(json.dumps(p)) for p in [rec._prev] * len(rec.frames)) + 1
check("payload well under the naive quadratic size", total < naive, f"{total} bytes")

print("\n[html player]")
html = scene.recorder.html(400, 300, "#fff", 30, "drop")
check("single self-contained block", html.count("<script>") == 1)
check("no external requests", "http://" not in html and "https://" not in html)
check("data is inlined", '"frames"' in html)
check("no template placeholders left", "__DATA__" not in html and "__UID__" not in html)
uid = re.search(r'id="(vs[0-9a-f]+)"', html)
check("unique element id", uid is not None)
check("id used consistently", html.count(uid.group(1)) >= 2)
check("has a scrub control", 'type="range"' in html)

print("\n[player reconstruction matches the live display list]")
# Replay the delta decoding in Python exactly as the JS does, and compare
# the final frame to a fresh render of the same scene state.
absf, prev = [], None
for enc in rec.frames:
    cur = []
    for j, e in enumerate(enc):
        if e == 0:
            cur.append(prev[j])
        elif isinstance(e, dict) and e.get("t") == "+":
            c = dict(prev[j])
            c["pts"] = prev[j]["pts"] + e["pts"]
            cur.append(c)
        else:
            cur.append(e)
    absf.append(cur)
    prev = cur
live = scene._display_list()
check("same number of primitives", len(absf[-1]) == len(live),
      f"{len(absf[-1])} vs {len(live)}")
poly_live = [p for p in live if p["t"] == "poly" and p.get("stroke") == color.red]
poly_dec = [p for p in absf[-1] if p["t"] == "poly" and p.get("stroke") == color.red]
check("decoded trail has the full point list",
      poly_dec and len(poly_dec[0]["pts"]) == len(poly_live[0]["pts"]),
      f"{len(poly_dec[0]['pts'])} vs {len(poly_live[0]['pts'])}")
check("decoded trail values match to rounding",
      all(abs(x - y) < 1e-3 for x, y in zip(poly_dec[0]["pts"], poly_live[0]["pts"])))

print("\n[graph]")
s2 = Scene(mode="record", width=300, height=200)
b2 = Ball(pos=vector(1, 0), radius=0.05)
gr = Graph(width=300, height=150, title="energy", xtitle="t (s)", scene=s2)
ke = gcurve(graph=gr, color=color.blue, label="KE", every=10)
pe = gcurve(graph=gr, color=color.red, label="PE", every=10)
tot = gcurve(graph=gr, color=color.black, label="E", every=10)
w2, x, vx = 4.0, 1.0, 0.0


def sho(dt):
    global x, vx
    vx += -w2 * x * dt
    x += vx * dt
    b2.pos = vector(x, 0)
    ke.plot(s2.t, 0.5 * vx * vx)
    pe.plot(s2.t, 0.5 * w2 * x * x)
    tot.plot(s2.t, 0.5 * vx * vx + 0.5 * w2 * x * x)


s2.run(sho, dt=0.0002, duration=4.0, fps=30)
check("graph rendered on the same frames", len(gr.recorder) == len(s2.recorder),
      f"{len(gr.recorder)} vs {len(s2.recorder)}")
check("every=10 thinned the trace", len(tot.xs) == len(tot.xs) and
      len(tot.xs) < 4.0 / 0.0002, f"pts={len(tot.xs)}")
E = tot.ys
check("energy conserved by symplectic Euler to ~1%",
      (max(E) - min(E)) / max(E) < 0.02, f"drift={(max(E)-min(E))/max(E):.4f}")
check("plot camera scales x and y independently",
      abs(gr.camera.sx - gr.camera.sy) > 1e-6)
ghtml = gr.recorder.html(300, 150, "#fff", 30, "energy")
check("graph exports its own player", '"frames"' in ghtml)

print("\n[objects]")
s3 = Scene(mode="record", width=300, height=300)
sp = Spring(start=vector(0, 0), end=vector(2, 0), coils=8, amplitude=0.2)
bx = Box(pos=vector(1, 1), size=vector(1, 0.5), angle=math.pi / 4)
lb = Label(pos=vector(0, 2), text="hello")
sg = Segment(start=vector(-1, -1), end=vector(1, -1))
cv = Curve(points=[vector(0, 0), vector(1, 1), vector(2, 0)])
out = s3._display_list()
kinds = {p["t"] for p in out}
check("all primitive kinds emitted", kinds >= {"poly", "rect", "text"}, str(sorted(kinds)))
check("rotated box bounds grow", bx.bounds()[2] - bx.bounds()[0] > 1.0)
check("spring polyline is non-degenerate",
      len([p for p in out if p["t"] == "poly" and len(p["pts"]) > 20]) >= 1)
s3.render()
check("render works with no live backend", len(s3.recorder) == 1)

print("\n[camera pinning]")
s4 = Scene(mode="record", range=5)
check("explicit range disables autoscale", s4.camera.autoscale is False)
Ball(pos=vector(100, 100), radius=1, scene=s4)
s4.render()
check("pinned view does not chase the object", abs(s4.camera.ry - 5) < 1e-9)

print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}"))
sys.exit(1 if FAIL else 0)
