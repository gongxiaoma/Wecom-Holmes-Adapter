#!/usr/bin/env bash
set -euo pipefail

: "${WECHAT_BOT_ID:?Please export WECHAT_BOT_ID}"
: "${WECHAT_BOT_SECRET:?Please export WECHAT_BOT_SECRET}"

kubectl -n sre-ai create secret generic wecom-holmes-adapter \
  --from-literal=WECHAT_BOT_ID="${WECHAT_BOT_ID}" \
  --from-literal=WECHAT_BOT_SECRET="${WECHAT_BOT_SECRET}" \
  --from-literal=HOLMES_API_KEY="${HOLMES_API_KEY:-}" \
  --dry-run=client -o yaml | kubectl apply -f -
