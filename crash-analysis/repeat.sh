#!/usr/bin/env bash
# LOCAL arm64 repeat sweep (not Harbor).
set -uo pipefail
S=$1
TASK=$HOME/infrabench-work/ai-infra-bench/tasks/vllm-trimmed-video-frame-sampling
WT=$HOME/infrabench-work/vllm-scratch; B=11baa0ebd88480b0a3e30138e4ee189420cd33be
LV=$HOME/infrabench-evidence/vllm-video-container-frame-count/local-verifier
one() { # label patch-list... ; empty list = installed Base tree
  local label=$1; shift
  git -C $WT reset -q --hard $B; git -C $WT clean -qfd
  local tree=""
  if [ $# -gt 0 ]; then for p in "$@"; do git -C $WT apply "$p"; done; tree=$WT; fi
  local res=$($LV/run_local.sh rep-$label $tree 2>&1 | tail -1)
  local codes=$(grep -h "^exit=" $LV/rep-$label/work/worker-*.log | tr '\n' ' ')
  local st=$(python3 -c "import json;d=json.load(open('$LV/rep-$label/status.json'));print('INFRA' if 'infrastructure_error' in d else 'behavior', (d.get('candidate_problem') or '')[:90])")
  printf '%-34s %-34s %s | %s\n' "$label" "$res" "$st" "$codes"
}
O=$TASK/solution/oracle.patch; P=$TASK/validation/patches
for i in 1 2 3 4 5; do one oracle-$i $O; done
for i in 1 2 3; do one base-$i; done
for i in 1 2 3; do one alternative-$i $P/alternative-decode-count.patch; done
for i in 1 2 3; do one segv-mid-$i $O $P/oracle-segfault-mid-run.patch; done
for i in 1 2 3; do one segv-exit-$i $O $P/oracle-segfault-at-exit.patch; done
for i in 1 2 3; do one alt-release-v1-$i $S/ocvv1-pavv2.patch; done
for name in upstream-48608-as-merged oracle-opencv-only oracle-pyav-only dedupe-repeated-frames clamp-to-last-presentable hidden-lead-in-frames special-case-statement-example opencv-counts-with-pyav skip-all-conftest forged-success-report; do one $name $P/$name.patch; done
one oracle-systemexit-zero $O $P/oracle-systemexit-zero.patch
one oracle-os-exit-zero $O $P/oracle-os-exit-zero.patch
git -C $WT reset -q --hard $B; git -C $WT clean -qfd
