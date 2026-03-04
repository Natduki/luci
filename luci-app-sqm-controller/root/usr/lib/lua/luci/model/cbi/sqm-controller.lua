local sys = require "luci.sys"
local fs = require "nixio.fs"

m = Map("sqm-controller", translate("SQM Controller"), 
    translate("Configure Smart Queue Management (SQM) for traffic shaping."))

s = m:section(TypedSection, "config", translate("General Settings"))
s.addremove = false
s.anonymous = true

-- 启用/禁用
enabled = s:option(Flag, "enabled", translate("Enable"))
enabled.default = "0"
enabled.rmempty = false

-- 接口选择
iface = s:option(Value, "interface", translate("Interface"))
iface.default = "eth0"
iface.rmempty = false
iface.datatype = "string"

-- 下载速度
download = s:option(Value, "download_speed", translate("Download Speed (kbit/s)"))
download.default = "1000000"
download.rmempty = false
download.datatype = "uinteger"
download:value("10000", "10 Mbps")
download:value("50000", "50 Mbps")
download:value("100000", "100 Mbps")
download:value("500000", "500 Mbps")
download:value("1000000", "1 Gbps")

-- 上传速度
upload = s:option(Value, "upload_speed", translate("Upload Speed (kbit/s)"))
upload.default = "100000"
upload.rmempty = false
upload.datatype = "uinteger"
upload:value("1000", "1 Mbps")
upload:value("5000", "5 Mbps")
upload:value("10000", "10 Mbps")
upload:value("50000", "50 Mbps")
upload:value("100000", "100 Mbps")

-- QoS脚本
qos_script = s:option(Value, "qos_script", translate("QoS Script"))
qos_script.default = "simple.qos"
qos_script.rmempty = false
qos_script:value("simple.qos", "Simple QoS")
qos_script:value("fq_codel.qos", "FQ_CODEL")
qos_script:value("cake.qos", "CAKE")

-- 队列算法
qdisc = s:option(ListValue, "queue_algorithm", translate("Queue Algorithm"))
qdisc.default = "fq_codel"
qdisc.rmempty = false
qdisc:value("fq_codel", "Fair Queuing with Controlled Delay (fq_codel)")
qdisc:value("cake", "Common Applications Kept Enhanced (CAKE)")
qdisc:value("sfq", "Stochastic Fairness Queuing (SFQ)")

-- 链路层
linklayer = s:option(ListValue, "linklayer", translate("Link Layer Adaptation"))
linklayer.default = "ethernet"
linklayer.rmempty = false
linklayer:value("ethernet", "Ethernet")
linklayer:value("atm", "ATM")
linklayer:value("adsl", "ADSL")

-- 额外开销
overhead = s:option(Value, "overhead", translate("Per-Packet Overhead (bytes)"))
overhead.default = "0"
overhead.datatype = "integer"
overhead.rmempty = true

-- 高级设置部分
advanced = m:section(TypedSection, "advanced", translate("Advanced Settings"))
advanced.addremove = false
advanced.anonymous = true

-- 自动启动
autostart = advanced:option(Flag, "autostart", translate("Auto Start on Boot"))
autostart.default = "1"
autostart.rmempty = false

-- 日志级别
loglevel = advanced:option(ListValue, "log_level", translate("Log Level"))
loglevel.default = "info"
loglevel.rmempty = false
loglevel:value("debug", "Debug")
loglevel:value("info", "Info")
loglevel:value("warning", "Warning")
loglevel:value("error", "Error")

-- 日志文件路径
logfile = advanced:option(Value, "log_file", translate("Log File Path"))
logfile.default = "/var/log/sqm-controller.log"
logfile.rmempty = false

-- 自定义脚本
custom_script = advanced:option(TextValue, "custom_script", translate("Custom Script"))
custom_script.rows = 10
custom_script.wrap = "off"
custom_script.rmempty = true

-- 应用按钮
apply = m:section(SimpleSection)
apply.template = "sqm-controller/apply"

-- 保存后重启服务
function m.on_after_apply(self, has_changes)
    if has_changes then
        luci.sys.call("/etc/init.d/sqm-controller restart >/dev/null 2>&1")
    end
end

return m
