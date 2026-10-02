"""Small QMP client for screenshots, deliberate resets and input in the test VM.

uv run --no-project system/qmp.py screendump '{"filename":"/build/vm/screen.ppm"}'
uv run --no-project system/qmp.py human-monitor-command '{"command-line":"sendkey ret"}'
"""
import json
import os
from pathlib import Path
import socket
import sys

def command(name, arguments=None):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        directory = Path(os.environ.get("TODDLERBOX_VM_DIR", "build/vm"))
        client.connect(str(Path(__file__).resolve().parents[1] / directory / "qmp.sock"))
        stream = client.makefile("rwb")
        json.loads(stream.readline())
        for request in [{"execute": "qmp_capabilities"},
                        {"execute": name, "arguments": arguments or {}}]:
            stream.write(json.dumps(request).encode() + b"\n")
            stream.flush()
            while True:
                result = json.loads(stream.readline())
                if "error" in result:
                    raise RuntimeError(result["error"])
                if "return" in result:
                    break
        return result["return"]

if __name__ == "__main__":
    print(json.dumps(command(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else None)))
