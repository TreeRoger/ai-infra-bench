#!/usr/bin/env python3
"""Look for REAL untrimmed files whose header frame count disagrees with decode.

For each file: header counts (cv2 CAP_PROP_FRAME_COUNT, av stream.frames),
decodable frames (sequential decode), upstream OpenCV end-seek probe value, and
PyAV round(duration*fps). Usage: overcorrection_search.py WORKDIR
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import av
import cv2
import numpy as np

W, H = 160, 120


def ff(args, stdin=None):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], input=stdin, check=True)


def raw(n):
    rows, cols = np.indices((H, W))
    out = []
    for i in range(n):
        img = np.empty((H, W, 3), np.uint8)
        img[..., 0] = (cols * 2 + i * 3) % 256
        img[..., 1] = (rows * 3 + i * 5) % 256
        img[..., 2] = ((rows + cols) + i * 7) % 256
        out.append(img.tobytes())
    return b"".join(out)


def src(n, fps):
    return ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0"]


def variants(d: Path):
    x = ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    yield "mp4_bf2", lambda p: ff([*src(300, 30), *x, "-bf", "2", str(p)], raw(300)), ".mp4"
    yield "mp4_bf0", lambda p: ff([*src(300, 30), *x, "-bf", "0", str(p)], raw(300)), ".mp4"
    yield "mp4_2997", lambda p: ff([*src(300, "30000/1001"), *x, str(p)], raw(300)), ".mp4"
    yield "mp4_with_audio", lambda p: ff([*src(300, 30), "-f", "lavfi", "-i", "sine=d=10.3", *x, "-c:a", "aac", "-shortest", str(p)], raw(300)), ".mp4"
    yield "mov_bf2", lambda p: ff([*src(300, 30), *x, str(p)], raw(300)), ".mov"
    yield "mp4_frag", lambda p: ff([*src(300, 30), *x, "-movflags", "frag_keyframe+empty_moov", str(p)], raw(300)), ".mp4"
    yield "mp4_faststart", lambda p: ff([*src(300, 30), *x, "-movflags", "+faststart", str(p)], raw(300)), ".mp4"
    yield "mp4_hevc", lambda p: ff([*src(300, 30), "-c:v", "libx265", "-pix_fmt", "yuv420p", "-x265-params", "log-level=error", str(p)], raw(300)), ".mp4"
    yield "mp4_mpeg4", lambda p: ff([*src(300, 30), "-c:v", "mpeg4", str(p)], raw(300)), ".mp4"
    yield "avi_mpeg4", lambda p: ff([*src(300, 30), "-c:v", "mpeg4", str(p)], raw(300)), ".avi"
    yield "mp4_vfr_dropdup", lambda p: ff([*src(300, 30), "-vf", "mpdecimate", "-fps_mode", "vfr", *x, str(p)], raw(300)), ".mp4"
    # Re-encoded (not stream-copied) trim: ordinary output, no hidden frames.
    def reenc(p):
        tmp = d / "reenc_src.mp4"
        ff([*src(300, 30), *x, str(tmp)], raw(300))
        ff(["-ss", "2.5", "-i", str(tmp), "-t", "3", *x, str(p)])
    yield "mp4_reencoded_trim", reenc, ".mp4"
    # Stream-copy cut that starts exactly on a keyframe (no hidden lead-in).
    def keycut(p):
        tmp = d / "keycut_src.mp4"
        ff([*src(300, 30), *x, "-g", "60", "-keyint_min", "60", "-sc_threshold", "0", str(tmp)], raw(300))
        ff(["-ss", "2.0", "-i", str(tmp), "-t", "3", "-c", "copy", str(p)])
    yield "mp4_copy_cut_on_keyframe", keycut, ".mp4"
    # Remux to a different container with -c copy (no trim).
    def remux_mkv_to_mp4(p):
        tmp = d / "remux_src.mkv"
        ff([*src(300, 30), *x, str(tmp)], raw(300))
        ff(["-i", str(tmp), "-c", "copy", str(p)])
    yield "mp4_remux_from_mkv", remux_mkv_to_mp4, ".mp4"


def measure(path: Path) -> dict:
    data = path.read_bytes()
    cap = cv2.VideoCapture(str(path))
    hdr_cv = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    probe = None
    if cap.set(cv2.CAP_PROP_POS_AVI_RATIO, 1.0):
        probe = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        at_end = not cap.grab()
        probe = (probe, at_end)
    cap.release()
    cap = cv2.VideoCapture(str(path))
    cv_decoded = 0
    while cap.grab():
        cv_decoded += 1
    cap.release()
    with av.open(io.BytesIO(data)) as c:
        s = c.streams.video[0]
        hdr_av = s.frames
        fps = float(s.average_rate) if s.average_rate else 0.0
        dur = float(s.duration * s.time_base) if s.duration else 0.0
        av_decoded = sum(1 for _ in c.decode(video=0))
    return {"cv_header": hdr_cv, "cv_decoded": cv_decoded, "cv_end_seek_probe": probe,
            "av_header": hdr_av, "av_decoded": av_decoded, "av_fps": round(fps, 4),
            "av_duration": round(dur, 4), "av_round_dur_fps": round(dur * fps)}


def main():
    d = Path(sys.argv[1]); d.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, make, ext in variants(d):
        p = d / f"{name}{ext}"
        try:
            make(p)
            results[name] = measure(p)
        except Exception as e:
            results[name] = {"error": f"{type(e).__name__}: {e}"}
        r = results[name]
        flag = ""
        if "error" not in r:
            if r["cv_header"] != r["cv_decoded"] or r["av_header"] != r["av_decoded"]:
                flag += " HEADER!=DECODE"
            if r["cv_end_seek_probe"] and r["cv_end_seek_probe"][0] != r["cv_decoded"]:
                flag += " PROBE!=DECODE"
            if r["av_round_dur_fps"] != r["av_decoded"]:
                flag += " DURxFPS!=DECODE"
        print(f"{name:26s} {r}{flag}", flush=True)
    (d / "overcorrection-search.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
