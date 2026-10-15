from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT / "public"


def main() -> None:
    (PUBLIC_DIR / "imagem").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "src" / "index.html", PUBLIC_DIR / "index.html")
    shutil.copy2(ROOT / "src" / "app.js", PUBLIC_DIR / "app.js")
    for image in (ROOT / "imagem").iterdir():
        if image.is_file():
            shutil.copy2(image, PUBLIC_DIR / "imagem" / image.name)


if __name__ == "__main__":
    main()
