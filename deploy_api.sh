#!/bin/bash
# ================================================================
# ELN Platform — Deploy API to Azure App Service
# Run from Cloud Shell after restore_session.sh
# ================================================================

set -e

echo "=== Deploy API ==="
cd ~/eln-api
zip -r ~/eln-api-deploy.zip main.py requirements.txt startup.sh routers/ prompts/

# Sanity check before shipping — this exact omission (prompts/ missing from
# the zip) caused a full production outage on 22 Jul 2026: agent_v2.py reads
# prompts/agent_tools_current_export.json at import time with no fallback,
# so its absence crashes the entire app on every container start, not just
# one feature. Never skip this check.
if ! unzip -l ~/eln-api-deploy.zip | grep -q "prompts/agent_tools_current_export.json"; then
  echo "FATAL: prompts/agent_tools_current_export.json is missing from the deploy zip. Aborting." >&2
  exit 1
fi

az webapp deploy \
  --name eln-api-covvalent \
  --resource-group rg-eln-covvalent \
  --src-path ~/eln-api-deploy.zip \
  --type zip \
  --async true

echo "API deployment triggered."
