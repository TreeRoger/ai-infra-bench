#!/usr/bin/env python3
"""Curator-only probe (not part of the task): does releasing a stream-backed
cv2.VideoCapture that holds the last reference to its BytesIO crash?

Runs each case in a fresh subprocess, 3 times, PyAV blocked so only OpenCV's
FFmpeg is loaded. Usage: opencv_release_probe.py OUTPUT_JSON
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

CHILD = r'''
import gc, sys
sys.modules["av"] = None
from io import BytesIO
import cv2
from cv2 import videoio_registry as vr
data = open(sys.argv[3], "rb").read()
api = next(b for b in vr.getStreamBufferedBackends() if vr.hasBackend(b))
held, end = sys.argv[1], sys.argv[2]
b = BytesIO(data)
c = cv2.VideoCapture(b, api, [])
assert c.isOpened()
while c.grab():
    pass
if held == "no":
    del b
if end == "release":
    c.release()
elif end == "del":
    del c
gc.collect()
print("ok", flush=True)
'''


def main():
    work = Path(tempfile.mkdtemp())
    clip = work / "clip.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=s=160x120:r=30:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(clip)], check=True)
    child = work / "child.py"
    child.write_text(CHILD)
    import cv2
    out = {"cv2": cv2.__version__, "results": {}}
    for held in ("yes", "no"):
        for end in ("release", "del", "exit"):
            codes = [subprocess.run([sys.executable, "-I", str(child), held, end, str(clip)],
                                    capture_output=True).returncode for _ in range(3)]
            out["results"][f"buffer_held={held} end={end}"] = codes
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
