# What happened while you were away (2026-11-09)

All Harbor results: GitHub Actions linux/amd64 on the fork. "Local" = arm64 macOS, not Harbor.

1. **VFR preserved fixture.** In the image (ffmpeg 7.1) the two-input concat recipe hid the last frame
   (header 120, plays 119). Probed 7 recipes in the image (ci/run4-evidence/vfr-variants.txt): every
   concat variant fails; single-input `select` variants are clean. Regenerated the fixture that way.
   **Preserved set is still 16 files; nothing dropped.**
2. **Duration check vs controls.** Local and amd64: every control has the same failure count as before
   loosening. Added `oracle-stale-duration` (oracle frames, header-derived OpenCV duration): 0 with 43
   duration failures. A clip with a one-frame lead-in where the stale value equals the container
   duration is accepted by design.
3. **Instruction.** Re-measured in the image: the OpenCV numbers hold; PyAV changed to "2 frames, total 272;
   64 frames with the last repeated at -1". No requirement changed.
4. **Full amd64 run 42559412170:** every case matches expected reward; Base/Oracle/alternative/segfault
   controls x3 each, identical counts. OpenCV release() crash also reproduces on amd64 (-11, 3/3).
5. **Standard `Task validation` workflow** on the final commit 40b462d: run 42745455183 passed. It used the cached image; all 18 cases matched their expected reward.
6. Repo checks pass: task_ci validate, normalize_task_configs/sync_collect_hooks/normalize_image_manifests
   --check, git diff --check.

Not done: Phase 8 review-rubric pass (after CP3 per plan). Nothing pushed upstream; no PR opened.
Housekeeping: deleted my local copy of curator/vllm-trimmed-video-ci (content duplicated on -ci-2);
the fork copy is untouched and can be deleted.
