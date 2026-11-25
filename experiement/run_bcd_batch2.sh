#!/bin/bash
# Batch 2 of the B-D pilot (25 Nov 2026): B on the ten remaining held-out cases, C/D on priority cases.
# Usage: run_bcd_batch2.sh KEYTAG "B-cases" "C-cases" "D-cases"  (inside the OpenRouter credential wrapper)
export RESEARCH_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
S=/home/user/workspace/experiments/run_bcd.sh; O=/home/user/workspace/rundata/eval
[ -n "$2" ] && $S B "$2" $O/NEM2-$1-B
[ -n "$3" ] && $S C "$3" $O/NEM2-$1-C
[ -n "$4" ] && $S D "$4" $O/NEM2-$1-D
echo ALLDONE
