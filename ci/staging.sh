#!/usr/bin/env bash
# ci/staging.sh: phoebe-staging (push to main). Builds the two images from
# backend/Dockerfile, pushes them to ECR phoebe-api as <sha> (api)
# and <sha>-jobs (jobs), reads their digests back from ECR, then runs
# ci/deploy.sh staging <api_digest> <jobs_digest>.
#
# Tags are immutable, so a retried build for the same commit reuses the images
# it already pushed instead of failing on the push.
set -euo pipefail
# shellcheck source=ci/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SHA="${CODEBUILD_RESOLVED_SOURCE_VERSION:-}"
require_commit CODEBUILD_RESOLVED_SOURCE_VERSION "$SHA"

REGISTRY="$(account_id).dkr.ecr.$AWS_REGION.amazonaws.com"
IMAGE="$REGISTRY/$ECR_REPO"

cd "$REPO_ROOT"
log "ECR login $REGISTRY"
aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null

# build_push <target> <tag>: prints nothing; sets ECR_DIGEST to the pushed digest.
build_push() {
  if ecr_digest "$2"; then
    log "$ECR_REPO:$2 already pushed ($ECR_DIGEST); reusing it"
    return 0
  fi
  log "build $1 -> $ECR_REPO:$2"
  # Single-platform manifests (no provenance/SBOM index), which Lambda accepts.
  docker buildx build --platform linux/arm64 --target "$1" -f backend/Dockerfile \
    --provenance=false --sbom=false -t "$IMAGE:$2" --push .
  ecr_digest "$2" || die "$ECR_REPO:$2 not found after push"
}

build_push api "$SHA"
API_DIGEST="$ECR_DIGEST"
build_push jobs "$SHA-jobs"
JOBS_DIGEST="$ECR_DIGEST"
log "api $API_DIGEST jobs $JOBS_DIGEST"

bash "$REPO_ROOT/ci/deploy.sh" staging "$API_DIGEST" "$JOBS_DIGEST"
