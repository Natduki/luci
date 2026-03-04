local sys = require "luci.sys"
local translate = luci.i18n.translate

local function get_service_status()
    local enabled = sys.exec("uci -q get sqm_controller.basic_config.enabled"):gsub("%s+", "")
    if enabled == "1" then
        return "已启用"
    end
    return "未启用"
end

m = Map("sqm_controller", translate("SQM流量控制器"),
    translate("智能队列管理（SQM）用于优化延迟并提高带宽公平性。"))

status_section = m:section(SimpleSection, translate("服务状态"))
status_field = status_section:option(DummyValue, "_status", translate("当前状态"))
status_field.cfgvalue = function()
    return get_service_status()
end

basic = m:section(NamedSection, "basic_config", "basic_config", translate("基础配置"))
basic.addremove = false

enabled = basic:option(Flag, "enabled", translate("启用SQM"))
enabled.default = 0
enabled.rmempty = false

interface = basic:option(ListValue, "interface", translate("网络接口"))
for _, dev in ipairs(sys.net.devices()) do
    if dev ~= "lo" then
        interface:value(dev)
    end
end

-- Keep a safe fallback in case device list is empty in VM/container.
interface:value("eth0", "eth0")


download_speed = basic:option(Value, "download_speed", translate("下载带宽 (kbit/s)"))
download_speed.datatype = "uinteger"

upload_speed = basic:option(Value, "upload_speed", translate("上传带宽 (kbit/s)"))
upload_speed.datatype = "uinteger"

queue_algorithm = basic:option(ListValue, "queue_algorithm", translate("队列算法"))
queue_algorithm:value("fq_codel", "fq_codel")
queue_algorithm:value("cake", "cake")
queue_algorithm.default = "fq_codel"

advanced = m:section(NamedSection, "advanced_config", "advanced_config", translate("高级配置"))
advanced.addremove = false

autostart = advanced:option(Flag, "autostart", translate("开机自启"))
autostart.default = 1

log_level = advanced:option(ListValue, "log_level", translate("日志级别"))
log_level:value("debug", "Debug")
log_level:value("info", "Info")
log_level:value("warn", "Warn")
log_level:value("error", "Error")
log_level.default = "info"

log_file = advanced:option(Value, "log_file", translate("日志文件路径"))
log_file.default = "/var/log/sqm_controller.log"

return m