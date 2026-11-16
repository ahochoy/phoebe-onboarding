#!/usr/bin/env bash
# ci/release-apply.sh [plan_dir]: phoebe-release-apply (pipeline Apply stage,
# after the owner approved the plan), run as phoebe-ci-deploy-production.
#
#   1. Reads release.env from the `plan` artifact ($CODEBUILD_SRC_DIR_plan) and
#      checks it: the commit matches $RELEASE_COMMIT, digests and tag are well
#      formed.
#   2. Checks the release tags (ruling R13). release-<tag> and
#      release-<tag>-jobs may already exist (phoebe-ci-deploy-staging can push
#      any tag); that is fine only if they point at the digests being promoted.
#      Anything else stops the release before any change.
#   3. ci/deploy.sh production with PHOEBE_PLAN_FILE=<plan_dir>/production.tfplan:
#      applies that saved plan (no re-plan), migrates, seeds, publishes the
#      SPA, smoke-tests.
#   4. Adds the missing release tags to the promoted digests (BatchGetImage for
#      the manifest, PutImage under the new tag). ECR lifecycle rule 1 keeps
#      release-* images forever.
set -euo pipefail
# shellcheck source=ci/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PLAN_DIR="${1:-${CODEBUILD_SRC_DIR_plan:-}}"
[ -n "$PLAN_DIR" ] && [ -d "$PLAN_DIR" ] || die "plan artifact directory not found (CODEBUILD_SRC_DIR_plan)"
PLAN_FILE="$PLAN_DIR/production.tfplan"
[ -f "$PLAN_FILE" ] || die "saved plan not found: $PLAN_FILE"
[ -f "$PLAN_DIR/release.env" ] || die "release.env not found in $PLAN_DIR"

# Parse release.env as data (never `source` it).
R_COMMIT="" R_TAG="" R_API="" R_JOBS=""
while IFS='=' read -r key value || [ -n "$key" ]; do
  case "$key" in
    RELEASE_COMMIT) R_COMMIT="$value" ;;
    RELEASE_TAG) R_TAG="$value" ;;
    API_IMAGE_DIGEST) R_API="$value" ;;
    JOBS_IMAGE_DIGEST) R_JOBS="$value" ;;
    "") ;;
    *) die "unexpected key in release.env: $key" ;;
  esac
done <"$PLAN_DIR/release.env"
require_commit RELEASE_COMMIT "$R_COMMIT"
require_git_tag "$R_TAG"
require_digest API_IMAGE_DIGEST "$R_API"
require_digest JOBS_IMAGE_DIGEST "$R_JOBS"
if [ -n "${RELEASE_COMMIT:-}" ] && [ "$RELEASE_COMMIT" != "$R_COMMIT" ]; then
  die "the saved plan is for commit $R_COMMIT, but this run is for $RELEASE_COMMIT"
fi
log "release $R_TAG commit $R_COMMIT api $R_API jobs $R_JOBS"

# check_tag <tag> <digest>: prints "new" or "present"; dies on a conflict.
check_tag() {
  if ecr_digest "$1"; then
    [ "$ECR_DIGEST" = "$2" ] ||
      die "$ECR_REPO:$1 already exists at $ECR_DIGEST, not the promoted digest $2. Tags are immutable; refusing to release."
    echo present
  else
    echo new
  fi
}
API_TAG="release-$R_TAG"
JOBS_TAG="release-$R_TAG-jobs"
API_TAG_STATE="$(check_tag "$API_TAG" "$R_API")"
JOBS_TAG_STATE="$(check_tag "$JOBS_TAG" "$R_JOBS")"

PHOEBE_PLAN_FILE="$PLAN_FILE" bash "$REPO_ROOT/ci/deploy.sh" production "$R_API" "$R_JOBS"

# put_tag <tag> <digest>
put_tag() {
  local resp manifest media
  resp="$(aws ecr batch-get-image --repository-name "$ECR_REPO" --image-ids "imageDigest=$2" --output json)"
  manifest="$(jq -r '.images[0].imageManifest // empty' <<<"$resp")"
  media="$(jq -r '.images[0].imageManifestMediaType // empty' <<<"$resp")"
  [ -n "$manifest" ] && [ -n "$media" ] || die "no manifest for $ECR_REPO@$2"
  if ! aws ecr put-image --repository-name "$ECR_REPO" --image-tag "$1" --image-digest "$2" \
    --image-manifest "$manifest" --image-manifest-media-type "$media" >/dev/null; then
    # Lost a race with another writer: fine only if it is the same digest.
    [ "$(check_tag "$1" "$2")" = present ] || die "could not tag $ECR_REPO@$2 as $1"
  fi
  log "tagged $ECR_REPO@$2 as $1"
}
if [ "$API_TAG_STATE" = new ]; then put_tag "$API_TAG" "$R_API"; else log "$API_TAG already on $R_API"; fi
if [ "$JOBS_TAG_STATE" = new ]; then put_tag "$JOBS_TAG" "$R_JOBS"; else log "$JOBS_TAG already on $R_JOBS"; fi
log "release $R_TAG done"
