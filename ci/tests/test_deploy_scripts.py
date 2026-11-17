"""Offline tests for the ci/ deploy scripts, buildspecs and workflows.

Every external binary the scripts call (aws, terraform, docker, npm, curl) is
replaced by a stub on PATH that records its argv and answers from per-test
rules. Nothing here reaches AWS or the network.
"""

import itertools
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CI = REPO / "ci"

API = "sha256:" + "a" * 64
JOBS = "sha256:" + "b" * 64
OTHER = "sha256:" + "f" * 64
COMMIT = "c" * 40
SITE = "https://d111example.cloudfront.net"
FN = "https://abc123.lambda-url.us-east-2.on.aws/"
DIST = "E2EXAMPLE123"
BUCKET = "phoebe-staging-site-123456789012"
OPS = "phoebe-staging-ops"

STUBBED = ("aws", "terraform", "docker", "npm", "curl", "git")

STUB = r"""#!{python}
import json, os, sys

name = os.path.basename(sys.argv[0])
argv = sys.argv[1:]
d = os.environ["STUB_DIR"]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps({
        "cmd": name,
        "argv": argv,
        "cwd": os.getcwd(),
        "env": {k: os.environ.get(k) for k in ("PHOEBE_BASE", "PHOEBE_PLAN_FILE")},
    }) + "\n")

rules_path = os.path.join(d, name + ".rules.json")
rules = json.load(open(rules_path)) if os.path.exists(rules_path) else []
used_path = os.path.join(d, "used.json")
used = json.load(open(used_path)) if os.path.exists(used_path) else {}
joined = " ".join(argv)
for i, r in enumerate(rules):
    key = name + ":" + str(i)
    if r.get("once") and used.get(key):
        continue
    if "url" in r and (not argv or argv[-1] != r["url"]):
        continue
    if not all(m in joined for m in r.get("match", [])):
        continue
    if r.get("once"):
        used[key] = True
        json.dump(used, open(used_path, "w"))
    content = r.get("content", "")
    if "write_after" in r:
        with open(argv[argv.index(r["write_after"]) + 1], "w") as out:
            out.write(content)
    if r.get("write_last"):
        with open(argv[-1], "w") as out:
            out.write(content)
    sys.stdout.write(r.get("stdout", ""))
    sys.stderr.write(r.get("stderr", ""))
    sys.exit(r.get("exit", 0))
sys.exit(0)
"""


class Harness:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.stub_dir = tmp / "stub"
        self.bin.mkdir()
        self.stub_dir.mkdir()
        self.rules: dict[str, list[dict[str, Any]]] = {c: [] for c in STUBBED}
        for cmd in STUBBED:
            p = self.bin / cmd
            p.write_text(STUB.replace("{python}", sys.executable))
            p.chmod(0o755)

    def rule(self, cmd: str, **r: Any) -> None:
        self.rules[cmd].append(r)

    def run(
        self, script: str, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        for cmd, rules in self.rules.items():
            (self.stub_dir / f"{cmd}.rules.json").write_text(json.dumps(rules))
        full_env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.tmp),
            "TMPDIR": str(self.tmp),
            "STUB_DIR": str(self.stub_dir),
            "SMOKE_ATTEMPTS": "1",
            "SMOKE_DELAY": "0",
            "STATE_BUCKET": "phoebe-tfstate-123456789012",
            "CODEBUILD_BUILD_ARN": "arn:aws:codebuild:us-east-2:123456789012:build/phoebe-staging:1",
        }
        full_env.update(env or {})
        return subprocess.run(
            ["bash", str(CI / script), *args],
            env=full_env,
            capture_output=True,
            text=True,
            cwd=self.tmp,
            timeout=60,
            check=False,
        )

    def calls(self, cmd: str | None = None) -> list[dict[str, Any]]:
        log = self.stub_dir / "calls.jsonl"
        if not log.exists():
            return []
        out = [json.loads(line) for line in log.read_text().splitlines()]
        return [c for c in out if cmd is None or c["cmd"] == cmd]

    def argvs(self, cmd: str) -> list[list[str]]:
        return [c["argv"] for c in self.calls(cmd)]

    def index(self, cmd: str, *needles: str) -> int:
        """Position in the overall call log of the first `cmd` call containing all needles."""
        for i, c in enumerate(self.calls()):
            if c["cmd"] == cmd and all(n in c["argv"] for n in needles):
                return i
        raise AssertionError(f"no {cmd} call with {needles}: {self.argvs(cmd)}")


def has_pair(argv: list[str], flag: str, value: str) -> bool:
    return any(a == flag and b == value for a, b in itertools.pairwise(argv))


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def smoke_ok(h: Harness, site: str = SITE, fn: str = FN) -> None:
    fn = fn.rstrip("/")
    h.rule(
        "curl",
        url=f"{site}/api/health",
        write_after="-o",
        content='{"status":"ok"}',
        stdout="200",
    )
    h.rule(
        "curl",
        url=f"{site}/",
        write_after="-o",
        content='<html><div id="root"></div></html>',
        stdout="200",
    )
    h.rule(
        "curl",
        url=f"{site}/api/status",
        write_after="-o",
        content='{"state":"open","chat_available":true,"upload_available":true,"reasons":[]}',
        stdout="200",
    )
    h.rule(
        "curl",
        url=f"{fn}/api/status",
        write_after="-o",
        content='{"detail":"forbidden"}',
        stdout="403",
    )
    h.rule(
        "curl", url=f"{site}/pr-0/", write_after="-o", content="<Error/>", stdout="403"
    )


