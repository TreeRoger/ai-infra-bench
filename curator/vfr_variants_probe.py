#!/usr/bin/env python3
"""Curator-only: try VFR (30 fps then 10 fps) recipes and report which yield a file
whose header frame count equals its decoded frame count with this ffmpeg build.
Usage: vfr_variants_probe.py TESTS_DIR OUTPUT_JSON
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import videolab as V  # noqa: E402

W, H = V.W, V.H
X = [*V.X264, "-pix_fmt", "yuv420p"]
CONCAT = ["-f", "lavfi", "-i", f"testsrc=s={W}x{H}:r=30:d=3", "-f", "lavfi", "-i", f"testsrc=s={W}x{H}:r=10:d=3",
          "-filter_complex", "[0:v]settb=1/90000,setpts=PTS[a];[1:v]settb=1/90000,setpts=PTS[b];[a][b]concat=n=2:v=1[v]",
          "-map", "[v]", "-fps_mode", "vfr"]
SELECT = ["-f", "lavfi", "-i", f"testsrc=s={W}x{H}:r=30:d=6",
          "-vf", "select='lt(n\\,90)+gte(n\\,90)*not(mod(n-90\\,3))'", "-fps_mode", "vfr"]

VARIANTS = {
    "current": [*CONCAT, *X],
    "concat_bf0": [*CONCAT, *X, "-bf", "0"],
    "concat_timescale90k": [*CONCAT, *X, "-video_track_timescale", "90000"],
    "concat_bf0_timescale90k": [*CONCAT, *X, "-bf", "0", "-video_track_timescale", "90000"],
    "select": [*SELECT, *X],
    "select_bf0": [*SELECT, *X, "-bf", "0"],
    "select_bf0_timescale90k": [*SELECT, *X, "-bf", "0", "-video_track_timescale", "90000"],
}


def info(path):
    import av

    with av.open(str(path)) as c:
        s = c.streams.video[0]
        pk = [p for p in c.demux(s) if p.size]
        discard = sum(1 for p in pk if p.is_discard)
    rate = V.ffprobe_stream(path).get("avg_frame_rate")
    dur = V.container_duration(path)
    header, decoded = V.header_frames(path), len(V.decode_frames(path))
    return {"header": header, "decoded": decoded, "discard": discard, "avg_frame_rate": rate,
            "duration": dur, "ok": header == decoded and discard == 0 and decoded == 120}


def main():
    work = Path(tempfile.mkdtemp())
    out = {"ffmpeg": subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]}
    for name, args in VARIANTS.items():
        path = work / f"{name}.mp4"
        try:
            V._ffmpeg([*args, str(path)])
            out[name] = info(path)
        except Exception as exc:
            out[name] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
        print(name, out[name], flush=True)
    Path(sys.argv[2]).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
