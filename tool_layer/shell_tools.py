"""
tool_layer/shell_tools.py
Shell command execution with whitelist enforcement.
"""

import subprocess

SHELL_TIMEOUT = 60


def shell(command: str, allowed_commands: list[str] | None = None) -> str:
    """Execute a shell command.

    Args:
        command: The command string to execute.
        allowed_commands: Whitelist of allowed command prefixes.
            If None, all commands are allowed (use with caution).

    Returns:
        Command output as string.
    """
    if not command or not command.strip():
        return "[Error] Empty command."

    # Whitelist check
    if allowed_commands:
        cmd_first = command.strip().split()[0] if command.strip().split() else ""
        cmd_lower = cmd_first.lower()

        # Also check full path variants (e.g., .\python\python.exe → python)
        import os as _os
        cmd_basename = _os.path.basename(cmd_first).lower()

        allowed_lower = [c.lower() for c in allowed_commands]

        if cmd_lower not in allowed_lower and cmd_basename not in allowed_lower:
            # Check if it starts with an allowed command
            found = False
            for allowed in allowed_lower:
                if command.strip().lower().startswith(allowed):
                    found = True
                    break
            if not found:
                return f"[Blocked] Command '{cmd_first}' is not in the allowed whitelist.\nAllowed: {', '.join(allowed_commands)}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=SHELL_TIMEOUT,
            cwd=str(subprocess.os.getcwd()),
        )

        output = (result.stdout or "").rstrip()
        stderr = (result.stderr or "").rstrip()

        if result.returncode != 0:
            if output and stderr:
                return f"{output}\n\n[stderr]:\n{stderr}\n[Exit code: {result.returncode}]"
            elif stderr:
                return f"{stderr}\n[Exit code: {result.returncode}]"
            elif output:
                return f"{output}\n[Exit code: {result.returncode}]"
            else:
                return f"[Exit code: {result.returncode}] (no output)"

        if output:
            max_len = 4000
            if len(output) > max_len:
                return output[:max_len] + f"\n\n[...truncated {len(output) - max_len} chars...]"
            return output

        return "[OK] Command executed (no output)."

    except subprocess.TimeoutExpired:
        return f"[Timeout] Command exceeded {SHELL_TIMEOUT}s limit."
    except FileNotFoundError:
        return f"[Error] Command not found: {command.split()[0] if command.split() else command}"
    except Exception as e:
        return f"[Error] {e}"
