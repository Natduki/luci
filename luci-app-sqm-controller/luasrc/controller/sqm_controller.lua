module("luci.controller.sqm_controller", package.seeall)

local fs = require "nixio.fs"
local http = require "luci.http"
local jsonc = require "luci.jsonc"
local sys = require "luci.sys"
local util = require "luci.util"

local APP_PY = "/usr/lib/sqm-controller/main.py"
local LOGF = "/var/log/sqm_controller.log"
local CONF = "/etc/config/sqm_controller"

local function exec_with_rc(cmd)
    local marker = "__SQM_RC__:"
    local out = sys.exec("(" .. cmd .. ") 2>&1; echo " .. marker .. "$?")
    local code = tonumber(out:match(marker .. "(%d+)%s*$")) or 1
    out = out:gsub("\n?" .. marker .. "%d+%s*$", "")
    return code, out
end

local function exec_json(cmd, fallback)
    local code, out = exec_with_rc(cmd)
    local data = jsonc.parse(out)
    if type(data) == "table" then
        return data
    end

    local result = {}
    if type(fallback) == "table" then
        for k, v in pairs(fallback) do
            result[k] = v
        end
    end

    result.success = false
    result.code = code
    result.error = result.error or "后端返回不是合法JSON"
    result.output = out or ""
    return result
end

function index()
    entry({"admin", "services", "sqm_controller"}, alias("admin", "services", "sqm_controller", "settings"), _("SQM流量控制"), 60)
    entry({"admin", "services", "sqm_controller", "settings"}, cbi("sqm_controller"), _("基础设置"), 10)
    entry({"admin", "services", "sqm_controller", "wizard"}, template("sqm_controller/wizard"), _("配置向导"), 12)
    entry({"admin", "services", "sqm_controller", "status"}, template("sqm_controller/status"), _("状态监控"), 20)
    entry({"admin", "services", "sqm_controller", "monitor"}, template("sqm_controller/monitor"), _("实时监控"), 23)
    entry({"admin", "services", "sqm_controller", "templates"}, template("sqm_controller/templates"), _("场景模板"), 25)
    entry({"admin", "services", "sqm_controller", "logs"}, template("sqm_controller/logs"), _("系统日志"), 30)
    entry({"admin", "services", "sqm_controller", "help"}, template("sqm_controller/help"), _("帮助文档"), 40)

    entry({"admin", "services", "sqm_controller", "get_status"}, call("action_get_status")).leaf = true
    entry({"admin", "services", "sqm_controller", "get_monitor"}, call("action_get_monitor")).leaf = true
    entry({"admin", "services", "sqm_controller", "get_monitor_history"}, call("action_get_monitor_history")).leaf = true
    entry({"admin", "services", "sqm_controller", "speedtest"}, call("action_speedtest")).leaf = true
    entry({"admin", "services", "sqm_controller", "self_check"}, call("action_self_check")).leaf = true
    entry({"admin", "services", "sqm_controller", "apply_template"}, call("action_apply_template")).leaf = true
    entry({"admin", "services", "sqm_controller", "wizard_apply"}, call("action_wizard_apply")).leaf = true
    entry({"admin", "services", "sqm_controller", "backup_config"}, call("action_backup_config")).leaf = true
    entry({"admin", "services", "sqm_controller", "restore_config"}, call("action_restore_config")).leaf = true

    entry({"admin", "services", "sqm_controller", "start_service"}, call("action_start_service")).leaf = true
    entry({"admin", "services", "sqm_controller", "stop_service"}, call("action_stop_service")).leaf = true
    entry({"admin", "services", "sqm_controller", "restart_service"}, call("action_restart_service")).leaf = true

    entry({"admin", "services", "sqm_controller", "get_logs"}, call("action_get_logs")).leaf = true
    entry({"admin", "services", "sqm_controller", "clear_logs"}, call("action_clear_logs")).leaf = true
    entry({"admin", "services", "sqm_controller", "download_log"}, call("action_download_log")).leaf = true
    entry({"admin", "services", "sqm_controller", "rotate_logs"}, call("action_rotate_logs")).leaf = true
