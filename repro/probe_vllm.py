#!/usr/bin/env python3
"""Load fixtures through vLLM's public VideoMediaIO path and decode frame labels.

Usage: probe_vllm.py FIXTURE_DIR OUT_JSON [--loaders opencv,...] [--recovery]
The vllm imported is whatever is first on sys.path (PYTHONPATH selects the tree).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import numpy as np

import vllm
from vllm.multimodal.media.image import ImageMediaIO
from vllm.multimodal.media.video import VideoMediaIO


def label(frame: np.ndarray) -> int:
    value = 0
    for k in range(3):
        level = float(np.median(frame[5:15, 5 + 20 * k:15 + 20 * k]))
        value = value * 16 + min(15, max(0, round((level - 40) / 11)))
    return value


def run(path: Path, loader: str, backend: str, num_frames: int, recovery: bool) -> dict:
    kwargs = {"video_backend": loader}
    if loader in ("opencv",):
        kwargs["backend"] = backend
    if recovery:
        kwargs["frame_recovery"] = True
    io = VideoMediaIO(ImageMediaIO(), num_frames=num_frames, **kwargs)
    try:
        media = io.load_bytes(path.read_bytes())
        frames, meta = media.media
    except Exception as exc:  # report, don't crash the sweep
        return {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    labels = [label(f) for f in frames]
    return {
        "n_frames": int(frames.shape[0]),
        "labels": labels,
        "distinct": len(set(labels)),
        "total_num_frames": meta.get("total_num_frames"),
        "fps": round(float(meta.get("fps") or 0), 3),
        "duration": round(float(meta.get("duration") or 0), 3),
        "frames_indices": list(meta.get("frames_indices", [])),
        "video_backend": meta.get("video_backend"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixtures")
    ap.add_argument("out")
    ap.add_argument("--recovery", action="store_true")
    ap.add_argument("--counts", default="8,-1")
    ap.add_argument("--combos", default="opencv:opencv,opencv:pyav,opencv:torchcodec,opencv_dynamic:opencv,qwen2_vl:opencv")
    args = ap.parse_args()
    results = {"vllm_file": vllm.__file__, "recovery": args.recovery, "runs": []}
    for path in sorted(Path(args.fixtures).glob("*")):
        if path.suffix not in {".mp4", ".webm", ".mkv", ".h264"} or path.name.startswith("src_"):
            continue
        for combo in args.combos.split(","):
            loader, backend = combo.split(":")
            for n in map(int, args.counts.split(",")):
                r = run(path, loader, backend, n, args.recovery)
                r.update(file=path.name, loader=loader, backend=backend, num_frames=n)
                results["runs"].append(r)
                short = {k: r.get(k) for k in ("n_frames", "distinct", "total_num_frames", "duration", "error")}
                labels = r.get("labels", [])
                shown = labels if len(labels) <= 10 else labels[:3] + ["..."] + labels[-3:]
                print(f"{path.name:32s} {loader:15s} {backend:10s} n={n:3d} {short} labels={shown}", flush=True)
    Path(args.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
