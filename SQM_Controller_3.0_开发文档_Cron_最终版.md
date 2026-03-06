# SQM Controller 3.0 开发文档（最终版｜Cron 方案｜可直接喂给 Codex）
> 目标：在现有 2.0（已具备 tc+ifb+htb、LuCI 监控/日志/模板/测速）基础上完成 3.0「智能优化版」：**流量识别与分类 + 自适应策略 + 分类可视化 + 性能报告**，并满足毕设任务书“iptables/标记 + tc(HTB+fq_codel)调度 + Web 界面 + 打包 + 测试验证”的要求。  
> 策略执行方式：**cron**（不引入常驻进程，降低出错面，便于复现和论文描述）。

---

## 0. 对齐与约束

### 0.1 与毕设任务的对齐（必须完成）
- **流量分类与标记**：基于端口/协议/IP 等多维规则分类并打标记（iptables / nftables）。
- **队列调度与带宽管理**：基于 **HTB + fq_codel**（允许保留 cake 作为可选）实现优先级保障与公平分配。
- **Web 管理界面（LuCI）**：策略配置、状态可视化、系统开关。
- **系统集成与测试**：封装成 OpenWrt 标准软件包（ipk），做功能与性能测试（延迟改善、CPU 开销）。

> 备注：3.0 是最后一版，范围应以“可落地+可复现+论文可写”为优先。

### 0.2 不破坏 2.0 的兼容约束（必须遵守）
- **不改旧接口语义**：现有 `--status-json / --monitor / --monitor-history / --speedtest / --template / --enable / --disable` 行为保持不变；LuCI 现有页面和接口不回归。
- **tc 主链路保留**：仍使用 2.0 的 `ifb0 + htb` 结构扩展多 class，而不是换架构。
- **前端稳定性优先**：新增字段只“加”，不删除不改名；任何失败都返回可解析 JSON（带 `success/error`）。

---

## 1. 3.0 MVP 范围（必做）与选做

### 1.1 MVP（必做、可验收、可写论文）
1) **流量识别与分类模块**
   - 端口 / 协议 / IP 规则 → 类别（gaming / streaming / bulk / other）
   - 支持规则启用/禁用、优先级、应用/清理（不残留）
2) **分类队列（HTB 多 class）**
   - 上行（WAN egress）+ 下行（ifb0）均支持多 class
   - 用 `tc filter ... fw` 按 mark 导流到 class
   - leaf qdisc 默认 fq_codel（对齐任务书），cake 可选保留
3) **自适应策略引擎（最小可行）**
   - 输入：延迟/丢包/带宽（来自现有 monitor + 可选 tc class stats）
   - 输出：动态调整各 class 的 rate/ceil/prio 或切换 profile
   - **cron 触发**（每分钟一次或自定义频率）
4) **LuCI 高级展示**
   - 分类占比/速率视图（traffic）
   - 策略状态/手动触发（policy）
5) **性能分析报告**
   - 导出 CSV/JSON：时间序列（lat/loss/bw/class_kbps/policy_mode/changes）
   - 支撑论文：对照组 2.0 vs 实验组 3.0

### 1.2 选做（时间够再做）
- sfq（仅作为 bulk 类 leaf qdisc 可选）
- 定时规则（按时间段切 profile，依旧用 cron）
- 多接口（放最后；先做单 WAN/单 ifb0 的稳定闭环）

---

## 2. 目录结构与新增文件

保持你现有包结构不变，仅新增 python 文件与少量 LuCI view/controller 增量。

新增文件建议放在：
```
files/usr/lib/sqm-controller/
  ├── firewall_manager.py      # nft/iptables 规则应用与清理（mark+connmark）
  ├── traffic_classifier.py    # 读取 UCI 分类规则 -> 生成 mark_to_class -> 调用 firewall_manager
  ├── traffic_stats.py         # 读取 tc class 统计（tc -s class show）并计算 kbps/占比
  ├── policy_engine.py         # 策略决策（一次执行）+ 状态输出（供 LuCI/报告）
  └── report_manager.py        # 汇总并导出 CSV/JSON（可选）
```