end

function action_get_status()
    local data = exec_json("python3 " .. APP_PY .. " --status-json", {
        service_status = "error",
        pid = "N/A",
        tc_state = "error",
        tc_wan = "",
        tc_ifb = "",
        error = "状态后端失败"
    })
    http.write_json(data)
end

function action_get_monitor()
    local data = exec_json("python3 " .. APP_PY .. " --monitor", {
        latency = "-",
        loss = "-",
        bandwidth = "-",
        bandwidth_kbps = "-",
        error = "监控后端失败"
    })
    http.write_json(data)
end

function action_get_monitor_history()
    local window = http.formvalue("window") or "5m"
    if window ~= "1m" and window ~= "5m" and window ~= "1h" then
        window = "5m"
    end

    local data = exec_json(
        "python3 " .. APP_PY .. " --monitor-history --window " .. util.shellquote(window),
        {
            success = false,
            window = window,
            points = {},
            current = { bandwidth = "-", bandwidth_kbps = "-", latency = "-", loss = "-" },
            error = "监控历史后端失败"
        }
    )
    http.write_json(data)
end

function action_speedtest()
    local data = exec_json("python3 " .. APP_PY .. " --speedtest", {
        error = "测速后端失败"
    })
    http.write_json(data)
end

function action_self_check()
    local data = exec_json("python3 " .. APP_PY .. " --self-check", {
        success = false,
        error = "自检后端失败"
    })
    http.write_json(data)
end

function action_apply_template()
    local tpl = http.formvalue("name")
    if not tpl or tpl == "" then
        http.write_json({ success = false, error = "缺少模板名" })
        return
    end
    if not tpl:match("^[%w%-%_]+$") then
        http.write_json({ success = false, error = "模板名格式错误" })
        return
    end

    local data = exec_json("python3 " .. APP_PY .. " --template " .. util.shellquote(tpl), {
        success = false,
        error = "模板后端失败"
    })
    http.write_json(data)
end

function action_wizard_apply()
    local iface = (http.formvalue("iface") or ""):gsub("%s+", "")
    local download = (http.formvalue("download") or ""):gsub("%s+", "")
    local upload = (http.formvalue("upload") or ""):gsub("%s+", "")
    local algorithm = (http.formvalue("algorithm") or ""):gsub("%s+", "")
    local enabled = (http.formvalue("enabled") or "1"):gsub("%s+", "")

    if not iface:match("^[%w%._:%-]+$") then
        http.write_json({ success = false, error = "接口参数错误" })
        return
    end
    if not download:match("^%d+$") or tonumber(download) <= 0 then
        http.write_json({ success = false, error = "下载带宽参数错误" })
        return
    end
    if not upload:match("^%d+$") or tonumber(upload) <= 0 then
        http.write_json({ success = false, error = "上传带宽参数错误" })
        return
    end
    if algorithm ~= "fq_codel" and algorithm ~= "cake" then
        http.write_json({ success = false, error = "队列算法参数错误" })
        return
    end
    if enabled ~= "0" and enabled ~= "1" then
        http.write_json({ success = false, error = "启停参数错误" })
        return
    end

    local qiface = util.shellquote(iface)
    local qdownload = util.shellquote(download)
    local qupload = util.shellquote(upload)
    local qalgo = util.shellquote(algorithm)
    local qenabled = util.shellquote(enabled)

    local rc = 0
    rc = rc + sys.call("uci -q set sqm_controller.basic_config.interface=" .. qiface)
    rc = rc + sys.call("uci -q set sqm_controller.basic_config.download_speed=" .. qdownload)
    rc = rc + sys.call("uci -q set sqm_controller.basic_config.upload_speed=" .. qupload)
    rc = rc + sys.call("uci -q set sqm_controller.basic_config.queue_algorithm=" .. qalgo)
    rc = rc + sys.call("uci -q set sqm_controller.basic_config.enabled=" .. qenabled)
    rc = rc + sys.call("uci -q commit sqm_controller")

    if rc ~= 0 then
        http.write_json({ success = false, error = "保存配置失败", code = rc })
        return
    end

    local runtime_code, out
    if enabled == "1" then
        runtime_code, out = exec_with_rc("python3 " .. APP_PY .. " --enable")
    else
        runtime_code, out = exec_with_rc("python3 " .. APP_PY .. " --disable")
    end

    http.write_json({
        success = (runtime_code == 0),
        runtime_code = runtime_code,
        output = out,
        config = {
            iface = iface,
            download = tonumber(download),
            upload = tonumber(upload),
            algorithm = algorithm,
            enabled = (enabled == "1")
        }
    })
