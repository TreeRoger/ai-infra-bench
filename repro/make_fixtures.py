#!/usr/bin/env python3
"""Generate labeled test videos with the ffmpeg CLI (curator-only evidence).

Each source frame i carries three 16x16 gray blocks in the top-left corner
encoding i in base 16 with levels 40 + 11*digit (40..205), away from the
limited-range clamp, so the index survives lossy coding and YUV->RGB. Usage: make_fixtures.py OUTDIR
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

W, H = 160, 120


def frame(i: int) -> bytes:
    rows, cols = np.indices((H, W))
    img = np.empty((H, W, 3), dtype=np.uint8)
    img[..., 0] = (cols * 2 + i * 3) % 256
    img[..., 1] = (rows * 3 + i * 5) % 256
    img[..., 2] = ((rows + cols) + i * 7) % 256
    img[:20, :60] = 128
    for k, digit in enumerate((i // 256 % 16, i // 16 % 16, i % 16)):
        img[2:18, 2 + 20 * k:18 + 20 * k] = 40 + 11 * digit
    return img.tobytes()


def ffmpeg(args: list[str], stdin: bytes | None = None, stdout=None) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        input=stdin, stdout=stdout, check=True,
    )


def encode(out: Path, n: int, fps: int, gop: int, extra: list[str]) -> None:
    raw = b"".join(frame(i) for i in range(n))
    ffmpeg(
        ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
         "-i", "pipe:0", *extra, "-g", str(gop), "-keyint_min", str(gop),
         "-sc_threshold", "0", "-pix_fmt", "yuv420p", str(out)],
        stdin=raw,
    )


def encode_to_pipe(out: Path, n: int, fps: int, gop: int, codec: list[str], fmt: str) -> None:
    raw = b"".join(frame(i) for i in range(n))
    with out.open("wb") as fh:
        ffmpeg(
            ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
             "-i", "pipe:0", *codec, "-g", str(gop), "-pix_fmt", "yuv420p",
             "-f", fmt, "pipe:1"],
            stdin=raw, stdout=fh,
        )


def trim_copy(src: Path, out: Path, ss: float, t: float) -> None:
    ffmpeg(["-ss", str(ss), "-i", str(src), "-t", str(t), "-c", "copy", str(out)])


def probe(path: Path) -> dict:
    def run(*extra):
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", *extra,
             "-of", "json", str(path)], capture_output=True, text=True,
        )
        return json.loads(r.stdout or "{}")
    hdr = run("-show_entries", "stream=nb_frames,duration,avg_frame_rate,r_frame_rate,start_time:format=duration")
    cnt = run("-count_frames", "-show_entries", "stream=nb_read_frames")
    return {
        "stream": hdr.get("streams", [{}])[0],
        "format_duration": hdr.get("format", {}).get("duration"),
        "decoded_frames": cnt.get("streams", [{}])[0].get("nb_read_frames"),
    }


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    x264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-bf", "2"]
    # Normal reference videos.
    encode(out / "normal_10s_gop60.mp4", 300, 30, 60, x264)
    encode(out / "src_12s_gop250.mp4", 360, 30, 250, x264)
    encode(out / "src_8s_gop48_25fps.mp4", 200, 25, 48, x264)
    # Lossless -c copy trims (edit-list lead-in).
    trim_copy(out / "normal_10s_gop60.mp4", out / "trim_mild_ss2.5_t3.mp4", 2.5, 3)
    trim_copy(out / "src_12s_gop250.mp4", out / "trim_severe_ss7_t2.mp4", 7, 2)
    trim_copy(out / "src_8s_gop48_25fps.mp4", out / "trim_mid_ss3.3_t2.5.mp4", 3.3, 2.5)
    # One-frame lead-in: cut exactly one frame after a keyframe.
    trim_copy(out / "normal_10s_gop60.mp4", out / "trim_one_frame_ss2.0333_t3.mp4", 61 / 30, 3)
    # Header-less containers written to a pipe.
    encode_to_pipe(out / "streamed_vp9.webm", 300, 30, 60,
                   ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30", "-deadline", "realtime"], "webm")
    encode_to_pipe(out / "streamed_h264.mkv", 300, 30, 60, x264, "matroska")
    encode_to_pipe(out / "raw.h264", 300, 30, 60, x264, "h264")
    # Seekable WebM for comparison.
    encode(out / "seekable_vp9.webm", 300, 30, 60,
           ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30", "-deadline", "realtime"])
    facts = {p.name: probe(p) for p in sorted(out.iterdir()) if p.suffix in {".mp4", ".webm", ".mkv", ".h264"}}
    (out / "ffprobe.json").write_text(json.dumps(facts, indent=2))
    for name, f in facts.items():
        s = f["stream"]
        print(f"{name:34s} nb_frames={s.get('nb_frames')!s:6s} dur={s.get('duration')!s:10s} "
              f"start={s.get('start_time')!s:10s} fmt_dur={f['format_duration']!s:10s} decoded={f['decoded_frames']}")


if __name__ == "__main__":
    main()