改动文件（增量，不破坏旧逻辑）：
- `files/usr/lib/sqm-controller/main.py`：新增 CLI 入口
- `files/usr/lib/sqm-controller/tc_manager.py`：新增多 class/filter 支持（保留原 `setup_htb()`）
- `files/etc/init.d/sqm-controller`：加入 cron 写入/清理逻辑
- `luasrc/controller/sqm_controller.lua`：新增 LuCI endpoints
- `luasrc/view/sqm_controller/`：新增 `traffic.htm / policy.htm / report.htm`

---

## 3. UCI 配置设计（建议 schema）

在 `/etc/config/sqm_controller` 增量添加：

### 3.1 classification
```
config classification 'classification'
  option enabled '1'
  option backend 'auto'              # auto | nft | iptables
  option mark_other '0x10'
  option mark_gaming '0x11'
  option mark_streaming '0x12'
  option mark_bulk '0x13'
  option apply_scope 'forward'       # forward | all
```

### 3.2 classifier_rules（多条规则）
每条规则一个 `config class_rule`：
```
config class_rule
  option name 'gaming_udp'
  option enabled '1'
  option category 'gaming'           # gaming|streaming|bulk|other
  option priority '100'              # 数字越大优先级越高
  option proto 'udp'                 # tcp|udp|any
  option dport '3074,3478,3659'      # 逗号分隔
  option sport ''                    # 可空
  option src_ip ''                   # 可空，CIDR
  option dst_ip ''                   # 可空，CIDR
```

冲突处理（必须写进实现）：
- priority 高的先匹配；priority 相同按“更具体优先（IP > 端口 > 协议）”
- 命中后应保存到 conntrack mark，后续包一致

### 3.3 policy（cron 执行）
```
config policy 'policy'
  option enabled '1'
  option cron '*/1 * * * *'          # 默认每分钟（可调）
  option mode 'auto'                 # auto|balanced|gaming|streaming|bulk
  option latency_high_ms '80'
  option loss_high_pct '2'
  option bulk_cap_pct '60'           # bulk ceil 不超过总下载的 60%
  option gaming_floor_pct '15'       # gaming rate 至少 15%
  option streaming_floor_pct '25'
  option cooldown_min '2'            # 连续 N 分钟才切换/回退，防抖
```

---

## 4. 流量识别与标记（nft 优先，iptables 兜底）

### 4.1 目标
- 基于规则给流量打 `fwmark`（0x10~0x13）
- 使用 conntrack 保存：避免每包重复匹配，降低 CPU
- 支持 apply/clear 幂等

### 4.2 nftables 实现要点（推荐）
- `table inet sqm_controller`  
- `chain forward`（hook forward priority mangle）  
- 规则动作：`meta mark set 0x11; ct mark set meta mark`

### 4.3 iptables 实现要点（兜底）
- mangle 表 `FORWARD` 链挂入自定义链 `SQM_CLASSIFY`
- 用 `MARK --set-mark` + `CONNMARK --save-mark`
- 在 PREROUTING 处 `CONNMARK --restore-mark`（确保后续包继承）

### 4.4 规则应用与清理
- apply：创建链/表（如不存在）→ flush → 按优先级写入 → 挂 hook（只挂一次）
- clear：卸载 hook → 删除链/表（建议彻底删除）

---

## 5. tc 分类队列（HTB 多 class + fw filter）

### 5.1 class 规划（最小可行）
在上传（iface root 1:）与下载（ifb0 root 2:）各建 4 类：

- other/default：`1:10` / `2:20`
- gaming：`1:11` / `2:21`
- streaming：`1:12` / `2:22`
- bulk：`1:13` / `2:23`

### 5.2 filter（按 mark 导流）
- `mark_gaming` → flowid `1:11` / `2:21`
- `mark_streaming` → flowid `1:12` / `2:22`
- `mark_bulk` → flowid `1:13` / `2:23`
- other/default → 走默认 class

### 5.3 leaf qdisc（论文默认 fq_codel）
- 每个 class 下挂 fq_codel（ecn/noecn 由现有配置决定）
- cake 可选：允许用户全局算法选择 cake 时改为 cake

