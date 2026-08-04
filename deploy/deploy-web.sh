#!/usr/bin/env bash
#
# Deploy the Angular admin app to the pre-production server. Run from your Mac.
#
#   export DENTAL_SERVER=deploy@5.161.42.7
#   ./deploy/deploy-web.sh
#
# REQUIRES a `staging` build configuration in the Angular repo's angular.json,
# with a matching src/environments/environment.staging.ts pointing apiUrl at
# https://$API_HOST. Until that exists this script exits early rather than
# shipping a bundle that still points at Railway.
set -euo pipefail

SERVER="${DENTAL_SERVER:?Set DENTAL_SERVER, e.g. export DENTAL_SERVER=deploy@5.161.42.7}"
REMOTE_DIR="${DENTAL_REMOTE_DIR:-/opt/dental}"
WEB_REPO="${DENTAL_WEB_REPO:-../dental-ordination}"
BRANCH="${DENTAL_BRANCH:-preprod}"

cd "$WEB_REPO"
WEB_ROOT="$(pwd)"
echo "==> Frontend repo: ${WEB_ROOT}"

if ! grep -q '"staging"' angular.json; then
	echo "!! No 'staging' configuration found in angular.json." >&2
	echo "!! Add a 'staging' configuration to angular.json (with a matching" >&2
	echo "!! src/environments/environment.staging.ts) before deploying." >&2
	exit 1
fi

CURRENT_BRANCH="$(git branch --show-current)"
if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
	echo "!! On branch '${CURRENT_BRANCH}', expected '${BRANCH}'." >&2
	echo "!! git checkout ${BRANCH} && git pull" >&2
	exit 1
fi

echo "==> Installing dependencies"
npm ci

echo "==> Building (configuration: staging, base-href: /)"
npx ng build --configuration staging --base-href /

DIST="dist/dental-ordination/browser"
[[ -f "${DIST}/index.html" ]] || { echo "!! ${DIST}/index.html missing" >&2; exit 1; }

echo "==> Syncing to ${SERVER}:${REMOTE_DIR}/www"
# --delete removes stale hashed bundles from previous builds. Safe: this
# directory holds only build output.
rsync -avz --delete "${DIST}/" "${SERVER}:${REMOTE_DIR}/www/"

ADMIN_HOST="$(ssh "$SERVER" "grep -E '^ADMIN_HOST=' ${REMOTE_DIR}/.env | cut -d= -f2-")"
echo "==> Deploy complete: https://${ADMIN_HOST}"
