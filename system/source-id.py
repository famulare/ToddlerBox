"""Content ID includes uncommitted application and system work, excluding outputs."""
import hashlib
from pathlib import Path

def source_id(root: Path) -> str:
    digest = hashlib.sha256()
    paths = [root / name for name in ("pyproject.toml", "uv.lock", "config.yaml",
                                      "data-schema.json", "README.md", "LICENSE")]
    for name in ("src", "assets", "system"):
        paths.extend(p for p in (root / name).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.suffix != ".pyc"
                     and not any(part.endswith(".egg-info") for part in p.parts))
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()[:16]


if __name__ == "__main__":
    print(source_id(Path(__file__).resolve().parents[1]))
