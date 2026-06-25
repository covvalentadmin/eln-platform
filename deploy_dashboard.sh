#!/bin/bash
# ================================================================
# ELN Platform — Build & Deploy Dashboard to Azure Static Web App
# Run from Cloud Shell after restore_session.sh
# ================================================================

set -e

echo "=== Build Dashboard ==="
cd ~/eln-dashboard
REACT_APP_API_URL=https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net \
  npm run build

echo ""
echo "=== Deploy to Static Web App ==="
SWA_TOKEN=$(az staticwebapp secrets list \
  --name eln-dashboard-covvalent \
  --query "properties.apiKey" \
  -o tsv)

npx @azure/static-web-apps-cli@1.1.7 deploy ./build \
  --deployment-token "$SWA_TOKEN" \
  --env production

echo "Dashboard deployed."
