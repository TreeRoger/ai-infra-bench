#!/usr/bin/env python3
"""Curator-only diagnostic (not part of the task): build every verifier fixture
with the task's own videolab/cases code inside the image and report how each
file is put together. Usage: fixture_probe.py TESTS_DIR OUTPUT_JSON
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import cases as C  # noqa: E402
import videolab as V  # noqa: E402


def ffprobe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=nb_frames,duration,avg_frame_rate,r_frame_rate,start_time:format=duration,start_time",
         "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def pyav(path):
    import av

    with av.open(str(path)) as c:
        s = c.streams.video[0]
        info = {"frames": s.frames, "stream_duration_s": float(s.duration * s.time_base) if s.duration else None,
                "container_duration_s": c.duration / 1e6 if c.duration else None}
        pk = [p for p in c.demux(s) if p.size]
        info["packets"] = len(pk)
        info["discard"] = sum(1 for p in pk if p.is_discard)
        info["discard_positions"] = [i for i, p in enumerate(pk) if p.is_discard][:20]
    with av.open(str(path)) as c:
        info["decoded"] = sum(1 for _ in c.decode(video=0))
    return info


def editlist(path):
    data = Path(path).read_bytes()
    return {"has_elst": b"elst" in data}


def main():
    work = Path(tempfile.mkdtemp())
    media, scratch = work / "media", work / "scratch"
    media.mkdir(); scratch.mkdir()
    files = {}
    sources = {}
    for name, spec in C.SOURCES.items():
        sources[name] = scratch / f"{name}.mp4"
        V.encode_source(sources[name], spec)
    for name, (src, start, length) in C.TRIMS.items():
        files[name] = media / f"trim_{name}.mp4"
        V.copy_trim(sources[src], files[name], start, length)
    parent, start, length = C.DERIVED["trim_of_trim"]
    files["trim_of_trim"] = media / "derived_trim_of_trim.mp4"
    V.copy_trim(files[parent], files["trim_of_trim"], start, length)
    for name in C.NORMAL:
        files[name] = media / f"normal_{name}{C.NORMAL_EXT.get(name, '.mp4')}"
        V.make_normal(name, files[name], scratch)
    out = {"ffmpeg": subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0],
           "files": {}}
    for name, path in files.items():
        rec = {"kind": "normal" if name in C.NORMAL else "trim",
               "header": V.header_frames(path), "decoded_cli": len(V.decode_frames(path)),
               "nominal_fps": V.nominal_fps(path), "ffprobe": ffprobe(path), **editlist(path)}
        try:
            rec["pyav"] = pyav(path)
        except Exception as exc:
            rec["pyav"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
        out["files"][name] = rec
    Path(sys.argv[2]).write_text(json.dumps(out, indent=1))
    for name, r in out["files"].items():
        p = r["pyav"]
        print(f"{name:28s} {r['kind']:6s} header={r['header']:4d} decoded={r['decoded_cli']:4d} "
              f"pyav_frames={p.get('frames')} discard={p.get('discard')} elst={r['has_elst']} "
              f"fmt_dur={r['ffprobe'].get('format', {}).get('duration')} "
              f"{'MISMATCH' if r['kind'] == 'normal' and r['header'] != r['decoded_cli'] else ''}")


if __name__ == "__main__":
    main()
