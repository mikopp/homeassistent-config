# The MQTT broker the tests run against (plans/test-execution.md, Step 4), pinned like Home
# Assistant itself (.github/ha-versions/ha/Dockerfile).
#
# What this pins: the latest release of the official Home Assistant "Mosquitto broker" app (add-on,
# source github.com/home-assistant/addons, directory `mosquitto`; image ghcr.io/home-assistant/
# app-mosquitto, multi-arch), because that is the broker a Home Assistant installation runs. The
# image is not an apk or Debian package: its Dockerfile builds Eclipse mosquitto from the git tag
# `v${MOSQUITTO_VERSION}` (plus a websocket patch) on debian:trixie-slim.
#
# How it is used: nothing runs this image per test. .github/scripts/install-mosquitto.sh copies the
# broker binary out of it (`docker cp`), and the tests start that binary per test (about 6 ms,
# docker run would cost about 150 ms). tests/ha/test_versions.py fails when the binary on PATH is
# not the version mapped below.
#
# How to bump (Dependabot raises a PR for the FROM line only): add the new line below (read the
# version with `.github/scripts/install-mosquitto.sh` then `mosquitto -h`, or from the app's
# CHANGELOG and Dockerfile `ARG MOSQUITTO_VERSION`). The guard test says so when the line is missing.
#
# app version -> mosquitto version inside it (one line per version in use; parsed by the guard test):
# mosquitto-in-app: 7.1.3 = 2.1.2
FROM ghcr.io/home-assistant/app-mosquitto:7.1.3
