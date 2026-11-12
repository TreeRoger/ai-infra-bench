# Upstream findings — vllm-video-container-frame-count

Search date: 2026-11-08. vLLM main inspected: 3b33a845c6733a50aafae933c10ac0be0f18be93.
Base: 11baa0ebd88480b0a3e30138e4ee189420cd33be (2026-08-20T03:52:42Z, parent of 9b2aef512).
Proposed Oracle source: 9b2aef512 (#48608) [+ 3f1b04e04 (#61759) for scope B], with repairs below.

Reproduction environment (LOCAL, NOT HARBOR): macOS arm64 (Apple M4), Python 3.12.13,
vLLM Base editable (VLLM_TARGET_DEVICE=empty, no native build), opencv-python-headless 5.0.0.93,
av 18.1.0, torch 2.13.0 (deps resolved with --exclude-newer Base timestamp), ffmpeg CLI 9.0.2 (Homebrew).
Entry: VideoMediaIO(ImageMediaIO(), num_frames=N, video_backend=<loader>, backend=<codec>).load_bytes.
Logs: repro/base-results.log, repro/fix-both-results.log, repro/base-recovery-results.log, repro/fixtures/ffprobe.json.

Queries: gh search issues/PRs (incl. closed/unmerged) for: edit list, c copy trim, duplicate/repeated last frame,
CAP_PROP_FRAME_COUNT, stream.frames, total_num_frames negative, webm, mkv, raw h264, variable frame rate,
frame count wrong, torchcodec approximate, presentable frames (raw hits: research/searches.txt).
`git log 11baa0ebd..origin/main -- vllm/multimodal/video_decoders/ vllm/multimodal/video.py vllm/multimodal/media/video.py`.
Limitations: GitHub search is keyword-based and noisy; "no report found" != no bug. torchcodec could not be
exercised locally (libtorchcodec rejects Homebrew ffmpeg 9); deferred to the amd64 image.

| Finding and source | Base and scope applicability | Oracle evidence | Disposition and coverage |
| --- | --- | --- | --- |
| F1 #48608 (merged 2026-08-20): MP4 edit-list trims overstate frame count; OpenCV drops samples past visible end, PyAV duplicates last frame | Reachable at Base via `ffmpeg -ss X -i in -t Y -c copy`. Base: mild trim (107 hdr/92 vis) OpenCV 7/8, severe (272/62) OpenCV 2/8, PyAV 8 returned/3 distinct; 25fps trim (99/64) both backends 5/8 | Upstream applied: all multi-frame-lead-in trims return 8 distinct visible frames on both backends | Core requirement; verifier cases over GOP/cut/fps/num_frames |
| F2 #48608 PR description describes a different design (resample after truncated read) than merged code (seek-to-end probe, rewritten by maintainer commit 2a78502) | Informational | n/a | Oracle = merged code + repairs; no structure required by grader |
| F3 GAP: OpenCV one-frame lead-in trim (hdr 93/vis 92) not corrected (upstream `< total-1` tolerance) | Reachable at Base (cut one frame after keyframe). Base and upstream: OpenCV 7/8 at n=8, last sample missing | Upstream FAILS | Repair Oracle; include case. Need evidence that removing tolerance does not over-correct normal files (open, Phase 5) |
| F4 GAP: PyAV `round(duration*fps)` overestimates trimmed clips (94 vs 92; 64 vs 62) | Reachable; with num_frames=-1 upstream returns 2 duplicate last frames | Upstream FAILS at n=-1 | Repair Oracle (count presentable frames); include n=-1 / large-n cases; grader tolerant on exact count but rejects duplicates |
| F5 #60518 (closed) / #61759 (merged 2026-10-18): streamed WebM/MKV and raw H.264 report negative CAP_PROP_FRAME_COUNT; OpenCV returns 1 frame, Qwen/dynamic loaders raise | Reachable at Base (reproduced: 1 frame, total=-2.77e17; qwen2_vl RuntimeError; opencv_dynamic ValueError) | Upstream applied: 300/300 frames, 8 distinct at n=8 | Scope B only |
| F6 #60534 (closed, unmerged): alternative fix by decode-count + reopen | Same trigger as F5 | Not merged; superseded by #61759 | Basis for "decode-count" correct-alternative control |
| F7 GAP: PyAV reports 0 frames/0 duration for ALL Matroska/WebM (even seekable; `stream.duration` None, only container.duration set) → 1 frame | Reachable at Base; never fixed upstream (PyAV removed by #54231 on 2026-08-29) | Upstream FAILS | Scope B+PyAV needs original Oracle work; otherwise exclude PyAV WebM explicitly |
| F8 PyAV raw H.264: `container.seek` raises PermissionError (EPERM, demuxer unseekable) | Reachable at Base; failure is in decode/seek path, not counting | Upstream FAILS | Exclude (different defect); don't score PyAV raw H.264 |
| F9 raw H.264 has no timing; OpenCV reports default 25 fps (duration 12.0 for a 30 fps stream) | Inherent to format | n/a | Grader must not assert fps/duration for raw H.264 |
| F10 frame_recovery=True does not change trim/streamed symptoms | Base, OpenCV | n/a | Optionally cover recovery mode as same contract |
| F11 #54231 deprecates/removes PyAV (2026-08-29, after Base) | PyAV fully supported at Base (registry, docs, `backend="pyav"`) | n/a | PyAV may stay in scope; decision at Checkpoint 1 |
| F12 #48332/#48331 (open): opencv_dynamic should reject invalid metadata; #54390 (open)/#60501 (merged): Qwen3 fps==0 | Adjacent (fps==0, invalid metadata) | n/a | Exclude (different trigger: unknown fps) |
| F13 llava_onevision2 comment: CAP_PROP_FRAME_COUNT can differ ±1 on some containers | Supports an over-correction guard | n/a | Find a real normal file with ±1 header discrepancy for the over-correction case (open) |
| F14 tasks/vllm-pyav-target-frame-selection (#42586): PyAV seek returns wrong moments | Different Base (a7737cb) and defect (which frame is decoded), fix already present at our Base | n/a | No overlap; our verifier also checks frame identity, consistent with that contract |
| F15 torchcodec (CPU dep at Base): #48608 says exact mode unaffected | Unverified locally | Unverified | Check in amd64 image; preserved-behavior only, not scored until verified |
