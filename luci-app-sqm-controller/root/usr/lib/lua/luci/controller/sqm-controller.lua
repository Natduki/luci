module("luci.controller.sqm-controller", package.seeall)

function index()
    entry({"admin", "services", "sqm-controller"}, firstchild(), _("SQM Controller"), 60).index = true
    
    -- 状态页面
    entry({"admin", "services", "sqm-controller", "status"}, template("sqm-controller/status"), _("Status"), 10)
    
    -- 配置页面
    entry({"admin", "services", "sqm-controller", "config"}, cbi("sqm-controller"), _("Configuration"), 20)
    
    -- 日志页面
    entry({"admin", "services", "sqm-controller", "log"}, template("sqm-controller/log"), _("Log"), 30)
    
    -- API调用
    entry({"admin", "services", "sqm-controller", "action"}, call("action_handler"), nil).leaf = true
end

function action_handler()
    local action = luci.http.formvalue("action")
    local res = { success = false, message = "Unknown action" }
    
    if action == "start" then
        -- 启动服务
        local result = luci.sys.call("/usr/bin/sqm-start.sh >/dev/null 2>&1")
        if result == 0 then
            res = { success = true, message = "SQM Controller started successfully" }
        else
            res = { success = false, message = "Failed to start SQM Controller" }
        end
        
    elseif action == "stop" then
        -- 停止服务
        local result = luci.sys.call("/usr/bin/sqm-stop.sh >/dev/null 2>&1")
        if result == 0 then
            res = { success = true, message = "SQM Controller stopped successfully" }
        else
            res = { success = false, message = "Failed to stop SQM Controller" }
        end
        
    elseif action == "restart" then
        -- 重启服务
        local result = luci.sys.call("/usr/bin/sqm-start.sh >/dev/null 2>&1")
        if result == 0 then
            res = { success = true, message = "SQM Controller restarted successfully" }
        else
            res = { success = false, message = "Failed to restart SQM Controller" }
        end
        
    elseif action == "status" then
        -- 获取状态
        local status = luci.sys.exec("/usr/bin/sqm-status.sh")
        res = { 
            success = true, 
            message = "Status retrieved",
            data = status
        }
    end
    
    luci.http.prepare_content("application/json")
    luci.http.write_json(res)
end
