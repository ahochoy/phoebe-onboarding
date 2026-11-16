#!/usr/bin/env bash
# ci/release-plan.sh [out_dir]: phoebe-release-plan (pipeline Plan stage, run
# as the read-only phoebe-ci-plan-production).
#
#   1. Resolves the tag commit's two images, phoebe-api:<sha> and <sha>-jobs,
#      to digests. Missing means the commit never went through phoebe-staging,
#      and the release stops here.
#   2. Finds the v* git tag on that commit (GitHub's public API; the pipeline's
#      source variables carry only the commit).
#   3. terraform plan -lock=false for production, saved to
#      <out_dir>/production.tfplan, plus <out_dir>/release.env with the commit,
#      tag and digests. Both are the pipeline's `plan` artifact; release-apply
#      applies that exact plan.
#
# Env: RELEASE_COMMIT (required), PHOEBE_GITHUB_REPO (owner/repo),
# RELEASE_TAG (optional override of step 2).
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

# resolve_tag: the single v* tag pointing at $COMMIT.
resolve_tag() {
  local repo="${PHOEBE_GITHUB_REPO:-}" page=1 json found="" n
  [ -n "$repo" ] || die "PHOEBE_GITHUB_REPO is not set"
  while [ "$page" -le 10 ]; do
    json="$(curl -fsS --max-time 20 -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/$repo/tags?per_page=100&page=$page")" ||
      die "could not list the tags of $repo"
    found="$found$(jq -r --arg c "$COMMIT" \
      '.[] | select(.commit.sha == $c) | .name | select(test("^v[0-9A-Za-z._-]+$"))' <<<"$json")
"
    n="$(jq 'length' <<<"$json")"
    [ "$n" -lt 100 ] && break
    page=$((page + 1))
  done
  found="$(printf '%s' "$found" | sed '/^$/d')"
  [ -n "$found" ] || die "no v* git tag points at commit $COMMIT in $repo"
  [ "$(printf '%s\n' "$found" | wc -l | tr -d ' ')" = 1 ] ||
    die "several v* tags point at commit $COMMIT ($(printf '%s' "$found" | tr '\n' ' ')); set RELEASE_TAG"
  RELEASE_TAG="$found"
}
if [ -z "${RELEASE_TAG:-}" ]; then
  resolve_tag
fi
require_git_tag "$RELEASE_TAG"
log "release tag $RELEASE_TAG"

mkdir -p "$OUT_DIR"
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
