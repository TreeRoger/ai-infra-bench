# Rubric review (fresh session) — responses

Review of 40b462d: 18/20, gate 3 blocked by B1. Fixes are in commit 2ee9c90 on task/vllm-trimmed-video-frame-sampling.
Validation: Harbor linux/amd64, fork run 42753815093; standard Task validation run 42758938390.

| Finding | Resolution | Evidence |
|---|---|---|
| B1 Base PyAV repeats on VFR fixtures | Labelled VFR/mpdecimate fixtures; preserved pairs scored only where Base is correct (12 PyAV pairs excluded, 60 scored); runtime re-check; alternative-pyav-nth-frame added (expected 1) | ci/run6-evidence/preserved-probe.txt (in image: Base wrong on 16 pairs, i.e. the 12 excluded + 4 unscored qwen3_vl); nth-frame 1,1,1 |
| S1 integrity check counted as behavior | Moved into Lab.build -> infrastructure_error | tests/test_trimmed_video.py Lab.build |
| S2 indices weakly checked | frames_indices == clip positions of returned labels | oracle + both alternatives pass 159/159 x3 |
| M1 duration conventions vs opencv_dynamic | Build-time check floor(frames/fps*2) == floor(container*2) on compared trims | Lab.build |
| M2 total tolerance +/-2 | Tightened to exact; no correct approach rejected (oracle, decode-count, nth-frame all pass) | run6 |
| M3 ffmpeg unpinned | Limitations entry (7.1.5-0+deb13u1 recorded; image ID pins it) | drafts/pr-description.md |
| M4 trust comment | Rewritten; status + JUnit kept in root-owned WORK; extra: Base first + sealed outputs, kill all `nobody` processes after each worker (setsid escape) | tests/test.sh, run_worker |
| M5 backend isolation / mpdecimate | All backend=opencv requests (candidate and Base) run with PyAV blocked; mpdecimate now drops a static stretch (240 of 300) | opencv-counts-with-pyav now fails 90 incl. 36 preserved |
| (extra) HEVC labels unreadable at x265 default | -crf 14 | repro/preserved-arm64.json |

## Re-review (19/20, no blockers) — responses

Fixes are in a3c001d. Validation: Harbor linux/amd64, fork run 42902955247 (with repeats); standard Task validation run 42902944960 (20/20 cases expected).

| Finding | Resolution | Evidence |
|---|---|---|
| P2-1 opencv-counts-with-pyav count | 93 → 90 (36 preserved). Every other count rechecked against the final run | run8 harbor-jobs |
| P2-2 behavior-test-map stale | Rewritten: exact totals (161), direct Base comparison, `fetch_video` entry point, the 12 excluded pairs, the AV1 file | drafts/behavior-test-map.md |
| N1 header wording | "decodes to its header frame count, or has no header count" | PR draft, test map |
| N2 excluded-pair evidence | Probe records raw returned labels, frames_indices, labels at those indices, total, fps and duration for every bad or excluded pair; asserts all 12 are recorded. cases.py comment no longer names one cause | run8 evidence/preserved-probe.json (`raw`, 18 pairs) |
| N4 pyav-via-opencv | Control added. A pixel-difference catch held on arm64 only; amd64 frames are byte-identical, so it scored 1 (runs 42893241585, 42893286010). Replaced by a behavioral catch: `mp4_av1`, PyAV-only preserved pairs (image OpenCV has no AV1 decoder; Base PyAV fully correct), plus a guard that Base OpenCV still loads no frames. Control now scores 0 (2 failures) | probe-42899165976/backend-fixture-probe.txt; run8 |
