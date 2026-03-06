#!/bin/sh

check_dependency() {
    if ! opkg list-installed | grep -q "^$1"; then
        echo "Missing dependency: $1"
        return 1
    fi
    return 0
}

REQUIRED_PKGS="ip-full tc-full python3 python3-light curl ca-bundle kmod-ifb kmod-sched-core kmod-sched-cake luci-base luci-compat luci-lib-ip luci-lib-nixio"

MISSING=""
for pkg in $REQUIRED_PKGS; do
    if ! check_dependency "$pkg"; then
        MISSING="$MISSING $pkg"
    fi
done

if [ -n "$MISSING" ]; then
    echo "Missing packages:$MISSING"
    echo "Please install them with:"
    echo "  opkg install$MISSING"
    exit 1
fi

echo "All dependencies satisfied"
exit 0
