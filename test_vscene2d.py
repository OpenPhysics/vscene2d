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
    check("immutable, with a useful message", "trail" in str(e))
check("sum() of vectors", sum([vector(1, 2), vector(3, 4)]) == vector(4, 6))
check("VPython-style vector(x, y, 0)", vector(1, 2, 0) == vector(1, 2))
try:
    vector(1, 2, 3)
    check("nonzero z rejected", False)
except ValueError:
    check("nonzero z rejected", True)

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
bl = Ball(pos=vector(0, 1), radius=0.1)
ar = Arrow(pos=vector(0, 0), axis=vector(1, 1))
out = s3._display_list()
kinds = {p["t"] for p in out}
check("all primitive kinds emitted", kinds == {"circle", "rect", "poly", "arrow", "text"},
      str(sorted(kinds)))
check("rotated box bounds grow", bx.bounds()[2] - bx.bounds()[0] > 1.0)
sp_out = []
sp.emit(sp_out, s3.camera)
pts = sp_out[0]["pts"]
peaks = sum(1 for i in range(1, len(pts), 2) if pts[i] > 0.1)
check("spring draws the requested coil count", peaks == 8, f"peaks={peaks}")
check("spring runs from start to end", pts[:2] == [0.0, 0.0] and pts[-2:] == [2.0, 0.0])
s3.render()
check("render works with no live backend", len(s3.recorder) == 1)

print("\n[camera pinning]")
s4 = Scene(mode="record", range=5)
check("explicit range disables autoscale", s4.camera.autoscale is False)
Ball(pos=vector(100, 100), radius=1, scene=s4)
s4.render()
check("pinned view does not chase the object", abs(s4.camera.ry - 5) < 1e-9)

print("\n[timekeeping]")
s5 = Scene(mode="record")
Ball(pos=vector(0, 0), scene=s5)
for _ in range(100):
    s5.rate(100, 0.001)
check("rate(fps, dt) advances scene.t by dt", abs(s5.t - 0.1) < 1e-9, f"t={s5.t:.4f}")
s5.clear()
for _ in range(100):
    s5.rate(100)
check("rate(fps) alone advances scene.t by 1/fps", abs(s5.t - 1.0) < 1e-9)

s6 = Scene(mode="record")
b6 = Ball(pos=vector(0, 0), scene=s6)


def drift(dt):
    b6.pos = b6.pos + vector(1, 0) * dt


s6.run(drift, dt=0.01, duration=3.0, fps=30)
check("playback speed not distorted by substep rounding",
      abs(s6.frame - (1 + 3.0 * 30)) <= 1, f"frames={s6.frame}, expected ~91")
before = s6.frame
s6.run(drift, dt=0.01, duration=10.0, fps=30, max_frames=20)
check("run(max_frames=) caps this run, not the scene total",
      s6.frame - before == 20, f"rendered {s6.frame - before}")

slow = Scene(mode="record", grid=False)
slow.run(lambda dt: None, dt=0.1, fps=30, speed=0.1, max_frames=31)
check("slow playback can render frames without an integration step",
      abs(slow.t - 0.1) < 1e-9, f"t={slow.t:.4f}")

print("\n[html escaping]")
s7 = Scene(mode="record")
Label(pos=vector(0, 0), text="</script><b>x</b> __TITLE__", scene=s7)
Ball(scene=s7)
s7.render()
h7 = s7.recorder.html(100, 100, "#fff", 30, "<i>t</i>")
check("label text can't close the script tag", h7.count("</script>") == 1)
check("title is escaped", "<i>" not in h7 and "&lt;i&gt;" in h7)
check("data text isn't treated as a placeholder", "__TITLE__" in h7)

print("\n[mouse]")
m = s7.mouse
m.clicked = True
check("clicked is true once per click", m.clicked is True and m.clicked is False)

print("\n[truncation note]")
import tempfile
cap = Scene(mode="record", max_frames=3, grid=False, title="cap")
Ball(pos=vector(0, 0), radius=0.2, scene=cap)
cap.run(lambda dt: None, dt=0.1, duration=5, fps=30)
check("recorder cap sets truncated while dropped stays 0",
      cap.recorder.truncated and cap.recorder.dropped == 0,
      f"truncated={cap.recorder.truncated} dropped={cap.recorder.dropped} n={len(cap.recorder)}")
