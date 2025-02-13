import subprocess
import json
from typing import Tuple, List, Optional
from dataclasses import dataclass

@dataclass
class IncusInstance:
    name: str
    status: str
    type: str
    project: str
    remote: str

class IncusError(Exception):
    pass

def run_incus_command(command: List[str]) -> str:
    """Run an incus command and return its output."""
    try:
        result = subprocess.run(
            ["incus", "--format", "json"] + command,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise IncusError(f"Incus command failed: {e.stderr}")

def parse_json_output(output: str) -> List[dict]:
    """Parse JSON output from incus command."""
    if not output:
        return []
    
    try:
        data = json.loads(output)
        # Handle both single object and list responses
        if isinstance(data, dict):
            data = [data]
        return data
    except json.JSONDecodeError as e:
        raise IncusError(f"Failed to parse JSON output: {e}")

def get_current_project_and_remote() -> Tuple[str, str]:
    """Get the current project and remote from incus output."""
    try:
        # Get projects list
        projects_output = run_incus_command(["project", "list"])
        projects = parse_json_output(projects_output)
        current_project = next(
            (p["name"].replace(" (current)", "") for p in projects if "(current)" in p["name"]),
            "default"
        )

        # Get remotes list
        remotes_output = run_incus_command(["remote", "list"])
        remotes = parse_json_output(remotes_output)
        current_remote = next(
            (r["name"].replace(" (current)", "") for r in remotes if "(current)" in r["name"]),
            "local"
        )

        return current_project, current_remote
    except Exception as e:
        raise IncusError(f"Failed to get current project/remote: {e}")

def get_instance(name: str) -> Optional[IncusInstance]:
    """Get instance details by name."""
    try:
        output = run_incus_command(["list", name])
        instances = parse_json_output(output)
        
        if not instances:
            return None
            
        # Get current project and remote
        project, remote = get_current_project_and_remote()
        
        # Parse instance details
        instance = instances[0]  # Should only be one instance when filtering by name
        return IncusInstance(
            name=instance["name"],
            status=instance["status"],
            type=instance["type"].upper(),  # Normalize type to match previous format
            project=project,
            remote=remote
        )
    except Exception as e:
        raise IncusError(f"Failed to get instance details: {e}")

def is_running(instance: IncusInstance) -> bool:
    """Check if an instance is running."""
    return instance.status.lower() == "running"

def get_instance_type(instance: IncusInstance) -> str:
    """Get the instance type (container or virtual-machine)."""
    return instance.type

def list_instances() -> List[IncusInstance]:
    """List all instances in the current project."""
    try:
        # Get current project and remote
        project, remote = get_current_project_and_remote()
        
        # Get all instances
        output = run_incus_command(["list"])
        instances = parse_json_output(output)
        
        return [
            IncusInstance(
                name=instance["name"],
                status=instance["status"],
                type=instance["type"].upper(),  # Normalize type to match previous format
                project=project,
                remote=remote
            )
            for instance in instances
        ]
    except Exception as e:
        raise IncusError(f"Failed to list instances: {e}")
