#!/bin/bash
# ================================================================
# ELN Platform — Deploy API to Azure App Service
# Run from Cloud Shell after restore_session.sh
# ================================================================

set -e

echo "=== Deploy API ==="
cd ~/eln-api
zip -r ~/eln-api-deploy.zip main.py requirements.txt startup.sh routers/

az webapp deploy \
  --name eln-api-covvalent \
  --resource-group rg-eln-covvalent \
  --src-path ~/eln-api-deploy.zip \
  --type zip \
  --async true

echo "API deployment triggered."
