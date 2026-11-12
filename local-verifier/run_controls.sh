#!/usr/bin/env bash
# LOCAL arm64 control sweep (not Harbor). Applies each control to a scratch Base worktree.
set -uo pipefail
TASK=$HOME/infrabench-work/ai-infra-bench/tasks/vllm-trimmed-video-frame-sampling
WT=$HOME/infrabench-work/vllm-scratch
B=11baa0ebd88480b0a3e30138e4ee189420cd33be
for name in $(python3 -c "import json;print(' '.join(c['name'] for c in json.load(open('$TASK/validation/ci-cases.json'))['cases']))"); do
  git -C $WT reset -q --hard $B; git -C $WT clean -qfd
  after=$(python3 -c "import json;print(next(c.get('apply_after','base') for c in json.load(open('$TASK/validation/ci-cases.json'))['cases'] if c['name']=='$name'))")
  [ "$after" = oracle ] && git -C $WT apply $TASK/solution/oracle.patch
  git -C $WT apply $TASK/validation/patches/$name.patch
  res=$($HOME/infrabench-evidence/vllm-video-container-frame-count/local-verifier/run_local.sh ctl-$name $WT 2>&1 | grep -E "passed|failed|error" | tail -1)
  printf '%-34s %s\n' "$name" "$res"
done
git -C $WT reset -q --hard $B; git -C $WT clean -qfd
