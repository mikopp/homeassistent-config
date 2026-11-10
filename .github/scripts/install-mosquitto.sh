#!/usr/bin/env bash
# Install the pinned mosquitto broker (.github/ha-versions/mosquitto/Dockerfile) as a plain binary.
#
# Why not `apt-get install mosquitto`: the distribution's version drifts (the sandbox has 2.0.18,
# the Home Assistant Mosquitto app ships 2.1.2). The tests pin the broker like Home Assistant, to
# the one the official app ships, so the binary is taken out of that very image.
# Why not `docker run` per test: measured about 150 ms per start against about 6 ms for a binary.
#
# Usage:  .github/scripts/install-mosquitto.sh [dest]     (default .cache/mosquitto, git-ignored)
# Result: <dest>/bin/mosquitto, a wrapper that runs the extracted binary. Put <dest>/bin first on
#         PATH (CI appends it to $GITHUB_PATH, ci-local.sh exports it). The tests find the broker
#         with `shutil.which("mosquitto")` and tests/ha/test_versions.py checks its version.
# Needs:  docker (to pull the image), Linux (the binary is a Linux ELF; on macOS install the same
#         version with brew and let the guard test tell you whether it matches).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
DEST=$(realpath -m "${1:-.cache/mosquitto}")

[ "$(uname -s)" = "Linux" ] || {
  echo "install-mosquitto.sh extracts a Linux binary; on $(uname -s) install mosquitto with the" >&2
  echo "version in .github/ha-versions/mosquitto/Dockerfile yourself (brew install mosquitto)." >&2
  exit 1
}

# The image is the FROM line of the pin file (never typed twice).
IMAGE=$(awk '/^FROM /{print $2}' .github/ha-versions/mosquitto/Dockerfile)
echo "Pinned broker image: $IMAGE"
docker pull --quiet "$IMAGE" >/dev/null

# The broker binary is built into /usr/local/sbin by the app's Dockerfile. Its only library the
# usual runner does not have is libcjson; the rest (libssl, libz, libc) the host provides, the
# binary needs glibc 2.34 at most. Ask the image where libcjson is instead of hard-coding the
# architecture dependent path.
CJSON=$(docker run --rm --entrypoint sh "$IMAGE" -c "ldd /usr/local/sbin/mosquitto | awk '/libcjson/{print \$3}'")
[ -n "$CJSON" ] || { echo "libcjson not found in $IMAGE (the app's build changed?)" >&2; exit 1; }

mkdir -p "$DEST/bin" "$DEST/lib"
CID=$(docker create "$IMAGE")
trap 'docker rm -f "$CID" >/dev/null' EXIT
docker cp "$CID:/usr/local/sbin/mosquitto" "$DEST/lib/mosquitto.bin"
docker cp -L "$CID:$CJSON" "$DEST/lib/$(basename "$CJSON")"

# The wrapper only adds our lib dir to the library path. `exec` keeps the broker's pid, so the
# tests' `Popen.kill()` stops the broker itself and not just a shell around it.
cat > "$DEST/bin/mosquitto" <<WRAPPER
#!/bin/sh
LD_LIBRARY_PATH="$DEST/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}" exec "$DEST/lib/mosquitto.bin" "\$@"
WRAPPER
chmod +x "$DEST/bin/mosquitto" "$DEST/lib/mosquitto.bin"

"$DEST/bin/mosquitto" -h 2>&1 | grep -m1 '^mosquitto version'
echo "Installed: $DEST/bin/mosquitto"