cap_path = os.path.join(tempfile.mkdtemp(), "cap.html")
cap.save_html(cap_path, title="Δt")
cap_html = open(cap_path, encoding="utf-8").read()
check("save_html mentions the frame cap", "frame cap" in cap_html and "max_frames" in cap_html)
check("save_html writes utf-8", "Δt" in cap_html)

print("\n[opacity]")
op = Scene(mode="record", grid=False)
ball_op = Ball(pos=vector(0, 0), radius=0.2, opacity=0.25, scene=op)
op_out = []
ball_op.emit(op_out, op.camera)
check("opacity in the primitive", op_out and op_out[0].get("alpha") == 0.25)
op.render()
op_html = op.recorder.html(80, 80, "#fff", 30, "")
check("player honors alpha", "globalAlpha" in op_html and "0.25" in op_html)

print("\n[dt and fps]")
try:
    Scene(mode="record").run(lambda dt: None, dt=0, duration=1)
    check("dt=0 raises", False)
except ValueError:
    check("dt=0 raises", True)
try:
    Scene(mode="record").run(lambda dt: None, dt=-0.01, duration=1)
    check("negative dt raises", False)
except ValueError:
    check("negative dt raises", True)
try:
    Scene(mode="record").rate(0)
    check("fps=0 raises", False)
except ValueError:
    check("fps=0 raises", True)
try:
    Scene(mode="record").rate(-5)
    check("negative fps raises", False)
except ValueError:
    check("negative fps raises", True)

print("\n[max_frames=1]")
one = Scene(mode="record", grid=False)
one.run(lambda dt: None, dt=0.1, duration=10, fps=30, max_frames=1)
check("max_frames=1 records exactly 1 frame",
      one.frame == 1 and len(one.recorder) == 1,
      f"frame={one.frame} recorded={len(one.recorder)}")

print("\n[explicit live outside a notebook]")
try:
    Scene(mode="live")
    check("explicit live outside notebook raises", False)
except RuntimeError as e:
    check("explicit live outside notebook raises", "notebook" in str(e).lower(), str(e))

print("\n[clear graphs]")
sg = Scene(mode="record", grid=False)
Graph(scene=sg, title="g")
gc = gcurve(graph=sg._graphs[0])
gc.plot(0, 0)
gc.plot(1, 1)
sg.render()
check("graph has samples before clear", len(gc.xs) == 2 and len(sg._graphs[0].recorder) >= 1)
sg.clear()
check("clear() clears graph curves", len(gc.xs) == 0 and len(gc.ys) == 0)
check("clear() clears graph frames", len(sg._graphs[0].recorder) == 0)

print("\n[hidden objects]")
hid = Scene(mode="record", grid=False, autoscale=True)
Ball(pos=vector(0, 0), radius=0.5, scene=hid)
far = Ball(pos=vector(80, 0), radius=0.5, scene=hid, visible=False)
empty = far.bounds()
check("hidden bounds are empty", empty[0] > empty[2])
hid.render()
check("autoscale skips hidden objects", hid.camera.bounds[2] < 20, str(hid.camera.bounds))

print("\n[ball then scene]")
import vscene2d.scene as scene_mod
scene_mod._scene = None
scene_mod._unbound.clear()
early = Ball(pos=vector(3, 4), radius=0.1)
check("ball created before any scene stays unbound", early.scene is None)
adopted = Scene(mode="record", grid=False)
check("first explicit Scene adopts the ball", early in adopted.objects and early.scene is adopted)

print("\n[replace trail]")
tr_scene = Scene(mode="record", grid=False)
tr_ball = Ball(pos=vector(0, 0), radius=0.2, make_trail=True, scene=tr_scene)
old_trail = tr_ball.trail
attach_trail(tr_ball, color=color.blue)
check("new trail replaces the old one",
      tr_ball.trail is not old_trail and old_trail not in tr_scene.objects
      and tr_ball.trail in tr_scene.objects)

print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}"))
sys.exit(1 if FAIL else 0)
