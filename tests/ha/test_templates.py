"""Every Jinja template in the config renders on the in-process HA.

Templates are extracted by .github/scripts/extract_templates.py and rendered in two modes:
- state templates (no runtime variables): strict. The shared baseline is applied first, so an
  error, an undefined variable or a sentinel output (unknown, unavailable, None, empty) is a
  real failure.
- runtime templates (trigger, this, wait, repeat, script fields, ...): lenient. Those variables
  only exist inside a live run, so undefined-variable errors are expected; any other error
  (syntax, unknown filter, type error on defined data) is a failure.

ONE test on ONE HA instance: render all templates in a loop, collect every failure, one assert
that lists them all. No parametrize, so the cost is one HA boot, not one per template.

With `--package NAME` (tests/ha/conftest.py) only the templates extracted from
packages/NAME.yaml are rendered; without it, all of them.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.template import Template

from conftest import REPO, apply_baseline

# Outputs that mean "no value": a state template that renders one of these is broken.
_SENTINELS = {"unknown", "unavailable", "None", "none", ""}


def _extract() -> dict[str, list[dict[str, str]]]:
    """Run the CI extractor on the repo (loaded by path: .github/scripts is not a package)."""
    path = REPO / ".github" / "scripts" / "extract_templates.py"
    spec = importlib.util.spec_from_file_location("extract_templates", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.extract_templates(REPO)


def _render(hass: HomeAssistant, source: str) -> tuple[str | None, str | None, list[str]]:
    """Render like /api/template did: (output, error, undefined-variable messages).

    `log_fn` collects HA's undefined-variable messages for this template instead of logging
    them, so they are judged per mode below and do not trip the log guard.
    """
    undefined: list[str] = []

    def log_fn(level: int, message: str) -> None:
        undefined.append(f"{logging.getLevelName(level)}: {message}")

    try:
        output: Any = Template(source, hass).async_render(parse_result=False, log_fn=log_fn)
    except (TemplateError, ValueError) as err:
        return None, str(err), undefined
    return str(output), None, undefined


def _is_undefined_error(message: str) -> bool:
    """A runtime-only variable missing (expected outside a live run)."""
    return "is undefined" in message or "UndefinedError" in message


async def test_every_template_renders(ha: HomeAssistant, request: pytest.FixtureRequest) -> None:
    """All extracted templates (of the selected packages) render; failures are listed in one assert."""
    templates = _extract()
    # Guard against a silently empty extraction (e.g. a path change): it would pass vacuously.
    assert templates["state_templates"] and templates["runtime_templates"], templates
    # `--package`: keep only the templates whose source file is a selected package's YAML.
    if selected := request.config.getoption("package"):
        files = {f"packages/{name}.yaml" for name in selected}
        templates = {
            kind: [t for t in items if t["file"] in files] for kind, items in templates.items()
        }
        # A selected package without a single template would pass vacuously (e.g. a renamed file).
        assert templates["state_templates"] or templates["runtime_templates"], (
            f"no template extracted from {sorted(files)}"
        )
    await apply_baseline(ha)

    failures: list[str] = []
    # Strict: no error, no undefined variable, no sentinel output.
    for item in templates["state_templates"]:
        output, error, undefined = _render(ha, item["template"])
        where = f"{item['file']} (state): {item['template'].strip()[:120]!r}"
        if error is not None:
            failures.append(f"{where}\n    error: {error}")
        elif undefined:
            failures.append(f"{where}\n    undefined: {'; '.join(undefined)}")
        elif output.strip() in _SENTINELS:
            failures.append(f"{where}\n    sentinel output: {output.strip()!r}")
    # Lenient: only errors that are not about a runtime-only variable.
    for item in templates["runtime_templates"]:
        _output, error, _undefined = _render(ha, item["template"])
        if error is not None and not _is_undefined_error(error):
            where = f"{item['file']} (runtime): {item['template'].strip()[:120]!r}"
            failures.append(f"{where}\n    error: {error}")

    assert not failures, f"{len(failures)} template(s) failed:\n" + "\n".join(failures)
