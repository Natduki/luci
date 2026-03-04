#!/usr/bin/env python3
"""
Traffic control manager.
Supports fq_codel and cake.
"""
import logging
import re
import subprocess


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class TCManager:
    def __init__(self, config):
        if not isinstance(config, dict):
            raise ValueError("config must be dict")

        self.interface = config.get("interface", "eth0")
        self.upload_kbps = int(config.get("upload_speed", config.get("upload_bandwidth", 0)))
        self.download_kbps = int(config.get("download_speed", config.get("download_bandwidth", 0)))
        self.algorithm = str(config.get("queue_algorithm", "fq_codel")).lower()
        self.ecn = _to_bool(config.get("ecn", True), default=True)
        self.logger = logging.getLogger(__name__)

    def run(self, cmd):
        self.logger.debug(cmd)
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def clear_tc_rules(self):
        cmds = [
            f"tc qdisc del dev {self.interface} root 2>/dev/null",
            f"tc qdisc del dev {self.interface} ingress 2>/dev/null",
            f"tc filter del dev {self.interface} ingress 2>/dev/null",
            "tc qdisc del dev ifb0 root 2>/dev/null",
            "tc filter del dev ifb0 root 2>/dev/null",
        ]
        for cmd in cmds:
            self.run(cmd)

    def setup_ifb(self):
        self.run("modprobe ifb 2>/dev/null || true")
        self.run("ip link add ifb0 type ifb 2>/dev/null || true")
        self.run("ip link set ifb0 up")

    def setup_htb(self):
        ecn_flag = "ecn" if self.ecn else "noecn"
        self.logger.info(
            "iface=%s up=%s down=%s algo=%s ecn=%s",
            self.interface,
            self.upload_kbps,
            self.download_kbps,
            self.algorithm,
            ecn_flag,
        )

        self.clear_tc_rules()
        cmds = []

        if self.upload_kbps > 0:
            cmds += [
                f"tc qdisc add dev {self.interface} root handle 1: htb default 10",
                f"tc class add dev {self.interface} parent 1: classid 1:1 htb rate {self.upload_kbps}kbit ceil {self.upload_kbps}kbit",
                f"tc class add dev {self.interface} parent 1:1 classid 1:10 htb rate {self.upload_kbps}kbit ceil {self.upload_kbps}kbit",
            ]

            if self.algorithm == "cake":
                cmds.append(
                    f"tc qdisc add dev {self.interface} parent 1:10 handle 10: cake bandwidth {self.upload_kbps}kbit"
                )
            else:
                cmds.append(
                    f"tc qdisc add dev {self.interface} parent 1:10 handle 10: fq_codel {ecn_flag}"
                )

        if self.download_kbps > 0:
            self.setup_ifb()
            cmds += [
                f"tc qdisc add dev {self.interface} ingress",
                f"tc filter add dev {self.interface} parent ffff: protocol ip u32 match u32 0 0 action mirred egress redirect dev ifb0",
                f"tc qdisc add dev ifb0 root handle 2: htb default 20",
                f"tc class add dev ifb0 parent 2: classid 2:1 htb rate {self.download_kbps}kbit ceil {self.download_kbps}kbit",
                f"tc class add dev ifb0 parent 2:1 classid 2:20 htb rate {self.download_kbps}kbit ceil {self.download_kbps}kbit",
            ]

            if self.algorithm == "cake":
                cmds.append(
                    f"tc qdisc add dev ifb0 parent 2:20 handle 20: cake bandwidth {self.download_kbps}kbit"
                )
            else:
                cmds.append(
                    f"tc qdisc add dev ifb0 parent 2:20 handle 20: fq_codel {ecn_flag}"
                )

        ok = 0
        for cmd in cmds:
            result = self.run(cmd)
            if result.returncode == 0:
                ok += 1
            else:
                self.logger.error("failed: %s -> %s", cmd, result.stderr.strip())

        return ok == len(cmds)

    def show_status(self):
        status = {}
        cmds = [
            f"tc -s qdisc show dev {self.interface}",
            f"tc -s class show dev {self.interface}",
            "ip link show ifb0 2>/dev/null || echo 'ifb0 missing'",
            "tc -s qdisc show dev ifb0 2>/dev/null || echo 'ifb0 no tc rule'",
        ]
        for cmd in cmds:
            result = self.run(cmd)
            status[cmd] = result.stdout
        return status

    def get_current_bandwidth(self):
        bw = {"upload": 0, "download": 0}

        result = self.run(f"tc class show dev {self.interface}")
        for line in result.stdout.splitlines():
            matched = re.search(r"rate (\d+)kbit", line)
            if matched:
                bw["upload"] = int(matched.group(1))

        result = self.run("tc class show dev ifb0 2>/dev/null")
        for line in result.stdout.splitlines():
            matched = re.search(r"rate (\d+)kbit", line)
            if matched:
                bw["download"] = int(matched.group(1))

        return bw
