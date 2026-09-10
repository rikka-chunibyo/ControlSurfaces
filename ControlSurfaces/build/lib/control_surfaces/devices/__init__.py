# ═══════════════════════════════════════════════════════════════════
# control_surfaces/devices/__init__.py
#
# Each supported physical device gets its own module here, built on
# the shared ControlSurface base class (control_surfaces/surface.py).
# Adding a new device means adding one new file to this folder --
# nothing above this level needs to change.
# ═══════════════════════════════════════════════════════════════════

from .tricaster import TriCasterSurface
from .lc11      import LC11Surface

__all__ = ['TriCasterSurface', 'LC11Surface']