### 5.4 幂等性要求（必须）
- 重复 apply 不应报错：存在则跳过/先删再建
- clear 只清理 3.0 新增的 class/filter，不破坏 2.0 默认结构

---

## 6. 自适应策略引擎（cron 方案）

### 6.1 cron 执行模型（推荐）
- cron 每分钟执行一次：`python3 /usr/lib/sqm-controller/main.py --policy-once`
- 策略引擎只做“一次评估 + 可能的调整 + 写日志”，无常驻进程

### 6.2 输入（MVP）
- monitor current：latency/loss/bandwidth_kbps
- traffic_stats：各 class 的 kbps/占比（建议做）

### 6.3 输出（MVP）
- latency/loss 过阈值：提升 gaming、限制 bulk
- streaming 占比高：保障 streaming floor
- 正常：回到 balanced（cooldown 防抖）

### 6.4 记录与报告
- `/tmp/sqm_policy_state.json`（当前策略状态）
- `/var/log/sqm_policy.jsonl`（每次执行追加一行 JSON）
- export：聚合生成 CSV/JSON（report 页面或 main.py export）

---

## 7. LuCI/UI 与 API（只增不改）

### 7.1 新增后端 API（controller 路由）
- apply_classifier / clear_classifier
- get_class_stats
- policy_once
- export_report

### 7.2 新增页面
- `traffic.htm`：分类占比、各类 kbps，3 秒刷新
- `policy.htm`：策略状态、阈值、按钮“运行一次策略”
- `report.htm`：导出报告按钮 + 简要统计

---

## 8. 测试与验收（论文可复现）

### 8.1 对照组与实验组
- 对照组：2.0（关闭 classification/policy）
- 实验组：3.0（开启 classification，policy auto）

### 8.2 场景（至少 3 组）
1) bulk 下载压测 + gaming（UDP）并发 → 延迟改善 ≥30%
2) streaming + bulk 并发 → streaming 更稳定
3) 空闲→突发→恢复 → 策略不震荡（cooldown 生效）

### 8.3 指标
- 分类准确率 ≥80%（在可控实验流量集合上）
- 延迟：中位数/95th（对照 vs 实验）
- CPU：平均增量 <10%

---

# 9. Codex 分步喂养指令（按顺序执行）

> 每次让 Codex **只改少量文件**，并要求输出 **unified diff patch**。

## Step 0：规范（只输出约束）
**Prompt：**
> 这是一个 OpenWrt LuCI 包（2.0 已稳定）。你必须：只增不改旧接口语义；所有后端 API 返回 JSON 并包含 success/error；tc/nft/iptables 操作必须幂等；所有 shell 调用检查返回码；策略执行用 cron，不引入常驻 daemon。确认你已理解，然后不输出代码。

## Step 1：新增 UCI schema（仅配置片段）
**Prompt：**
> 为 `/etc/config/sqm_controller` 增量添加 classification、class_rule、policy 三个 section 的样例配置。不要修改 Python/Lua 代码，只给出配置片段和默认值说明。

## Step 2：firewall_manager.py
**Prompt：**
> 在 `files/usr/lib/sqm-controller/` 新增 `firewall_manager.py`：  
> 1) 探测 nft 是否可用（优先 nft，否则 iptables）；  
> 2) 输入规则列表（proto/ports/ip/priority/category->mark）；  
> 3) apply：生成并应用规则（nft table/chain 或 iptables chain），使用 conntrack mark 保存；  
> 4) clear：清理所有该模块创建的规则；  
> 5) 输出 JSON（success/error/backend/details）。  
> 只新增文件，不改其他文件。

## Step 3：tc_manager.py（多 class/filter）
**Prompt：**
> 修改 `tc_manager.py`：保留原 `setup_htb()` 行为不变。新增：  
> - `apply_classes(plan)`：创建多 class（1:11/1:12/1:13 与 2:21/2:22/2:23），并在每个 class 下挂 fq_codel/cake；  
> - `apply_fwmark_filters(map)`：按 mark 添加 `tc filter ... fw flowid ...` 到 iface 与 ifb0；  
> - `clear_classifier_tc()`：只清理新增 class/filter，不影响默认 class。  
> 所有 tc 命令必须幂等。只输出 unified diff。

