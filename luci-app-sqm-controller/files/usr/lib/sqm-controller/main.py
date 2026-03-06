#!/usr/bin/env python3
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import subprocess
import time

from config_manager import ConfigManager
from tc_manager import TCManager
from template_manager import get_template
import firewall_manager
import policy_engine
import traffic_classifier
import traffic_stats


LOG_FILE = "/var/log/sqm_controller.log"
SELF_CHECK_PY = "/usr/lib/sqm-controller/self_check.py"
CONFIG_FILE = "/etc/config/sqm_controller"
ALLOWED_ALGORITHMS = {"fq_codel", "cake"}
ALLOWED_LOG_LEVELS = {"debug", "info", "warn", "warning", "error"}
LOG_MAX_BYTES = 256 * 1024
LOG_BACKUP_COUNT = 5
POLICY_REPORT_FILE = "/var/log/sqm_policy.jsonl"


def setup_logging():
    try:
        os.makedirs("/var/log", exist_ok=True)
    except Exception:
        pass

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = []
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root.addHandler(handler)


def rotate_logs(log_path=LOG_FILE, backup_count=LOG_BACKUP_COUNT):
    if backup_count < 1:
        backup_count = 1

    rotated = False
    oldest = f"{log_path}.{backup_count}"
    if os.path.exists(oldest):
        try:
            os.remove(oldest)
        except Exception:
            pass

    for index in range(backup_count - 1, 0, -1):
        src = f"{log_path}.{index}"
        dst = f"{log_path}.{index + 1}"
        if os.path.exists(src):
            try:
                os.replace(src, dst)
            except Exception:
                pass

    if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
        try:
            os.replace(log_path, f"{log_path}.1")
            rotated = True
        except Exception:
            rotated = False

    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8"):
            pass
    except Exception:
        pass

    return {
        "success": True,
        "rotated": rotated,
        "max_bytes": LOG_MAX_BYTES,
        "backup_count": backup_count,
    }


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _ecn_from_tc_output(text):
    if not text:
        return None
    lower = text.lower()
    if " fq_codel" in lower:
        if " noecn" in lower:
            return False
        if " ecn" in lower:
            return True
        return None
    if " cake" in lower:
        # On OpenWrt 23.05, cake does not expose explicit ecn/noecn options.
        # Treat cake as ECN-capable unless noecn is explicitly present.
        if " noecn" in lower:
            return False
        return True
    return None


def _merge_ecn_state(wan_state, ifb_state, running):
    if not running:
        return "not_applied"

    if wan_state is None and ifb_state is None:
        return "unknown"
    if wan_state is not None and ifb_state is None:
        return "upload_only"
    if wan_state is None and ifb_state is not None:
        return "download_only"
    if wan_state == ifb_state:
        return "enabled" if wan_state else "disabled"
    if wan_state or ifb_state:
        return "partial_enabled"
    return "partial_disabled"


def _csv_escape(value):
    text = "" if value is None else str(value)
    if any(ch in text for ch in [",", '"', "\n", "\r"]):
        return '"' + text.replace('"', '""') + '"'
    return text


def _dict_get(data, path, default=""):
    current = data
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


def _load_policy_report_entries(path=POLICY_REPORT_FILE):
    if not os.path.exists(path):
        return None, {"success": False, "error": "report log not found", "details": {"path": path}}

    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            lines = [line.strip() for line in file_handle if line.strip()]
    except Exception as exc:
        return None, {"success": False, "error": f"failed to read report log: {exc}", "details": {"path": path}}

    if not lines:
        return None, {"success": False, "error": "report log is empty", "details": {"path": path}}

    entries = []
    for index, line in enumerate(lines, start=1):
        try:
            entries.append(json.loads(line))
        except Exception as exc:
            return None, {
                "success": False,
                "error": f"invalid jsonl line at {index}: {exc}",
                "details": {"path": path, "line": index},
            }
    return entries, None


