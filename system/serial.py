"""Run a diagnostic command on a disposable VM via its independent serial login.

uv run --no-project system/serial.py --password-file build/vm/test-password 'id'
The password file is local to the test overlay, never part of a built image.
"""
import argparse
import os
from pathlib import Path
import re
import socket
import time

parser = argparse.ArgumentParser()
parser.add_argument("--password-file", type=Path, required=True)
parser.add_argument("command")
args = parser.parse_args()
password = args.password_file.read_text().strip()
root = Path(__file__).resolve().parents[1]
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
    directory = Path(os.environ.get("TODDLERBOX_VM_DIR", "build/vm"))
    client.connect(str(root / directory / "serial.sock"))
    client.settimeout(1)
    def read_until(pattern, timeout=30):
        data = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data += client.recv(65536).decode(errors="replace")
            except socket.timeout:
                continue
            if re.search(pattern, data):
                return data
        raise TimeoutError("VM serial prompt did not arrive: " + data.replace(password, "[redacted]")[-2000:])
    client.sendall(b"\n")
    prompt = read_until(r"login:|[$#] ")
    if "login:" in prompt:
        client.sendall(b"parent\n")
        read_until(r"Password:")
        client.sendall(password.encode() + b"\n")
        read_until(r"[$] ")
        prompt = "$ "
    if "$ " in prompt or "$ \x1b" in prompt:
        client.sendall(b"sudo -S -p 'VM_SUDO_PASSWORD: ' -i\n")
        response = read_until(r"VM_SUDO_PASSWORD: $|# ")
        if not re.search(r"# ", response):
            client.sendall(password.encode() + b"\n")
            read_until(r"# ")
    # A split marker avoids matching the terminal's echoed command.
    client.sendall((args.command + "\nprintf '\\nVM_COMMAND_%s\\n' DONE\n").encode())
    result = read_until(r"\nVM_COMMAND_DONE\r?\n", timeout=60)
    print(result.replace(password, "[redacted]"))