end

function action_backup_config()
    if not fs.access(CONF) then
        http.status(404, "Not Found")
        http.prepare_content("application/json")
        http.write_json({ success = false, error = "配置文件不存在" })
        return
    end

    local filename = "sqm_controller-" .. os.date("%Y%m%d-%H%M%S") .. ".backup"
    http.header("Content-Disposition", 'attachment; filename="' .. filename .. '"')
    http.prepare_content("text/plain")
    http.write(sys.exec("cat " .. util.shellquote(CONF)))
end

function action_restore_config()
    local tmpfile = "/tmp/sqm_controller.restore.upload"
    local fp = nil
    local uploaded = false

    fs.remove(tmpfile)

    http.setfilehandler(function(meta, chunk, eof)
        if not fp and meta and meta.name == "backup_file" then
            fp = io.open(tmpfile, "w")
            uploaded = fp ~= nil
        end
        if fp and chunk then
            fp:write(chunk)
        end
        if fp and eof then
            fp:close()
            fp = nil
        end
    end)

    http.formvalue("backup_file")
    if fp then
        fp:close()
    end

    if not uploaded or not fs.access(tmpfile) then
        http.prepare_content("application/json")
        http.write_json({ success = false, error = "未上传备份文件" })
        return
    end

    local apply_now = http.formvalue("apply_now")
    local cmd = "python3 " .. APP_PY .. " --restore-config " .. util.shellquote(tmpfile)
    if apply_now == "0" or apply_now == "false" then
        cmd = cmd .. " --no-apply"
    end

    local data = exec_json(cmd, {
        success = false,
        error = "恢复后端失败"
    })

    fs.remove(tmpfile)
    http.write_json(data)
end

function action_start_service()
    local code, out = exec_with_rc("python3 " .. APP_PY .. " --enable")
    http.write_json({ success = (code == 0), code = code, output = out })
end

function action_stop_service()
    local code, out = exec_with_rc("python3 " .. APP_PY .. " --disable")
    http.write_json({ success = (code == 0), code = code, output = out })
end

function action_restart_service()
    local stop_code, stop_out = exec_with_rc("python3 " .. APP_PY .. " --disable")
    local start_code, start_out = exec_with_rc("python3 " .. APP_PY .. " --enable")
    local out = (stop_out or "") .. "\n" .. (start_out or "")
    out = out:gsub("^\n+", "")
    http.write_json({
        success = (start_code == 0),
        code = start_code,
        stop_code = stop_code,
        output = out
    })
end

function action_get_logs()
    local data = sys.exec("test -f " .. LOGF .. " && cat " .. LOGF .. " || true")
    http.prepare_content("application/json")
    http.write_json({ content = data })
end

function action_clear_logs()
    sys.call("mkdir -p /var/log; : > " .. LOGF)
    http.prepare_content("application/json")
    http.write_json({ success = true })
end

function action_download_log()
    http.header("Content-Disposition", 'attachment; filename="sqm_controller.log"')
    http.prepare_content("text/plain")
    http.write(sys.exec("test -f " .. LOGF .. " && cat " .. LOGF .. " || echo 'no log'"))
end

function action_rotate_logs()
    local data = exec_json("python3 " .. APP_PY .. " --rotate-logs", {
        success = false,
        error = "日志轮转后端失败"
    })
    http.write_json(data)
end