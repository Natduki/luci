#!/bin/sh

# 检查必要的包是否安装
check_dependency() {
    if ! opkg list-installed | grep -q "^$1"; then
        echo "Missing dependency: $1"
        return 1
    fi
    return 0
}

# 必需的依赖
REQUIRED_PKGS="sqm-scripts tc python3 python3-light luci-lib-jsonc"

# 检查所有依赖
MISSING=""
for pkg in $REQUIRED_PKGS; do
    if ! check_dependency "$pkg"; then
        MISSING="$MISSING $pkg"
    fi
done

if [ -n "$MISSING" ]; then
    echo "Missing packages:$MISSING"
    echo "Please install them with: opkg install$MISSING"
    exit 1
fi

echo "All dependencies satisfied"
exit 0