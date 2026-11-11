"""Install the custom components of tests/custom_components.yaml (the one implementation).

    python .github/scripts/install_custom_components.py            # into <repo>/custom_components
    python .github/scripts/install_custom_components.py <config>   # into <config>/custom_components
    ... --force                                                    # fetch again even if present

Used by the CI workflows (tests.yaml, e2e.yaml), `ci-local.sh`, and `tests/e2e/stage.py` (which
imports `install`). Nothing else may carry its own copy of this logic.

For every entry under `dependencies` (a HACS/GitHub custom component):
- if `<repo>/custom_components/<domain>` exists (a developer checkout, or an earlier run of this
  script) it is copied as is, so offline work and a locally edited component keep working;
- else GitHub's archive of `ref` of `repository` (a branch, tag or full commit SHA; default
  `main`) is downloaded and its `custom_components/<domain>` copied. A tag or SHA pins the
  component; a branch follows it.
- if that download fails, the same `ref` is fetched with a shallow `git fetch --depth 1`
  instead. Why the fallback: sandboxed sessions (Claude Code cloud) refuse github.com archive
  downloads of repositories not attached to the session but allow anonymous git reads of any
  public repository; CI runners can do both.
`ha_yaml_config` of the same file is gone: it only fed the retired Docker harness (the workday YAML
platform, which Home Assistant at the pin rejects); the tests create workday as a config entry.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
LISTING = ROOT / "tests" / "custom_components.yaml"


def install(target: Path, repo: Path = ROOT, force: bool = False) -> list[str]:
    """Put the listed components into `target`/custom_components; return their domains."""
    listed = yaml.safe_load(LISTING.read_text())
    domains = []
    for dep in listed.get("dependencies", []):
        domain = dep["domain"]
        domains.append(domain)
        destination = target / "custom_components" / domain
        local = repo / "custom_components" / domain
        if destination.exists() and not force:
            continue
        if destination.exists():
            shutil.rmtree(destination)
        if local.is_dir() and local != destination:
            shutil.copytree(local, destination, ignore=shutil.ignore_patterns("__pycache__"))
            continue
        repository = dep["repository"].rstrip("/").removesuffix(".git")
        ref = dep.get("ref", "main")
        print(f"Installing {dep.get('name', domain)} ({domain}) from {repository}@{ref}")
        with tempfile.TemporaryDirectory() as tmp:
            tree = _archive_download(repository, ref, Path(tmp) / "archive")
            if tree is None:
                tree = _git_fetch(repository, ref, Path(tmp) / "git")
            source = tree / "custom_components" / domain
            if not source.is_dir():
                sys.exit(f"{repository}@{ref} has no custom_components/{domain}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git"))
    return domains


def _git_fetch(repository: str, ref: str, work: Path) -> Path:
    """Check out `ref` (branch, tag or commit SHA) of `repository` into `work`, shallow.

    `git fetch <ref>` accepts all three forms, `git clone --branch` no SHA. Exits when git is
    missing or a step fails (both ways are then exhausted). No credential prompt: a private
    repository fails instead of waiting for input.
    """
    if shutil.which("git") is None:
        sys.exit(f"archive download of {repository}@{ref} failed and git is not installed")
    env = os.environ | {"GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    steps = (["init", "-q"], ["fetch", "-q", "--depth", "1", f"{repository}.git", ref],
             ["checkout", "-q", "FETCH_HEAD"])
    work.mkdir(parents=True)
    for args in steps:
        try:
            # Bounded: an unanswered GitHub must fail the job, not stall it.
            done = subprocess.run(["git", "-C", str(work), *args], env=env, timeout=120,
                                  capture_output=True, text=True, check=False)
        except subprocess.TimeoutExpired:
            sys.exit(f"git {args[0]} of {repository}@{ref} timed out")
        if done.returncode != 0:
            sys.exit(f"git {args[0]} of {repository}@{ref} failed: {done.stderr.strip()}")
    return work


def _archive_download(repository: str, ref: str, work: Path) -> Path | None:
    """Download and unpack GitHub's archive of `ref`; return the unpacked tree.

    `archive/<ref>.tar.gz` resolves a branch, tag or commit SHA, like the git path. Returns None
    (and says why) when the download fails, so the caller falls back to git.
    """
    work.mkdir(parents=True)
    archive = work / "component.tar.gz"
    try:
        # A bounded download: an unanswered GitHub must fail the job, not stall it.
        with urllib.request.urlopen(f"{repository}/archive/{ref}.tar.gz", timeout=60) as response, \
                archive.open("wb") as out:
            shutil.copyfileobj(response, out)
    except (OSError, ValueError) as error:  # URLError/HTTPError/timeouts are OSErrors
        print(f"  archive download failed ({error}), falling back to git fetch")
        return None
    with tarfile.open(archive) as tar:
        tar.extractall(work, filter="data")
    (tree,) = [p for p in work.iterdir() if p.is_dir()]
    return tree


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) > 1 or set(sys.argv[1:]) - set(args) - {"--force"}:
        sys.exit(__doc__)
    done = install(Path(args[0]).resolve() if args else ROOT, force="--force" in sys.argv)
    print("Custom components ready:", ", ".join(done))