## Step 4：traffic_classifier.py
**Prompt：**
> 新增 `traffic_classifier.py`：  
> - 从 ConfigManager 读取 classification/policy/class_rule；  
> - 对规则按 priority + 具体性排序；  
> - 生成 mark_to_classid 映射；  
> - 调用 firewall_manager.apply_rules()；  
> - 调用 tc_manager.apply_classes() + apply_fwmark_filters()；  
> - 返回 JSON（success, rules_count, backend, marks, errors）。  
> 只新增文件，不改其他文件。

## Step 5：traffic_stats.py
**Prompt：**
> 新增 `traffic_stats.py`：  
> - 解析 `tc -s class show dev <iface|ifb0>` 的 bytes/packets；  
> - 用 state 文件做差分，输出每类 kbps 与占比；  
> - 返回 JSON（time, classes{...}, total_kbps）。  
> 只新增文件，不改其他文件。

## Step 6：policy_engine.py（一次执行）
**Prompt：**
> 新增 `policy_engine.py`：  
> - 输入：UCI policy 阈值 + monitor current + traffic_stats；  
> - 输出：policy_state（/tmp/sqm_policy_state.json）与决策日志（/var/log/sqm_policy.jsonl）；  
> - 动作：调用 tc_manager 调整 class rate/ceil/prio（仅增量修改，不重建整棵树）；  
> - 加 cooldown 防抖；  
> - 返回 JSON（success, mode, reason, actions, changed）。  
> 只新增文件。

## Step 7：main.py 接入 3.0（只增 CLI）
**Prompt：**
> 修改 `main.py`：保持所有旧参数行为不变。新增：  
> - `--apply-classifier`：调用 traffic_classifier.apply()；  
> - `--clear-classifier`：调用 firewall_manager.clear() + tc_manager.clear_classifier_tc()；  
> - `--get-class-stats`：调用 traffic_stats 输出；  
> - `--policy-once`：调用 policy_engine.run_once()；  
> - `--export-report`：从 /var/log/sqm_policy.jsonl 输出 CSV/JSON。  
> 输出 unified diff patch，确保旧 API 不回归。

## Step 8：init.d 写入/清理 cron（不启 procd）
**Prompt：**
> 修改 `files/etc/init.d/sqm-controller`：  
> - 当 `policy.enabled=1` 时：写入 `/etc/crontabs/root` 一条任务（使用 policy.cron 或默认每分钟），执行 `python3 /usr/lib/sqm-controller/main.py --policy-once`；  
> - stop 时删除该 crontab 行；  
> - start/stop 仍保持 2.0 enable/disable 行为不变；  
> - 修改后要幂等，不重复写多行。  
> 输出 unified diff patch。

## Step 9：LuCI controller 增加新 endpoint（只增不改）
**Prompt：**
> 修改 `luasrc/controller/sqm_controller.lua`：新增 endpoints：  
> - apply_classifier → `main.py --apply-classifier`  
> - clear_classifier → `main.py --clear-classifier`  
> - get_class_stats → `main.py --get-class-stats`  
> - policy_once → `main.py --policy-once`  
> - export_report → `main.py --export-report`（下载）  
> 保持旧 endpoints 不变。输出 unified diff patch。

## Step 10：新增 traffic.htm / policy.htm / report.htm
**Prompt：**
> 在 `luasrc/view/sqm_controller/` 新增 traffic.htm、policy.htm、report.htm。  
> - traffic：每 3 秒刷新 class stats；  
> - policy：展示 policy_state + 按钮触发 policy_once；  
> - report：提供导出 CSV/JSON 按钮。  
> 注意：不要嵌套多余 `<script>` 标签；返回字段缺失时要容错显示。  
> 只输出新增文件内容。

---

# 10. 每步最小验收命令（OpenWrt）

- 分类 apply 后：
  - `tc -s class show dev ifb0`
  - `tc filter show dev ifb0 parent 2:`
  - `nft list ruleset | grep sqm_controller`（或 `iptables -t mangle -S | grep SQM_CLASSIFY`）
- 策略执行：
  - `python3 /usr/lib/sqm-controller/main.py --policy-once`
  - `tail -n 5 /var/log/sqm_policy.jsonl`
