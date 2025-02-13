import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Dict
import signal
import atexit
import psutil

from .config import Config
from .incus import IncusInstance, run_incus_command, IncusError

class ProxyError(Exception):
    pass

class Proxy:
    def __init__(self, config: Config):
        self.config = config
        self.active_proxies: Dict[str, subprocess.Popen] = {}
        self.socket_paths: Dict[str, str] = {}
        atexit.register(self.cleanup)

    def cleanup(self):
        """Clean up all active proxy processes and temporary files."""
        for process in self.active_proxies.values():
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                process.kill()
        
        # Clean up socket files
        for socket_path in self.socket_paths.values():
            try:
                os.unlink(socket_path)
            except:
                pass

    def _create_fake_remote_viewer(self, socket_path: str) -> str:
        """Create a fake remote-viewer script that captures the socket path."""
        viewer_dir = Path(self.config.remote_viewer_path)
        viewer_path = viewer_dir / "remote-viewer"
        
        script_content = f"""#!/bin/bash
# Log the socket path for the proxy
echo "$@" | grep -o "unix-socket=[^,]*" > {socket_path}.path
# Exit successfully to trick incus
exit 0
"""
        viewer_path.write_text(script_content)
        viewer_path.chmod(0o755)
        return str(viewer_path)

    def _get_socket_path_from_log(self, log_path: str, timeout: int = 10) -> Optional[str]:
        """Get the socket path from the log file created by fake remote-viewer."""
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if os.path.exists(log_path):
                with open(log_path) as f:
                    content = f.read().strip()
                    if content.startswith("unix-socket="):
                        return content.split("=")[1]
            time.sleep(0.1)
        
        raise ProxyError("Timeout waiting for socket path")

    def proxy_shell(self, instance: IncusInstance, port: Optional[int] = None) -> int:
        """Proxy an incus shell connection."""
        instance_config = self.config.get_instance_config(instance.name)
        if port is None:
            port = instance_config.get("port") if instance_config else self.config.get_next_port()

        # Start socat to proxy the shell
        cmd = [
            "socat",
            f"TCP-LISTEN:{port},reuseaddr,fork",
            f"EXEC:'incus exec {instance.name} -- /bin/bash',pty,stderr,setsid,sigint,sane"
        ]

        try:
            process = subprocess.Popen(cmd)
            self.active_proxies[f"shell_{instance.name}"] = process
            return port
        except Exception as e:
            raise ProxyError(f"Failed to start shell proxy: {e}")

    def proxy_console(self, instance: IncusInstance, vga: bool = False, port: Optional[int] = None) -> int:
        """Proxy an incus console connection."""
        instance_config = self.config.get_instance_config(instance.name)
        if port is None:
            port = instance_config.get("port") if instance_config else self.config.get_next_port()

        if vga and instance.type == "virtual-machine":
            return self._proxy_vga_console(instance, port)
        else:
            return self._proxy_regular_console(instance, port)

    def _proxy_regular_console(self, instance: IncusInstance, port: int) -> int:
        """Proxy a regular (non-VGA) console connection."""
        cmd = [
            "socat",
            f"TCP-LISTEN:{port},reuseaddr,fork",
            f"EXEC:'incus console {instance.name}',pty,raw,echo=0"
        ]

        try:
            process = subprocess.Popen(cmd)
            self.active_proxies[f"console_{instance.name}"] = process
            return port
        except Exception as e:
            raise ProxyError(f"Failed to start console proxy: {e}")

    def _proxy_vga_console(self, instance: IncusInstance, port: int) -> int:
        """Proxy a VGA console connection by intercepting the remote-viewer socket."""
        # Create temporary file for socket path
        socket_log = tempfile.mktemp(prefix="console-share-", suffix=".path")
        
        # Create fake remote-viewer
        fake_viewer = self._create_fake_remote_viewer(socket_log)
        
        # Modify PATH to use our fake remote-viewer
        modified_env = os.environ.copy()
        modified_env["PATH"] = f"{os.path.dirname(fake_viewer)}:{modified_env.get('PATH', '')}"
        
        try:
            # Start console with modified PATH
            console_proc = subprocess.Popen(
                ["incus", "console", "--type=vga", instance.name],
                env=modified_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Get the socket path
            socket_path = self._get_socket_path_from_log(socket_log)
            if not socket_path or not os.path.exists(socket_path):
                raise ProxyError("Failed to get console socket path")
            
            # Store socket path for cleanup
            self.socket_paths[instance.name] = socket_path
            
            # Start socat to proxy the Unix socket
            cmd = [
                "socat",
                f"TCP-LISTEN:{port},reuseaddr,fork",
                f"UNIX-CONNECT:{socket_path}"
            ]
            
            process = subprocess.Popen(cmd)
            self.active_proxies[f"vga_{instance.name}"] = process
            
            return port
            
        except Exception as e:
            raise ProxyError(f"Failed to start VGA console proxy: {e}")
        finally:
            # Clean up temporary files
            try:
                os.unlink(socket_log)
            except:
                pass

    def stop_proxy(self, instance_name: str):
        """Stop all proxy processes for an instance."""
        keys_to_remove = []
        
        for key, process in self.active_proxies.items():
            if instance_name in key:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except:
                    process.kill()
                keys_to_remove.append(key)
        
        # Clean up socket if it exists
        if instance_name in self.socket_paths:
            try:
                os.unlink(self.socket_paths[instance_name])
                del self.socket_paths[instance_name]
            except:
                pass
        
        # Remove stopped proxies from tracking
        for key in keys_to_remove:
            del self.active_proxies[key]

    def list_active(self) -> Dict[str, Dict[str, any]]:
        """List active proxy connections."""
        active = {}
        for key, process in self.active_proxies.items():
            if process.poll() is None:  # Check if still running
                proxy_type, instance = key.split("_", 1)
                active[key] = {
                    "type": proxy_type,
                    "instance": instance,
                    "pid": process.pid
                }
        return active
