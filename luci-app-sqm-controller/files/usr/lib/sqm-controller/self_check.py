#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import time
import shlex

from config_manager import ConfigManager


LOG_FILE = "/var/log/sqm_controller.log"
DEFAULT_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


def ensure_path():
    current = os.environ.get("PATH", "")
    if not current:
        os.environ["PATH"] = DEFAULT_PATH
        return

    items = current.split(":")
    for seg in DEFAULT_PATH.split(":"):
        if seg not in items:
            items.append(seg)
    os.environ["PATH"] = ":".join(items)


def find_command(name):
    candidates = [name, f"/usr/sbin/{name}", f"/usr/bin/{name}", f"/sbin/{name}", f"/bin/{name}"]
    for cand in candidates:
        if "/" in cand:
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
            continue
        found = shutil.which(cand)
        if found:
            return found
    return None


def run(command):
    return subprocess.run(command, shell=True, capture_output=True, text=True)


def to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def check_dependencies():
    required = ["python3", "tc", "ip", "uci"]
    missing = []
    resolved = {}
    for name in required:
        path = find_command(name)
        if path is None:
            missing.append(name)
        else:
            resolved[name] = path

    return {
        "name": "dependencies",
        "ok": len(missing) == 0,
        "detail": (
            "all found"
            if not missing
            else f"missing: {', '.join(missing)}"
        ),
        "data": {"resolved": resolved},
    }


def check_interface(settings):
    ip_cmd = find_command("ip") or "ip"
    iface = settings.get("interface", "eth0")
    result = run(f"{shlex.quote(ip_cmd)} link show {shlex.quote(iface)}")
    return {
        "name": "interface",
        "ok": result.returncode == 0,
        "detail": iface if result.returncode == 0 else f"{iface} not found",
    }


def check_tc_rules(settings):
    tc_cmd = find_command("tc") or "tc"
    iface = settings.get("interface", "eth0")
    enabled = to_bool(settings.get("enabled", False))
    want_download = int(settings.get("download_speed", 0)) > 0

    wan = run(f"{shlex.quote(tc_cmd)} qdisc show dev {shlex.quote(iface)}")
    ifb = run(f"{shlex.quote(tc_cmd)} qdisc show dev ifb0 2>/dev/null")
    flt = run(f"{shlex.quote(tc_cmd)} filter show dev {shlex.quote(iface)} parent ffff: 2>/dev/null")

    wan_ok = ("fq_codel" in wan.stdout) or ("cake" in wan.stdout) or ("htb" in wan.stdout)
    ifb_ok = ("fq_codel" in ifb.stdout) or ("cake" in ifb.stdout) or ("htb" in ifb.stdout)
    filter_ok = "mirred" in flt.stdout

    if not enabled:
        ok = True
        detail = "service disabled; tc rules not required"
    elif want_download:
        ok = wan_ok and ifb_ok and filter_ok
        detail = f"wan={wan_ok} ifb={ifb_ok} filter={filter_ok}"
    else:
        ok = wan_ok
        detail = f"wan={wan_ok} download=off"

    return {
        "name": "tc_rules",
        "ok": ok,
        "detail": detail,
        "data": {
            "wan_qdisc": wan.stdout.strip(),
            "ifb_qdisc": ifb.stdout.strip(),
            "ingress_filter": flt.stdout.strip(),
        },
    }


def check_log_rw():
    marker = f"SQM_SELF_CHECK {int(time.time())}"
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as file_handle:
            file_handle.write(marker + "\n")
        with open(LOG_FILE, "r", encoding="utf-8") as file_handle:
            found = marker in file_handle.read()
        return {
            "name": "log_rw",
            "ok": found,
            "detail": "write/read ok" if found else "marker not found after write",
        }
    except Exception as exc:
        return {
            "name": "log_rw",
            "ok": False,
            "detail": f"failed: {exc}",
        }


def main():
    ensure_path()

    cfg = ConfigManager()
    cfg.load_config()
    settings = cfg.get_settings().get("all", {})

    checks = [
        check_dependencies(),
        check_interface(settings),
        check_tc_rules(settings),
        check_log_rw(),
    ]
    success = all(item.get("ok") for item in checks)

    result = {
        "success": success,
        "time": int(time.time()),
        "interface": settings.get("interface", "eth0"),
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
