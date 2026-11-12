#!/usr/bin/env bash
# LOCAL arm64 probe of the task verifier (not Harbor): $1 = label, $2 = candidate tree (empty = installed Base)
set -uo pipefail
label=$1; cand=${2:-}
T=$HOME/infrabench-work/ai-infra-bench/tasks/vllm-trimmed-video-frame-sampling/tests
OUT=$HOME/infrabench-evidence/vllm-video-container-frame-count/local-verifier/$label
rm -rf "$OUT"; mkdir -p "$OUT/work/base-vllm"
git -C $HOME/infrabench-work/vllm archive 11baa0ebd88480b0a3e30138e4ee189420cd33be vllm | tar -x -C "$OUT/work/base-vllm"
cp $T/*.py "$OUT/work/"
# LOCAL ONLY: macOS OpenCV decodes AV1, so the in-image OpenCV-undecodable guard is disabled here.
sed -i "" "s/    return loaded$/    return []  # local-only: guard disabled/" "$OUT/work/test_trimmed_video.py"
source $HOME/infrabench-work/venv-base/bin/activate
cd "$OUT/work"
VERIFIER_WORK="$OUT/work" VERIFIER_STATUS="$OUT/status.json" BASE_VLLM_ROOT="$OUT/work/base-vllm" \
CANDIDATE_VLLM_ROOT="${cand:-$HOME/infrabench-work/vllm-base}" CANDIDATE_PYTHONPATH="$cand" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="$OUT/work" \
python -P -m pytest --noconftest -c /dev/null --rootdir="$OUT/work" -p no:cacheprovider -q -rfE \
  --junitxml="$OUT/junit.xml" "$OUT/work/test_trimmed_video.py" > "$OUT/pytest.log" 2>&1
echo "pytest_rc=$?"
python -P "$OUT/work/check_junit.py" "$OUT/junit.xml"; echo "junit_rc=$?"
grep -E "passed|failed" "$OUT/pytest.log" | tail -1
# Drop the regenerable frame dumps and copies (about 1 GB per run); logs stay.
rm -rf "$OUT/work"/out-* "$OUT/work/base-vllm" "$OUT/work/media" "$OUT/work/scratch"
