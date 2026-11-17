#!/usr/bin/env bash
# ci/release-plan.sh [out_dir]: phoebe-release-plan (pipeline Plan stage, run
# as the read-only phoebe-ci-plan-production).
#
#   1. Resolves the tag commit's two images, phoebe-api:<sha> and <sha>-jobs,
#      to digests. Missing means the commit never went through phoebe-staging,
#      and the release stops here.
#   2. Finds the v* git tag on that commit with `git tag --points-at` in the
#      CODEBUILD_CLONE_REF clone (R17; the source variables carry no tag). If
#      several, the highest by `sort -V`; none stops the release.
#   3. terraform plan -lock=false for production, saved to
#      <out_dir>/production.tfplan, plus <out_dir>/release.env with the commit,
#      tag and digests. Both are the pipeline's `plan` artifact; release-apply
#      applies that exact plan.
#
# Env: RELEASE_COMMIT (required; the clone's HEAD must be this commit).
# The plan output goes to the build log for the approver; Terraform redacts
# sensitive values in it.
set -euo pipefail
# shellcheck source=ci/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

OUT_DIR="${1:-$REPO_ROOT/release-out}"
COMMIT="${RELEASE_COMMIT:-}"
require_commit RELEASE_COMMIT "$COMMIT"

missing() {
  die "$ECR_REPO:$1 not found in ECR: commit $COMMIT never reached staging. Push it to main, let phoebe-staging finish, then re-run the release."
}
ecr_digest "$COMMIT" || missing "$COMMIT"
API_DIGEST="$ECR_DIGEST"
ecr_digest "$COMMIT-jobs" || missing "$COMMIT-jobs"
JOBS_DIGEST="$ECR_DIGEST"
log "commit $COMMIT api $API_DIGEST jobs $JOBS_DIGEST"

# resolve_tag: the highest v* tag (sort -V) on $COMMIT, read from the
# CODEBUILD_CLONE_REF git clone (ruling R17). Fails closed if there is none.
resolve_tag() {
  local head tags
  # CodeBuild's clone can be owned by another uid than the build user; without
  # this git refuses it ("dubious ownership") and every call below fails.
  git config --global --add safe.directory "$REPO_ROOT" || die "could not mark $REPO_ROOT as a safe git directory"
  head="$(git -C "$REPO_ROOT" rev-parse HEAD)" || die "the source is not a git clone (expected CODEBUILD_CLONE_REF)"
  [ "$head" = "$COMMIT" ] || die "the clone is at $head, not the release commit $COMMIT"
  if [ "$(git -C "$REPO_ROOT" rev-parse --is-shallow-repository)" = true ]; then
    log "shallow clone: fetching tags"
    git -C "$REPO_ROOT" fetch --quiet --force --tags origin || die "could not fetch tags"
  fi
  tags="$(git -C "$REPO_ROOT" tag --points-at "$COMMIT" --list 'v*' | grep -E '^v[0-9][0-9A-Za-z._-]*$' || true)"
  [ -n "$tags" ] || die "no v* git tag points at commit $COMMIT"
  RELEASE_TAG="$(printf '%s\n' "$tags" | sort -V | tail -n 1)"
  if [ "$(printf '%s\n' "$tags" | wc -l | tr -d ' ')" != 1 ]; then
    log "several v* tags on $COMMIT ($(printf '%s' "$tags" | tr '\n' ' ')); using the highest"
  fi
}
resolve_tag
require_git_tag "$RELEASE_TAG"
log "release tag $RELEASE_TAG"

mkdir -p "$OUT_DIR"
# Absolute before the cd below: the buildspec passes a relative `release-out`.
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
cd "$REPO_ROOT/infra/app"
tf_init production
log "terraform plan (production, read-only, -lock=false)"
terraform plan -lock=false -input=false -no-color -compact-warnings \
  -var-file=envs/production.tfvars \
  -var "api_image_digest=$API_DIGEST" -var "jobs_image_digest=$JOBS_DIGEST" \
  "-out=$OUT_DIR/production.tfplan"

printf 'RELEASE_COMMIT=%s\nRELEASE_TAG=%s\nAPI_IMAGE_DIGEST=%s\nJOBS_IMAGE_DIGEST=%s\n' \
  "$COMMIT" "$RELEASE_TAG" "$API_DIGEST" "$JOBS_DIGEST" >"$OUT_DIR/release.env"
log "saved $OUT_DIR/production.tfplan and release.env"
