#!/usr/bin/env python3
"""Curator-only: look for a realistic preserved fixture that tells the two
decoders apart behaviorally (Base OpenCV cannot load it, Base PyAV loads it
fully correctly), or, failing that, one whose OpenCV and PyAV frames differ.
Usage: backend_fixture_probe.py TESTS_DIR OUTPUT_JSON
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, sys.argv[1])
import videolab as V  # noqa: E402

N = 300


def raw():
    return b"".join(V.label_frame(i).tobytes() for i in range(N))


def src():
    return ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{V.W}x{V.H}", "-r", "30", "-i", "pipe:0"]


X264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-threads", "1"]
CANDIDATES = {
    # behavioral: codecs/containers commonly produced today
    "mp4_av1_svt": ["-c:v", "libsvtav1", "-preset", "8", "-crf", "20", "-g", "60", "-pix_fmt", "yuv420p"],
    "mp4_av1_aom": ["-c:v", "libaom-av1", "-cpu-used", "8", "-crf", "20", "-g", "60", "-pix_fmt", "yuv420p"],
    "webm_av1_svt": ["-c:v", "libsvtav1", "-preset", "8", "-crf", "20", "-g", "60", "-pix_fmt", "yuv420p"],
    "webm_vp9": ["-c:v", "libvpx-vp9", "-crf", "20", "-b:v", "0", "-g", "60", "-pix_fmt", "yuv420p"],
    "mp4_vp9": ["-c:v", "libvpx-vp9", "-crf", "20", "-b:v", "0", "-g", "60", "-pix_fmt", "yuv420p"],
    "mov_prores": ["-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le"],
    # pixel-difference fallbacks
    "mp4_h264_fullrange": [*X264, "-pix_fmt", "yuvj420p"],
    "mp4_h264_bt709": [*X264, "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
                       "-color_trc", "bt709"],
    "mp4_h264_yuv444": [*X264, "-pix_fmt", "yuv444p"],
    "mp4_h264_10bit": [*X264, "-pix_fmt", "yuv420p10le"],
    "mp4_hevc_10bit": ["-c:v", "libx265", "-crf", "14", "-pix_fmt", "yuv420p10le",
                       "-x265-params", "log-level=error:pools=1:frame-threads=1"],
}


def load(path, root, backend, n):
    from vllm.multimodal.media.connector import MediaConnector
    conn = MediaConnector(media_io_kwargs={"video": {"video_backend": "opencv", "backend": backend,
                                                     "num_frames": n}},
                          allowed_local_media_path=str(root))
    frames, meta = conn.fetch_video(path.as_uri()).media
    return np.asarray(frames), dict(meta)


def verdict(frames, meta, visible, n):
    labels = [V.read_label(f) for f in frames]
    p = []
    if any(x not in set(visible) for x in labels):
        p.append("frames not in clip")
    if any(a >= b for a, b in zip(labels, labels[1:])):
        p.append(f"repeats ({len(labels)} returned, {len(set(labels))} distinct)")
    want = len(visible) if n < 0 else min(n, len(visible))
    if len(labels) != want:
        p.append(f"returned {len(labels)}, expected {want}")
    if meta.get("total_num_frames") != len(visible):
        p.append(f"total {meta.get('total_num_frames')} vs plays {len(visible)}")
    if not p and [int(i) for i in meta["frames_indices"]] != [visible.index(x) for x in labels]:
        p.append("frames_indices do not name returned frames")
    return p


def main():
    work = Path(tempfile.mkdtemp())
    out = {"ffmpeg": subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]}
    try:
        import av
        import cv2
        out["av"], out["cv2"] = av.__version__, cv2.__version__
    except Exception as exc:  # noqa: BLE001
        out["import_error"] = str(exc)
    for name, args in CANDIDATES.items():
        ext = "." + name.split("_")[0]
        path = work / f"{name}{ext}"
        rec = {}
        try:
            V._ffmpeg([*src(), *args, str(path)], raw())
        except Exception as exc:  # noqa: BLE001
            rec["build_error"] = str(exc)[-300:]
            out[name] = rec
            print(f"{name:22s} BUILD FAILED", flush=True)
            continue
        try:
            visible = V.visible_labels(path)
            rec.update(header=V.header_frames(path), plays=len(visible), distinct=len(set(visible)),
                       stream=V.ffprobe_stream(path))
        except Exception as exc:  # noqa: BLE001
            rec["ground_truth_error"] = str(exc)[-300:]
            out[name] = rec
            print(f"{name:22s} GROUND TRUTH FAILED", flush=True)
            continue
        results = {}
        for backend in ("opencv", "pyav"):
            for n in (8, -1):
                key = f"{backend}-{n}"
                try:
                    frames, meta = load(path, work, backend, n)
                    results[key] = {"frames": frames, "meta": meta,
                                    "problems": verdict(frames, meta, visible, n) if len(frames) else ["no frames"]}
                except Exception as exc:  # noqa: BLE001
                    results[key] = {"raised": f"{type(exc).__name__}: {exc}"[:300]}
        for key, r in results.items():
            rec[key] = {k: v for k, v in r.items() if k != "frames"}
            if "meta" in rec[key]:
                rec[key]["meta"] = {k: (v if k != "frames_indices" else [int(i) for i in v][:12])
                                    for k, v in r["meta"].items()}
        for n in (8, -1):
            a, b = results[f"opencv-{n}"], results[f"pyav-{n}"]
            if "frames" in a and "frames" in b:
                fa, fb = a["frames"], b["frames"]
                same_shape = fa.shape == fb.shape
                rec[f"identical-{n}"] = bool(same_shape and np.array_equal(fa, fb))
                if same_shape and fa.size:
                    rec[f"max_abs_diff-{n}"] = int(np.abs(fa.astype(int) - fb.astype(int)).max())
        cv_fails = all("raised" in results[f"opencv-{n}"] or results[f"opencv-{n}"].get("problems") == ["no frames"]
                       for n in (8, -1))
        pyav_ok = all("problems" in results[f"pyav-{n}"] and not results[f"pyav-{n}"]["problems"]
                      for n in (8, -1))
        rec["opencv_cannot_load"], rec["pyav_correct"] = cv_fails, pyav_ok
        out[name] = rec
        print(f"{name:22s} header={rec['header']} plays={rec['plays']} opencv_cannot_load={cv_fails} "
              f"pyav_correct={pyav_ok} identical8={rec.get('identical-8')} identical_all={rec.get('identical--1')} "
              f"maxdiff={rec.get('max_abs_diff--1')} | cv8={results['opencv-8'].get('raised') or results['opencv-8'].get('problems')} "
              f"pyav8={results['pyav-8'].get('raised') or results['pyav-8'].get('problems')} "
              f"pyav-1={results['pyav--1'].get('raised') or results['pyav--1'].get('problems')}", flush=True)
    Path(sys.argv[2]).write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
