include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-sqm-controller
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_MAINTAINER:=Your Name <your.email@example.com>
PKG_LICENSE:=MIT
PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)

LUCI_TITLE:=SQM Controller
LUCI_DEPENDS:=+sqm-scripts +tc +python3 +python3-light +luci-lib-jsonc
LUCI_PKGARCH:=all

include $(TOPDIR)/feeds/luci/luci.mk

# call BuildPackage - OpenWrt buildroot signature
