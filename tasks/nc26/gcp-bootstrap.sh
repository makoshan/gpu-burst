#!/usr/bin/env bash
# 在 GCP VM 上:装环境,后台起 dataprep.sh(DEST=gcs),成功后机器自删。用法: gcp-bootstrap.sh <gs://bucket> <zone>
set -euo pipefail
BUCKET=$1; ZONE=$2
sudo apt-get -qq update >/dev/null && sudo apt-get -qq install -y git rsync curl tmux >/dev/null
mkdir -p ~/neural-compet26 && rm -rf ~/neural-compet26/code && mv ~/nc26-code ~/neural-compet26/code
# Debian 12 自带 Python 3.11,neuralfetch 0.3.1 要 3.12 → uv
curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1; export PATH=$HOME/.local/bin:$PATH
[ -d ~/nc26env ] || uv venv -q -p 3.12 ~/nc26env
# 与本地 / Spark 上验证过的版本一致(同 sky/nc26-dataprep.yaml)
VIRTUAL_ENV=~/nc26env uv pip install -q neuralset==0.3.1 neuralfetch==0.3.1 exca==0.5.29 eegdash==0.9.1 mne mne-bids pandas numpy torch --extra-index-url https://download.pytorch.org/whl/cpu
~/nc26env/bin/python -c "import neuralfetch, eegdash, mne, torch; print('env ok', eegdash.__version__, mne.__version__)"
cat > ~/run.sh <<RUN
DEST=gcs COMPACT=1 GCS_OUT=$BUCKET bash ~/neural-compet26/code/dataprep.sh > ~/dataprep.log 2>&1
rc=\$?; echo "NC26_DATAPREP_RC=\$rc" >> ~/dataprep.log
gcloud storage cp ~/dataprep.log $BUCKET/logs/dataprep-\$(date -u +%Y%m%dT%H%M).log
# 只在成功时自删;失败留着查,由 --max-run-duration 兜底
[ \$rc = 0 ] && gcloud compute instances delete \$(hostname) --zone $ZONE --quiet
RUN
tmux new -d -s prep "bash ~/run.sh"
sleep 20; cat ~/dataprep.log