def deploy_ok(h: Harness, env: str = "staging") -> None:
    outputs = {
        "site_url": SITE,
        "site_bucket": BUCKET.replace("staging", env),
        "ops_function_name": OPS.replace("staging", env),
        "api_function_url": FN,
        "distribution_id": DIST,
    }
    for k, v in outputs.items():
        h.rule("terraform", match=["output", "-raw", k], stdout=v)
    h.rule(
        "aws",
        match=["lambda", "invoke"],
        write_last=True,
        content='{"applied": []}',
        stdout='{"StatusCode": 200}',
    )
    h.rule("aws", match=["create-invalidation"], stdout="I2INVALIDATION")
    smoke_ok(h)


# ---- deploy.sh -------------------------------------------------------------------


def test_deploy_staging_terraform_args(h: Harness) -> None:
    deploy_ok(h)
    r = h.run("deploy.sh", "staging", API, JOBS)
    assert r.returncode == 0, r.stdout + r.stderr
    tf = h.calls("terraform")
    assert all(c["cwd"] == str(REPO / "infra" / "app") for c in tf), (
        "terraform only runs in infra/app (R12)"
    )
    init = next(c["argv"] for c in tf if c["argv"][0] == "init")
    assert "-backend-config=envs/staging.s3.tfbackend" in init
    assert "-backend-config=bucket=phoebe-tfstate-123456789012" in init
    apply = next(c["argv"] for c in tf if c["argv"][0] == "apply")
    assert "-auto-approve" in apply
    assert "-var-file=envs/staging.tfvars" in apply
    assert has_pair(apply, "-var", f"api_image_digest={API}")
    assert has_pair(apply, "-var", f"jobs_image_digest={JOBS}")
    assert h.index("terraform", "init") < h.index("terraform", "apply")


@pytest.mark.parametrize(
    "args",
    [
        ("prod", API, JOBS),
        ("staging", "sha256:abc", JOBS),
        ("staging", API, "latest"),
        ("staging", API),
    ],
)
def test_deploy_rejects_bad_args(h: Harness, args: tuple[str, ...]) -> None:
    r = h.run("deploy.sh", *args)
    assert r.returncode != 0
    assert h.calls() == []


def test_deploy_runs_migrate_before_seed(h: Harness) -> None:
    deploy_ok(h)
    r = h.run("deploy.sh", "staging", API, JOBS)
    assert r.returncode == 0, r.stdout + r.stderr
    invokes = [a for a in h.argvs("aws") if a[:2] == ["lambda", "invoke"]]
    payloads = [a[a.index("--payload") + 1] for a in invokes]
    assert [json.loads(p)["task"] for p in payloads] == ["migrate", "seed_if_empty"]
    assert all(has_pair(a, "--function-name", OPS) for a in invokes)
    assert h.index("terraform", "apply") < h.index("aws", "lambda", "invoke")


def test_deploy_stops_on_ops_function_error(h: Harness) -> None:
    h.rule(
        "aws",
        match=["lambda", "invoke", "migrate"],
        write_last=True,
        content='{"errorType": "OperationalError", "errorMessage": "password=hunter2"}',
        stdout='{"StatusCode": 200, "FunctionError": "Unhandled"}',
    )
    deploy_ok(h)
    r = h.run("deploy.sh", "staging", API, JOBS)
    assert r.returncode != 0
    assert "migrate" in r.stderr
    # Only the error type is logged, never the payload text.
    assert "OperationalError" in r.stderr
    assert "hunter2" not in r.stdout + r.stderr
    assert not any(a[:2] == ["s3", "sync"] for a in h.argvs("aws"))
    assert not any("seed_if_empty" in " ".join(a) for a in h.argvs("aws"))


def test_deploy_stops_on_ops_error_result(h: Harness) -> None:
    h.rule(
        "aws",
        match=["lambda", "invoke"],
        write_last=True,
        content='{"error": "unknown_task"}',
    )
    deploy_ok(h)
    r = h.run("deploy.sh", "staging", API, JOBS)
    assert r.returncode != 0
    assert not any(a[:2] == ["s3", "sync"] for a in h.argvs("aws"))


def test_deploy_builds_frontend_at_root(h: Harness) -> None:
    deploy_ok(h)
    r = h.run("deploy.sh", "staging", API, JOBS)
    assert r.returncode == 0, r.stdout + r.stderr
    npm = h.calls("npm")
    assert [c["argv"][0] for c in npm] == ["ci", "run"]
    assert npm[1]["argv"][:2] == ["run", "build"]
    assert npm[1]["env"]["PHOEBE_BASE"] == "/"
    assert all(c["cwd"] == str(REPO / "frontend") for c in npm)


def test_deploy_site_sync_excludes_and_cache_headers(h: Harness) -> None:
    deploy_ok(h)
    r = h.run("deploy.sh", "staging", API, JOBS)
    assert r.returncode == 0, r.stdout + r.stderr
    syncs = [a for a in h.argvs("aws") if a[:2] == ["s3", "sync"]]
    assert len(syncs) == 3
    assets, root, prune = syncs
    # 1. hashed assets: cached forever
    assert assets[3] == f"s3://{BUCKET}/assets/"
    assert has_pair(assets, "--cache-control", "public, max-age=31536000, immutable")
    # 2. index.html and other root files: always revalidated
    assert root[3] == f"s3://{BUCKET}/"
    assert has_pair(root, "--cache-control", "no-cache")
    assert has_pair(root, "--exclude", "assets/*")
    # 3. prune, never touching previews or seed sources
    assert prune[3] == f"s3://{BUCKET}/"
    assert "--delete" in prune
    assert has_pair(prune, "--exclude", "previews/*")
    assert has_pair(prune, "--exclude", "seed-sources/*")
    for s in (assets, root):
        assert "--delete" not in s
    for s in syncs:
        assert s[2].startswith(str(REPO / "frontend" / "dist"))


