"""Apply trusted locally built Docker-save layers without a vfs container copy.

Run only inside the disposable image-tools container, with a fresh output folder.
"""
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

archive, destination = Path(sys.argv[1]), Path(sys.argv[2])
if destination.exists():
    raise SystemExit("Output must not exist; preserve previous build inputs")
destination.mkdir(parents=True)
with tarfile.open(archive, "r:*") as outer:
    manifest = json.load(outer.extractfile("manifest.json"))
    if len(manifest) != 1:
        raise SystemExit("Expected exactly one locally built image")
    for filename in manifest[0]["Layers"]:
        with tarfile.open(fileobj=outer.extractfile(filename), mode="r:") as layer:
            files = layer.getmembers()
            for member in files:
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts:
                    raise SystemExit("Invalid Docker layer path")
                if not name.name.startswith(".wh."):
                    continue
                directory = destination / str(name.parent)
                victims = list(directory.iterdir()) if name.name == ".wh..wh..opq" and directory.exists() else [directory/name.name[4:]]
                for victim in victims:
                    if victim.is_dir() and not victim.is_symlink():
                        shutil.rmtree(victim)
                    else:
                        victim.unlink(missing_ok=True)
            # Trusted Ubuntu/local build layers, including Unix ownership/devices.
            layer.extractall(destination, members=[m for m in files if not PurePosixPath(m.name).name.startswith(".wh.")], filter="fully_trusted")
