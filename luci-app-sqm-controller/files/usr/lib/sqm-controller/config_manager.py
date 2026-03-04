#!/usr/bin/env python3
import logging
import os
import re


class ConfigManager:
    DEFAULT_CONFIG_PATH = "/etc/config/sqm_controller"

    def __init__(self, config_path=None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.config = {}
        self.basic_config = {}
        self.advanced_config = {}
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Config path: %s", self.config_path)

    def load_config(self):
        if not os.path.exists(self.config_path):
            self.logger.warning("Config file does not exist: %s", self.config_path)
            return {}

        try:
            with open(self.config_path, "r", encoding="utf-8") as file_handle:
                content = file_handle.read()

            self.basic_config = self._parse_config_section(content, "basic_config")
            self.advanced_config = self._parse_config_section(content, "advanced_config")
            self.config = {**self.advanced_config, **self.basic_config}

            self.logger.info(
                "Config loaded: basic=%d advanced=%d",
                len(self.basic_config),
                len(self.advanced_config),
            )
            return self.config
        except Exception as exc:
            self.logger.error("Failed to load config: %s", exc)
            return {}

    def _parse_config_section(self, content, section_name):
        parsed = {}
        section_pattern = (
            rf"config\s+{re.escape(section_name)}\s+['\"]?{re.escape(section_name)}['\"]?"
            r"(.*?)(?=\nconfig|\Z)"
        )
        match = re.search(section_pattern, content, re.DOTALL)
        if not match:
            return parsed

        section_content = match.group(1)
        option_pattern = r"option\s+(\w+)\s+['\"]?([^'\"]+)['\"]?"
        for key, value in re.findall(option_pattern, section_content):
            value_str = value.strip()
            value_lower = value_str.lower()
            if value_lower in ("1", "true", "yes", "on"):
                parsed[key] = True
            elif value_lower in ("0", "false", "no", "off"):
                parsed[key] = False
            elif value_str.isdigit():
                parsed[key] = int(value_str)
            else:
                parsed[key] = value_str
        return parsed

    def get_settings(self):
        if not self.config:
            self.load_config()
        return {
            "basic_config": self.basic_config.copy(),
            "advanced_config": self.advanced_config.copy(),
            "all": self.config.copy(),
        }

    def get_basic_settings(self):
        if not self.basic_config:
            self.load_config()
        return self.basic_config.copy()

    def get_advanced_settings(self):
        if not self.advanced_config:
            self.load_config()
        return self.advanced_config.copy()

    def get_value(self, key, default=None, section=None):
        if section == "basic_config":
            return self.basic_config.get(key, default)
        if section == "advanced_config":
            return self.advanced_config.get(key, default)
        return self.config.get(key, default)

    def set_value(self, key, value, section=None):
        if section is None:
            if key in self.basic_config:
                section = "basic_config"
            elif key in self.advanced_config:
                section = "advanced_config"
            else:
                section = "basic_config"

        if section == "basic_config":
            self.basic_config[key] = value
        elif section == "advanced_config":
            self.advanced_config[key] = value
        self.config[key] = value

    def save_config(self):
        try:
            lines = []
            lines.append("config basic_config 'basic_config'")
            for key, value in self.basic_config.items():
                lines.append(f"\toption {key} '{self._value_to_string(value)}'")

            lines.append("")
            lines.append("config advanced_config 'advanced_config'")
            for key, value in self.advanced_config.items():
                lines.append(f"\toption {key} '{self._value_to_string(value)}'")

            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as file_handle:
                file_handle.write("\n".join(lines))

            self.logger.info("Config saved: %s", self.config_path)
            return True
        except Exception as exc:
            self.logger.error("Failed to save config: %s", exc)
            return False

    def _value_to_string(self, value):
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        return str(value)

    def is_enabled(self):
        return bool(self.basic_config.get("enabled", False))

    def get_interface(self):
        return self.basic_config.get("interface", "eth0")

    def get_bandwidth(self, direction="download"):
        if direction == "download":
            return self.basic_config.get("download_speed", 100000)
        if direction == "upload":
            return self.basic_config.get("upload_speed", 50000)
        return 0

    def get_algorithm(self):
        return self.basic_config.get("queue_algorithm", "fq_codel")

    def get_log_level(self):
        return self.advanced_config.get("log_level", "info")

    def get_log_file(self):
        return self.advanced_config.get("log_file", "/var/log/sqm_controller.log")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    manager = ConfigManager()
    print("all:", manager.load_config())
    print("algorithm:", manager.get_algorithm())
    print("enabled:", manager.is_enabled())