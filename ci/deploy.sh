#!/usr/bin/env bash
# ci/deploy.sh <env> <api_digest> <jobs_digest>
#
# Deploys one env of infra/app and publishes the SPA. Runs in CodeBuild only
# (phoebe-staging, phoebe-release-apply). Steps:
#   1. terraform init + apply in infra/app. Staging applies with the two
#      digests; production applies the approved saved plan in $PHOEBE_PLAN_FILE
#      (no re-plan). infra/ai is never applied here (ruling R12).
#   2. ops `migrate`, then ops `seed_if_empty`.
#   3. npm ci + build (base /), then sync to the site bucket with the R11
#      caching contract (infra/app/README.md), leaving previews/ and
#      seed-sources/ alone, and upload the seed sources.
#   4. Invalidate /* and wait, then ci/smoke.sh.
#
# Optional env: STATE_BUCKET (default phoebe-tfstate-<account_id>),
# PHOEBE_PLAN_FILE (production: the saved plan to apply).
set -euo pipefail
# shellcheck source=ci/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[ $# -eq 3 ] || die "usage: ci/deploy.sh <staging|production> <api_digest> <jobs_digest>"
ENV_NAME="$1"
API_DIGEST="$2"
JOBS_DIGEST="$3"
require_env_name "$ENV_NAME"
require_digest api_digest "$API_DIGEST"
require_digest jobs_digest "$JOBS_DIGEST"
PLAN_FILE="${PHOEBE_PLAN_FILE:-}"

log "deploy $ENV_NAME api=$API_DIGEST jobs=$JOBS_DIGEST"

# ---- 1. infra/app ------------------------------------------------------------------
cd "$REPO_ROOT/infra/app"
tf_init "$ENV_NAME"
if [ -n "$PLAN_FILE" ]; then
  [ -f "$PLAN_FILE" ] || die "saved plan not found: $PLAN_FILE"
  log "terraform apply (saved plan $(basename "$PLAN_FILE"))"
  terraform apply -input=false -no-color -compact-warnings "$PLAN_FILE"
else
  [ "$ENV_NAME" = staging ] || die "production applies only an approved saved plan (set PHOEBE_PLAN_FILE)"
  log "terraform apply ($ENV_NAME)"
  terraform apply -input=false -no-color -compact-warnings -auto-approve \
    "-var-file=envs/$ENV_NAME.tfvars" \
    -var "api_image_digest=$API_DIGEST" -var "jobs_image_digest=$JOBS_DIGEST"
fi

tf_out() { terraform output -no-color -raw "$1"; }
SITE_URL="$(tf_out site_url)"
SITE_BUCKET="$(tf_out site_bucket)"
OPS_FUNCTION="$(tf_out ops_function_name)"
FUNCTION_URL="$(tf_out api_function_url)"
DISTRIBUTION_ID="$(tf_out distribution_id)"
log "site $SITE_URL bucket $SITE_BUCKET distribution $DISTRIBUTION_ID"

# ---- 2. ops tasks ------------------------------------------------------------------
# Successful results are metadata (migration names, seed counts), safe to log.
# A function error's message or trace can quote config, so only its
# errorType is logged; the full error is in the ops Lambda's own log group.
invoke_ops() {
  local task="$1" out meta kind
  out="$(mktemp)"
  meta="$(aws lambda invoke --function-name "$OPS_FUNCTION" \
    --cli-binary-format raw-in-base64-out --cli-read-timeout 900 \
    --payload "{\"task\":\"$task\"}" "$out")" || die "ops $task: invoke failed"
  if grep -q FunctionError <<<"$meta"; then
    kind="$(jq -r '.errorType // "unknown"' "$out" 2>/dev/null || echo unknown)"
    kind="${kind//[^A-Za-z0-9_.]/}"
    rm -f "$out"
    die "ops $task: function error ($kind); see /aws/lambda/$OPS_FUNCTION"
  fi
  if grep -q '"error"' "$out"; then
    kind="$(jq -r '.error' "$out" 2>/dev/null || echo unknown)"
    kind="${kind//[^A-Za-z0-9_.]/}"
    rm -f "$out"
    die "ops $task: returned error '$kind'"
  fi
  log "ops $task: $(head -c 500 "$out")"
  rm -f "$out"
}
invoke_ops migrate
invoke_ops seed_if_empty

# ---- 3. SPA ------------------------------------------------------------------------
cd "$REPO_ROOT/frontend"
log "frontend build (base /)"
npm ci --no-audit --no-fund
VITE_SITE_ORIGIN="$SITE_URL" PHOEBE_BASE=/ npm run build

DIST="$REPO_ROOT/frontend/dist"
DEST="s3://$SITE_BUCKET"
# Caching contract (R11): hashed assets/ are immutable for a year; index.html
# and the other root files are revalidated on every request. Assets go first
# so a new index.html never points at a missing file.
log "sync assets/ (immutable)"
aws s3 sync "$DIST/assets/" "$DEST/assets/" --only-show-errors \
  --cache-control "public, max-age=31536000, immutable"
log "sync root files (no-cache)"
aws s3 sync "$DIST/" "$DEST/" --only-show-errors --exclude "assets/*" \
  --exclude "previews/*" --exclude "seed-sources/*" \
  --cache-control "no-cache"
log "prune stale files"
# Everything is already uploaded, so this pass only deletes (size-only, so it
# never re-uploads a file without its Cache-Control).
aws s3 sync "$DIST/" "$DEST/" --only-show-errors --delete --size-only \
  --exclude "previews/*" --exclude "seed-sources/*"

log "upload seed sources"
for f in benefits.html project-manifest.txt; do
  aws s3 cp "$REPO_ROOT/backend/seed/content/$f" "$DEST/seed-sources/$f" \
    --only-show-errors --cache-control "no-cache"
done

# ---- 4. invalidate + smoke ---------------------------------------------------------
log "invalidate /*"
INVALIDATION_ID="$(aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION_ID" \
  --paths "/*" --query Invalidation.Id --output text)"
aws cloudfront wait invalidation-completed --distribution-id "$DISTRIBUTION_ID" --id "$INVALIDATION_ID"
log "invalidation $INVALIDATION_ID complete"

bash "$REPO_ROOT/ci/smoke.sh" "$SITE_URL" "$FUNCTION_URL"
log "deploy $ENV_NAME done"
