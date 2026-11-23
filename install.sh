#!/bin/sh
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
probe='import platform, struct, sys, sysconfig; sys.exit(not (sys.implementation.name == "cpython" and (3, 10) <= sys.version_info[:2] < (3, 15) and struct.calcsize("P") == 8 and platform.machine().lower() in ("amd64", "x86_64") and not sysconfig.get_config_var("Py_GIL_DISABLED")))'
for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -I -c "$probe" >/dev/null 2>&1; then
        exec "$candidate" -I "$repo/scripts/install_env.py" "$repo"
    fi
done
printf '%s\n' 'Install 64-bit CPython 3.10-3.14 and run the installer again.' >&2
exit 1
