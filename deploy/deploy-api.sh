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

# Tag the image with the commit it was built from. Everything about rollback
# depends on this, and so does being able to answer "what is actually running"
# — with a fixed tag, a redeploy that changes nothing and a redeploy that
# changes everything look identical.
export IMAGE_TAG="\$(git rev-parse --short HEAD)"

echo "--> Rebuilding containers (image tag: \${IMAGE_TAG})"
docker compose --env-file "${REMOTE_DIR}/.env" up -d --build

# Keep the five most recent images so rollback-api.sh has somewhere to go.
# \`docker image prune\` cannot do this job any more: it only removes *dangling*
# images, and every image here is now tagged, so they would accumulate forever.
# \`docker rmi\` refuses to remove an image a container is using, which is the
# safety net for whichever build is currently live.
# Written on one line on purpose: this heredoc is unquoted, so a trailing
# backslash would be eaten as a line continuation before the server ever sees it.
echo "--> Trimming old images (keeping the newest 5)"
docker images dental-api --format '{{.Repository}}:{{.Tag}}' | tail -n +6 | xargs -r docker rmi >/dev/null 2>&1 || true

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
