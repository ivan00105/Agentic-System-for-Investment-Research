#!/bin/bash
# Usage: run_bcd.sh CONDITIONS CASES OUT   (run inside the OpenRouter credential wrapper)
cd /home/user/workspace/src/Agentic-System-for-Investment-Research-main
export NO_PROXY="sec.gov,.sec.gov,.yahoo.com,api.frankfurter.app,api.stlouisfed.org,api.fiscaldata.treasury.gov,localhost,127.0.0.1"
export no_proxy=$NO_PROXY
export RESEARCH_MODEL_PROVIDER=openrouter RESEARCH_MODEL=${RESEARCH_MODEL:-google/gemma-4-31b-it:free} OPENROUTER_API_KEY=proxy-injected
export SEC_USER_AGENT="Fieldnote COMP7608 u3665604@connect.hku.hk" RESEARCH_DATA_DIR=/home/user/workspace/rundata
.venv/bin/python eval/run_eval.py --conditions "$1" --split held_out --cases "$2" --out "$3"
