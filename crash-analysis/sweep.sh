#!/usr/bin/env bash
set -uo pipefail
S=$1; shift; WT=$HOME/infrabench-work/vllm-scratch; B=11baa0ebd88480b0a3e30138e4ee189420cd33be
LV=$HOME/infrabench-evidence/vllm-video-container-frame-count/local-verifier
for tag in "$@"; do for i in 1 2 3; do
  git -C $WT reset -q --hard $B; git -C $WT clean -qfd; git -C $WT apply $S/$tag.patch
  res=$($LV/run_local.sh crash-$tag-$i $WT 2>&1 | tail -1)
  codes=$(grep -ho "exit=-\?[0-9]*" $LV/crash-$tag-$i/work/*.log 2>/dev/null | sort | uniq -c | tr '\n' ' ')
  printf '%-14s run%d  %-40s %s\n' $tag $i "$res" "$codes"
done; done
git -C $WT reset -q --hard $B
