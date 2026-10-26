#!/usr/bin/env bash
# Deploy one image digest with Docker Compose and roll back when the new container is not healthy.
#   sudo /opt/fdo-knowledge-dashboard/deploy/deploy.sh ghcr.io/fair2adapt/fdo-knowledge-dashboard@sha256:<digest>
set -euo pipefail
DASHBOARD_DIR=${DASHBOARD_DIR:-/opt/fdo-knowledge-dashboard}
IMAGE=${1:?image reference by digest}
[[ "$IMAGE" =~ ^ghcr\.io/[a-z0-9][a-z0-9._/-]{0,200}@sha256:[0-9a-f]{64}$ ]] || { echo "refused: not an image reference by digest" >&2; exit 2; }
cd "$DASHBOARD_DIR"
current=$(cat .current 2>/dev/null || true)
docker pull "$IMAGE"
[ -n "$current" ] && printf '%s\n' "$current" > .previous
printf '%s\n' "$IMAGE" > .current
DASHBOARD_IMAGE="$IMAGE" docker compose up -d --no-deps --wait --wait-timeout 90 dashboard && { echo "deployed $IMAGE"; exit 0; }
echo "new container unhealthy; rolling back" >&2
if [ -n "$current" ]; then
  printf '%s\n' "$current" > .current
  DASHBOARD_IMAGE="$current" docker compose up -d --no-deps --wait --wait-timeout 90 dashboard
  echo "rolled back to $current" >&2
fi
exit 1
