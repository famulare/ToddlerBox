"""Content ID includes uncommitted application and system work, excluding outputs."""
import hashlib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
digest = hashlib.sha256()
paths = [root / name for name in ("pyproject.toml", "uv.lock", "config.yaml")]
for name in ("src", "assets", "system"):
    paths.extend(p for p in (root / name).rglob("*") if p.is_file()
                 and "__pycache__" not in p.parts and not p.suffix == ".pyc")
for path in sorted(paths):
    digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes() + b"\0")
print(digest.hexdigest()[:16])
