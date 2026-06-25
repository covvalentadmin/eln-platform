#!/bin/bash
# ============================================================
# ELN Platform — Cloud Shell Session Restore Script
# Run at the start of EVERY new Cloud Shell session
# ============================================================

set -e

echo "=== 1. Set subscription ==="
az account set --subscription 9e25d11c-3753-4b8c-a575-0bcc44f964d4
az account show --query "{name:name,id:id}" -o table

echo ""
echo "=== 2. Create directory structure ==="
mkdir -p ~/eln-api/routers ~/eln-api/prompts
mkdir -p ~/eln-dashboard/src ~/eln-dashboard/public
echo "Directories ready"

echo ""
echo "=== 3. Restore eln-api from live App Service ==="
# Download live deployment zip via Kudu
TOKEN=$(az account get-access-token \
  --resource https://management.azure.com \
  --query accessToken -o tsv)

HTTP_STATUS=$(curl -s -o ~/eln-api-live.zip -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  "https://eln-api-covvalent.scm.southindia-01.azurewebsites.net/api/zip/site/wwwroot/")

if [ "$HTTP_STATUS" = "200" ] && [ -s ~/eln-api-live.zip ]; then
  echo "Kudu zip downloaded (HTTP $HTTP_STATUS)"
  cd ~/eln-api
  unzip -o ~/eln-api-live.zip
  echo "API source restored from live deployment"
else
  echo "WARNING: Kudu zip failed (HTTP $HTTP_STATUS) — upload source files manually"
fi

echo ""
echo "=== 4. Smoke tests ==="
echo "--- Health ---"
curl -s https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net/health

echo ""
echo "--- SQL check ---"
curl -s https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net/health/sql | python3 -m json.tool | head -20

echo ""
echo "--- Efficiency endpoint ---"
curl -s "https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net/api/dashboard/efficiency" | python3 -m json.tool | head -20

echo ""
echo "--- Agent ---"
AGENT_TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)
curl -s "https://aifoundry-eln-covvalent.services.ai.azure.com/api/projects/eln-agent-project/assistants/asst_iujfiErrYF9CfqgyB6BqY4Xn?api-version=2025-05-15-preview" \
  -H "Authorization: Bearer $AGENT_TOKEN" | python3 -m json.tool | grep -E '"model"|"name"'

echo ""
echo "=== 5. Deploy commands (use when ready) ==="
echo ""
echo "-- Deploy API --"
echo 'cd ~/eln-api && zip -r ~/eln-api.zip . --exclude "antenv/*" && az webapp deploy --name eln-api-covvalent --resource-group rg-eln-covvalent --src-path ~/eln-api.zip --type zip --async true'
echo ""
echo "-- Deploy Dashboard --"
echo 'cd ~/eln-dashboard && REACT_APP_API_URL=https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net npm run build'
echo 'SWA_TOKEN=$(az staticwebapp secrets list --name eln-dashboard-covvalent --query "properties.apiKey" -o tsv)'
echo 'npx @azure/static-web-apps-cli@1.1.7 deploy ./build --deployment-token "$SWA_TOKEN" --env production'

echo ""
echo "=== Session restore complete ==="
