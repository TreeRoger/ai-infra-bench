# Behavior-to-test map (matches tests/ at the final task commit)

**Entry point.** Every scored request goes through vLLM's public media connector, as the serving path does:

```python
MediaConnector(media_io_kwargs={"video": {"video_backend": <loader>, "backend": <codec>, "num_frames": N, ...}},
               allowed_local_media_path=<fixture dir>).fetch_video("file://...").media
```

That covers `VideoMediaIO`, the loader registry and the decoder. Requests run in `tests/worker.py` subprocesses as `nobody`. The root pytest parent never imports vLLM.

**Ground truth.** It comes from outside vLLM.
- Fixtures are built at verify time with the image's ffmpeg CLI, from frame-labelled sources. Each label is three mid-gray base-16 blocks.
- A file's *visible frames* are the labels from a sequential CLI decode (`-fps_mode passthrough`), which follows the presentation timeline.
- Returned frames are identified by reading their labels.

**Base comparisons are direct.** Differential and preservation checks run the pristine Base tree, extracted from the checkout's Git objects, in a worker before the candidate. They compare the candidate's output to what Base actually returned. Base's sampling formulas are not re-implemented anywhere.

## Totals (161 tests, all must pass)

| Test | Count | Parameters |
|---|---|---|
| `test_fixtures_are_real_trims_and_untrimmed_files` | 1 | none |
| `test_generic_loader_on_trim` | 60 | 6 trims × {opencv, pyav} × N ∈ {4, 8, 16, -1, visible+37} |
| `test_generic_loader_fps_sampling_on_trim` | 4 | {mild, severe} × {opencv, pyav}, `fps=2`, `num_frames=-1` |
| `test_fps_loaders_match_reencoded_clip` | 19 | {severe, mild, one_frame_lead_in, very_short} × 5 loader/codec pairs, minus `very_short`/`opencv_dynamic`/`opencv` |
| `test_frame_recovery_matches_reencoded_clip` | 4 | {severe, one_frame_lead_in} × N ∈ {8, -1}, `frame_recovery=True` |
| `test_untrimmed_and_correct_videos_unchanged` | 62 | 17 files × generic loader × {opencv, pyav} × N ∈ {8, -1} (68), minus the 2 OpenCV pairs on `mp4_av1`; plus 4 files × {opencv_dynamic/opencv, qwen3_vl/pyav} at N=8 (8); minus the 12 pairs excluded below |
| `test_opencv_without_pyav` | 3 | severe/opencv/8, one_frame_lead_in/opencv/-1, severe/opencv_dynamic/8 |
| `test_independently_derived_trims` | 8 | {trim_of_trim, rebased_remux} × {opencv, pyav} × N ∈ {8, -1} |

`check_junit.py` requires exactly these 161 names, each once, with 0 failures, errors and skips.

## Requirements → assertions

| # | Requirement (instruction) | Assertion | Tests |
|---|---|---|---|
| R1 | Returned frames play in the clip, with no repeats | every label is in the visible set, and labels are strictly increasing | generic, fps-sampling, fps loaders, recovery, no-PyAV, derived |
| R2 | Samples cover the clip from start to end | the first sample is clip position 0; the last is within one sampling step of the end; no gap exceeds 2 × step + 1 | generic (N ≤ visible), fps-sampling, no-PyAV (`opencv_dynamic`) |
| R3 | Exactly `num_frames` when the clip has that many | `len(frames) == N` | generic, no-PyAV, derived |
| R4 | `-1`, or N > visible, returns each frame once | returned labels == the visible list | generic, no-PyAV, derived |
| R5 | `total_num_frames`, `duration` and `frames_indices` describe the clip and match the frames | `total_num_frames == visible` (exact). `frames_indices` equals the returned frames' positions in the clip (exact), strictly increasing and in range. `(visible − 1)/fps ≤ duration ≤ max(visible/fps, container duration) + 1/fps` | every trim test |
| R6 | fps-based loaders (`opencv_dynamic`, `qwen2_vl`, `qwen3_vl`) | the trimmed clip's labels equal the labels Base returns from a re-encoded copy holding exactly the visible frames, plus R1 and R5 | fps loaders; fps-sampling (generic loader, 2 fps: sample count within ±2 frames' worth) |
| R7 | `frame_recovery` enabled | the same differential comparison against Base on the re-encoded copy, plus R1 and R5 | recovery |
| R8 | Videos that already load correctly are unchanged | `np.array_equal` on frames, and metadata dict equality (`total_num_frames`, `fps`, `duration`, `video_backend`, `frames_indices`, `do_sample_frames`) against Base's own output on the same file | preserved |
| R9 | The selected backend decodes | `metadata["video_backend"]` is the requested loader. Every `backend="opencv"` request, candidate and Base, runs in a worker where `import av` fails. On preserved PyAV pairs, frames must be byte-identical to Base's PyAV decode. `mp4_av1` is preserved on PyAV only: the image's OpenCV cannot decode AV1, so a `backend="pyav"` request decoded by OpenCV returns no frames there. This is a behavioral check, with no inspection of library calls | all; preserved |
| R10 | OpenCV works without PyAV installed | request runs with `sys.modules["av"] = None`, and the worker reports `av_imported is False`; R1–R5 hold | no-PyAV (and, through R9, every OpenCV request) |
| — | Evaluation integrity (not a product feature) | a worker must finish every request and exit 0, and a crash or timeout is a behavior failure. Exact JUnit name set. Reward is written by `test.sh` only after pytest and `check_junit.py` both finish | all |

