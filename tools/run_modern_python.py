"""Run a repository script with verified Python 3.13; never install or fall back."""

# Keep launcher syntax compatible with the host's legacy Python so it can refuse
# that runtime cleanly without importing application code.
import json
import os
import subprocess
import sys


def execute(arguments, executable=None, run=None):
    run = run or subprocess.run
    executable = executable or sys.executable
    if not arguments:
        raise ValueError("a repository Python script is required")
    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    script = os.path.realpath(os.path.join(root, arguments[0]))
    if os.path.commonpath([root, script]) != root or not os.path.isfile(script) or not script.endswith(".py"):
        raise ValueError("script must be an existing repository Python file")
    if script == os.path.realpath(__file__):
        raise ValueError("recursive runner execution is forbidden")
    probe = run([executable, "-I", "-c", "import json,sys; print(json.dumps(list(sys.version_info[:2])))"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    if probe.returncode != 0:
        raise ValueError("interpreter probe failed; no fallback")
    try:
        version = json.loads(probe.stdout.decode("utf-8"))
    except (ValueError, UnicodeError, AttributeError):
        raise ValueError("invalid interpreter probe; no fallback")
    if version != [3, 13] or any(type(value) is not int for value in version):
        raise ValueError("Python 3.13 is required; no install or alternate-version fallback")
    return run([executable, script] + arguments[1:], cwd=root).returncode


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    executable = None
    if arguments[:1] == ["--python"]:
        if len(arguments) < 3:
            print("--python requires an executable and repository script", file=sys.stderr)
            return 2
        executable, arguments = arguments[1], arguments[2:]
    # The default host is rejected before using APIs absent on legacy Python.
    if executable is None and sys.version_info[:2] != (3, 13):
        print("Python 3.13 is required; no install or fallback", file=sys.stderr)
        return 2
    if not hasattr(subprocess, "run") or not hasattr(os.path, "commonpath"):
        print("launcher host must support subprocess.run/commonpath", file=sys.stderr)
        return 2
    try:
        return execute(arguments, executable)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
