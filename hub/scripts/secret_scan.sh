#!/usr/bin/env bash
# Fail (exit 1) if real-looking MQTT credentials appear in tracked hub/ files.
# Placeholders (xxxxx..., your_password, 여기_...) are allowed. Legacy reference
# copies hub_cloud.py / en/ are excluded (documented in docs/DRIFT.md).
set -uo pipefail
cd "$(dirname "$0")/.."
EX=(--exclude-dir=.venv --exclude-dir=__pycache__ --exclude=secret_scan.sh)
hits=0
# 1) a real HiveMQ cluster host: 32 hex chars before .s1.eu.hivemq.cloud
if grep -rEn "${EX[@]}" --exclude-dir=en --exclude=hub_cloud.py \
     '[0-9a-f]{32}\.s[0-9]\.[a-z-]+\.hivemq\.cloud' . ; then hits=1; fi
# 2) MQTT_PASSWORD= with anything but the placeholder
if grep -rEn "${EX[@]}" 'MQTT_PASSWORD=' . | grep -v 'MQTT_PASSWORD=your_password' ; then hits=1; fi
# 3) PASSWORD / USERNAME literals in python other than placeholders
if grep -rEn "${EX[@]}" --include='*.py' --exclude-dir=en --exclude=hub_cloud.py \
     '^(PASSWORD|USERNAME)\s*=\s*"[^"]+"' . | grep -vE '"(\*+|여기_[a-z]+|your_[a-z]+)"' ; then hits=1; fi
if [ $hits = 1 ]; then echo "secret_scan: FAIL"; exit 1; fi
echo "secret_scan: OK"
