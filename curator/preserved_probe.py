#!/usr/bin/env python3
"""Curator-only: build the preserved (untrimmed / already-correct) fixtures with
the task's videolab and report, for every candidate preserved pair, whether the
installed vLLM (Base, in the image) loads it correctly against the labels.
Usage: preserved_probe.py TESTS_DIR OUTPUT_JSON
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import cases as C  # noqa: E402
import videolab as V  # noqa: E402

PAIRS = [("opencv", b, c) for b in ("opencv", "pyav") for c in ("8", "all")]
FPS_PAIRS = [("opencv_dynamic", "opencv", "8"), ("qwen3_vl", "pyav", "8")]


def verdict(labels, visible, requested, meta, uniform):
    problems = []
    vis = set(visible)
    hidden = [x for x in labels if x not in vis]
    if hidden:
        problems.append(f"frames not in clip: {hidden[:5]}")
    if any(a >= b for a, b in zip(labels, labels[1:])):
        problems.append(f"repeated/out-of-order ({len(labels)} returned, {len(set(labels))} distinct)")
    if uniform:
        want = len(visible) if requested < 0 else min(requested, len(visible))
        if len(labels) != want:
            problems.append(f"returned {len(labels)}, expected {want}")
    if meta.get("total_num_frames") != len(visible):
        problems.append(f"total_num_frames {meta.get('total_num_frames')} vs plays {len(visible)}")
    if not problems and labels:
        pos = [visible.index(x) for x in labels]
        if [int(i) for i in meta.get("frames_indices", [])] != pos:
            problems.append("frames_indices do not match returned frames")
    return problems


def main():
    from vllm.multimodal.media.connector import MediaConnector

    work = Path(tempfile.mkdtemp())
    scratch = work / "scratch"
    scratch.mkdir()
    out = {"files": {}, "pairs": {}}
    for name in C.NORMAL:
        path = work / f"normal_{name}{C.NORMAL_EXT.get(name, '.mp4')}"
        V.make_normal(name, path, scratch)
        visible = V.visible_labels(path)
        out["files"][name] = {"header": V.header_frames(path), "plays": len(visible),
                              "distinct": len(set(visible)), "labels_head": visible[:6],
                              "labels_tail": visible[-4:]}
        for loader, codec, count in PAIRS + FPS_PAIRS:
            n = -1 if count == "all" else int(count)
            key = f"{name}-{loader}-{codec}-{count}"
            try:
                conn = MediaConnector(media_io_kwargs={"video": {"video_backend": loader, "backend": codec,
                                                                 "num_frames": n}},
                                      allowed_local_media_path=str(work))
                frames, meta = conn.fetch_video(path.as_uri()).media
                labels = [V.read_label(f) for f in frames]
                problems = verdict(labels, visible, n, dict(meta), uniform=loader == "opencv")
            except Exception as exc:
                problems = [f"raised {type(exc).__name__}: {exc}"[:200]]
            out["pairs"][key] = problems
            print(f"{key:48s} {'OK' if not problems else 'BAD ' + '; '.join(problems)}", flush=True)
    Path(sys.argv[2]).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
