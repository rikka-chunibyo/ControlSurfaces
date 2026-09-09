from __future__ import annotations

import logging
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT.parent / "ControlSurfaces"))

from obscontrol.config import load_config
from obscontrol.gui import OBSControlApp


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = tk.Tk()
    try:
        config = load_config()
    except Exception as exc:
        messagebox.showerror("OBSControl configuration error", str(exc))
        return 1
    OBSControlApp(root, config)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
