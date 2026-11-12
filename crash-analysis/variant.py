import sys, re
from pathlib import Path
root, ocv, pav = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
o = root/"vllm/multimodal/video_decoders/opencv.py"; p = root/"vllm/multimodal/video_decoders/pyav.py"
if ocv == "v1":
    s = o.read_text()
    new_body = '''def _count_decodable_frames(data: bytes) -> int:
    """Number of frames a sequential decode yields (follows the timeline)."""
    counter = OpenCVVideoBackendMixin.open_video_capture(data)
    try:
        count = 0
        while counter.grab():
            count += 1
        return count
    finally:
        counter.release()


class OpenCVVideoBackendMixin:'''
    s2 = re.sub(r"def _count_decodable_frames.*?\nclass OpenCVVideoBackendMixin:", new_body, s, flags=re.S)
    assert s2 != s; o.write_text(s2)
if pav == "v1":
    s = p.read_text()
    old = '''            with av.open(BytesIO(data)) as counter:
                decodable = sum(1 for _ in counter.decode(video=0))
'''
    new = '''            decodable = sum(1 for _ in container.decode(stream))
            container.seek(0, stream=stream)
'''
    assert old in s; p.write_text(s.replace(old, new))
