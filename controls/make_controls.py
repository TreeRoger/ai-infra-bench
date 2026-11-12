#!/usr/bin/env python3
"""Generate the reference fix and control patches against Base (curator-only).

Usage: make_controls.py SCRATCH_WORKTREE TASK_DIR
SCRATCH_WORKTREE must be a clean vLLM worktree at Base.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

WT = Path(sys.argv[1])
TASK = Path(sys.argv[2])
BASE = "11baa0ebd88480b0a3e30138e4ee189420cd33be"
OPENCV = "vllm/multimodal/video_decoders/opencv.py"
PYAV = "vllm/multimodal/video_decoders/pyav.py"
UPSTREAM_48608 = Path.home() / "infrabench-work/vllm"


def git(*args, capture=False):
    return subprocess.run(["git", "-C", str(WT), *args], check=True, text=True,
                          capture_output=capture).stdout


def reset():
    git("reset", "-q", "--hard", BASE)
    git("clean", "-qfd")


def edit(rel, old, new):
    path = WT / rel
    text = path.read_text()
    assert text.count(old) == 1, (rel, old[:60])
    path.write_text(text.replace(old, new))


def apply_patch(patch_text):
    subprocess.run(["git", "-C", str(WT), "apply", "-"], input=patch_text, text=True, check=True)


def diff():
    return git("diff", "--binary", "--full-index", "--no-color", capture=True)


# ---------------------------------------------------------------- reference fix
OPENCV_PROBE_OLD = '''        total_frames_num = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        original_fps = cap.get(cv2.CAP_PROP_FPS)
        duration = total_frames_num / original_fps if original_fps > 0 else 0
'''
# Upstream #48608 (9b2aef512) end-of-stream seek probe; the condition
# `< total_frames_num` (instead of upstream's `< total_frames_num - 1`) and the
# last comment sentence are the curator's G1 repair.
OPENCV_PROBE_NEW = '''        total_frames_num = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        original_fps = cap.get(cv2.CAP_PROP_FPS)
        # CAP_PROP_FRAME_COUNT counts every physical sample in the container,
        # overstating the presentable frames when an mp4 edit list hides the
        # decode lead-in (e.g. a lossless `ffmpeg -ss ... -c copy` trim).
        # Cross-check with an end-of-stream seek: the FFMPEG backend reports
        # the resulting position against the edit-list-aware timeline, which
        # exposes the true frame count without decoding anything. The seek
        # may land mid-stream on corrupt files, so only trust it when the
        # stream really ends there. Even a single hidden lead-in frame (a cut
        # one frame after a keyframe) leaves the last sample unreadable, so
        # any shortfall confirmed at the real stream end is corrected.
        if total_frames_num > 0 and cap.set(cv2.CAP_PROP_POS_AVI_RATIO, 1.0):
            visible_frames = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            at_stream_end = not cap.grab()
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            if at_stream_end and 0 < visible_frames < total_frames_num:
                logger.warning(
                    "Video header claims %d frames but only %d are "
                    "presentable; sampling over the true frame count.",
                    total_frames_num,
                    visible_frames,
                )
                total_frames_num = visible_frames
        duration = total_frames_num / original_fps if original_fps > 0 else 0
'''
PYAV_META_OLD = '''        if total_frames == 0 and duration > 0 and fps > 0:
            total_frames = int(duration * fps)
        return VideoSourceMetadata(total_frames, fps, duration)
'''
# Curator's G2 repair (replaces upstream's round(duration * fps) estimate).
PYAV_META_NEW = '''        if total_frames == 0 and duration > 0 and fps > 0:
            total_frames = int(duration * fps)
        elif total_frames > 0:
            # ``stream.frames`` counts every physical sample, including the
            # decode lead-in that an mp4 edit list hides after a lossless
            # ``ffmpeg -ss ... -c copy`` trim. The demuxer flags those
            # samples as discardable, so count the presentable ones without
            # decoding anything and sample over that timeline instead.
            presentable = PyAVVideoBackendMixin._count_presentable_packets(
                container, stream
            )
            if 0 < presentable < total_frames:
                total_frames = presentable
        return VideoSourceMetadata(total_frames, fps, duration)

    @staticmethod
    def _count_presentable_packets(
        container: "av.container.InputContainer",
        stream: "av.video.stream.VideoStream",
    ) -> int:
        count = 0
        for packet in container.demux(stream):
            if packet.size and not packet.is_discard:
                count += 1
        container.seek(0, stream=stream)
        return count
'''


def oracle_opencv():
    edit(OPENCV, OPENCV_PROBE_OLD, OPENCV_PROBE_NEW)


def oracle_pyav():
    edit(PYAV, PYAV_META_OLD, PYAV_META_NEW)


def oracle():
    oracle_opencv()
    oracle_pyav()


# ---------------------------------------------------------------- controls
def alternative_decode_count():
    """Count by sequential decode, at the decode entry points (not metadata)."""
    edit(OPENCV, '''    source = loader_cls._prepare_source(OpenCVVideoBackendMixin.get_video_metadata(cap))
''', '''    metadata = OpenCVVideoBackendMixin.get_video_metadata(cap)
    if metadata.total_frames_num > 0:
        decodable = _count_decodable_frames(data)
        if 0 < decodable < metadata.total_frames_num:
            fps = metadata.original_fps
            metadata = VideoSourceMetadata(
                total_frames_num=decodable,
                original_fps=fps,
                duration=decodable / fps if fps > 0 else 0,
            )
    source = loader_cls._prepare_source(metadata)
''')
    edit(OPENCV, '''class OpenCVVideoBackendMixin:
''', '''def _count_decodable_frames(data: bytes) -> int:
    """Number of frames a sequential decode yields (follows the timeline)."""
    # The stream buffer must outlive the capture: OpenCV's Python stream
    # binding does not own it.
    buffer = BytesIO(data)
    counter = cv2.VideoCapture(
        buffer, OpenCVVideoBackendMixin.get_cv2_video_api(), []
    )
    try:
        count = 0
        while counter.grab():
            count += 1
        return count
    finally:
        counter.release()
        del buffer


class OpenCVVideoBackendMixin:
''')
    edit(PYAV, '''        source = loader_cls._prepare_source(
            PyAVVideoBackendMixin.get_metadata(container)
        )
''', '''        metadata = PyAVVideoBackendMixin.get_metadata(container)
        if metadata.total_frames_num > 0:
            with av.open(BytesIO(data)) as counter:
                decodable = sum(1 for _ in counter.decode(video=0))
            if 0 < decodable < metadata.total_frames_num:
                metadata = VideoSourceMetadata(
                    decodable, metadata.original_fps, metadata.duration
                )
        source = loader_cls._prepare_source(metadata)
''')


def upstream_48608():
    patch = subprocess.run(["git", "-C", str(UPSTREAM_48608), "show", "9b2aef512", "--", "vllm/"],
                           check=True, text=True, capture_output=True).stdout
    apply_patch(patch)


def dedupe_repeated_frames():
    """Symptom patch: drop repeated PyAV frames after decoding."""
    edit(PYAV, '''            if chosen is not None:
                frames_list.append(chosen.to_ndarray(format="rgb24"))
                valid_indices.append(idx)
''', '''            if chosen is not None and chosen.pts not in seen_pts:
                seen_pts.add(chosen.pts)
                frames_list.append(chosen.to_ndarray(format="rgb24"))
                valid_indices.append(idx)
''')
    edit(PYAV, '''        decoder = None
        last_pts = None
''', '''        decoder = None
        last_pts = None
        seen_pts: set[int] = set()
''')


def clamp_to_last_presentable():
    """Keep header-count sampling, clamp targets onto the last playable frame."""
    oracle()
    edit(OPENCV, '''            if at_stream_end and 0 < visible_frames < total_frames_num:
                logger.warning(
                    "Video header claims %d frames but only %d are "
                    "presentable; sampling over the true frame count.",
                    total_frames_num,
                    visible_frames,
                )
                total_frames_num = visible_frames
''', '''            if at_stream_end and 0 < visible_frames < total_frames_num:
                cap.vllm_last_presentable = visible_frames - 1
''')
    edit(OPENCV, '''    frame_idx = loader_cls.compute_frames_index_to_sample(
        source=source, target=target, **sampling_kwargs
    )
''', '''    frame_idx = loader_cls.compute_frames_index_to_sample(
        source=source, target=target, **sampling_kwargs
    )
    last = getattr(cap, "vllm_last_presentable", None)
    if last is not None:
        frame_idx = [min(i, last) for i in frame_idx]
''')
    edit(OPENCV, '''    def get_video_metadata(cap: "cv2.VideoCapture") -> VideoSourceMetadata:''',
         '''    def get_video_metadata(cap) -> VideoSourceMetadata:''')
    edit(OPENCV, '''        cap = cv2.VideoCapture(BytesIO(data), backend, [])
        if not cap.isOpened():
            raise ValueError("Could not open video stream")
        return cap
''', '''        cap = cv2.VideoCapture(BytesIO(data), backend, [])
        if not cap.isOpened():
            raise ValueError("Could not open video stream")
        return _Capture(cap)
''')
    edit(OPENCV, '''class OpenCVVideoBackendMixin:
''', '''class _Capture:
    """VideoCapture proxy that can carry an attribute."""

    def __init__(self, cap):
        self._cap = cap
        self.vllm_last_presentable = None

    def __getattr__(self, name):
        return getattr(self._cap, name)


class OpenCVVideoBackendMixin:
''')
    edit(PYAV, '''            if 0 < presentable < total_frames:
                total_frames = presentable
''', '''            if 0 < presentable < total_frames:
                PyAVVideoBackendMixin.last_presentable = presentable - 1
''')
    edit(PYAV, '''        frame_idx = loader_cls.compute_frames_index_to_sample(
            source=source, target=target, **sampling_kwargs
        )
''', '''        PyAVVideoBackendMixin.last_presentable = None
        source = loader_cls._prepare_source(
            PyAVVideoBackendMixin.get_metadata(container)
        )
        frame_idx = loader_cls.compute_frames_index_to_sample(
            source=source, target=target, **sampling_kwargs
        )
        last = PyAVVideoBackendMixin.last_presentable
        if last is not None:
            frame_idx = [min(i, last) for i in frame_idx]
''')


def hidden_lead_in_frames():
    """Decode the physical stream instead of the trimmed timeline."""
    edit(OPENCV, '''        backend = cls.get_cv2_video_api()
        cap = cv2.VideoCapture(BytesIO(data), backend, [])
''', '''        import os

        backend = cls.get_cv2_video_api()
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "ignore_editlist;1"
        cap = cv2.VideoCapture(BytesIO(data), backend, [])
''')
    edit(PYAV, '''    with av.open(BytesIO(data)) as container:
''', '''    with av.open(BytesIO(data), options={"ignore_editlist": "1"}) as container:
''')


def special_case_example():
    """Hard-codes the clip from the task statement (272-frame header, 30 fps)."""
    edit(OPENCV, '''        duration = total_frames_num / original_fps if original_fps > 0 else 0
        return VideoSourceMetadata(''', '''        if total_frames_num == 272 and round(original_fps) == 30:
            total_frames_num = 62
        duration = total_frames_num / original_fps if original_fps > 0 else 0
        return VideoSourceMetadata(''')
    edit(PYAV, '''        if total_frames == 0 and duration > 0 and fps > 0:
            total_frames = int(duration * fps)
        return VideoSourceMetadata''', '''        if total_frames == 0 and duration > 0 and fps > 0:
            total_frames = int(duration * fps)
        if total_frames == 272 and round(fps) == 30:
            total_frames = 62
        return VideoSourceMetadata''')


def opencv_counts_with_pyav():
    """Correct counts everywhere, but the OpenCV path now requires PyAV."""
    oracle_pyav()
    edit(OPENCV, '''    source = loader_cls._prepare_source(OpenCVVideoBackendMixin.get_video_metadata(cap))
''', '''    import av

    metadata = OpenCVVideoBackendMixin.get_video_metadata(cap)
    with av.open(BytesIO(data)) as container:
        stream = container.streams.video[0]
        presentable = sum(
            1 for p in container.demux(stream) if p.size and not p.is_discard
        )
    if 0 < presentable < metadata.total_frames_num:
        fps = metadata.original_fps
        metadata = VideoSourceMetadata(
            presentable, fps, presentable / fps if fps > 0 else 0
        )
    source = loader_cls._prepare_source(metadata)
''')


VIDEO_PY = "vllm/multimodal/video.py"
IMPORT_ANCHOR = '''VIDEO_LOADER_REGISTRY = VideoLoaderRegistry()
'''


def systemexit_zero():
    edit(VIDEO_PY, IMPORT_ANCHOR, IMPORT_ANCHOR + "raise SystemExit(0)\n")


def os_exit_zero():
    edit(VIDEO_PY, IMPORT_ANCHOR, IMPORT_ANCHOR + "__import__('os')._exit(0)\n")


def forged_report():
    """At import, write a passing reward/JUnit report, then keep Base behavior."""
    edit(VIDEO_PY, IMPORT_ANCHOR, IMPORT_ANCHOR + '''

def _forge_success_report():
    import glob
    import os

    names = []
    try:
        import cases

        names = sorted(cases.expected_test_names())
    except Exception:
        pass
    cases_xml = "".join(f'<testcase classname="t" name="{n}"/>' for n in names)
    junit = (
        f'<testsuites><testsuite name="pytest" tests="{len(names)}" '
        f'failures="0" errors="0" skipped="0">{cases_xml}</testsuite></testsuites>'
    )
    targets = ["/logs/verifier", *glob.glob("/tmp/trimmed-video-verifier.*")]
    for directory in targets:
        for name, body in (("reward.txt", "1\\n"), ("junit.xml", junit),
                           ("reward.json", '{"reward":1}\\n')):
            try:
                with open(os.path.join(directory, name), "w") as handle:
                    handle.write(body)
            except OSError:
                pass


_forge_success_report()
''')


OPENCV_DECODE_ENTRY = '''    cap = OpenCVVideoBackendMixin.open_video_capture(data)
    check_frame_pixel_limit(
'''


def segfault_mid_run():
    """Correct oracle logic, but the process dies with SIGSEGV after a few loads."""
    edit(OPENCV, OPENCV_DECODE_ENTRY, '''    _CALLS.append(None)
    if len(_CALLS) == 5:
        import os
        import signal

        os.kill(os.getpid(), signal.SIGSEGV)
''' + OPENCV_DECODE_ENTRY)
    edit(OPENCV, '''logger = init_logger(__name__)
''', '''logger = init_logger(__name__)
_CALLS: list = []
''')


def segfault_at_exit():
    """Correct oracle logic; every load succeeds, then SIGSEGV at shutdown."""
    edit(VIDEO_PY, IMPORT_ANCHOR, IMPORT_ANCHOR + '''

def _crash_at_shutdown():
    import os
    import signal

    os.kill(os.getpid(), signal.SIGSEGV)


__import__("atexit").register(_crash_at_shutdown)
''')


PYAV_DECODE_FRAMES_BODY = '''        """Decode target frames via per-frame seek + forward decode to PTS."""
        stream = container.streams.video[0]
        # SLICE parallelizes within a single frame without the
        # one-frame-per-thread latency penalty of FRAME threading.
        stream.thread_type = "SLICE"
        time_base = stream.time_base

        frames_list: list[npt.NDArray] = []
        valid_indices: list[int] = []
        frame_interval = 1.0 / fps if fps > 0 else 0.1
        max_ts = max(0.0, duration - frame_interval) if duration > 0 else float("inf")

        decoder = None
        last_pts = None
        for idx in frame_indices:
            ts = min(idx / fps, max_ts) if fps > 0 else 0.0
            pts = int(ts / time_base)
            # seek() snaps backward to a keyframe; reuse the running decoder
            # while targets advance monotonically to avoid re-decoding the
            # GOP prefix once per requested frame.
            if decoder is None or last_pts is None or pts <= last_pts:
                container.seek(pts, stream=stream)
                decoder = container.decode(video=0)
            chosen = None
            for frame in decoder:
                if frame.pts is not None and frame.pts >= pts:
                    chosen = frame
                    last_pts = frame.pts
                    break
            if chosen is not None:
                frames_list.append(chosen.to_ndarray(format="rgb24"))
                valid_indices.append(idx)
            else:
                decoder = None
'''


def pyav_nth_frame():
    """Oracle metadata, but PyAV maps index n to the n-th presented frame by decoding
    sequentially instead of seeking by index / fps."""
    edit(PYAV, PYAV_DECODE_FRAMES_BODY, '''        """Decode sequentially; index n is the n-th frame the clip presents."""
        stream = container.streams.video[0]
        stream.thread_type = "SLICE"
        container.seek(0, stream=stream)

        wanted = set(frame_indices)
        last_wanted = max(frame_indices, default=-1)
        decoded: dict[int, npt.NDArray] = {}
        for position, frame in enumerate(container.decode(video=0)):
            if position in wanted:
                decoded[position] = frame.to_ndarray(format="rgb24")
            if position >= last_wanted:
                break
        valid_indices = [idx for idx in frame_indices if idx in decoded]
        frames_list = [decoded[idx] for idx in valid_indices]
''')


def pyav_via_opencv():
    """Oracle, but backend="pyav" requests are quietly decoded by the OpenCV path
    (the OpenCV-only fix applied to both backends); PyAV is never opened."""
    edit(PYAV, '''    with av.open(BytesIO(data)) as container:
        stream = container.streams.video[0]
        check_frame_pixel_limit(stream.width, stream.height)
        source = loader_cls._prepare_source(
            PyAVVideoBackendMixin.get_metadata(container)
        )
        frame_idx = loader_cls.compute_frames_index_to_sample(
            source=source, target=target, **sampling_kwargs
        )
        frames, valid = PyAVVideoBackendMixin.decode_frames(
            container, frame_idx, source.original_fps, source.duration
        )
    return frames, source, frame_idx, valid
''', '''    from .opencv import decode_opencv

    return decode_opencv(loader_cls, data, target, sampling_kwargs)
''')


def stale_duration():
    """Oracle frames and counts, but OpenCV keeps the header-derived duration."""
    edit(OPENCV, '''        original_fps = cap.get(cv2.CAP_PROP_FPS)
''', '''        original_fps = cap.get(cv2.CAP_PROP_FPS)
        header_frames_num = total_frames_num
''')
    edit(OPENCV, '''        duration = total_frames_num / original_fps if original_fps > 0 else 0
        return VideoSourceMetadata(''', '''        duration = header_frames_num / original_fps if original_fps > 0 else 0
        return VideoSourceMetadata(''')


def skip_all_conftest():
    (WT / "conftest.py").write_text(
        "import pytest\n\n\ndef pytest_collection_modifyitems(config, items):\n"
        "    for item in items:\n        item.add_marker(pytest.mark.skip(reason='skipped'))\n"
    )
    git("add", "-N", "conftest.py")


CONTROLS = [
    # name, builder, expected reward, apply_after
    ("alternative-decode-count", alternative_decode_count, 1, None),
    ("alternative-pyav-nth-frame", pyav_nth_frame, 1, "oracle"),
    ("upstream-48608-as-merged", upstream_48608, 0, None),
    ("oracle-opencv-only", oracle_opencv, 0, None),
    ("oracle-pyav-only", oracle_pyav, 0, None),
    ("dedupe-repeated-frames", dedupe_repeated_frames, 0, None),
    ("clamp-to-last-presentable", clamp_to_last_presentable, 0, None),
    ("hidden-lead-in-frames", hidden_lead_in_frames, 0, None),
    ("special-case-statement-example", special_case_example, 0, None),
    ("opencv-counts-with-pyav", opencv_counts_with_pyav, 0, None),
    ("skip-all-conftest", skip_all_conftest, 0, None),
    ("forged-success-report", forged_report, 0, None),
    ("oracle-systemexit-zero", systemexit_zero, 0, "oracle"),
    ("oracle-os-exit-zero", os_exit_zero, 0, "oracle"),
    ("oracle-segfault-mid-run", segfault_mid_run, 0, "oracle"),
    ("oracle-segfault-at-exit", segfault_at_exit, 0, "oracle"),
    ("oracle-stale-duration", stale_duration, 0, "oracle"),
    ("oracle-pyav-via-opencv", pyav_via_opencv, 0, "oracle"),
]


def main():
    import hashlib
    import json

    patches = TASK / "validation" / "patches"
    patches.mkdir(parents=True, exist_ok=True)
    reset()
    oracle()
    (TASK / "solution" / "oracle.patch").write_text(diff())
    cases = []
    for name, builder, reward, after in CONTROLS:
        reset()
        if after == "oracle":
            oracle()
            git("add", "-A")
        builder()
        text = diff()
        assert text.strip(), name
        path = patches / f"{name}.patch"
        path.write_text(text)
        case = {"expected_reward": reward, "name": name, "patch": f"patches/{name}.patch",
                "patch_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        if after:
            case["apply_after"] = after
        cases.append(case)
        print(f"{name:34s} reward={reward} {len(text.splitlines())} lines")
    reset()
    manifest = {"cases": cases, "schema_version": "ai_infra_bench_validation_cases.v2"}
    (TASK / "validation" / "ci-cases.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
