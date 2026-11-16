#!/usr/bin/env bash
# ci/install-terraform.sh <version>: installs the linux_arm64 Terraform
# release into /usr/local/bin after checking it against HashiCorp's SHA256SUMS
# (same steps as the inline infra/bootstrap/buildspecs/pr.yml).
set -euo pipefail

VERSION="${1:?usage: ci/install-terraform.sh <version>}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "bad terraform version: $VERSION" >&2; exit 1; }
WORK="$(mktemp -d)"
cd "$WORK"
ZIP="terraform_${VERSION}_linux_arm64.zip"
curl -fsSLo tf.zip "https://releases.hashicorp.com/terraform/$VERSION/$ZIP"
curl -fsSLo tf.sums "https://releases.hashicorp.com/terraform/$VERSION/terraform_${VERSION}_SHA256SUMS"
grep " $ZIP\$" tf.sums | sed "s/terraform_.*zip\$/tf.zip/" | sha256sum -c -
unzip -o tf.zip terraform -d /usr/local/bin
cd /
rm -rf "$WORK"
terraform version