def test_deploy_uploads_seed_sources(h: Harness) -> None:
    deploy_ok(h)
    r = h.run("deploy.sh", "staging", API, JOBS)
    assert r.returncode == 0, r.stdout + r.stderr
    cps = [a for a in h.argvs("aws") if a[:2] == ["s3", "cp"]]
    dests = sorted(a[3] for a in cps)
    assert dests == [
        f"s3://{BUCKET}/seed-sources/benefits.html",
        f"s3://{BUCKET}/seed-sources/project-manifest.txt",
    ]
    for a in cps:
        assert Path(a[2]).is_file()


def test_deploy_invalidates_then_smokes(h: Harness) -> None:
    deploy_ok(h)
    r = h.run("deploy.sh", "staging", API, JOBS)
    assert r.returncode == 0, r.stdout + r.stderr
    inv = next(a for a in h.argvs("aws") if "create-invalidation" in a)
    assert has_pair(inv, "--distribution-id", DIST)
    assert has_pair(inv, "--paths", "/*")
    wait = next(a for a in h.argvs("aws") if "invalidation-completed" in a)
    assert has_pair(wait, "--id", "I2INVALIDATION")
    last_sync = max(
        i for i, c in enumerate(h.calls()) if c["argv"][:2] == ["s3", "sync"]
    )
    assert (
        last_sync
        < h.index("aws", "create-invalidation")
        < h.index("curl", f"{SITE}/api/health")
    )
    assert "SMOKE OK" in r.stdout


def test_deploy_fails_when_smoke_fails(h: Harness) -> None:
    h.rule("curl", url=f"{SITE}/api/health", write_after="-o", content="", stdout="502")
    deploy_ok(h)
    r = h.run("deploy.sh", "staging", API, JOBS)
    assert r.returncode != 0


def test_deploy_production_applies_saved_plan(h: Harness, tmp_path: Path) -> None:
    plan = tmp_path / "production.tfplan"
    plan.write_text("plan")
    deploy_ok(h, "production")
    r = h.run("deploy.sh", "production", API, JOBS, env={"PHOEBE_PLAN_FILE": str(plan)})
    assert r.returncode == 0, r.stdout + r.stderr
    init = next(a for a in h.argvs("terraform") if a[0] == "init")
    assert "-backend-config=envs/production.s3.tfbackend" in init
    apply = next(a for a in h.argvs("terraform") if a[0] == "apply")
    assert apply[-1] == str(plan)
    assert "-var" not in apply and not any(a.startswith("-var-file") for a in apply)
    assert not any(a[0] == "plan" for a in h.argvs("terraform"))


XTRACE = re.compile(r"^[^#\n]*\bset\s+(-[a-zA-Z]*x|-o\s+xtrace)\b", re.MULTILINE)


@pytest.mark.parametrize(
    ("line", "hit"),
    [
        ("set -x", True),
        ("  set -eux", True),
        ("set -o xtrace", True),
        ("foo; set -o  xtrace", True),
        ("# never set -x here", False),
        ("set -euo pipefail", False),
        ("set +x", False),
    ],
)
def test_xtrace_pattern(line: str, hit: bool) -> None:
    assert bool(XTRACE.search(line)) is hit


def test_deploy_never_sets_xtrace() -> None:
    for script in [*CI.glob("*.sh"), *CI.glob("buildspec-*.yml")]:
        assert not XTRACE.search(script.read_text()), f"{script.name} enables xtrace"


def test_deploy_production_requires_a_saved_plan(h: Harness) -> None:
    deploy_ok(h, "production")
    r = h.run("deploy.sh", "production", API, JOBS)
    assert r.returncode != 0
    assert "saved plan" in r.stderr
    assert not any(a[0] == "apply" for a in h.argvs("terraform"))


# ---- smoke.sh --------------------------------------------------------------------


def test_smoke_passes(h: Harness) -> None:
    smoke_ok(h)
    r = h.run("smoke.sh", SITE, FN)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SMOKE OK" in r.stdout
    urls = [a[-1] for a in h.argvs("curl")]
    assert urls[:2] == [f"{SITE}/api/health", f"{SITE}/"]
    assert f"{FN.rstrip('/')}/api/status" in urls
    assert "viewer" in r.stdout.lower()  # the viewer-address check reports its skip


def test_smoke_fails_when_health_not_200(h: Harness) -> None:
    h.rule("curl", url=f"{SITE}/api/health", write_after="-o", content="", stdout="503")
    smoke_ok(h)
    r = h.run("smoke.sh", SITE, FN)
    assert r.returncode != 0
    assert "health" in r.stderr


def test_smoke_fails_when_function_url_not_403(h: Harness) -> None:
    h.rule(
        "curl",
        url=f"{FN.rstrip('/')}/api/status",
        write_after="-o",
        content="{}",
        stdout="200",
    )
    smoke_ok(h)
    r = h.run("smoke.sh", SITE, FN)
    assert r.returncode != 0
    assert "403" in r.stderr


def test_smoke_fails_without_root_element(h: Harness) -> None:
    h.rule(
        "curl", url=f"{SITE}/", write_after="-o", content="<html></html>", stdout="200"
    )
    smoke_ok(h)
    r = h.run("smoke.sh", SITE, FN)
    assert r.returncode != 0


def test_smoke_fails_when_status_not_json(h: Harness) -> None:
    h.rule(
        "curl",
        url=f"{SITE}/api/status",
        write_after="-o",
        content="<html>",
        stdout="200",
    )
    smoke_ok(h)
    r = h.run("smoke.sh", SITE, FN)
    assert r.returncode != 0
    assert "status" in r.stderr


def test_smoke_fails_when_preview_route_404s(h: Harness) -> None:
    h.rule("curl", url=f"{SITE}/pr-0/", write_after="-o", content="", stdout="404")
    smoke_ok(h)
    r = h.run("smoke.sh", SITE, FN)
    assert r.returncode != 0
    assert "pr-0" in r.stderr


