import os
import tomli
from pathlib import Path
from typing import Dict, Any

DEFAULT_CONFIG = {
    "proxy": {
        "bind_address": "0.0.0.0",
        "start_port": 8000,
    },
    "console": {
        "socket_dir": "/tmp/console-share",
        "remote_viewer_path": "/tmp/console-share/bin",
    },
    "shell": {
        "term": "xterm-256color",
    }
}

class Config:
    def __init__(self):
        self.config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "console-share"
        self.config_file = self.config_dir / "config.toml"
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from TOML file or return defaults."""
        if not self.config_file.exists():
            return DEFAULT_CONFIG.copy()
        
        try:
            with open(self.config_file, "rb") as f:
                config = tomli.load(f)
                # Merge with defaults to ensure all required keys exist
                return {
                    **DEFAULT_CONFIG,
                    **config
                }
        except Exception as e:
            print(f"Error loading config: {e}")
            return DEFAULT_CONFIG.copy()

    def ensure_directories(self):
        """Ensure required directories exist."""
        os.makedirs(self.config["console"]["socket_dir"], exist_ok=True)
        os.makedirs(self.config["console"]["remote_viewer_path"], exist_ok=True)

    def get_next_port(self) -> int:
        """Get next available port starting from start_port."""
        # TODO: Implement port tracking
        return self.config["proxy"]["start_port"]

    @property
    def bind_address(self) -> str:
        return self.config["proxy"]["bind_address"]

    @property
    def socket_dir(self) -> str:
        return self.config["console"]["socket_dir"]

    @property
    def remote_viewer_path(self) -> str:
        return self.config["console"]["remote_viewer_path"]

    @property
    def term(self) -> str:
        return self.config["shell"]["term"]

    def generate_config(self, instances: list) -> dict:
        """Generate a configuration based on current instances."""
        config = DEFAULT_CONFIG.copy()
        
        # Add instances section
        config["instances"] = {}
        
        for instance in instances:
            instance_config = {
                "type": "vga" if instance.type == "virtual-machine" else "shell",
                "port": None,  # Will be assigned dynamically
                "enabled": True
            }
            config["instances"][instance.name] = instance_config
        
        return config

    def save_config(self, config: dict):
        """Save configuration to disk."""
        import tomli_w
        
        # Ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Write config file
        with open(self.config_file, "wb") as f:
            tomli_w.dump(config, f)