- UI：
  - traffic/policy/report 页面拉取 JSON 正常，控制台无 JS 错

#### 一、后端命令行验收

先确认 Python 文件没语法问题：

```
python3 -m py_compile /usr/lib/sqm-controller/main.py
python3 -m py_compile /usr/lib/sqm-controller/traffic_classifier.py
python3 -m py_compile /usr/lib/sqm-controller/traffic_stats.py
python3 -m py_compile /usr/lib/sqm-controller/policy_engine.py
python3 -m py_compile /usr/lib/sqm-controller/tc_manager.py
```

确认核心命令都能返回 JSON 或明确结果：

```
python3 /usr/lib/sqm-controller/main.py --status-json
python3 /usr/lib/sqm-controller/main.py --get-class-stats --dev ifb0
python3 /usr/lib/sqm-controller/main.py --get-class-stats --dev iface
python3 /usr/lib/sqm-controller/main.py --policy-once
python3 /usr/lib/sqm-controller/main.py --export-report --format json | head -c 300; echo
python3 /usr/lib/sqm-controller/main.py --export-report --format csv | head -n 5
```

```
root@OpenWrt:~# python3 /usr/lib/sqm-controller/main.py --status-json
{"service_status": "running", "pid": "N/A(no resident process)", "tc_state": "applied", "ecn_state": "enabled", "tc_wan": "qdisc htb 1: root refcnt 2 r2q 10 default 0x10 direct_packets_stat 0 direct_qlen 1000\nqdisc fq_codel 10: parent 1:10 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms memory_limit 32Mb ecn drop_batch 64 \nqdisc ingress ffff: parent ffff:fff1 ---------------- ", "tc_ifb": "qdisc htb 2: root refcnt 2 r2q 10 default 0x20 direct_packets_stat 0 direct_qlen 32\nqdisc fq_codel 20: parent 2:20 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms memory_limit 32Mb ecn drop_batch 64 "}
root@OpenWrt:~# python3 /usr/lib/sqm-controller/main.py --get-class-stats --dev ifb0
{"success": true, "time": 1772814866, "dt": 566.0, "device": "ifb0", "classes": {"other": {"classid": "2:20", "bytes": 747157602, "packets": 633249, "kbps": 259.54, "pct": 100.0}, "gaming": {"classid": "2:21", "bytes": 0, "packets": 0, "kbps": 0.0, "pct": 0.0}, "streaming": {"classid": "2:22", "bytes": 0, "packets": 0, "kbps": 0.0, "pct": 0.0}, "bulk": {"classid": "2:23", "bytes": 0, "packets": 0, "kbps": 0.0, "pct": 0.0}}, "total_kbps": 259.54}
root@OpenWrt:~# python3 /usr/lib/sqm-controller/main.py --get-class-stats --dev iface
{"success": true, "time": 1772814866, "dt": 589.0, "device": "eth1", "classes": {"other": {"classid": "1:10", "bytes": 95117520, "packets": 574220, "kbps": 28.34, "pct": 100.0}, "gaming": {"classid": "1:11", "bytes": 0, "packets": 0, "kbps": 0.0, "pct": 0.0}, "streaming": {"classid": "1:12", "bytes": 0, "packets": 0, "kbps": 0.0, "pct": 0.0}, "bulk": {"classid": "1:13", "bytes": 0, "packets": 0, "kbps": 0.0, "pct": 0.0}}, "total_kbps": 28.34}
root@OpenWrt:~# python3 /usr/lib/sqm-controller/main.py --policy-once
{"success": true, "mode": "gaming", "reason": "severe congestion", "actions": [], "changed": false}
root@OpenWrt:~# python3 /usr/lib/sqm-controller/main.py --export-report --format json | head -c 300; echo
{"success": true, "format": "json", "count": 57, "entries": [{"time": 1772804036, "inputs": {"policy": {"enabled": true, "mode": "auto", "latency_high_ms": 80, "loss_high_pct": 2, "bulk_cap_pct": 60, "gaming_floor_pct": 15, "streaming_floor_pct": 25, "cooldown_min": 2}, "monitor": {"latency": 223.44Exception ignored in: <_io.TextIOWrapper name='<stdout>' mode='w' encoding='utf-8'>
BrokenPipeError: [Errno 32] Broken pipe

root@OpenWrt:~# python3 /usr/lib/sqm-controller/main.py --export-report --format csv | head -n 5
time,decision.mode,decision.reason,inputs.monitor.latency,inputs.monitor.loss,inputs.traffic_stats.total_kbps,changed
1772804036,gaming,severe congestion,223.44,0.0,916.25,True
1772804037,gaming,severe congestion,223.44,0.0,40.65,False
1772804039,gaming,severe congestion,223.44,0.0,10.7,False
1772804046,gaming,severe congestion,223.44,0.0,2.03,False

```