def test_smoke_fails_when_unreachable(h: Harness) -> None:
    h.rule("curl", url=f"{SITE}/api/health", stdout="000", exit=6)
    smoke_ok(h)
    r = h.run("smoke.sh", SITE, FN)
    assert r.returncode != 0


# ---- staging.sh ------------------------------------------------------------------

NOT_FOUND = "An error occurred (ImageNotFoundException) when calling the DescribeImages operation"
REGISTRY = "123456789012.dkr.ecr.us-east-2.amazonaws.com"


def test_staging_builds_both_targets_and_deploys(h: Harness) -> None:
    for tag in (COMMIT, f"{COMMIT}-jobs"):
        h.rule(
            "aws",
            match=["describe-images", f"imageTag={tag} "],
            once=True,
            stderr=NOT_FOUND,
            exit=254,
        )
    # `imageTag=<sha> ` (trailing space) must not match `<sha>-jobs`; the stub joins argv with spaces.
    h.rule("aws", match=["describe-images", f"imageTag={COMMIT}-jobs"], stdout=JOBS)
    h.rule("aws", match=["describe-images", f"imageTag={COMMIT} "], stdout=API)
    deploy_ok(h)
    r = h.run("staging.sh", env={"CODEBUILD_RESOLVED_SOURCE_VERSION": COMMIT})
    assert r.returncode == 0, r.stdout + r.stderr
    builds = [a for a in h.argvs("docker") if a[:2] == ["buildx", "build"]]
    assert len(builds) == 2
    for a, target, tag in zip(builds, ("api", "jobs"), (COMMIT, f"{COMMIT}-jobs")):
        assert has_pair(a, "--platform", "linux/arm64")
        assert has_pair(a, "--target", target)
        assert has_pair(a, "-f", "backend/Dockerfile")
        assert has_pair(a, "-t", f"{REGISTRY}/phoebe-api:{tag}")
        assert "--push" in a
        assert a[-1] == "."
    login = next(a for a in h.argvs("docker") if a[0] == "login")
    assert "--password-stdin" in login and login[-1] == REGISTRY
    apply = next(a for a in h.argvs("terraform") if a[0] == "apply")
    assert has_pair(apply, "-var", f"api_image_digest={API}")
    assert has_pair(apply, "-var", f"jobs_image_digest={JOBS}")
    assert "-var-file=envs/staging.tfvars" in apply


def test_staging_reuses_existing_images(h: Harness) -> None:
    h.rule("aws", match=["describe-images", f"imageTag={COMMIT}-jobs"], stdout=JOBS)
    h.rule("aws", match=["describe-images", f"imageTag={COMMIT} "], stdout=API)
    deploy_ok(h)
    r = h.run("staging.sh", env={"CODEBUILD_RESOLVED_SOURCE_VERSION": COMMIT})
    assert r.returncode == 0, r.stdout + r.stderr
    assert not any(a[:2] == ["buildx", "build"] for a in h.argvs("docker"))


def test_staging_rejects_bad_commit(h: Harness) -> None:
    r = h.run("staging.sh", env={"CODEBUILD_RESOLVED_SOURCE_VERSION": "main"})
    assert r.returncode != 0
    assert not h.argvs("docker")


# ---- release-plan.sh -------------------------------------------------------------


def release_tags(
    h: Harness, tags: list[str], *, shallow: bool = False, head: str = COMMIT
) -> None:
    """Stub git for the CODEBUILD_CLONE_REF clone: HEAD, shallowness, tags on HEAD."""
    h.rule("git", match=["rev-parse", "HEAD"], stdout=head + "\n")
    h.rule(
        "git",
        match=["rev-parse", "--is-shallow-repository"],
        stdout="true\n" if shallow else "false\n",
    )
    h.rule(
        "git",
        match=["tag", "--points-at", COMMIT],
        stdout="".join(t + "\n" for t in tags),
    )


def plan_env(**extra: str) -> dict[str, str]:
    return {"RELEASE_COMMIT": COMMIT, **extra}


def images_present(h: Harness) -> None:
    h.rule("aws", match=["describe-images", f"imageTag={COMMIT}-jobs"], stdout=JOBS)
    h.rule("aws", match=["describe-images", f"imageTag={COMMIT} "], stdout=API)


def test_release_plan_fails_clearly_when_image_missing(
    h: Harness, tmp_path: Path
) -> None:
    h.rule("aws", match=["describe-images"], stderr=NOT_FOUND, exit=254)
    release_tags(h, ["v1.2.3"])
    r = h.run("release-plan.sh", str(tmp_path / "out"), env=plan_env())
    assert r.returncode != 0
    assert f"phoebe-api:{COMMIT}" in r.stderr
    assert "never reached staging" in r.stderr
    assert not any(a[0] == "plan" for a in h.argvs("terraform"))


def test_release_plan_fails_when_jobs_image_missing(h: Harness, tmp_path: Path) -> None:
    h.rule(
        "aws",
        match=["describe-images", f"imageTag={COMMIT}-jobs"],
        stderr=NOT_FOUND,
        exit=254,
    )
    h.rule("aws", match=["describe-images", f"imageTag={COMMIT} "], stdout=API)
    release_tags(h, ["v1.2.3"])
    r = h.run("release-plan.sh", str(tmp_path / "out"), env=plan_env())
    assert r.returncode != 0
    assert f"phoebe-api:{COMMIT}-jobs" in r.stderr
    assert "never reached staging" in r.stderr


def test_release_plan_surfaces_other_ecr_errors(h: Harness, tmp_path: Path) -> None:
    h.rule("aws", match=["describe-images"], stderr="AccessDeniedException", exit=254)
    r = h.run("release-plan.sh", str(tmp_path / "out"), env=plan_env())
    assert r.returncode != 0
    assert "AccessDenied" in r.stderr
    assert "never reached staging" not in r.stderr


