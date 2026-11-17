#!/usr/bin/env bash
# ci/db-stop.sh <staging|production>   (make db-stop ENV=...)
#
# Parks an env's Aurora cluster while it is not needed (usually staging), so it
# costs nothing and cannot spike: closes the demo first (kill switch `closed`,
# the landing page shows the offline copy), then stops the cluster. Already
# stopped or stopping is fine. Bring it back with `make db-start ENV=...`.
# Deploys to a stopped env stop early and say the same. AWS starts a stopped
# cluster by itself after 7 days; the demo stays closed until db-start runs.
set -euo pipefail
# shellcheck source=ci/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[ $# -eq 1 ] || die "usage: ci/db-stop.sh <staging|production>"
ENV_NAME="$1"
require_env_name "$ENV_NAME"

REGION="us-east-2"
CLUSTER="phoebe-$ENV_NAME"
TABLE="phoebe-$ENV_NAME-state"

status="$(aws rds describe-db-clusters --db-cluster-identifier "$CLUSTER" \
  --query 'DBClusters[0].Status' --output text --region "$REGION")"
log "$CLUSTER is $status"

case "$status" in
  stopped | stopping)
    log "nothing to do; restart with: make db-start ENV=$ENV_NAME"
    exit 0
    ;;
  available) ;;
  *) die "$CLUSTER is $status; run make db-stop ENV=$ENV_NAME again once it is available" ;;
esac

# Same item as DynamoDBControlStore: pk=control.
aws dynamodb put-item --table-name "$TABLE" --region "$REGION" \
  --item '{"pk":{"S":"control"},"state":{"S":"closed"}}'
log "$ENV_NAME demo closed"

aws rds stop-db-cluster --db-cluster-identifier "$CLUSTER" --region "$REGION" \
  --output text --query 'DBCluster.Status' >/dev/null
log "stopping $CLUSTER; restart with: make db-start ENV=$ENV_NAME"
