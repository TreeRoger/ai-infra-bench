# Add vLLM trimmed-video frame sampling task

## Problem

**Domain:** multimodal inference serving (vLLM video input).

Users often shorten recordings with ffmpeg's lossless cut (`ffmpeg -ss … -c copy`) before sending them to a VLM. The cut can only start on a keyframe. So the output MP4 keeps the hidden decode lead-in packets and an edit list that hides them during playback. At the pinned Base, vLLM's OpenCV and PyAV video backends size their sampling grid with `CAP_PROP_FRAME_COUNT` / `stream.frames`. Both count every physical sample. Two things go wrong as a result:

- OpenCV drops samples beyond the clip's end.
- PyAV clamps reads to the end of the clip, so it drops or repeats the final frame.

Both report `total_num_frames`, `duration` and `frames_indices` for a timeline the clip doesn't have. For the statement's example (a 62-frame clip), Base returns 2 of the 8 requested frames on both backends and reports 272 frames and 9.07 s on OpenCV. Wrong frames and metadata go straight into the model's prompt (vision tokens, timestamps).

**Source context:**
- vLLM PR #48608 fixed part of this upstream. On vLLM main it is the squash-merge commit `9b2aef512440f024fc98cd0ac954cd452613ad5b` (2026-08-20T04:23:09Z). Its OpenCV code comes from `2a7850284` ("seek to video end to get exact frames num"), a maintainer commit on the PR branch, not on main. It replaced the contributor's original resample-after-truncated-read design, which the PR description still describes.
- Base is its parent, `11baa0ebd88480b0a3e30138e4ee189420cd33be` (2026-08-20T03:52:42Z).
- PyAV was removed on 2026-08-29 by #54231 (`4fc943b86`). That PR is titled "Deprecate PyAV video decoder backend", but it deletes `vllm/multimodal/video_decoders/pyav.py`. PyAV is fully supported at Base, so it is in scope.
- **Related but distinct:** the existing task `vllm-pyav-target-frame-selection` (Base a7737cb4) covers PyAV returning frames from the wrong moments on an untrimmed video, a seek-accuracy bug. This task covers inflated frame counts and wrong metadata on edit-list trims, on both OpenCV and PyAV. The root causes, Base commits and verifiers are different.

## Task

**Required behavior** (see `instruction.md`). For clips trimmed this way, on both `opencv` and `pyav`:

- Returned frames are ones that play in the clip, with no repeats, and cover the clip from start to end.
- Exactly `num_frames` frames are returned when available. `-1`, or asking for more frames than the clip has, returns each frame once.
- The metadata describes the clip as it plays.

This also applies to the fps-based loaders (`opencv_dynamic`, `qwen2_vl`, `qwen3_vl`) and with `frame_recovery`. Videos that already load correctly must load exactly as at Base. The selected backend must still be the one that decodes. OpenCV must work without PyAV installed.

**End-to-end boundary:** vLLM's public `MediaConnector(media_io_kwargs={"video": …}).fetch_video(file://…)`, i.e. `VideoMediaIO` → loader registry → decoder.

**Verifier design (hidden, 161 tests, 0/1 reward):**
- **Fixtures** are real files built at verify time with the image's ffmpeg CLI. Every fixture is built from frame-labelled sources: 6 `-c copy` trims, a trim of a trim, a PyAV rebased remux, and 17 untrimmed or already-correct files. Those 17 include two variable-frame-rate files, an mpdecimate file that really drops a static stretch, and an AV1 MP4.
- **Ground truth** is a sequential ffmpeg CLI decode (`-fps_mode passthrough`). Returned frames are identified by their labels.
- **Trimmed clips:** frames are ones that play, with no repeats and coverage from start to end. The count is exact. `total_num_frames` equals the frames that play. `frames_indices` must name exactly the returned frames' positions in the clip. `duration` can be anything from (frames − 1)/fps to the container's own duration + 1/fps.
- **Differential checks** cover the fps-based loaders and `frame_recovery`. The trimmed clip must sample the same frames that pristine Base samples from a re-encoded copy holding exactly the same frames. So the tests don't re-implement each loader's sampling math. A build-time check confirms that both duration conventions give the same opencv_dynamic sample count on every compared trim.
- **Preservation checks:** 62 file/loader/backend/count pairs must give byte-identical frames and identical metadata vs Base. These are the pairs where Base's own output is correct against the labels. In the image, Base's PyAV path loads 12 pairs incorrectly (variable-frame-rate, mpdecimate, fragmented, AVI at `-1` and remuxed-MKV files). The symptoms differ by file: some return frames that `frames_indices` doesn't name, and some repeat or skip frames at `-1`. Those 12 pairs are not held to Base. Every OpenCV pair is scored except on the AV1 file, which the image's OpenCV build cannot decode. At run time the verifier re-checks that Base is correct on each scored pair, and that each preserved file decodes to its header frame count, or has no header count. A failure of either is an infrastructure error.
- **Backend isolation:**
  - Every `backend="opencv"` request runs, for both candidate and Base, in a worker where PyAV cannot be imported.
  - The AV1 MP4 (`mp4_av1`, SVT-AV1) is preserved on its PyAV pairs only. Base PyAV loads it fully correctly, while the image's OpenCV build has no AV1 decoder and returns no frames. A fix that quietly decodes `backend="pyav"` requests with OpenCV therefore fails it. This is checked through behavior, not by inspecting calls.
  - After the Base worker, a guard requires that Base OpenCV still loads no frames from that file. Otherwise the run is an infrastructure error.
