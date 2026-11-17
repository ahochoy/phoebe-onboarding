#!/usr/bin/env bash
# ci/db-start.sh <staging|production>   (make db-start ENV=...)
#
# Brings an env back after its Aurora cluster was stopped (the project's spend
# limit, or by hand): starts the cluster unless it is already available, waits
# for `available`, then reopens the demo (kill switch `open`). Run by the owner
# from a terminal with their AWS credentials. Nothing runs this automatically:
# starting the cluster spends money.
set -euo pipefail
# shellcheck source=ci/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[ $# -eq 1 ] || die "usage: ci/db-start.sh <staging|production>"
ENV_NAME="$1"
require_env_name "$ENV_NAME"

REGION="us-east-2"
CLUSTER="phoebe-$ENV_NAME"
TABLE="phoebe-$ENV_NAME-state"

status="$(aws rds describe-db-clusters --db-cluster-identifier "$CLUSTER" \
  --query 'DBClusters[0].Status' --output text --region "$REGION")"
log "$CLUSTER is $status"

case "$status" in
  available) ;;
  stopping) die "$CLUSTER is still stopping; run make db-start ENV=$ENV_NAME again in a few minutes" ;;
  starting) ;;
  *)
    log "starting $CLUSTER"
    aws rds start-db-cluster --db-cluster-identifier "$CLUSTER" \
      --region "$REGION" --output text --query 'DBCluster.Status' >/dev/null
    ;;
esac

log "waiting for $CLUSTER to be available (usually a few minutes)"
aws rds wait db-cluster-available --db-cluster-identifier "$CLUSTER" --region "$REGION" ||
  die "$CLUSTER did not become available; the demo stays closed"

# Same item as DynamoDBControlStore: pk=control.
aws dynamodb put-item --table-name "$TABLE" --region "$REGION" \
  --item '{"pk":{"S":"control"},"state":{"S":"open"}}'
log "$ENV_NAME is open"