分类器链路：

```
python3 /usr/lib/sqm-controller/main.py --apply-classifier
tc filter show dev ifb0 parent 2: | sed -n '1,120p'
nft list table inet sqm_fw | sed -n '1,120p'
```

```
root@OpenWrt:~# python3 /usr/lib/sqm-controller/main.py --apply-classifier
{"success": false, "rules_count": 0, "backend": "", "marks": {"category_marks": {}, "mark_to_classid": {}}, "errors": ["missing classification section"], "warnings": ["IPv4 download classification is guaranteed in v3.0 first release; IPv6 download classification requires setup_htb() redirect enhancement."], "details": {"config_path": "/etc/config/sqm_controller", "config_candidates": ["/etc/config/sqm_controller", "/etc/config/sqm-controller"], "firewall_applied": false, "config_path_used_by_manager": "/etc/config/sqm_controller", "sections_count": 2, "sections_found": {"classification": 0, "class_rule": 0, "policy": 0}, "policy": {}, "aborted_before_firewall": true}}
root@OpenWrt:~# tc filter show dev ifb0 parent 2: | sed -n '1,120p'
root@OpenWrt:~# nft list table inet sqm_fw | sed -n '1,120p'
Error: No such file or directory
list table inet sqm_fw
                ^^^^^^

```

清理分类器链路：

```
python3 /usr/lib/sqm-controller/main.py --clear-classifier
tc filter show dev ifb0 parent 2: | sed -n '1,120p'
nft list table inet sqm_fw 2>/dev/null || echo "sqm_fw removed or empty"
```

```
root@OpenWrt:~# python3 /usr/lib/sqm-controller/main.py --clear-classifier
{"success": false, "firewall": {"success": true, "backend": "nft", "error": "", "details": {"commands": [{"cmd": "/usr/sbin/nft delete table inet sqm_fw", "rc": 1, "stdout": "", "stderr": "Error: Could not process rule: No such file or directory\ndelete table inet sqm_fw\n                  ^^^^^^"}], "note": "table not found"}}, "tc": {"success": false, "error": "clear_classifier_tc failed"}, "errors": ["tc: clear_classifier_tc failed"]}
root@OpenWrt:~# tc filter show dev ifb0 parent 2: | sed -n '1,120p'
root@OpenWrt:~# nft list table inet sqm_fw 2>/dev/null || echo "sqm_fw removed or empty"
sqm_fw removed or empty

```



#### 二、traffic_stats 专项验收

验证 LuCI 环境下也能跑，不再依赖 PATH：

```
env -i PATH=/usr/bin:/bin python3 /usr/lib/sqm-controller/traffic_stats.py --dev ifb0
env -i PATH=/usr/bin:/bin python3 /usr/lib/sqm-controller/traffic_stats.py --dev eth1
```

连续跑两次，确认第二次有 `dt` 和速率：

```
python3 /usr/lib/sqm-controller/traffic_stats.py --dev ifb0
sleep 3
python3 /usr/lib/sqm-controller/traffic_stats.py --dev ifb0
```

检查 state 文件：

```
ls -l /tmp/sqm_traffic_stats_state_ifb0.json
cat /tmp/sqm_traffic_stats_state_ifb0.json
```

#### 三、policy engine 专项验收

先跑一次策略：

```
python3 /usr/lib/sqm-controller/main.py --policy-once
```

看 state 和日志：

