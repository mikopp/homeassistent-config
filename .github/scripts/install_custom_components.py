"""Install the custom components of tests/custom_components.yaml (the one implementation).

    python .github/scripts/install_custom_components.py            # into <repo>/custom_components
    python .github/scripts/install_custom_components.py <config>   # into <config>/custom_components
    ... --force                                                    # download again even if present

Used by the CI workflows (tests.yaml, e2e.yaml), `ci-local.sh`, and `tests/e2e/stage.py` (which
imports `install`). Nothing else may carry its own copy of this logic.

For every entry under `dependencies` (a HACS/GitHub custom component):
- if `<repo>/custom_components/<domain>` exists (a developer checkout, or an earlier run of this
  script) it is copied as is, so offline work and a locally edited component keep working;
- else the tarball of branch `ref` (default `main`, set it on a throw-away branch only, never on
  master) of `repository` is downloaded from GitHub and its `custom_components/<domain>` extracted.
`ha_yaml_config` of the same file is gone: it only fed the retired Docker harness (the workday YAML
platform, which Home Assistant at the pin rejects); the tests create workday as a config entry.
"""

from __future__ import annotations

import shutil
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
        owner_repo = dep["repository"].rstrip("/").removeprefix("https://github.com/")
        ref = dep.get("ref", "main")
        url = f"https://github.com/{owner_repo}/archive/refs/heads/{ref}.tar.gz"
        print(f"Installing {dep.get('name', domain)} ({domain}) from {dep['repository']}@{ref}")
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "component.tar.gz"
            # A bounded download: an unanswered GitHub must fail the job, not stall it.
            with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as out:
                shutil.copyfileobj(response, out)
            with tarfile.open(archive) as tar:
                tar.extractall(tmp, filter="data")
            (source,) = [p for p in Path(tmp).glob(f"*/custom_components/{domain}") if p.is_dir()]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)
    return domains


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) > 1 or set(sys.argv[1:]) - set(args) - {"--force"}:
        sys.exit(__doc__)
    done = install(Path(args[0]).resolve() if args else ROOT, force="--force" in sys.argv)
    print("Custom components ready:", ", ".join(done))