## Fixtures

- **Trims (scored)**, all real `ffmpeg -ss … -c copy` cuts that hide decode lead-in behind an edit list:
  - mild: GOP 60, `-ss 2.5 -t 3`;
  - one_frame_lead_in: GOP 60, cut one frame after a keyframe (the G1 case);
  - severe: GOP 250, `-ss 7 -t 2`;
  - fps25: GOP 48 at 25 fps, `-ss 3.3 -t 2.5`;
  - very_short: GOP 120, `-ss 3 -t 0.4`;
  - no_bframes: GOP 90, `-bf 0`, `-ss 4.1 -t 2`.
- **Independently derived trims:** a `-c copy` trim of the mild trim, and a PyAV stream-copy remux with rebased timestamps (upstream #48608's construction, re-implemented from its description).
- **Preserved (17 files):**
  - mp4 with and without B-frames;
  - 29.97 fps, with audio, MOV;
  - fragmented MP4, faststart;
  - HEVC (`-crf 14`), MPEG-4 in MP4, MPEG-4 in AVI;
  - mpdecimate (drops a 60-frame static stretch, 240 of 300 frames play);
  - two variable-frame-rate files (30 → 10 fps, and a 1 s gap);
  - re-encoded cut, `-c copy` cut on a keyframe, MKV → MP4 remux;
  - AV1 in MP4 (SVT-AV1, `mp4_av1`), scored on its PyAV pairs only.

**Build-time integrity checks.** Each one is an infrastructure error, not a grade:
- labels are distinct;
- every trim has header > plays > 0;
- every preserved file decodes to its header frame count, or has no header count;
- on every compared trim, both duration conventions give the same `opencv_dynamic` sample count;
- after the Base worker, Base loads every scored preserved pair correctly against the labels;
- after the Base worker, Base OpenCV still returns no frames (or raises) on `mp4_av1`, at N=8 and N=-1.

## Preserved pairs excluded from scoring (12)

Base itself loads these incorrectly in the task image, so a correct fix may change them. All are generic-loader PyAV pairs except one `qwen3_vl` pair:

| File | Excluded pairs |
|---|---|
| mp4_fragmented | opencv/pyav/8, opencv/pyav/-1, qwen3_vl/pyav/8 |
| avi_mpeg4 | opencv/pyav/-1 |
| mp4_mpdecimate | opencv/pyav/8, opencv/pyav/-1 |
| mp4_vfr_30_then_10 | opencv/pyav/8, opencv/pyav/-1 |
| mp4_vfr_gap | opencv/pyav/8, opencv/pyav/-1 |
| mp4_remuxed_from_mkv | opencv/pyav/8, opencv/pyav/-1 |

Base is also wrong on 4 `qwen3_vl`/`pyav` pairs that were never in the scored set (`mp4_mpdecimate`, both VFR files, `mp4_remuxed_from_mkv`). The symptoms differ by file, and the raw returned labels, indices and metadata for every such pair are in `ci/run8-42902955247/curator-evidence-42902955247/evidence/preserved-probe.json` (`raw`).

## Skipped / not scored

- `very_short` × `opencv_dynamic` × `opencv`: Base raises on the re-encoded copy as well, so no differential reference exists.
- torchcodec, header-less WebM/MKV and raw `.h264` are outside the instruction's scope.
- No over-correction fixture: no real file whose header under-counts by one frame was found, and none was invented.