def test_release_plan_saves_plan_and_digests(h: Harness, tmp_path: Path) -> None:
    images_present(h)
    release_tags(h, ["v1.2.3"])
    out = tmp_path / "out"
    r = h.run("release-plan.sh", str(out), env=plan_env())
    assert r.returncode == 0, r.stdout + r.stderr
    tf = h.argvs("terraform")
    init = next(a for a in tf if a[0] == "init")
    assert "-backend-config=envs/production.s3.tfbackend" in init
    plan = next(a for a in tf if a[0] == "plan")
    assert "-lock=false" in plan
    assert f"-out={out}/production.tfplan" in plan
    assert "-var-file=envs/production.tfvars" in plan
    assert has_pair(plan, "-var", f"api_image_digest={API}")
    assert has_pair(plan, "-var", f"jobs_image_digest={JOBS}")
    assert not any(a[0] == "apply" for a in tf)
    env = dict(
        line.split("=", 1) for line in (out / "release.env").read_text().splitlines()
    )
    assert env == {
        "RELEASE_COMMIT": COMMIT,
        "RELEASE_TAG": "v1.2.3",
        "API_IMAGE_DIGEST": API,
        "JOBS_IMAGE_DIGEST": JOBS,
    }


def test_release_plan_accepts_a_relative_out_dir(h: Harness) -> None:
    """The buildspec passes `release-out`, relative to the build's working
    directory. The script cds into infra/app before planning, so the path must
    be made absolute first or Terraform can't write the plan (v0.1.0, run 1)."""
    images_present(h)
    release_tags(h, ["v1.2.3"])
    r = h.run("release-plan.sh", "release-out", env=plan_env())
    assert r.returncode == 0, r.stdout + r.stderr
    out = (h.tmp / "release-out").resolve()
    plan = next(a for a in h.argvs("terraform") if a[0] == "plan")
    assert f"-out={out}/production.tfplan" in plan
    assert (out / "release.env").is_file()


def test_release_plan_fails_without_a_tag_for_the_commit(
    h: Harness, tmp_path: Path
) -> None:
    images_present(h)
    release_tags(h, [])
    r = h.run("release-plan.sh", str(tmp_path / "out"), env=plan_env())
    assert r.returncode != 0
    assert "no v* git tag" in r.stderr
    assert not any(a[0] == "plan" for a in h.argvs("terraform"))


def release_env(out: Path) -> dict[str, str]:
    lines = (out / "release.env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def test_release_plan_reads_the_tag_with_git_not_the_github_api(
    h: Harness, tmp_path: Path
) -> None:
    images_present(h)
    release_tags(h, ["v1.2.3"])
    out = tmp_path / "out"
    r = h.run("release-plan.sh", str(out), env=plan_env())
    assert r.returncode == 0, r.stdout + r.stderr
    tag = next(a for a in h.argvs("git") if "tag" in a)
    assert tag[-4:] == ["--points-at", COMMIT, "--list", "v*"]
    assert all(
        c["argv"][:2] == ["-C", str(REPO)]
        for c in h.calls("git")
        if c["argv"][0] != "config"
    )
    assert h.calls("curl") == []
    assert not any("fetch" in a for a in h.argvs("git"))
    assert release_env(out)["RELEASE_TAG"] == "v1.2.3"


def test_release_plan_marks_the_clone_safe_before_any_other_git_call(
    h: Harness, tmp_path: Path
) -> None:
    images_present(h)
    release_tags(h, ["v1.2.3"])
    r = h.run("release-plan.sh", str(tmp_path / "out"), env=plan_env())
    assert r.returncode == 0, r.stdout + r.stderr
    git = h.argvs("git")
    assert git[0] == ["config", "--global", "--add", "safe.directory", str(REPO)]
    assert all(a[0] != "config" for a in git[1:])


def test_release_plan_picks_the_highest_of_several_tags(
    h: Harness, tmp_path: Path
) -> None:
    images_present(h)
    release_tags(h, ["v1.9.2", "v1.10.0", "v1.2.3"])
    out = tmp_path / "out"
    r = h.run("release-plan.sh", str(out), env=plan_env())
    assert r.returncode == 0, r.stdout + r.stderr
    assert release_env(out)["RELEASE_TAG"] == "v1.10.0"
    assert "using the highest" in r.stdout


def test_release_plan_ignores_non_release_tags(h: Harness, tmp_path: Path) -> None:
    images_present(h)
    # git's `v*` glob still lets these through; only v<digit>... is a release tag.
    release_tags(h, ["v1.2.3", "vnext", "version-bump", "v2;rm"])
    out = tmp_path / "out"
    r = h.run("release-plan.sh", str(out), env=plan_env())
    assert r.returncode == 0, r.stdout + r.stderr
    assert release_env(out)["RELEASE_TAG"] == "v1.2.3"


def test_release_plan_dies_when_only_non_release_tags(
    h: Harness, tmp_path: Path
) -> None:
    images_present(h)
    release_tags(h, ["vnext", "latest"])
    r = h.run("release-plan.sh", str(tmp_path / "out"), env=plan_env())
    assert r.returncode != 0
    assert "no v* git tag" in r.stderr
    assert not any(a[0] == "plan" for a in h.argvs("terraform"))


def test_release_plan_fetches_tags_in_a_shallow_clone(
    h: Harness, tmp_path: Path
) -> None:
    images_present(h)
    release_tags(h, ["v1.2.3"], shallow=True)
    r = h.run("release-plan.sh", str(tmp_path / "out"), env=plan_env())
    assert r.returncode == 0, r.stdout + r.stderr
    fetch = h.index("git", "fetch")
    assert "--tags" in h.calls()[fetch]["argv"]
    assert fetch < h.index("git", "--points-at")


