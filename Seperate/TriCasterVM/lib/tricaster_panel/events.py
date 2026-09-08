# ═══════════════════════════════════════════════════════════════════
# tricaster_panel/events.py
#
# Typed event dataclasses emitted by the panel reader.
# ═══════════════════════════════════════════════════════════════════

from dataclasses import dataclass


@dataclass
class ButtonEvent:
    """Fired when any button is pressed or released."""
    row:    str    # 'LIVE' | 'NEXT' | 'MINI'
    button: int    # 1-indexed within the row
    label:  str    # 'CAM 1', 'FADE OVERLAY', etc.
    held:   bool   # True = pressed,  False = released


@dataclass
class TBarEvent:
    """Fired on every T-bar position change."""
    raw:       int    # raw byte value  0x00–0xFF
    position:  float  # 0.0 (physical bottom) – 1.0 (physical top)
    at_top:    bool   # True when raw == 0x00  (T-bar fully up)
    at_bottom: bool   # True when raw == 0xFF  (T-bar fully down)


@dataclass
class DialEvent:
    """Fired when any rotary dial changes position."""
    dial:  str   # 'TRANSITION_SPEED' | 'TRANSITION_SELECT' | 'OVERLAY_SELECT'
    value: int   # raw detent value reported by the hardware
