#!/usr/bin/env python3
"""Curator-only probe, run inside the task image with no network.

Rebuilds the statement's example (12 s, 30 fps recording; `ffmpeg -ss 7 -i
recording.mp4 -t 2 -c copy clip.mp4`) with the image's ffmpeg CLI and loads it
through vLLM's public MediaConnector for both backends. Also reports torchcodec
behavior on the same clip (informational; torchcodec is not scored).
Usage: instruction_probe.py OUTPUT_JSON
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

W, H = 160, 120


def frame(i):
    rows, cols = np.indices((H, W))
    img = np.empty((H, W, 3), dtype=np.uint8)
    img[..., 0] = (cols * 2 + i * 3) % 256
    img[..., 1] = (rows * 3 + i * 5) % 256
    img[..., 2] = ((rows + cols) + i * 7) % 256
    img[:20, :60] = 128
    for k, d in enumerate((i // 256 % 16, i // 16 % 16, i % 16)):
        img[2:18, 2 + 20 * k:18 + 20 * k] = 40 + 11 * d
    return img


def label(f):
    v = 0
    for k in range(3):
        level = float(np.median(f[5:15, 5 + 20 * k:15 + 20 * k]))
        v = v * 16 + min(15, max(0, round((level - 40) / 11)))
    return v


def main():
    out = {}
    work = Path(tempfile.mkdtemp())
    rec, clip = work / "recording.mp4", work / "clip.mp4"
    raw = b"".join(frame(i).tobytes() for i in range(360))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{W}x{H}", "-r", "30", "-i", "pipe:0", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "18", "-threads", "1", "-bf", "2", "-g", "250", "-keyint_min", "250",
                    "-sc_threshold", "0", "-pix_fmt", "yuv420p", str(rec)], input=raw, check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "7", "-i", str(rec), "-t", "2",
                    "-c", "copy", str(clip)], check=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                            "-show_entries", "stream=nb_frames,nb_read_frames,duration",
                            "-of", "json", str(clip)], capture_output=True, text=True, check=True)
    out["ffprobe"] = json.loads(probe.stdout)["streams"][0]
    out["ffmpeg_version"] = subprocess.run(["ffmpeg", "-version"], capture_output=True,
                                           text=True).stdout.splitlines()[0]
    from vllm.multimodal.media.connector import MediaConnector

    for backend in ("opencv", "pyav", "torchcodec"):
        try:
            conn = MediaConnector(media_io_kwargs={"video": {"num_frames": 8, "backend": backend}},
                                  allowed_local_media_path=str(work))
            frames, meta = conn.fetch_video(clip.as_uri()).media
            labels = [label(f) for f in frames]
            out[backend] = {"returned": len(labels), "distinct": len(set(labels)), "labels": labels,
                            "total_num_frames": meta["total_num_frames"],
                            "duration": round(float(meta["duration"]), 3)}
        except Exception as exc:
            out[backend] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    import av

    with av.open(str(clip)) as container:
        stream = container.streams.video[0]
        out["pyav_stream"] = {
            "frames": stream.frames, "time_base": str(stream.time_base),
            "duration": stream.duration, "start_time": stream.start_time,
            "container_duration": container.duration, "average_rate": str(stream.average_rate),
            "ffmpeg_libs": {k: str(v) for k, v in av.library_versions.items()},
        }
        out["pyav_packets"] = [
            [p.pts, p.dts, int(p.is_keyframe), int(p.is_discard), p.size]
            for p in container.demux(stream) if p.size
        ]
    with av.open(str(clip)) as container:
        out["pyav_decoded_pts"] = [f.pts for f in container.decode(video=0)]
    for n in (8, 16, -1):
        try:
            conn = MediaConnector(media_io_kwargs={"video": {"num_frames": n, "backend": "pyav"}},
                                  allowed_local_media_path=str(work))
            frames, meta = conn.fetch_video(clip.as_uri()).media
            out[f"pyav_num_frames_{n}"] = {"labels": [label(f) for f in frames],
                                           "frames_indices": [int(i) for i in meta["frames_indices"]]}
        except Exception as exc:
            out[f"pyav_num_frames_{n}"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
