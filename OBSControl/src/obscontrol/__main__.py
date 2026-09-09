from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ControlSurfaces"))

from .config import load_config
from .gui import OBSControlApp


def main() -> int:
    import tkinter as tk
    root = tk.Tk()
    OBSControlApp(root, load_config())
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
