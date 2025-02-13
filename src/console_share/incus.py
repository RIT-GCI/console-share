import subprocess
import csv
from io import StringIO
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

def run_incus_command(command: List[str], csv_output: bool = True) -> str:
    """Run an incus command and return its output."""
    try:
        if csv_output:
            command = ["-f", "csv"] + command
        
        result = subprocess.run(
            ["incus"] + command,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise IncusError(f"Incus command failed: {e.stderr}")

def parse_csv_output(output: str) -> List[List[str]]:
    """Parse CSV output from incus command."""
    if not output:
        return []
    
    reader = csv.reader(StringIO(output))
    return list(reader)

def get_current_project_and_remote() -> Tuple[str, str]:
    """Get the current project and remote from incus output."""
    try:
        # Get projects list
        projects_output = run_incus_command(["project", "list"])
        projects = parse_csv_output(projects_output)
        current_project = next(
            (p[0] for p in projects if "(current)" in p[0]),
            "default"
        ).replace(" (current)", "")

        # Get remotes list
        remotes_output = run_incus_command(["remote", "list"])
        remotes = parse_csv_output(remotes_output)
        current_remote = next(
            (r[0] for r in remotes if "(current)" in r[0]),
            "local"
        ).replace(" (current)", "")

        return current_project, current_remote
    except Exception as e:
        raise IncusError(f"Failed to get current project/remote: {e}")

def get_instance(name: str) -> Optional[IncusInstance]:
    """Get instance details by name."""
    try:
        output = run_incus_command(["list", name])
        instances = parse_csv_output(output)
        
        if not instances:
            return None
            
        # Get current project and remote
        project, remote = get_current_project_and_remote()
        
        # Parse instance details
        instance = instances[0]  # Should only be one instance when filtering by name
        return IncusInstance(
            name=instance[0],
            status=instance[1],
            type=instance[2],
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
        instances = parse_csv_output(output)
        
        return [
            IncusInstance(
                name=instance[0],
                status=instance[1],
                type=instance[2],
                project=project,
                remote=remote
            )
            for instance in instances
        ]
    except Exception as e:
        raise IncusError(f"Failed to list instances: {e}")
