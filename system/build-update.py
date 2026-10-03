"""Build one public executable update bundle; no OS image or family data needed.

Optional --app is an app-release tar.gz produced with the same Ubuntu ABI.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

from update_bundle import FILES, sha


def build(root, cage, output, app=None):
    spec = importlib.util.spec_from_file_location("source_id", root / "system/source-id.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = module.source_id(root)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    paths = {"controller.py": root / "system/controller.py",
             "update_bundle.py": root / "system/update_bundle.py",
             "toddlerbox-cage": cage}
    for name in FILES.keys() - paths.keys():
        paths[name] = root / "system/bin" / name
    manifest = {"format": 1, "source": {"git": revision, "content": source},
                "files": {name: sha(path) for name, path in paths.items()},
                "app": sha(app) if app else None}
    output.parent.mkdir(parents=True, exist_ok=True)
    # Fixed timestamps/order make the same inputs produce the same bytes.
    with output.open("wb") as handle:
        handle.write(b"#!/usr/bin/python3\n")
        with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            inputs = {"__main__.py": b"from update_bundle import main\nmain()\n",
                      "update_bundle.py": paths["update_bundle.py"].read_bytes(),
                      "manifest.json": json.dumps(manifest, sort_keys=True).encode()}
            inputs.update({"payload/" + name: path for name, path in paths.items()})
            if app:
                inputs["app.tar.gz"] = app
            for name, data in sorted(inputs.items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with archive.open(info, "w") as target:
                    if isinstance(data, Path):
                        with data.open("rb") as source_file:
                            shutil.copyfileobj(source_file, target)
                    else:
                        target.write(data)
    output.chmod(0o755)
    digest = sha(output)
    output.with_name(output.name + ".sha256").write_text(f"{digest}  {output.name}\n")
    output.with_name(output.name + ".source.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return digest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--app", type=Path)
    args = parser.parse_args()
    print(build(Path(__file__).resolve().parents[1], args.cage, args.output, args.app))