class SQMController:
    def __init__(self, config_path=None):
        self.config_manager = ConfigManager(config_path)
        self.config = {}
        self._reload_config(force=True)

    def _reload_config(self, force=False):
        if force or not self.config:
            self.config_manager.load_config()
            settings = self.config_manager.get_settings()
            self.config = settings["all"]
        return self.config

    def _current_all_settings(self):
        self._reload_config(force=True)
        return self.config_manager.get_settings()["all"].copy()

    def _diff_config(self, before, after):
        changes = {}
        for key in sorted(set(before.keys()) | set(after.keys())):
            old = before.get(key)
            new = after.get(key)
            if old != new:
                changes[key] = {"from": old, "to": new}
        return changes

    def _apply_runtime_config(self):
        self._reload_config(force=True)
        enabled = _to_bool(self.config.get("enabled", False))
        tc = TCManager(self.config)

        if not enabled:
            tc.clear_tc_rules()
            return {
                "requested": True,
                "enabled": False,
                "applied": True,
                "restart_success": True,
                "message": "service disabled, tc rules cleared",
            }

        ok = tc.setup_htb()
        return {
            "requested": True,
            "enabled": True,
            "applied": bool(ok),
            "restart_success": bool(ok),
            "message": "tc rules applied" if ok else "failed to apply tc rules",
        }

    def enable(self):
        logging.info("enable() called")
        self._reload_config(force=True)
        tc = TCManager(self.config)
        ok = tc.setup_htb()
        logging.info("enable() tc.setup_htb() => %s", ok)
        if ok:
            self.config_manager.set_value("enabled", True, "basic_config")
            self.config_manager.save_config()
        return ok

    def disable(self):
        logging.info("disable() called")
        self._reload_config(force=True)
        tc = TCManager(self.config)
        tc.clear_tc_rules()
        self.config_manager.set_value("enabled", False, "basic_config")
        self.config_manager.save_config()
        logging.info("disable() done")
        return True

    def apply_template(self, name):
        logging.info("apply_template(%s) called", name)
        template = get_template(name)
        if not template:
            logging.warning("template not found: %s", name)
            return {"success": False, "error": "template not found", "template": name}

        before = self._current_all_settings()

        self.config_manager.set_value("upload_speed", template["upload"], "basic_config")
        self.config_manager.set_value("download_speed", template["download"], "basic_config")
        self.config_manager.set_value("queue_algorithm", template["algorithm"], "basic_config")
        self.config_manager.set_value("ecn", str(template.get("ecn", False)).lower(), "advanced_config")

        saved = self.config_manager.save_config()
        if not saved:
            return {
                "success": False,
                "error": "failed to save config",
                "template": name,
                "changes": {},
            }

        after = self._current_all_settings()
        runtime = self._apply_runtime_config()
        success = bool(runtime.get("applied"))

        return {
            "success": success,
            "template": name,
            "changes": self._diff_config(before, after),
            "runtime": runtime,
        }

    def validate_config_file(self, path):
        result = {"valid": False, "errors": [], "warnings": []}

        if not path or not os.path.exists(path):
            result["errors"].append("file not found")
            return result

        if os.path.getsize(path) <= 0:
            result["errors"].append("file is empty")
            return result

        try:
            with open(path, "r", encoding="utf-8") as file_handle:
                content = file_handle.read()
        except Exception as exc:
            result["errors"].append(f"read failed: {exc}")
            return result

        if "config basic_config" not in content:
            result["errors"].append("missing section: basic_config")
        if "config advanced_config" not in content:
            result["errors"].append("missing section: advanced_config")

        cfg = ConfigManager(path)
        cfg.load_config()
        settings = cfg.get_settings()
        basic = settings.get("basic_config", {})
        advanced = settings.get("advanced_config", {})

        if not basic:
            result["errors"].append("basic_config has no options")
        if not advanced:
            result["warnings"].append("advanced_config has no options")

        interface = basic.get("interface")
        if not interface or not isinstance(interface, str):
            result["errors"].append("basic_config.interface is required")

        for key in ("download_speed", "upload_speed"):
            value = basic.get(key)
            if value is None:
                result["errors"].append(f"basic_config.{key} is required")
                continue
            try:
                number = int(value)
                if number <= 0:
                    result["errors"].append(f"basic_config.{key} must be > 0")
            except Exception:
                result["errors"].append(f"basic_config.{key} must be an integer")

        algorithm = str(basic.get("queue_algorithm", "")).lower()
        if algorithm not in ALLOWED_ALGORITHMS:
            result["errors"].append("basic_config.queue_algorithm must be fq_codel or cake")

        log_level = advanced.get("log_level")
        if log_level and str(log_level).lower() not in ALLOWED_LOG_LEVELS:
            result["warnings"].append("advanced_config.log_level is not in recommended values")

        result["valid"] = len(result["errors"]) == 0
        return result

    def restore_config(self, path, apply_now=True):
        validation = self.validate_config_file(path)
        if not validation["valid"]:
            return {
                "success": False,
                "error": "config validation failed",
                "validation": validation,
            }

        before = self._current_all_settings()
        backup_path = None

        try:
            if os.path.exists(CONFIG_FILE):
                backup_path = f"/tmp/sqm_controller.backup.{time.strftime('%Y%m%d-%H%M%S')}"
                shutil.copy2(CONFIG_FILE, backup_path)

            shutil.copy2(path, CONFIG_FILE)
            self._reload_config(force=True)
            after = self._current_all_settings()

            runtime = {"requested": bool(apply_now), "applied": False}
            if apply_now:
                runtime = self._apply_runtime_config()

            success = True if not apply_now else bool(runtime.get("applied"))
            return {
                "success": success,
                "backup_path": backup_path,
                "changes": self._diff_config(before, after),
                "validation": validation,
                "runtime": runtime,
            }
        except Exception as exc:
            logging.exception("restore_config() failed: %s", exc)
            return {
                "success": False,
                "error": f"restore failed: {exc}",
                "backup_path": backup_path,
                "validation": validation,
            }

    def status_json(self):
        iface = self.config_manager.get_interface()
        tc_wan = subprocess.getoutput(f"tc qdisc show dev {iface} 2>/dev/null")
        tc_ifb = subprocess.getoutput("tc qdisc show dev ifb0 2>/dev/null")
        tc_wan_detail = subprocess.getoutput(f"tc -d qdisc show dev {iface} 2>/dev/null")
        tc_ifb_detail = subprocess.getoutput("tc -d qdisc show dev ifb0 2>/dev/null")

        wan_lower = tc_wan.lower()
        ifb_lower = tc_ifb.lower()
        # "qdisc fq_codel 0: root" can be kernel default after clearing rules.
        # Only regard SQM as applied when our managed HTB roots exist.
        wan_managed = "qdisc htb 1:" in wan_lower
        ifb_managed = "qdisc htb 2:" in ifb_lower
        running = wan_managed or ifb_managed

        ecn_state = _merge_ecn_state(
            _ecn_from_tc_output(tc_wan_detail),
            _ecn_from_tc_output(tc_ifb_detail),
            running,
        )

        data = {
            "service_status": "running" if running else "stopped",
            "pid": "N/A(no resident process)",
            "tc_state": "applied" if running else "not_applied",
            "ecn_state": ecn_state,
            "tc_wan": tc_wan,
            "tc_ifb": tc_ifb,
        }
        print(json.dumps(data, ensure_ascii=False))

    def rotate_logs_json(self):
        result = rotate_logs()
        logging.info("rotate_logs_json() rotated=%s", result.get("rotated"))
        print(json.dumps(result, ensure_ascii=False))

    def self_check_json(self):
        if not os.path.exists(SELF_CHECK_PY):
            print(json.dumps({"success": False, "error": "self_check.py not found"}, ensure_ascii=False))
            return
        out = subprocess.getoutput(f"python3 {SELF_CHECK_PY}")
        print(out)

    def monitor_json(self):
        iface = self.config_manager.get_interface()
        logging.info("monitor_json() iface=%s", iface)
        out = subprocess.getoutput(f"/usr/lib/sqm-controller/monitor.py --iface {iface} --record")
        print(out)

    def monitor_history_json(self, window):
        iface = self.config_manager.get_interface()
        if window not in {"1m", "5m", "1h"}:
            window = "5m"
        logging.info("monitor_history_json() iface=%s window=%s", iface, window)
        out = subprocess.getoutput(
            f"/usr/lib/sqm-controller/monitor.py --iface {iface} --history --window {window}"
        )
        print(out)

    def speedtest(self):
        """
        改为调用 /usr/lib/sqm-controller/speedtest.py 做“下载测速（只下行）”，
        只更新 download_speed，不修改 upload_speed，保存并应用 tc 规则。
        """
        logging.info("speedtest() called")

        SPEEDTEST_PY = "/usr/lib/sqm-controller/speedtest.py"
        try:
            if not os.path.exists(SPEEDTEST_PY):
                raise Exception("speedtest.py not found")

            # 运行测速脚本，读取 JSON 输出
            out = subprocess.getoutput(f"python3 {SPEEDTEST_PY}")
            try:
                result = json.loads(out)
            except Exception:
                raise Exception(f"speedtest.py returned non-json: {out}")

            if isinstance(result, dict) and result.get("error"):
                # 透传错误信息（前端会看到 raw）
                raise Exception(result.get("raw") or result.get("error"))

            down_kbps = result.get("download")
            if down_kbps is None:
                raise Exception(f"speedtest result missing download: {result}")

            try:
                down_kbps = int(down_kbps)
            except Exception:
                raise Exception(f"invalid download value: {down_kbps}")

            if down_kbps <= 0:
                raise Exception("download speed is <= 0")

            # 预留 15% headroom（沿用你原逻辑的 0.85）
            down_apply = int(down_kbps * 0.85)

            # 记录变更前（用于回显）
            before = self._current_all_settings()
            old_up = before.get("upload_speed")

            # 只更新 download_speed，不动 upload_speed
            self.config_manager.set_value("download_speed", down_apply, "basic_config")
            saved = self.config_manager.save_config()
            if not saved:
                raise Exception("failed to save config")

            runtime = self._apply_runtime_config()
            if not runtime.get("applied"):
                raise Exception("speedtest result saved but failed to apply tc rules")

            after = self._current_all_settings()
            print(json.dumps({
                "download": down_apply,
                "upload": old_up,                 # 保留原 upload（不改）
                "backend": result.get("backend"),
                "source_url": result.get("url") or result.get("url_effective"),
                "time_total": result.get("time_total"),
                "http_code": result.get("http_code"),
                "changes": self._diff_config(before, after),
                "runtime": runtime
            }, ensure_ascii=False))

        except Exception as exc:
            logging.exception("speedtest() failed: %s", exc)
            print(json.dumps({"error": "speedtest failed", "raw": str(exc)}, ensure_ascii=False))

