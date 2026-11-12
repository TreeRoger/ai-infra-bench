# Oracle provenance: upstream code vs curator repairs

Base: vLLM `11baa0ebd88480b0a3e30138e4ee189420cd33be` (parent of `9b2aef512`, PR #48608).
Oracle: `tasks/vllm-trimmed-video-frame-sampling/solution/oracle.patch`.

| Hunk | Origin | Notes |
|---|---|---|
| OpenCV end-of-stream seek probe (`CAP_PROP_POS_AVI_RATIO=1.0`, read back position, restore) | **Upstream** #48608 as merged on main (squash commit `9b2aef512`; the code comes from maintainer commit `2a7850284` on the PR branch), verbatim | |
| OpenCV condition `0 < visible_frames < total_frames_num` | **Curator (G1)** | Upstream uses `< total_frames_num - 1`, which leaves a 1-frame lead-in (cut one frame after a keyframe) uncorrected: last sample unreadable, 7/8 frames returned. |
| Last sentence of the OpenCV comment ("Even a single hidden lead-in frame ...") | **Curator** | |
| PyAV: count presentable packets via `packet.is_discard` (`_count_presentable_packets`), replacing upstream's `round(duration*fps)` estimate | **Curator (G2)** | Upstream's estimate over-counts (94 vs 92, 64 vs 62, 49 vs 47 on real trims), so `num_frames=-1` duplicates the last frame. Packet count matched the decoded count on all 29 real files tested (local arm64). |
| `total_frames == 0` fallback to `int(duration*fps)` | **Base** (unchanged) | |

Upstream control `upstream-48608-as-merged` (expected reward 0) fails 36 of 161 tests: the G1 and G2 cases, now also caught by the exact count and index checks (linux/amd64 Harbor, run 42902955247).
