#!/usr/bin/env bash
#
# Roll the API back to a previously deployed image, without rebuilding.
#
#   export DENTAL_SERVER=deploy@5.161.42.7
#   ./deploy/rollback-api.sh              # list the images available on the server
#   ./deploy/rollback-api.sh 8261283      # switch to that one
#
# Images are tagged with the commit they were built from (see deploy-api.sh),
# and the five most recent are kept, so this is normally seconds: no fetch, no
# pip install, no build.
#
# TWO THINGS THIS DOES NOT DO, both deliberate:
#
#  1. It does not touch the git clone on the server. The clone stays on
#     whatever `preprod` points at, so the next deploy-api.sh run rebuilds from
#     the branch and silently undoes this rollback. That is the intended shape
#     — a rollback buys time to fix forward or to reset the branch, it is not a
#     state you should sit in.
#  2. It does not roll back the database. app/main.py runs DDL at startup, so
#     an older image re-executes an older version of those statements against a
#     schema a newer build may already have changed. If the deploy you are
#     backing out of altered the schema, check the app comes up before assuming
#     you are safe.
set -euo pipefail

SERVER="${DENTAL_SERVER:?Set DENTAL_SERVER, e.g. export DENTAL_SERVER=deploy@5.161.42.7}"
REMOTE_DIR="${DENTAL_REMOTE_DIR:-/opt/dental}"
TAG="${1:-}"

if [[ -z "$TAG" ]]; then
	echo "==> Images available on ${SERVER} (newest first)"
	ssh "$SERVER" "docker images dental-api --format '    {{.Tag}}\t{{.CreatedSince}}'"
	echo
	echo "Usage: $0 <tag>"
	exit 0
fi

echo "==> Rolling ${SERVER} back to dental-api:${TAG}"

ssh "$SERVER" bash -s <<EOF
set -euo pipefail

if ! docker image inspect "dental-api:${TAG}" >/dev/null 2>&1; then
	echo "!! No image dental-api:${TAG} on this server. Available:" >&2
	docker images dental-api --format '    {{.Tag}}  ({{.CreatedSince}})' >&2
	exit 1
fi

cd "${REMOTE_DIR}/app"

# --no-build is the whole point: use the image that is already on disk rather
# than rebuilding whatever the clone currently points at.
export IMAGE_TAG="${TAG}"
docker compose --env-file "${REMOTE_DIR}/.env" up -d --no-build

docker compose --env-file "${REMOTE_DIR}/.env" ps
EOF

echo "==> Waiting for the API to report healthy"
API_HOST="$(ssh "$SERVER" "grep -E '^API_HOST=' ${REMOTE_DIR}/.env | cut -d= -f2-")"

for i in $(seq 1 30); do
	if curl -fsS "https://${API_HOST}/health" 2>/dev/null; then
		echo
		echo "==> Rolled back to ${TAG}: https://${API_HOST}"
		echo "    The server's clone is untouched — the next deploy will rebuild from the branch."
		exit 0
	fi
	sleep 2
done

echo
echo "!! API did not become healthy within 60s. Check logs:" >&2
echo "   ssh ${SERVER} 'cd ${REMOTE_DIR}/app && docker compose --env-file ${REMOTE_DIR}/.env logs --tail=50'" >&2
exit 1
