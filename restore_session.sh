#!/bin/bash
# ================================================================
# ELN Platform — Cloud Shell Session Restore
# Fill in YOUR_PAT_HERE, then:  bash ~/eln-api/restore_session.sh
# ================================================================

# ---- Paste your GitHub PAT here before running ----------------
PAT="YOUR_PAT_HERE"
# ---------------------------------------------------------------

set -e

REPO_URL="https://covvalentadmin:${PAT}@github.com/covvalentadmin/eln-platform.git"
API_DIR=~/eln-api
DASH_DIR=~/eln-dashboard
API_BASE="https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net"

echo "=== 1. Azure subscription ==="
az account set --subscription 9e25d11c-3753-4b8c-a575-0bcc44f964d4
az account show --query "{name:name,id:id}" -o table

echo ""
echo "=== 2. Git identity ==="
git config --global user.email "aqeedat.kaur.sandhu@covvalent.com"
git config --global user.name "Aqeedat Kaur Sandhu"
echo "Git identity set"

echo ""
echo "=== 3. Clone / update repo ==="
if [ -d "$API_DIR/.git" ]; then
  echo "Repo exists — pulling latest"
  git -C "$API_DIR" remote set-url origin "$REPO_URL"
  git -C "$API_DIR" pull
else
  echo "Cloning repo to $API_DIR"
  git clone "$REPO_URL" "$API_DIR"
fi

echo ""
echo "=== 4. Health check ==="
curl -sf "$API_BASE/health" && echo "" || echo "WARNING: health check failed"

echo ""
echo "=== 5. Dashboard build workspace ==="
mkdir -p "$DASH_DIR/src" "$DASH_DIR/public"
cp "$API_DIR/dashboard/AIChatPanel.js"           "$DASH_DIR/src/"
cp "$API_DIR/dashboard/App.js"                   "$DASH_DIR/src/"
cp "$API_DIR/dashboard/index.js"                 "$DASH_DIR/src/"
cp "$API_DIR/dashboard/index.html"               "$DASH_DIR/public/"
cp "$API_DIR/dashboard/package.json"             "$DASH_DIR/"
cp "$API_DIR/dashboard/staticwebapp.config.json" "$DASH_DIR/"
echo "Dashboard files copied from repo"

echo ""
echo "=== 6. npm install ==="
cd "$DASH_DIR"
npm install

echo ""
echo "Session restored. Run deploy_api.sh or deploy_dashboard.sh to deploy."
