"""Needs a real HA because: `check_config` is Home Assistant's own script (`python -m homeassistant
--script check_config`), run in the pinned image. It resolves `!include`/`!secret`, validates every
package against the integrations' real schemas and imports the HACS `climate_template` platform.
Nothing in-process runs that code path, and it needs no running instance, so it takes a throw-away
container (`check-config`).

The staging is the one CI uses (`tests/e2e/stage.py`), so this test and the CI step cannot drift
apart. The boot test (test_boot.py) already proves the running config works; this one is the
fast, precise failure when a schema error is introduced, and it also catches errors a boot only
logs.
"""

from __future__ import annotations

import pytest

from .stage import check_config, stage

pytestmark = pytest.mark.needs_real_ha("check-config")


def test_staged_config_passes_check_config(tmp_path):
    ok, output = check_config(stage(tmp_path / "config"))
    assert ok, f"check_config reported errors:\n{output}"
