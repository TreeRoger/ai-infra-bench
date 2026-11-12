# Evidence: vllm-trimmed-video-frame-sampling

Curator evidence for the `tasks/vllm-trimmed-video-frame-sampling` PR. This branch lives only on the
contributor's fork and is not meant to be merged. It holds no task code.

GitHub Actions logs and artifacts expire, so the logs the PR cites are copied here.

**Labels.** Everything under `ci/` ran on GitHub Actions linux/amd64 (Harbor). Everything under
`local-verifier/`, `repro/` and `crash-analysis/` is local arm64 macOS, not Harbor.

## Final runs (task commit a3c001d)

| What | Actions run | Copy here |
|---|---|---|
| Standard `Task validation`, 20 cases | [42902944960](https://github.com/TreeRoger/ai-infra-bench/actions/runs/42902944960) | `ci/task-validation-42902944960.log` |
| Fork run, every case plus repeats, preserved-pair probe | [42902955247](https://github.com/TreeRoger/ai-infra-bench/actions/runs/42902955247) | `ci/run8-42902955247/` (`run.log`, Harbor job results, `evidence/preserved-probe.json`) |
| Codec probe that found the AV1 fixture | [42899165976](https://github.com/TreeRoger/ai-infra-bench/actions/runs/42899165976) | `ci/probe-42899165976/` |
| pyav-via-opencv scoring 1 with the pixel catch (superseded) | [42893241585](https://github.com/TreeRoger/ai-infra-bench/actions/runs/42893241585) | `ci/task-validation-42893241585.log`, `ci/run7-42893286010/` |

Older runs (`run1`–`run6`, `task-validation-42745455183`, `task-validation-42758938390`) are earlier revisions.

## Layout

- `drafts/`: PR description, behavior-to-test map, oracle provenance, full diff.
- `controls/make_controls.py`: generates the control patches in `validation/patches/`.
- `upstream-findings.md`, `research/`: upstream history and scope decisions.
- `review-response.md`: responses to both rubric reviews.
- `crash-analysis/`: the OpenCV `VideoCapture.release()` segfault.
- `repro/`: reproduction scripts and the over-correction search (`repro/overcorrection/overcorrection-search.json`).
- `local-verifier/`: local arm64 verifier sweeps (`allcases-*.log`) and per-case logs, JUnit and status.

Left out as regenerable: video fixtures, frame dumps, Base source copies, Harbor workspace tarballs,
`.pyc` files and copies of the task's test files.
