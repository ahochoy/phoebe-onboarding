# shellcheck shell=bash disable=SC2034  # globals are read by the sourcing scripts
# Shared helpers for the ci/ scripts (sourced, not run).
#
# House rules: never enable xtrace (`set -x`) here or in a caller, since it
# would print secret-bearing argv. Log metadata only: names, digests, counts.
# Bash 3.2 compatible (macOS runs the offline tests with /bin/bash).

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export AWS_REGION="${AWS_REGION:-us-east-2}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"
export AWS_PAGER=""
ECR_REPO="${ECR_REPO:-phoebe-api}"

log() { printf '==> %s\n' "$*"; }
die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_env_name() {
  case "$1" in
    staging | production) ;;
    *) die "env must be staging or production, got '$1'" ;;
  esac
}

require_digest() {
  [[ "$2" =~ ^sha256:[0-9a-f]{64}$ ]] || die "$1 must be sha256:<64 hex>, got '$2'"
}

require_commit() {
  [[ "$2" =~ ^[0-9a-f]{40}$ ]] || die "$1 must be a full 40-hex commit sha, got '$2'"
}

require_git_tag() {
  [[ "$1" =~ ^v[0-9][0-9A-Za-z._-]*$ ]] || die "release tag must match v<digit>[0-9A-Za-z._-]*, got '$1'"
}

# The account id, from the CodeBuild build ARN when there is one.
account_id() {
  local arn="${CODEBUILD_BUILD_ARN:-}"
  if [[ "$arn" =~ ^arn:aws:codebuild:[a-z0-9-]+:([0-9]{12}): ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  else
    aws sts get-caller-identity --query Account --output text
  fi
}

# State bucket: $STATE_BUCKET, else phoebe-tfstate-<account_id>.
state_bucket() {
  if [ -n "${STATE_BUCKET:-}" ]; then
    printf '%s\n' "$STATE_BUCKET"
  else
    printf 'phoebe-tfstate-%s\n' "$(account_id)"
  fi
}

# terraform init for infra/app (run from infra/app).
tf_init() {
  local bucket
  bucket="$(state_bucket)"
  log "terraform init ($1, state bucket $bucket)"
  terraform init -input=false -no-color \
    "-backend-config=envs/$1.s3.tfbackend" "-backend-config=bucket=$bucket"
}

# ecr_digest <tag>: sets ECR_DIGEST and returns 0 when $ECR_REPO:<tag> exists,
# returns 1 when it does not, and exits on any other error (e.g. AccessDenied),
# so a permissions problem is never mistaken for a missing image.
ECR_DIGEST=""
ecr_digest() {
  local err out
  ECR_DIGEST=""
  err="$(mktemp)"
  if out="$(aws ecr describe-images --repository-name "$ECR_REPO" --image-ids "imageTag=$1" \
    --query 'imageDetails[0].imageDigest' --output text 2>"$err")"; then
    rm -f "$err"
    [[ "$out" =~ ^sha256:[0-9a-f]{64}$ ]] || die "unexpected digest for $ECR_REPO:$1: '$out'"
    ECR_DIGEST="$out"
    return 0
  fi
  if grep -q ImageNotFoundException "$err"; then
    rm -f "$err"
    return 1
  fi
  cat "$err" >&2
  rm -f "$err"
  die "could not describe $ECR_REPO:$1"
}