- **Trust model:**
  - The pytest parent never imports vLLM.
  - Candidate and Base code run in subprocess workers as `nobody`.
  - Base runs first, and each worker's output is made root-owned and read-only once it exits.
  - After every worker, all of `nobody`'s processes are killed, including any that left the worker's process group.
  - A worker must finish every request and exit 0. Crashes are reported by signal, and a timeout counts as a behavior failure.
  - Pristine Base comes from `git archive` of the checkout's own objects (`GIT_NO_REPLACE_OBJECTS=1`).
  - Status and JUnit stay in the root-owned work dir until grading ends. The reward is written only after pytest and an exact-name JUnit check pass.
  - Infrastructure failures are classified separately (numeric `reward.json` flags, `result.txt`).

**Reference solution:** `solution/oracle.patch`. Each hunk is labeled by origin in [`drafts/oracle-provenance.md`](https://github.com/TreeRoger/ai-infra-bench/blob/curator/vllm-trimmed-video-evidence/drafts/oracle-provenance.md):
- **OpenCV:** upstream #48608's end-of-stream seek probe, verbatim. **Curator change (G1):** correct any confirmed shortfall (`< total`), not just shortfalls of 2 or more frames. Upstream leaves a one-frame lead-in uncorrected (7/8 frames).
- **PyAV:** **curator code (G2).** It counts the demuxer's non-discard packets (`packet.is_discard`) without decoding, in place of upstream's `round(duration × fps)` estimate. That estimate over-counts real trims by 2 frames (94 vs 92, 64 vs 62, 49 vs 47) and repeats the last frame at `-1`.

## Environment

- CPU only (`gpus = 0`); 8 CPUs / 16 GiB / 50 GiB declared; no network.
- **Retained image (linux/amd64):** `sha256:46c3557c0f9e09bd0f4ca888ac4b3db4c5888b2d7b9135287597f80063cad227`
  - cache tag `ghcr.io/treeroger/ai-infra-bench-task-envs:vllm-trimmed-video-frame-sampling-1f6b47c98978b53fd5eabc09575c18f3b7d53ab300a217e978f0075d40fb08fe`
  - built on GitHub-hosted ubuntu-24.04 in 2125 s, from the template-generated Dockerfile.
- **Pinned versions:** opencv-python-headless 5.0.0.93, av 18.1.0, torchcodec 0.16.0+cpu, torch 2.13.0+cpu, numpy 2.3.5, pytest 9.1.1, Debian ffmpeg CLI 7.1.5.
- **Audits:**
  - The image is at Base. The fix commit `9b2aef512` is absent, and no fix text is in the decoders.
  - No task or curator files are in the image (filesystem scan plus `docker history`).
  - `task_ci.py image-check` passes.
- **No reconstructed inputs.** All fixtures are generated from scratch by the verifier.
- **Hardware:** the curator had no x86 machine. All Harbor runs used GitHub Actions on the contributor's fork, on linux/amd64 4-CPU runners (`--override-cpus 4`, as task CI does). Local arm64 macOS runs (not Harbor) were used only for reproduction and fast iteration. They are labeled as such in the [evidence branch](https://github.com/TreeRoger/ai-infra-bench/tree/curator/vllm-trimmed-video-evidence/).

## Validation

**Harbor on linux/amd64**, on the final commit `a3c001d`: fork run [42902955247](https://github.com/TreeRoger/ai-infra-bench/actions/runs/42902955247) (every case, plus repeats) and the standard `Task validation` workflow, run [42902944960](https://github.com/TreeRoger/ai-infra-bench/actions/runs/42902944960) (20 of 20 cases at their expected reward). Actions logs expire, so both are also saved on the evidence branch: [`ci/run8-42902955247/`](https://github.com/TreeRoger/ai-infra-bench/tree/curator/vllm-trimmed-video-evidence/ci/run8-42902955247) and [`ci/task-validation-42902944960.log`](https://github.com/TreeRoger/ai-infra-bench/blob/curator/vllm-trimmed-video-evidence/ci/task-validation-42902944960.log). Counts are failed tests out of 161.

| Case | Expected | Observed | Why it fails |
|---|---|---|---|
| base (nop) ×3 | 0 | 0, 0, 0 | 98: every trim (dropped or repeated frames, wrong count, total, indices and duration), the fps loaders, recovery, no-PyAV and derived trims. No preserved pair fails. |
| oracle ×3 | 1 | 1, 1, 1 | passes 161/161 |
| alternative-decode-count ×3 | 1 | 1, 1, 1 | passes 161/161. Counts frames by sequential decode at the decode entry points, with different structure and names. |
| alternative-pyav-nth-frame ×3 | 1 | 1, 1, 1 | passes 161/161. Oracle count, but PyAV maps index *n* to the *n*-th presented frame by decoding sequentially instead of seeking by time. |
| upstream-48608-as-merged | 0 | 0 | 36: one-frame lead-in on OpenCV (G1); PyAV count off by 2 and repeats at `-1` (G2) |
| oracle-opencv-only | 0 | 0 | 44: PyAV trims only |
| oracle-pyav-only | 0 | 0 | 54: OpenCV trims, recovery and no-PyAV |
| dedupe-repeated-frames | 0 | 0 | 98: fewer frames than requested, wrong indices |
| clamp-to-last-presentable | 0 | 0 | 98: repeats the last frame |
| hidden-lead-in-frames | 0 | 0 | 117: returns frames from before the cut. It also changes 19 preserved loads. |
| special-case-statement-example | 0 | 0 | 77: only the 272 @ 30 fps example is fixed |
| opencv-counts-with-pyav | 0 | 0 | 90: the OpenCV path imports PyAV, so it fails wherever PyAV is unavailable (including 36 preserved pairs) |
| skip-all-conftest | 0 | 0 | 98: conftest not loaded; Base failures, 0 skipped |
| forged-success-report | 0 | 0 | 98: forged reports are never used; Base failures |
| oracle-systemexit-zero | 0 | 0 | 160: workers never start loading |
| oracle-os-exit-zero | 0 | 0 | 160: workers never start loading |
| oracle-segfault-mid-run ×3 | 0 | 0, 0, 0 | 90: the OpenCV worker crashes with SIGSEGV (a behavior failure), including 36 preserved pairs |
| oracle-segfault-at-exit ×3 | 0 | 0, 0, 0 | 160: workers finish, then SIGSEGV at shutdown |
| oracle-stale-duration | 0 | 0 | 43: oracle frames, but OpenCV keeps the header-derived duration |
| oracle-pyav-via-opencv | 0 | 0 | 2: the oracle, but `backend="pyav"` requests are quietly decoded by OpenCV. It passes everything else, then returns no frames on the AV1 file's two PyAV pairs. |

Failure counts are identical across repeats. The local arm64 sweep (not Harbor) ran with the AV1 guard disabled, because macOS OpenCV decodes AV1. It matches amd64 on every case except `oracle-pyav-via-opencv`: 26 failures locally, where OpenCV also decodes AV1 and its RGB output differs from PyAV's.

In the image, the preserved-pair probe finds Base incorrect on exactly the 12 excluded scored pairs, and correct on all 62 scored ones. It also finds Base wrong on 4 unscored `qwen3_vl` pairs and on the 2 AV1 OpenCV pairs (no frames). It records the raw returned labels, `frames_indices` and metadata for each of these pairs.

**Self-review findings and resolutions:**
1. **The alternative control's first version segfaulted.** This was the control itself. OpenCV 5.0.0.93's `VideoCapture.release()` on a stream capture that holds the last reference to its buffer crashes every time, on both arm64 and amd64. Base, the oracle and the verifier never call it. **Resolution:** classify crashes by signal, add a faulthandler stack to the worker log, require a clean exit, use process-group isolation, count a candidate timeout as a behavior failure, and add the two segfault controls.
2. **`reward.json` carried a string label**, which Harbor rejects. **Resolution:** numeric flags, plus `result.txt`.
3. **The PyAV duration window had zero margin under ffmpeg 7.1.** **Resolution:** accept from the frame-count duration to the container duration, ±1 frame. `oracle-stale-duration` still fails.
4. **The VFR fixture's two-input concat hid its last frame under ffmpeg 7.1.** **Resolution:** a single-input `select` recipe, plus the runtime header guard.
5. **The instruction's PyAV example was measured with local ffmpeg 9.** **Resolution:** re-measured in the image and rewritten.
6. **A pixel-based backend catch didn't hold on amd64.** On arm64, `oracle-pyav-via-opencv` failed through small RGB differences between OpenCV and PyAV. In the amd64 image the two decoders give byte-identical frames on every preserved file, so it scored 1. **Resolution:** I probed codecs in the image (run [42899165976](https://github.com/TreeRoger/ai-infra-bench/actions/runs/42899165976), saved as [`ci/probe-42899165976/`](https://github.com/TreeRoger/ai-infra-bench/tree/curator/vllm-trimmed-video-evidence/ci/probe-42899165976)). Base OpenCV returns no frames on AV1 in MP4, from both SVT-AV1 and libaom, while Base PyAV is fully correct on it, so I added it as a preserved file with a guard. Full-range, BT.709, 4:4:4 and VP9 files were byte-identical between the decoders in the image. ProRes and 10-bit files did differ, but the behavioral AV1 catch was preferred over a pixel-difference one.

**Independent rubric reviews.** First review: 18/20, one blocker. Re-review: 19/20, no blockers; its P2/N items are resolved in this revision (the backend control and AV1 file, the corrected counts, the updated test map, and raw probe evidence). Resolutions of the first review:
- **B1:** Base PyAV repeats or misplaces frames on the VFR fixtures, so holding a correct fix to Base there was unfair. **Resolution:** labelled VFR and mpdecimate fixtures; preserved pairs scored only where Base is correct (confirmed in the image); `alternative-pyav-nth-frame` added and passing ×3. The instruction is unchanged.
- **S1:** fixture integrity (trims hide lead-in, labels readable, preserved headers exact) is now checked while building and reported as an infrastructure error.
- **S2:** `frames_indices` must equal the returned frames' clip positions.
- **M1:** build-time check that both duration conventions give the same opencv_dynamic sample count on every compared trim.
- **M2:** `total_num_frames` must now be exact; the oracle and both alternatives meet it.
- **M3:** see Limitations.
- **M4:** the trust comment now states what is and isn't protected. Status and JUnit moved to the root-owned work dir. While reviewing M4 I found a gap: a worker could leave its process group with `setsid` and outlive it. **Resolution:** Base runs first and its output is sealed; all worker-user processes are killed after each worker.
- **M5:** all OpenCV-backend requests run with PyAV blocked. mpdecimate now really drops frames, so it is a true VFR file.
- **Extra finding while fixing B1:** the HEVC fixture's labels didn't read reliably at x265's default quality (298 distinct of 300 in the ground truth). It is now encoded at `-crf 14`.

**Run records** are on the fork-only branch [`curator/vllm-trimmed-video-evidence`](https://github.com/TreeRoger/ai-infra-bench/tree/curator/vllm-trimmed-video-evidence/), outside the task dir. It holds no task code and is not meant to be merged. Its [README](https://github.com/TreeRoger/ai-infra-bench/blob/curator/vllm-trimmed-video-evidence/README.md) indexes it: [`ci/`](https://github.com/TreeRoger/ai-infra-bench/tree/curator/vllm-trimmed-video-evidence/ci) (amd64 Harbor runs; copies of the Actions logs, which expire), [`crash-analysis/`](https://github.com/TreeRoger/ai-infra-bench/tree/curator/vllm-trimmed-video-evidence/crash-analysis), [`local-verifier/`](https://github.com/TreeRoger/ai-infra-bench/tree/curator/vllm-trimmed-video-evidence/local-verifier) and [`repro/`](https://github.com/TreeRoger/ai-infra-bench/tree/curator/vllm-trimmed-video-evidence/repro) (local arm64), [`upstream-findings.md`](https://github.com/TreeRoger/ai-infra-bench/blob/curator/vllm-trimmed-video-evidence/upstream-findings.md), and [`drafts/`](https://github.com/TreeRoger/ai-infra-bench/tree/curator/vllm-trimmed-video-evidence/drafts) (behavior-to-test map, oracle provenance). Video fixtures, frame dumps and other regenerable bulk are left out.

## Limitations

- **Reference fix provenance:** the OpenCV one-frame tolerance change (G1) and the entire PyAV fix (G2) are curator code, not upstream. Upstream #48608 as merged scores 0 on this task (36 failures), by design.
- **No over-correction fixture.** Over-correction means a fix shrinks the frame count of a file that already loads correctly, for example because its count probe lands one frame short. I looked for a real file that triggers this and found none: on 14 untrimmed or already-correct files, the header count, the decoded count and OpenCV's end-of-stream probe all agreed (local arm64, [`repro/overcorrection/overcorrection-search.json`](https://github.com/TreeRoger/ai-infra-bench/blob/curator/vllm-trimmed-video-evidence/repro/overcorrection/overcorrection-search.json)). So there is no fixture or control for that case; I did not invent one. A fix that changes files that already load correctly is still caught by the 62 scored preserved pairs on 17 files.
- **One fps-loader case skipped:** `very_short` × `opencv_dynamic` × `opencv`. Base raises on the re-encoded copy as well, so no differential reference exists.
- **torchcodec isn't scored.** In the image it already handles the example correctly (8 distinct frames, `total_num_frames=62`). It is outside the instruction's scope.
- **Header-less WebM/MKV is left for a follow-up task.** Raw `.h264` (PyAV can't seek) is out of scope.
- **ffmpeg is not version-pinned.** The image takes Debian's `ffmpeg` apt package (7.1.5-0+deb13u1, recorded in [`instruction-probe.json`](https://github.com/TreeRoger/ai-infra-bench/blob/curator/vllm-trimmed-video-evidence/ci/run8-42902955247/curator-evidence-42902955247/evidence/instruction-probe.json)), as the shared template does for other tasks. It builds both the fixtures and the ground truth. The retained image ID pins it for CI, but a rebuild could pick up a different ffmpeg. Fixture recipes are known to behave differently across ffmpeg versions (the old concat recipe under 7.1). The build-time integrity checks turn such drift into an infrastructure error instead of a wrong grade.
- **Trust boundary:** the agent runs as root in the grading container, so it could alter what the verifier relies on: the Python installation and its `.pth`/sitecustomize hooks, ffmpeg, or the Git objects Base is extracted from. This is inherent to in-container grading, and `test.sh` says so.
- **PyAV preserved pairs excluded:** 12 PyAV pairs (VFR, fragmented, AVI at `-1`, mpdecimate, remuxed MKV) are not scored for preservation, because Base itself loads them incorrectly. The symptoms differ by file, and the probe's raw labels and indices are in [`preserved-probe.json`](https://github.com/TreeRoger/ai-infra-bench/blob/curator/vllm-trimmed-video-evidence/ci/run8-42902955247/curator-evidence-42902955247/evidence/preserved-probe.json) (`raw`).
- **Backend substitution is caught through one codec gap in the pinned image.** `oracle-pyav-via-opencv` decodes `backend="pyav"` requests with OpenCV. Its metadata is correct and so are its trim results. It is caught only because the image's OpenCV build has no AV1 decoder, while PyAV (bundled dav1d) decodes AV1. On every other file the two decoders give byte-identical frames in the image. If a rebuilt image's OpenCV gained AV1 support, the guard reports an infrastructure error instead of silently losing the catch.
  - There is deliberately no check on which library the code calls.
  - A fix that counts with OpenCV and decodes with PyAV remains valid, provided it still loads the AV1 file as Base does. That much is already required, because the file loads correctly with `backend="pyav"` at Base.
- **The agent runs as root**, following sibling tasks built from the all-in-one image.
- **Upstream tests need the network.** Upstream `tests/multimodal/test_video.py` cases that download S3 assets error with no network, both for the agent and in the smoke test.
- **Hardware:** CI validation ran on 4-CPU runners against an 8-CPU declaration. Local probes were arm64 macOS, not Harbor, and are labeled as such.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
