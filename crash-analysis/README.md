# Why the alternative control's first run crashed (LOCAL arm64, macOS, not Harbor)

**Verdict: the candidate.** The first version of the `alternative-decode-count` control patch (curator-written,
in `ocvv1-pav*.patch`) called `cv2.VideoCapture.release()` on a stream-backed capture whose `BytesIO` was
referenced only by the capture. In opencv-python 5.0.0.93 that segfaults (SIGSEGV, exit -11) **every time**.
The verifier scored it correctly (0, behavior failure). The environment was not at fault.

Evidence:
- `sweep.log`: 4 variants x 3 runs. Old OpenCV half: crash 3/3 with either PyAV half; old PyAV half: no crash,
  80 tests failed 3/3 (thread_type error); committed patch: 171/171, 3/3.
- `matrix.py`, `release-probe-arm64.json`: crash iff release() is called while the capture holds the last
  reference to its buffer (3/3); del/GC without release() and buffer-held cases: exit 0 (3/3). Reproduces on an
  untrimmed testsrc clip -> generic OpenCV bug, not trim-related.
- `owner.py`: the binding DOES hold a reference (refcount 2 -> 3); my earlier note "binding does not own the stream"
  was wrong. The crash is in the release() path.
- Ruled out: macOS duplicate libavdevice (av + cv2 dylibs) -- the --block-av worker (no PyAV loaded) crashed too.
- Base, oracle, all other controls and the trusted verifier never call release(); grader's Base reference worker
  can't hit this path.

Hardening added to the verifier (tests/worker.py, tests/test_trimmed_video.py):
- faulthandler in the worker -> native crashes leave a Python stack in worker-*.log.
- Exit status reported by signal name; a worker must finish every request AND exit 0.
- Own process group per worker; group killed on timeout and after exit (no leftover children).
- Candidate timeout = behavior failure (was: TimeoutExpired -> "infrastructure error"); Base worker failure stays
  infrastructure_error.
- New controls (expected 0): oracle-segfault-mid-run, oracle-segfault-at-exit.

Determinism (`repeat.log`): oracle 5/5 171 passed; base 3/3 90 failed; alternative 3/3 171 passed;
segfault controls 3/3 each; identical failure counts across repeats; every other control once.
Hang test (VERIFIER_WORKER_TIMEOUT=20, local only): 0, "timed out after 20s", no leftover processes.
amd64: opencv_release_probe.py runs in the curator workflow (pending).
