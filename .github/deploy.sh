#!/usr/bin/env bash
# Deploys the item service (GitHub Actions, deploy job): copies this checkout to the
# server, then rebuilds and restarts the items service with BalatroFrontEnd's
# docker-compose.yml and waits until it is healthy. Until the front end has
# been deployed once (it brings the compose file), the code is only copied.
#
# The server keeps, in DEPLOY_PATH (/opt/balatro):
#   BalatroFrontEnd/   the front end and docker-compose.yml (its own deployment)
#   BalatroItemService/     this repository (copied here)
#   balatro_src/       a copy of the game, for the front end's image
#
# env: DEPLOY_HOST, DEPLOY_USER, DEPLOY_SSH_KEY, DEPLOY_KNOWN_HOSTS,
#      DEPLOY_PORT (22), DEPLOY_PATH (/opt/balatro)
set -euo pipefail

: "${DEPLOY_HOST:?}" "${DEPLOY_USER:?}" "${DEPLOY_SSH_KEY:?}" "${DEPLOY_KNOWN_HOSTS:?}"
port="${DEPLOY_PORT:-22}"
root="${DEPLOY_PATH:-/opt/balatro}"
target="$DEPLOY_USER@$DEPLOY_HOST"

mkdir -p ~/.ssh
chmod 700 ~/.ssh
printf '%s\n' "$DEPLOY_SSH_KEY" > ~/.ssh/deploy_key
chmod 600 ~/.ssh/deploy_key
printf '%s\n' "$DEPLOY_KNOWN_HOSTS" > ~/.ssh/deploy_known_hosts
ssh_cmd="ssh -i $HOME/.ssh/deploy_key -p $port -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOME/.ssh/deploy_known_hosts"

$ssh_cmd "$target" "mkdir -p '$root/BalatroItemService'"
rsync -az --delete -e "$ssh_cmd" \
  --exclude .git --exclude .venv --exclude __pycache__ --exclude .pytest_cache \
  --exclude .mypy_cache --exclude .ruff_cache --exclude '*.db' --exclude .env \
  ./ "$target:$root/BalatroItemService/"

$ssh_cmd "$target" bash -s -- "$root" <<'REMOTE'
set -euo pipefail
root="$1"
# one deployment at a time (the front end's deploys here too)
exec 9>"$root/.deploy.lock"
flock 9
if [ ! -f "$root/BalatroFrontEnd/docker-compose.yml" ]; then
  echo "::notice::The item service's code is on the server; it starts with the first deployment of BalatroFrontEnd (which has docker-compose.yml)"
  exit 0
fi
cd "$root/BalatroFrontEnd"
# the service and its database come with the front end's compose file
if ! docker compose config --services | grep -qx items; then
  echo "::warning::The item service's code is on the server; it starts once BalatroFrontEnd's docker-compose.yml (main) has the items service: deploy BalatroFrontEnd"
  exit 0
fi
docker compose up -d --build items
cid="$(docker compose ps -q items)"
status=starting
for _ in $(seq 90); do
  status="$(docker inspect -f '{{.State.Health.Status}}' "$cid")"
  [ "$status" = healthy ] && break
  [ "$status" = unhealthy ] && break
  sleep 2
done
docker compose ps
if [ "$status" != healthy ]; then
  docker compose logs --tail 80 items
  echo "::error::the items service is $status"
  exit 1
fi
docker image prune -f > /dev/null
REMOTE