def test_release_plan_refuses_a_clone_at_another_commit(
    h: Harness, tmp_path: Path
) -> None:
    images_present(h)
    release_tags(h, ["v1.2.3"], head="e" * 40)
    r = h.run("release-plan.sh", str(tmp_path / "out"), env=plan_env())
    assert r.returncode != 0
    assert "not the release commit" in r.stderr
    assert not any(a[0] == "plan" for a in h.argvs("terraform"))


def test_release_plan_rejects_bad_commit(h: Harness, tmp_path: Path) -> None:
    r = h.run(
        "release-plan.sh", str(tmp_path / "out"), env=plan_env(RELEASE_COMMIT="main")
    )
    assert r.returncode != 0
    assert h.calls() == []


# ---- release-apply.sh ------------------------------------------------------------

MANIFEST = '{"schemaVersion":2}'
MEDIA = "application/vnd.oci.image.manifest.v1+json"


def plan_dir(tmp_path: Path, tag: str = "v1.2.3") -> Path:
    d = tmp_path / "plan"
    d.mkdir()
    (d / "production.tfplan").write_text("plan")
    (d / "release.env").write_text(
        f"RELEASE_COMMIT={COMMIT}\nRELEASE_TAG={tag}\nAPI_IMAGE_DIGEST={API}\nJOBS_IMAGE_DIGEST={JOBS}\n"
    )
    return d


def manifests(h: Harness) -> None:
    for digest in (API, JOBS):
        h.rule(
            "aws",
            match=["batch-get-image", f"imageDigest={digest}"],
            stdout=json.dumps(
                {
                    "images": [
                        {"imageManifest": MANIFEST, "imageManifestMediaType": MEDIA}
                    ]
                }
            ),
        )


