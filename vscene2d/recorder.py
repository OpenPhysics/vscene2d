"""Frame recording and standalone HTML playback.

Why this exists
---------------
A live ipycanvas widget is a *kernel* artifact.  Save the notebook, push it to
GitHub, hand it to a grader, view it on nbviewer -- the animation is gone, and
all anyone sees is a blank rectangle.  For a course where students submit
notebooks, that is disqualifying.

So every scene records its frames as it runs, and ``scene.player()`` emits a
single self-contained HTML block: canvas, play/pause, and a scrub slider, with
the frame data inlined as JSON.  It renders in the notebook, in exported HTML,
on nbviewer, and in GitHub's notebook preview, with no kernel and no widget
extension.

Recording also unlocks a much faster workflow: run the simulation with no
sleeping and no per-frame widget traffic, then scrub the result.  A run that
takes 20 s to watch live records in well under a second.

Frames are prefix-delta encoded.  A trail re-emits its whole polyline every
frame, which is quadratic in storage if stored naively; since trails only ever
*append*, storing just the new points makes it linear.
"""

from __future__ import annotations

import json
import uuid


def _r(v, nd=4):
    return round(float(v), nd)


class Recorder:
    """Captures display lists frame by frame, with delta compression."""

    def __init__(self, max_frames=2000):
        self.frames = []
        self.cams = []
        self.times = []
        self.max_frames = max_frames
        self._prev = None
        self.dropped = 0

    def __len__(self):
        return len(self.frames)

    def clear(self):
        self.frames.clear()
        self.cams.clear()
        self.times.clear()
        self._prev = None
        self.dropped = 0

    def capture(self, prims, cam, t):
        if len(self.frames) >= self.max_frames:
            self.dropped += 1
            return
        enc = []
        prev = self._prev
        for i, p in enumerate(prims):
            q = prev[i] if (prev is not None and i < len(prev)) else None
            if q == p:
                enc.append(0)  # unchanged
                continue
            if (p["t"] == "poly" and q is not None and q["t"] == "poly"
                    and len(q["pts"]) < len(p["pts"])
                    and p["pts"][: len(q["pts"])] == q["pts"]
                    and q.get("stroke") == p.get("stroke")
                    and q.get("lw") == p.get("lw")):
                enc.append({"t": "+", "pts": [_r(v) for v in p["pts"][len(q["pts"]):]]})
                continue
            enc.append(_round_prim(p))
        self._prev = [dict(p) for p in prims]
        self.frames.append(enc)
        self.cams.append([_r(cam.cx), _r(cam.cy), _r(cam.ry), _r(cam.rx)])
        self.times.append(_r(t, 6))

    # --- export -------------------------------------------------------
    def payload(self, width, height, background, fps):
        return {
            "w": width, "h": height, "bg": background, "fps": fps,
            "frames": self.frames, "cams": self.cams, "t": self.times,
        }

    def html(self, width, height, background="#ffffff", fps=30, title=""):
        data = json.dumps(self.payload(width, height, background, fps),
                          separators=(",", ":"))
        return _PLAYER_HTML.replace("__UID__", "vs" + uuid.uuid4().hex[:8]) \
                           .replace("__DATA__", data) \
                           .replace("__TITLE__", title or "")


def _round_prim(p):
    q = {}
    for k, v in p.items():
        if k == "pts":
            q[k] = [_r(x) for x in v]
        elif isinstance(v, float):
            q[k] = _r(v)
        else:
            q[k] = v
    return q