def main():
    setup_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--disable", action="store_true")
    parser.add_argument("--status-json", action="store_true")
    parser.add_argument("--monitor", action="store_true")
    parser.add_argument("--monitor-history", action="store_true")
    parser.add_argument("--window", choices=["1m", "5m", "1h"], default="5m")
    parser.add_argument("--speedtest", action="store_true")
    parser.add_argument("--rotate-logs", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--template")
    parser.add_argument("--validate-config")
    parser.add_argument("--restore-config")
    parser.add_argument("--no-apply", action="store_true")
    parser.add_argument("--apply-classifier", action="store_true")
    parser.add_argument("--clear-classifier", action="store_true")
    parser.add_argument("--get-class-stats", action="store_true")
    parser.add_argument("--policy-once", action="store_true")
    parser.add_argument("--export-report", action="store_true")
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    parser.add_argument("--dev", default="ifb0")
    args = parser.parse_args()

    ctl = SQMController()

    if args.status_json:
        ctl.status_json()
    elif args.monitor:
        ctl.monitor_json()
    elif args.monitor_history:
        ctl.monitor_history_json(args.window)
    elif args.speedtest:
        ctl.speedtest()
    elif args.rotate_logs:
        ctl.rotate_logs_json()
    elif args.self_check:
        ctl.self_check_json()
    elif args.validate_config:
        result = ctl.validate_config_file(args.validate_config)
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result.get("valid") else 1)
    elif args.restore_config:
        result = ctl.restore_config(args.restore_config, apply_now=(not args.no_apply))
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result.get("success") else 1)
    elif args.template:
        result = ctl.apply_template(args.template)
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result.get("success") else 1)
    elif args.apply_classifier:
        try:
            run_fn = getattr(traffic_classifier, "run", None)
            if callable(run_fn):
                result = run_fn()
            else:
                result = traffic_classifier.run_classifier(config_path=ctl.config_manager.config_path)
        except Exception as exc:
            result = {"success": False, "error": str(exc)}

        if result.get("success"):
            verify_cmd = "tc filter show dev ifb0 parent 2:"
            verify_proc = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True)
            verify_stdout = (verify_proc.stdout or "").strip()
            verify_stderr = (verify_proc.stderr or "").strip()
            if verify_proc.returncode != 0 or not verify_stdout:
                result["success"] = False
                result["error"] = "classifier verify failed: ifb0 parent 2: has no filters"
                details = result.get("details")
                if not isinstance(details, dict):
                    details = {}
                details["verify_cmd"] = verify_cmd
                details["verify_rc"] = verify_proc.returncode
                details["verify_stdout"] = verify_stdout
                details["verify_stderr"] = verify_stderr
                result["details"] = details
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result.get("success") else 1)
    elif args.clear_classifier:
        errors = []
        firewall_result = {}
        tc_result = {"success": False}

        try:
            clear_fn = getattr(firewall_manager, "clear", None)
            if callable(clear_fn):
                firewall_result = clear_fn(prefer_backend="auto")
            else:
                firewall_result = firewall_manager.clear_rules()
        except Exception as exc:
            firewall_result = {"success": False, "error": str(exc)}
        if not firewall_result.get("success"):
            errors.append(f"firewall: {firewall_result.get('error', 'clear failed')}")

        try:
            settings = ctl.config_manager.get_settings()["all"]
            tc_ok = TCManager(settings).clear_classifier_tc()
            tc_result = {"success": bool(tc_ok)}
            if not tc_ok:
                tc_result["error"] = "clear_classifier_tc failed"
        except Exception as exc:
            tc_result = {"success": False, "error": str(exc)}
        if not tc_result.get("success"):
            errors.append(f"tc: {tc_result.get('error', 'clear failed')}")

        result = {
            "success": (len(errors) == 0),
            "firewall": firewall_result,
            "tc": tc_result,
            "errors": errors,
        }
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result.get("success") else 1)
    elif args.get_class_stats:
        try:
            dev = (args.dev or "ifb0").strip() or "ifb0"
            if dev in {"iface", "wan", "interface"}:
                dev = ctl.config_manager.get_interface()
            result = traffic_stats.collect(dev)
        except Exception as exc:
            result = {"success": False, "error": str(exc), "details": {}}
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result.get("success") else 1)
    elif args.policy_once:
        try:
            result = policy_engine.run_once(config_path=ctl.config_manager.config_path)
        except Exception as exc:
            result = {"success": False, "error": str(exc), "details": {}, "actions": [], "changed": False}
        if not isinstance(result, dict):
            result = {"success": False, "error": "invalid policy_once result", "details": {}, "actions": [], "changed": False}
        if not isinstance(result.get("actions"), list):
            result["actions"] = []
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result.get("success") else 1)
    elif args.export_report:
        entries, err = _load_policy_report_entries()
        if err:
            print(json.dumps(err, ensure_ascii=False))
            raise SystemExit(1)

        fmt = (args.format or "json").strip().lower()
        if fmt not in {"json", "csv"}:
            result = {"success": False, "error": "invalid format", "details": {"format": args.format}}
            print(json.dumps(result, ensure_ascii=False))
            raise SystemExit(1)

        if fmt == "json":
            result = {
                "success": True,
                "format": "json",
                "count": len(entries),
                "entries": entries,
            }
            print(json.dumps(result, ensure_ascii=False))
            raise SystemExit(0)

        headers = [
            "time",
            "decision.mode",
            "decision.reason",
            "inputs.monitor.latency",
            "inputs.monitor.loss",
            "inputs.traffic_stats.total_kbps",
            "changed",
        ]
        rows = [",".join(headers)]
        for item in entries:
            row = [
                _dict_get(item, ["time"], ""),
                _dict_get(item, ["decision", "mode"], ""),
                _dict_get(item, ["decision", "reason"], ""),
                _dict_get(item, ["inputs", "monitor", "latency"], ""),
                _dict_get(item, ["inputs", "monitor", "loss"], ""),
                _dict_get(item, ["inputs", "traffic_stats", "total_kbps"], ""),
                _dict_get(item, ["changed"], ""),
            ]
            rows.append(",".join(_csv_escape(value) for value in row))
        print("\n".join(rows))
        raise SystemExit(0)
    elif args.enable:
        ok = ctl.enable()
        print("enabled" if ok else "enable failed")
    elif args.disable:
        ctl.disable()
        print("disabled")
    else:
        ctl.status_json()


if __name__ == "__main__":
    main()
