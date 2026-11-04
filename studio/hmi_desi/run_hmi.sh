#!/bin/sh
set -eu
: "${AUGELAB_STUDIO_PYTHON:?Set AUGELAB_STUDIO_PYTHON to the installed Studio Python executable}"
package_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$AUGELAB_STUDIO_PYTHON" "$package_dir/hmi_start.py"