# Deliberately quiet styling: this sits inside a notebook, so it borrows the
# host's font stack and stays out of the way.  All the visual interest belongs
# to the simulation above the controls.
_PLAYER_HTML = """
<div id="__UID__" style="display:inline-block;font-family:inherit;font-size:13px;">
  <canvas></canvas>
  <div style="display:flex;align-items:center;gap:10px;margin-top:6px;">
    <button type="button" style="min-width:64px;padding:3px 10px;cursor:pointer;
      border:1px solid rgba(128,128,128,.45);border-radius:4px;background:transparent;
      font:inherit;color:inherit;">Play</button>
    <input type="range" min="0" value="0" style="flex:1;min-width:140px;">
    <span style="font-variant-numeric:tabular-nums;opacity:.7;min-width:86px;">&nbsp;</span>
  </div>
  <div style="opacity:.6;margin-top:2px;">__TITLE__</div>
</div>
<script>
(function(){
  var root = document.getElementById("__UID__");
  if (!root || root.dataset.ready) return;
  root.dataset.ready = "1";
  var D = __DATA__;
  var cv = root.querySelector("canvas"), btn = root.querySelector("button"),
      sl = root.querySelector("input"), lab = root.querySelector("span");
  var dpr = window.devicePixelRatio || 1;
  cv.width = D.w*dpr; cv.height = D.h*dpr;
  cv.style.width = D.w+"px"; cv.style.height = D.h+"px";
  cv.style.borderRadius = "4px";
  var g = cv.getContext("2d"); g.scale(dpr, dpr);
  var N = D.frames.length; sl.max = Math.max(N-1, 0);

  // Rebuild absolute frames from the prefix-delta encoding.
  var abs = [], prev = null;
  for (var i=0;i<N;i++){
    var enc = D.frames[i], cur = [];
    for (var j=0;j<enc.length;j++){
      var e = enc[j];
      if (e === 0) cur.push(prev[j]);
      else if (e && e.t === "+"){
        var c = Object.assign({}, prev[j]);
        c.pts = prev[j].pts.concat(e.pts);
        cur.push(c);
      } else cur.push(e);
    }
    abs.push(cur); prev = cur;
  }

  function cam(f){
    var c = D.cams[f], sx = D.w/(2*c[3]), sy = D.h/(2*c[2]);
    return {cx:c[0], cy:c[1], s:Math.min(sx,sy),
            px:function(x,y){return [D.w/2+(x-c[0])*sx, D.h/2-(y-c[1])*sy];}};
  }

  function draw(f){
    var C = cam(f);
    g.clearRect(0,0,D.w,D.h);
    g.fillStyle = D.bg; g.fillRect(0,0,D.w,D.h);
    var P = abs[f];
    for (var i=0;i<P.length;i++){
      var p = P[i], a;
      if (p.t === "circle"){
        a = C.px(p.x,p.y);
        g.beginPath(); g.arc(a[0],a[1],Math.max(p.r*C.s,1),0,6.2832);
        if (p.fill){ g.fillStyle=p.fill; g.fill(); }
        if (p.stroke){ g.strokeStyle=p.stroke; g.lineWidth=p.lw||1; g.stroke(); }
      } else if (p.t === "rect"){
        a = C.px(p.x,p.y);
        g.save(); g.translate(a[0],a[1]); if(p.angle) g.rotate(-p.angle);
        var w=p.w*C.s, h=p.h*C.s;
        if (p.fill){ g.fillStyle=p.fill; g.fillRect(-w/2,-h/2,w,h); }
        if (p.stroke){ g.strokeStyle=p.stroke; g.lineWidth=p.lw||1; g.strokeRect(-w/2,-h/2,w,h); }
        g.restore();
      } else if (p.t === "poly"){
        if (p.pts.length < 4) continue;
        g.beginPath();
        for (var k=0;k<p.pts.length;k+=2){
          a = C.px(p.pts[k],p.pts[k+1]);
          if (k===0) g.moveTo(a[0],a[1]); else g.lineTo(a[0],a[1]);
        }
        if (p.closed) g.closePath();
        if (p.fill){ g.fillStyle=p.fill; g.fill(); }
        if (p.stroke){ g.strokeStyle=p.stroke; g.lineWidth=p.lw||1;
                       g.lineJoin="round"; g.lineCap="round"; g.stroke(); }
      } else if (p.t === "arrow"){
        var s0 = C.px(p.x,p.y), s1 = C.px(p.x+p.dx, p.y+p.dy);
        var dx=s1[0]-s0[0], dy=s1[1]-s0[1], L=Math.hypot(dx,dy);
        if (L < 1e-9) continue;
        var ux=dx/L, uy=dy/L, hd=Math.min(p.head||10, L*0.5);
        var bx=s1[0]-ux*hd, by=s1[1]-uy*hd;
        g.strokeStyle=p.stroke; g.lineWidth=p.lw||2; g.lineCap="round";
        g.beginPath(); g.moveTo(s0[0],s0[1]); g.lineTo(bx,by); g.stroke();
        g.fillStyle=p.stroke; g.beginPath();
        g.moveTo(s1[0],s1[1]);
        g.lineTo(bx-uy*hd*0.42, by+ux*hd*0.42);
        g.lineTo(bx+uy*hd*0.42, by-ux*hd*0.42);
        g.closePath(); g.fill();
      } else if (p.t === "text"){
        a = C.px(p.x,p.y);
        g.fillStyle=p.fill||"#111"; g.font=(p.size||13)+"px sans-serif";
        g.textAlign=p.align||"center"; g.textBaseline=p.baseline||"middle";
        g.fillText(p.s, a[0], a[1]);
      }
    }
    lab.textContent = "t = " + (D.t[f]).toFixed(2) + " s";
  }

  var playing=false, raf=null, last=0, acc=0, frame=0;
  var dtms = 1000/(D.fps||30);
  function tick(ts){
    if (!playing) return;
    if (!last) last = ts;
    acc += ts-last; last = ts;
    while (acc >= dtms){ acc -= dtms; frame++; if (frame >= N){ frame=0; } }
    sl.value = frame; draw(frame);
    raf = requestAnimationFrame(tick);
  }
  btn.onclick = function(){
    playing = !playing;
    btn.textContent = playing ? "Pause" : "Play";
    last = 0; acc = 0;
    if (playing) raf = requestAnimationFrame(tick);
    else if (raf) cancelAnimationFrame(raf);
  };
  sl.oninput = function(){
    playing=false; btn.textContent="Play"; if (raf) cancelAnimationFrame(raf);
    frame = +sl.value; draw(frame);
  };
  if (N) draw(0);
})();
</script>
"""