```
cat /tmp/sqm_policy_state.json
tail -n 5 /var/log/sqm_policy.jsonl
```

确认 actions 一直是数组：

```
python3 - <<'PY'
import json, subprocess
out = subprocess.check_output(["python3","/usr/lib/sqm-controller/main.py","--policy-once"], text=True)
d = json.loads(out)
print(d)
assert isinstance(d.get("actions"), list)
print("OK")
PY
```

#### 四、LuCI 接口验收

用已登录 cookie 测接口，确认都是 JSON。

先准备 cookie 后测：

```
curl -i -s --cookie 'sysauth_http=你的值' \
  'http://127.0.0.1/cgi-bin/luci/admin/services/sqm_controller/policy_once' \
  | head -n 20
```

策略状态接口：

```
curl -s --cookie 'sysauth_http=你的值' \
  'http://127.0.0.1/cgi-bin/luci/admin/services/sqm_controller/get_policy_state'
```

分类流量统计接口：

```
curl -s --cookie 'sysauth_http=你的值' \
  'http://127.0.0.1/cgi-bin/luci/admin/services/sqm_controller/get_class_stats?dev=ifb0'
```

报告导出接口：

```
curl -s --cookie 'sysauth_http=你的值' \
  'http://127.0.0.1/cgi-bin/luci/admin/services/sqm_controller/export_report?format=json' \
  | head -c 300; echo
```

#### 五、LuCI 页面验收

浏览器里重点看这三页：

##### 1. 分类流量统计

检查：

- 能自动刷新
- `device` 切到 `ifb0` 和 `iface` 都不报错
- 不再出现 `[Errno 2] No such file or directory: 'tc'`
- `kbps / pct / bytes / packets` 有值

##### 2. 策略引擎

检查：

- 页面能加载
- “执行一次策略”按钮正常
- “已加载状态接口快照”提示正常
- `mode / reason / last_change_ts` 正常显示
- 最近一次返回里 `actions` 是 `[]` 不是 `{}`

##### 3. 策略报告

检查：

- 预览按钮正常
- 表格列顺序是 `time / mode / reason / changed`
- 导出 CSV 正常下载
- 导出 JSON 正常打开/下载

#### 六、服务与启动项验收

检查 init 脚本是否正常：

```
/etc/init.d/sqm-controller stop
/etc/init.d/sqm-controller start
/etc/init.d/sqm-controller restart
```

如果启用了 policy：

```
grep -n 'sqm-controller-policy' /etc/crontabs/root
```

停服务后应移除：

```
/etc/init.d/sqm-controller stop
grep -n 'sqm-controller-policy' /etc/crontabs/root || echo "cron removed"
```

再启动恢复：

```
/etc/init.d/sqm-controller start
grep -n 'sqm-controller-policy' /etc/crontabs/root
```

#### 七、重启后验收

重启后再检查：

```
reboot
```

重启起来后确认：

```
opkg info luci-app-sqm-controller | sed -n '1,20p'
/etc/init.d/sqm-controller status 2>/dev/null || true
python3 /usr/lib/sqm-controller/main.py --status-json
python3 /usr/lib/sqm-controller/main.py --policy-once
ls -l /tmp/sqm_policy_state.json
```

然后浏览器重新打开三页，确认菜单、页面、按钮都还在。

#### 八、打包内容验收

在 SDK/源码目录确认新文件都进包了：

- `files/usr/lib/sqm-controller/traffic_classifier.py`
- `files/usr/lib/sqm-controller/traffic_stats.py`
- `files/usr/lib/sqm-controller/policy_engine.py`
- `luasrc/view/sqm_controller/traffic.htm`
- `luasrc/view/sqm_controller/policy.htm`
- `luasrc/view/sqm_controller/report.htm`

以及 Makefile 安装项、依赖项正确。

#### 九、上线前最后一条建议

在你重新打 ipk 之前，最好再跑一遍 BOM 检查和语法检查，避免“Windows 改完上传后首字符丢失”这类问题再出现。

---

## 11. 版本管理建议
- `v2.0.0` tag 固定为 2.0 基线
- `v3` 分支开发 3.0
- 每完成一个 Step 做一次 commit（便于回退和论文过程记录）

