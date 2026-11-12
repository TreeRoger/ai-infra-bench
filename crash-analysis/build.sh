#!/usr/bin/env bash
set -euo pipefail
S=$1; WT=$HOME/infrabench-work/vllm-scratch; B=11baa0ebd88480b0a3e30138e4ee189420cd33be
P=$HOME/infrabench-work/ai-infra-bench/tasks/vllm-trimmed-video-frame-sampling/validation/patches/alternative-decode-count.patch
for o in v1 v2; do for p in v1 v2; do
  git -C $WT reset -q --hard $B; git -C $WT clean -qfd; git -C $WT apply $P
  python3 $S/variant.py $WT $o $p
  git -C $WT diff > $S/ocv$o-pav$p.patch; echo "ocv$o-pav$p $(git -C $WT diff --stat | tail -1)"
done; done
git -C $WT reset -q --hard $B