def test_release_apply_applies_saved_plan_and_tags(h: Harness, tmp_path: Path) -> None:
    d = plan_dir(tmp_path)
    h.rule(
        "aws",
        match=["describe-images", "imageTag=release-"],
        stderr=NOT_FOUND,
        exit=254,
    )
    manifests(h)
    deploy_ok(h, "production")
    r = h.run(
        "release-apply.sh",
        env={"CODEBUILD_SRC_DIR_plan": str(d), "RELEASE_COMMIT": COMMIT},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    apply = next(a for a in h.argvs("terraform") if a[0] == "apply")
    assert apply[-1] == str(d / "production.tfplan")
    assert "-var" not in apply
    assert not any(a[0] == "plan" for a in h.argvs("terraform"))
    puts = [a for a in h.argvs("aws") if a[:2] == ["ecr", "put-image"]]
    assert len(puts) == 2
    tags = {
        a[a.index("--image-tag") + 1]: a[a.index("--image-digest") + 1] for a in puts
    }
    assert tags == {"release-v1.2.3": API, "release-v1.2.3-jobs": JOBS}
    for a in puts:
        assert has_pair(a, "--image-manifest", MANIFEST)
        assert has_pair(a, "--image-manifest-media-type", MEDIA)
    # Tags go on only after the deploy (and its smoke test) succeeded.
    assert h.index("curl", f"{SITE}/api/health") < h.index("aws", "ecr", "put-image")


def test_release_apply_accepts_existing_tag_on_same_digest(
    h: Harness, tmp_path: Path
) -> None:
    d = plan_dir(tmp_path)
    h.rule(
        "aws", match=["describe-images", "imageTag=release-v1.2.3-jobs"], stdout=JOBS
    )
    h.rule("aws", match=["describe-images", "imageTag=release-v1.2.3 "], stdout=API)
    deploy_ok(h, "production")
    r = h.run(
        "release-apply.sh",
        env={"CODEBUILD_SRC_DIR_plan": str(d), "RELEASE_COMMIT": COMMIT},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert not any(a[:2] == ["ecr", "put-image"] for a in h.argvs("aws"))


def test_release_apply_refuses_tag_on_other_digest(h: Harness, tmp_path: Path) -> None:
    d = plan_dir(tmp_path)
    h.rule(
        "aws", match=["describe-images", "imageTag=release-v1.2.3-jobs"], stdout=JOBS
    )
    h.rule("aws", match=["describe-images", "imageTag=release-v1.2.3 "], stdout=OTHER)
    deploy_ok(h, "production")
    r = h.run(
        "release-apply.sh",
        env={"CODEBUILD_SRC_DIR_plan": str(d), "RELEASE_COMMIT": COMMIT},
    )
    assert r.returncode != 0
    assert "release-v1.2.3" in r.stderr and OTHER in r.stderr
    # Checked before anything changes.
    assert not any(a[0] == "apply" for a in h.argvs("terraform"))
    assert not any(a[:2] == ["ecr", "put-image"] for a in h.argvs("aws"))


def test_release_apply_refuses_commit_mismatch(h: Harness, tmp_path: Path) -> None:
    d = plan_dir(tmp_path)
    r = h.run(
        "release-apply.sh",
        env={"CODEBUILD_SRC_DIR_plan": str(d), "RELEASE_COMMIT": "e" * 40},
    )
    assert r.returncode != 0
    assert not any(a[0] == "apply" for a in h.argvs("terraform"))


def test_release_apply_rejects_bad_release_env(h: Harness, tmp_path: Path) -> None:
    d = plan_dir(tmp_path, tag="v1; rm -rf /")
    r = h.run(
        "release-apply.sh",
        env={"CODEBUILD_SRC_DIR_plan": str(d), "RELEASE_COMMIT": COMMIT},
    )
    assert r.returncode != 0
    assert h.calls() == []


# ---- buildspecs ------------------------------------------------------------------


def buildspec(name: str) -> dict[str, Any]:
    return yaml.safe_load((CI / f"buildspec-{name}.yml").read_text())


def commands(spec: dict[str, Any]) -> str:
    return "\n".join(
        c for phase in spec["phases"].values() for c in phase.get("commands", [])
    )


def test_pr_buildspecs_stay_inline() -> None:
    # Ruling R15: the PR projects take their buildspecs from infra/bootstrap.
    assert not (CI / "buildspec-pr.yml").exists()
    assert not (CI / "buildspec-pr-cleanup.yml").exists()


def test_bootstrap_buildspec_paths_exist() -> None:
    codebuild = (REPO / "infra" / "bootstrap" / "codebuild.tf").read_text()
    assert '"ci/buildspec-${each.key}.yml"' in codebuild
    for key in ("staging", "release-plan", "release-apply"):
        spec = buildspec(key)
        assert spec["version"] == 0.2


def test_buildspecs_run_the_scripts() -> None:
    assert "ci/staging.sh" in commands(buildspec("staging"))
    plan = buildspec("release-plan")
    assert "ci/release-plan.sh" in commands(plan)
    assert plan["artifacts"]["base-directory"] == "release-out"
    assert sorted(plan["artifacts"]["files"]) == ["production.tfplan", "release.env"]
    assert "ci/release-apply.sh" in commands(buildspec("release-apply"))
    for key in ("staging", "release-plan", "release-apply"):
        assert "ci/install-terraform.sh" in commands(buildspec(key))


def test_install_terraform_verifies_checksum() -> None:
    text = (CI / "install-terraform.sh").read_text()
    assert "SHA256SUMS" in text and "sha256sum -c" in text


# ---- GitHub Actions --------------------------------------------------------------

WORKFLOWS = REPO / ".github" / "workflows"


def workflow(name: str) -> dict[Any, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def steps_text(job: dict[str, Any]) -> str:
    return "\n".join(str(s.get("run", "")) for s in job["steps"])


def test_ci_has_infra_and_e2e_jobs() -> None:
    jobs = workflow("ci.yml")["jobs"]
    infra = jobs["infra"]
    assert "make tf-check" in steps_text(infra)
    assert "make deploy-check" in steps_text(infra)
    e2e = jobs["e2e"]
    assert e2e["runs-on"] == "ubuntu-24.04"
    run = steps_text(e2e)
    assert (
        run.index("make stack-e2e")
        < run.index("playwright install --with-deps")
        < run.index("make e2e")
    )
    upload = next(s for s in e2e["steps"] if "upload-artifact" in s.get("uses", ""))
    assert upload["if"] == "failure()"
    assert upload["with"]["path"] == "frontend/playwright-report"


def test_preview_link_workflow() -> None:
    wf = workflow("preview-link.yml")
    # PyYAML reads the bare key `on` as True.
    on = wf["on"] if "on" in wf else wf[True]
    assert sorted(on["pull_request"]["types"]) == ["opened", "reopened", "synchronize"]
    assert wf["permissions"] == {"pull-requests": "write"}
    (job,) = wf["jobs"].values()
    assert (
        job["if"]
        == "github.event.pull_request.head.repo.full_name == github.repository"
    )
    text = (WORKFLOWS / "preview-link.yml").read_text()
    assert "Preview (deploys in a few minutes):" in text
    assert "vars.STAGING_SITE_URL" in text
    assert "/pr-${" in text
    assert "aws" not in text.lower().replace("always", "")


def test_actions_pinned_by_sha() -> None:
    for wf in WORKFLOWS.glob("*.yml"):
        for line in wf.read_text().splitlines():
            m = re.search(r"uses:\s*(\S+)", line)
            if m:
                assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", m.group(1)), line
                assert re.search(r"# v\d", line), f"missing version comment: {line}"


def test_github_actions_hold_no_aws_credentials() -> None:
    for wf in WORKFLOWS.glob("*.yml"):
        text = wf.read_text()
        assert "aws-actions/" not in text
        assert "AWS_" not in text
        assert "id-token" not in text


def test_lint_runs_actionlint() -> None:
    makefile = (REPO / "Makefile").read_text()
    lint = makefile.split("\nlint:", 1)[1].split("\n\n", 1)[0]
    assert "ci/actionlint.sh" in lint
    script = (CI / "actionlint.sh").read_text()
    assert re.search(r"[0-9a-f]{64}", script), (
        "actionlint download must be checksum-pinned"
    )
    assert os.access(CI / "actionlint.sh", os.X_OK)


# ---- spend-limit mode: deploy pre-check and db-start.sh ----------------------------

OPEN_ITEM = '{"pk":{"S":"control"},"state":{"S":"open"}}'
PAUSED_ITEM = '{"pk":{"S":"control"},"state":{"S":"chat_paused"}}'


def cluster_status(h: Harness, status: str) -> None:
    h.rule("aws", match=["rds", "describe-db-clusters"], stdout=f"{status}\n")


@pytest.mark.parametrize("status", ["stopped", "stopping"])
def test_deploy_stops_when_cluster_stopped(h: Harness, status: str) -> None:
    cluster_status(h, status)
    deploy_ok(h)
    r = h.run("deploy.sh", "staging", API, JOBS)
    assert r.returncode != 0
    assert "run make db-start ENV=staging" in r.stdout + r.stderr
    assert not [a for a in h.argvs("aws") if a[:2] == ["lambda", "invoke"]]
    # Before terraform: a production apply would spend the approved plan.
    assert h.calls("terraform") == []
    describe = next(a for a in h.argvs("aws") if "describe-db-clusters" in a)
    assert has_pair(describe, "--db-cluster-identifier", "phoebe-staging")
    assert has_pair(describe, "--region", "us-east-2")


def test_deploy_proceeds_when_cluster_available(h: Harness) -> None:
    cluster_status(h, "available")
    deploy_ok(h)
    r = h.run("deploy.sh", "staging", API, JOBS)
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.index("aws", "rds", "describe-db-clusters") < h.index(
        "aws", "lambda", "invoke"
    )


def test_db_start_starts_waits_then_reopens(h: Harness) -> None:
    cluster_status(h, "stopped")
    r = h.run("db-start.sh", "production")
    assert r.returncode == 0, r.stdout + r.stderr
    rds = [a for a in h.argvs("aws") if a[0] in ("rds", "dynamodb")]
    assert [a[:2] for a in rds] == [
        ["rds", "describe-db-clusters"],
        ["rds", "start-db-cluster"],
        ["rds", "wait"],
        ["dynamodb", "put-item"],
    ]
    assert has_pair(rds[1], "--db-cluster-identifier", "phoebe-production")
    assert rds[2][2] == "db-cluster-available"
    assert has_pair(rds[2], "--db-cluster-identifier", "phoebe-production")
    assert has_pair(rds[3], "--table-name", "phoebe-production-state")
    # By default it reopens browse-only: Budgets won't re-alert this month.
    assert json.loads(rds[3][rds[3].index("--item") + 1]) == json.loads(PAUSED_ITEM)
    assert all(has_pair(a, "--region", "us-east-2") for a in rds)


def test_db_start_skips_start_when_available(h: Harness) -> None:
    cluster_status(h, "available")
    r = h.run("db-start.sh", "staging")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not [a for a in h.argvs("aws") if "start-db-cluster" in a]
    put = next(a for a in h.argvs("aws") if a[:2] == ["dynamodb", "put-item"])
    assert has_pair(put, "--table-name", "phoebe-staging-state")


def test_db_start_refuses_while_stopping(h: Harness) -> None:
    cluster_status(h, "stopping")
    r = h.run("db-start.sh", "staging")
    assert r.returncode != 0
    assert "still stopping" in r.stdout + r.stderr
    assert not [
        a for a in h.argvs("aws") if a[0] == "dynamodb" or "start-db-cluster" in a
    ]


def test_db_start_stops_if_the_wait_fails(h: Harness) -> None:
    # Never reopen a demo whose database did not come back.
    cluster_status(h, "stopped")
    h.rule("aws", match=["rds", "wait"], exit=255, stderr="Waiter failed")
    r = h.run("db-start.sh", "staging")
    assert r.returncode != 0
    assert not [a for a in h.argvs("aws") if a[0] == "dynamodb"]


def test_db_start_open_reopens_fully(h: Harness) -> None:
    cluster_status(h, "available")
    r = h.run("db-start.sh", "production", "--open")
    assert r.returncode == 0, r.stdout + r.stderr
    put = next(a for a in h.argvs("aws") if a[:2] == ["dynamodb", "put-item"])
    assert json.loads(put[put.index("--item") + 1]) == json.loads(OPEN_ITEM)


@pytest.mark.parametrize(
    "args",
    [(), ("dev",), ("staging", "extra"), ("--open", "staging"), ("staging", "-o")],
)
def test_db_start_rejects_bad_args(h: Harness, args: tuple[str, ...]) -> None:
    r = h.run("db-start.sh", *args)
    assert r.returncode != 0
    assert h.calls() == []


def test_deploy_proceeds_when_cluster_does_not_exist_yet(h: Harness) -> None:
    # A first deploy creates the cluster in terraform apply.
    h.rule(
        "aws",
        match=["rds", "describe-db-clusters"],
        exit=254,
        stderr="An error occurred (DBClusterNotFoundFault)",
    )
    deploy_ok(h)
    r = h.run("deploy.sh", "staging", API, JOBS)
    assert r.returncode == 0, r.stdout + r.stderr


CLOSED_ITEM = '{"pk":{"S":"control"},"state":{"S":"closed"}}'


def test_db_stop_closes_the_demo_then_stops(h: Harness) -> None:
    cluster_status(h, "available")
    r = h.run("db-stop.sh", "staging")
    assert r.returncode == 0, r.stdout + r.stderr
    calls = [a for a in h.argvs("aws") if a[0] in ("rds", "dynamodb")]
    assert [a[:2] for a in calls] == [
        ["rds", "describe-db-clusters"],
        ["dynamodb", "put-item"],
        ["rds", "stop-db-cluster"],
    ]
    # Closed first, so no visitor hits a database that is shutting down.
    assert json.loads(calls[1][calls[1].index("--item") + 1]) == json.loads(CLOSED_ITEM)
    assert has_pair(calls[1], "--table-name", "phoebe-staging-state")
    assert has_pair(calls[2], "--db-cluster-identifier", "phoebe-staging")
    assert all(has_pair(a, "--region", "us-east-2") for a in calls)
    assert "make db-start ENV=staging" in r.stdout


@pytest.mark.parametrize("status", ["stopped", "stopping"])
def test_db_stop_is_a_no_op_when_already_stopping_or_stopped(
    h: Harness, status: str
) -> None:
    cluster_status(h, status)
    r = h.run("db-stop.sh", "staging")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not [a for a in h.argvs("aws") if "stop-db-cluster" in a]


@pytest.mark.parametrize("status", ["starting", "modifying", "backing-up"])
def test_db_stop_refuses_mid_transition(h: Harness, status: str) -> None:
    cluster_status(h, status)
    r = h.run("db-stop.sh", "staging")
    assert r.returncode != 0
    assert status in r.stdout + r.stderr
    assert not [
        a for a in h.argvs("aws") if a[0] == "dynamodb" or "stop-db-cluster" in a
    ]


@pytest.mark.parametrize("args", [(), ("dev",), ("staging", "extra")])
def test_db_stop_rejects_bad_args(h: Harness, args: tuple[str, ...]) -> None:
    r = h.run("db-stop.sh", *args)
    assert r.returncode != 0
    assert h.calls() == []
