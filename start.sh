#!/bin/bash
# Start the SlackGantt app with proper matplotlib backend
export MPLBACKEND=Agg
cd /home/mmi041/Dropbox/work/prog/slackgantt
source ~/miniconda3/etc/profile.d/conda.sh
conda activate slackgantt
exec python app.py "$@"

