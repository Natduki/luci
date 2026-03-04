#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import time


PING_HOST = "8.8.8.8"
STATE_FILE = "/tmp/sqm_controller_monitor_state.json"
HISTORY_FILE = "/tmp/sqm_controller_monitor_history.json"
MAX_POINTS = 900
WINDOW_SECONDS = {"1m": 60, "5m": 300, "1h": 3600}
PING_COUNT = 4
PING_TIMEOUT = 1


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if data is not None else default
    except Exception:
        return default


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def get_iface_total_bytes(iface):
    rx_path = f"/sys/class/net/{iface}/statistics/rx_bytes"
    tx_path = f"/sys/class/net/{iface}/statistics/tx_bytes"
    try:
        with open(rx_path, "r", encoding="utf-8") as f:
            rx = int((f.read() or "0").strip())
        with open(tx_path, "r", encoding="utf-8") as f:
            tx = int((f.read() or "0").strip())
        return rx + tx
    except Exception:
        return 0


def get_bandwidth_kbps(iface, ts):
    total = get_iface_total_bytes(iface)
    state = _read_json(STATE_FILE, {})

    prev_ts = state.get("ts")
    prev_total = state.get("total")
    prev_iface = state.get("iface")
    kbps = 0.0

    if (
        prev_iface == iface
        and isinstance(prev_ts, (int, float))
        and isinstance(prev_total, int)
        and ts > prev_ts
        and total >= prev_total
    ):
        delta_bits = (total - prev_total) * 8.0
        delta_seconds = ts - float(prev_ts)
        kbps = delta_bits / delta_seconds / 1000.0 if delta_seconds > 0 else 0.0

    _write_json(STATE_FILE, {"iface": iface, "ts": ts, "total": total})
    return round(max(kbps, 0.0), 2)


def get_ping_stats(host=PING_HOST):
    # Keep sampling fast to avoid blocking the UI.
    # Use 4 probes so loss granularity is 25% instead of only 0/50/100.
    out = subprocess.getoutput(f"ping -c {PING_COUNT} -W {PING_TIMEOUT} {host} 2>/dev/null")

    loss = 100
    m_loss = re.search(r"(\d+)% packet loss", out)
    if m_loss:
        loss = int(m_loss.group(1))

    latency = None
    m_rtt = re.search(r"=\s*([\d\.]+)/([\d\.]+)/([\d\.]+)/", out)
    if m_rtt:
        latency = float(m_rtt.group(2))
    else:
        m_time = re.search(r"time=([\d\.]+)\s*ms", out)
        if m_time:
            latency = float(m_time.group(1))

    return latency, loss


def _last_valid_latency(history):
    if not isinstance(history, list):
        return None
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        value = item.get("latency")
        if value is None:
            continue
        try:
            value = float(value)
        except Exception:
            continue
        if value >= 0:
            return round(value, 3)
    return None


def collect_sample(iface):
    ts = int(time.time())
    bandwidth_kbps = get_bandwidth_kbps(iface, ts)
    latency, loss = get_ping_stats()

    # If current latency probe failed, reuse the previous valid latency.
    # If no history is available, keep it as null.
    if latency is None:
        history = _read_json(HISTORY_FILE, [])
        latency = _last_valid_latency(history)

    return {
        "time": ts,
        "bandwidth_kbps": bandwidth_kbps,
        "bandwidth": bandwidth_kbps,
        "latency": latency,
        "loss": loss,
    }


def append_history(sample):
    history = _read_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []
    history.append(sample)
    if len(history) > MAX_POINTS:
        history = history[-MAX_POINTS:]
    _write_json(HISTORY_FILE, history)
    return history


def get_window_history(window, include_current=True, sample=None):
    if window not in WINDOW_SECONDS:
        window = "5m"

    history = _read_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []

    if include_current and sample is not None:
        history = append_history(sample)

    now = int(time.time())
    cutoff = now - WINDOW_SECONDS[window]
    points = [p for p in history if isinstance(p, dict) and int(p.get("time", 0)) >= cutoff]

    return {"window": window, "points": points}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iface", default="eth0")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--window", choices=["1m", "5m", "1h"], default="5m")
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()

    sample = collect_sample(args.iface)

    if args.history:
        data = get_window_history(args.window, include_current=True, sample=sample)
        data["current"] = sample
        data["success"] = True
        print(json.dumps(data, ensure_ascii=False))
        return

    if args.record:
        append_history(sample)

    print(json.dumps(sample, ensure_ascii=False))


if __name__ == "__main__":
    main()
