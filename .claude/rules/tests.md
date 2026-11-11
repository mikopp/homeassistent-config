---
paths:
  - "tests/**"
  - ".github/workflows/tests.yaml"
  - ".github/workflows/e2e.yaml"
  - ".github/scripts/ci-local.sh"
  - ".github/scripts/install-mosquitto.sh"
  - ".github/scripts/install_custom_components.py"
  - ".github/test-paths"
  - "requirements_test.txt"
---

Before writing, running, debugging or reviewing tests here, invoke the `ha-test-harness` skill: where a test
goes (`tests/ha` by default, `tests/e2e` only with a `needs_real_ha` reason), how to run each layer, the
fixtures (`ha`, `seed`, `Clock`, real broker, `log_guard`) and the pins. Package-specific test facts are in the
package note.
