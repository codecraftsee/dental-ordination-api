#!/usr/bin/env bash
#
# Deploy the API to the pre-production server. Run from your Mac.
#
#   export DENTAL_SERVER=deploy@5.161.42.7
#   ./deploy/deploy-api.sh
#
# Assumes the branch is already pushed. The usual sequence is:
#   git checkout preprod && git pull
#   git merge --no-ff develop -m "preprod: cut build $(date +%F)"
#   git push
#   ./deploy/deploy-api.sh
set -euo pipefail

SERVER="${DENTAL_SERVER:?Set DENTAL_SERVER, e.g. export DENTAL_SERVER=deploy@5.161.42.7}"
REMOTE_DIR="${DENTAL_REMOTE_DIR:-/opt/dental}"
BRANCH="${DENTAL_BRANCH:-preprod}"

echo "==> Deploying '${BRANCH}' to ${SERVER}:${REMOTE_DIR}"

ssh "$SERVER" bash -s <<EOF
set -euo pipefail

cd "${REMOTE_DIR}/app"

echo "--> Fetching ${BRANCH}"
git fetch --prune origin
git checkout "${BRANCH}"
# Hard reset: this clone is a deploy artifact, not a workspace. Any local edit
# made on the server is intentionally discarded so the running code always
# matches origin/${BRANCH} exactly.
git reset --hard "origin/${BRANCH}"
git --no-pager log -1 --pretty='    now at %h %s'

echo "--> Rebuilding containers"
docker compose --env-file "${REMOTE_DIR}/.env" up -d --build

echo "--> Pruning dangling images"
docker image prune -f >/dev/null

docker compose --env-file "${REMOTE_DIR}/.env" ps
EOF

echo "==> Waiting for the API to report healthy"
API_HOST="$(ssh "$SERVER" "grep -E '^API_HOST=' ${REMOTE_DIR}/.env | cut -d= -f2-")"

for i in $(seq 1 30); do
	if curl -fsS "https://${API_HOST}/health" 2>/dev/null; then
		echo
		echo "==> Deploy complete: https://${API_HOST}"
		exit 0
	fi
	sleep 2
done

echo
echo "!! API did not become healthy within 60s. Check logs:" >&2
echo "   ssh ${SERVER} 'cd ${REMOTE_DIR}/app && docker compose --env-file ${REMOTE_DIR}/.env logs --tail=50'" >&2
exit 1
