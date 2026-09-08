"""
example_usage.py — TriCaster Panel library examples

Uncomment the example you want to run at the bottom of the file.
"""

import time
from tricaster_panel import TriCasterPanel, ButtonEvent, TBarEvent, DialEvent, DialTracker

PORT = '/dev/ttyUSB1'


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 1 — LED demo sequence
#  Exercises every LED on the panel.  No callbacks, pure LED control.
# ═══════════════════════════════════════════════════════════════════

def demo_sequence():
    print('── Demo sequence ─────────────────────────────────────')

    with TriCasterPanel(PORT) as panel:

        def pause(t=0.10):
            time.sleep(t)

        # LIVE row: chase each button, then all on, then off
        print('LIVE row (CAM 1 → BLK)')
        for n in range(1, 9):
            panel.live.set_only(n)
            pause()
        panel.live.set(list(range(1, 9)))
        pause(0.35)
        panel.live.clear()
        pause(0.2)

        # NEXT row: same
        print('NEXT row (CAM 1 → BLK)')
        for n in range(1, 9):
            panel.next.set_only(n)
            pause()
        panel.next.set(list(range(1, 9)))
        pause(0.35)
        panel.next.clear()
        pause(0.2)

        # Mini row: chase each named button by label, then all on, then off
        print('Mini row (FADE OVERLAY → TAKE ALL)')
        for label in ['FADE OVERLAY', 'TAKE OVERLAY', 'FADE ALL', 'TAKE ALL']:
            panel.mini.set_only(label)
            pause(0.15)
        panel.mini.set(list(range(1, 5)))
        pause(0.4)
        panel.mini.clear()
        pause(0.2)

        # Fader LEDs: top, bottom, both, off
        print('Fader LEDs')
        panel.fader.set('top')
        pause(0.4)
        panel.fader.set_only('bottom')
        pause(0.4)
        panel.fader.set([1, 2])    # both
        pause(0.4)
        panel.fader.clear()
        pause(0.2)

        # Everything on at once
        print('All LEDs on')
        panel.live.set(list(range(1, 9)))
        panel.next.set(list(range(1, 9)))
        panel.mini.set(list(range(1, 5)))
        panel.fader.set([1, 2])
        pause(0.8)
        panel.all_off()

        print('Done.\n')


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 2 — Auto LED interactive (simplest possible usage)
#
#  auto_leds=True wires the default behaviour automatically:
#    • Hold button → LED on while held
#    • Release     → LED off
#    • T-bar top   → fader top LED
#    • T-bar bottom → fader bottom LED
# ═══════════════════════════════════════════════════════════════════

def auto_interactive():
    print('── Auto LED interactive (Ctrl-C to quit) ─────────────')
    print('  Hold any button → LED lights while pressed')
    print('  T-bar to top/bottom → fader LED follows\n')

    with TriCasterPanel(PORT, auto_leds=True) as panel:
        panel.run()


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 3 — Manual callbacks with custom per-row behaviour
#
#  LIVE  → radio buttons (one lit at a time, stays on after release)
#  NEXT  → toggle (press on, press again off — independent per button)
#  MINI  → momentary (on while held, off on release)
#  T-bar → fader LEDs track min/max
#  Dials → print to console
# ═══════════════════════════════════════════════════════════════════

def manual_interactive():
    print('── Manual callback interactive (Ctrl-C to quit) ──────')
    print('  LIVE: radio (one button lit, stays on)')
    print('  NEXT: toggle (press on, press again off)')
    print('  MINI: momentary (on while held)')
    print('  T-bar: fader LEDs follow top/bottom')
    print()
    print(f"  {'ROW':<6} {'BTN':>3}  {'LABEL':<16}  EVENT")
    print('  ' + '─' * 44)

    with TriCasterPanel(PORT) as panel:

        @panel.on_live
        def _(event: ButtonEvent):
            print(f"  {event.row:<6} {event.button:>3}  {event.label:<16}  "
                  f"{'PRESS' if event.held else 'release'}")
            if event.held:
                # Radio: light only the pressed button, leave it on
                panel.live.set_only(event.button)

        @panel.on_next
        def _(event: ButtonEvent):
            if not event.held:
                return
            print(f"  {event.row:<6} {event.button:>3}  {event.label:<16}  "
                  f"{'on' if event.button not in panel.state.next else 'off'}")
            if event.button in panel.state.next:
                panel.next.clear(event.button)
            else:
                panel.next.set(event.button)

        @panel.on_mini
        def _(event: ButtonEvent):
            print(f"  {event.row:<6} {event.button:>3}  {event.label:<16}  "
                  f"{'PRESS' if event.held else 'release'}")
            if event.held:
                panel.mini.set(event.button)
            else:
                panel.mini.clear(event.button)

        @panel.on_tbar
        def _(event: TBarEvent):
            pos_str = f"{event.position * 100:.1f}%"
            flag    = ' (TOP)' if event.at_top else ' (BOTTOM)' if event.at_bottom else ''
            print(f"  {'TBAR':<6} {'':>3}  {pos_str + flag:<16}")
            panel.fader.clear()
            if event.at_top:
                panel.fader.set('top')
            elif event.at_bottom:
                panel.fader.set('bottom')

        @panel.on_dial
        def _(event: DialEvent):
            print(f"  {'DIAL':<6} {'':>3}  {event.dial:<16}  pos={event.value}")

        panel.run()


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 4 — Mixed: auto_leds as base, override one row manually
#
#  auto_leds handles LIVE, MINI, and T-bar automatically.
#  NEXT is excluded from auto so the toggle handler runs uncontested:
#  without exclude(), auto fires first (LED on), then the toggle sees
#  the button already lit and immediately clears it — a flicker, not
#  a toggle.
# ═══════════════════════════════════════════════════════════════════

def mixed_interactive():
    print('── Mixed mode (Ctrl-C to quit) ────────────────────────')
    print('  LIVE: auto LED (on while held)')
    print('  NEXT: toggle (press to latch on, press again to latch off)')
    print('  MINI: auto LED (on while held)')
    print('  T-bar: auto fader LEDs\n')

    with TriCasterPanel(PORT, auto_leds=True) as panel:

        # Exclude NEXT from auto_leds *before* registering our callback.
        # auto_leds will skip any NEXT event entirely, so our handler
        # sees a clean slate and the toggle logic works as expected.
        panel.auto_leds.exclude('next')

        @panel.on_next
        def _(event: ButtonEvent):
            if not event.held:
                return
            print(f"  {event.row:<6} {event.button:>3}  {event.label:<16}  "
                  f"{'on' if event.button not in panel.state.next else 'off'}")
            if event.button in panel.state.next:
                panel.next.clear(event.button)
            else:
                panel.next.set(event.button)

        panel.run()


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 5 — State inspection (no run loop needed)
# ═══════════════════════════════════════════════════════════════════

def state_snapshot():
    with TriCasterPanel(PORT) as panel:

        # Address LEDs by number, string, or mixed list
        panel.live.set([1, 3, 5])
        panel.live.set('cam 2')               # case-insensitive
        panel.next.set([2, 'vga', 'VCR'])     # mixed
        panel.mini.set('fade overlay')
        panel.mini.set(3)                     # FADE ALL
        panel.fader.set('top')

        s = panel.state
        print(f"LIVE lit:  {sorted(s.live)}")    # [1, 2, 3, 5]
        print(f"NEXT lit:  {sorted(s.next)}")    # [2, 4, 5]
        print(f"MINI lit:  {sorted(s.mini)}")    # [1, 3]
        print(f"Fader lit: {sorted(s.fader)}")   # [1]
        print(f"T-bar:     {s.tbar}")            # None (no input yet)

        panel.all_off()


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 6 — simulate() for testing without hardware
# ═══════════════════════════════════════════════════════════════════

def simulate_without_hardware():
    """
    Run and test callbacks without a physical panel connected.
    Call connect() manually after injecting a mock serial object,
    or just register callbacks and use simulate() directly.
    """
    panel = TriCasterPanel.__new__(TriCasterPanel)
    TriCasterPanel.__init__(panel, port='FAKE', auto_leds=False)

    results = []

    @panel.on_button
    def _(event: ButtonEvent):
        results.append(event)
        print(f"  Button: {event.row} #{event.button} ({event.label}) "
              f"{'PRESS' if event.held else 'release'}")

    @panel.on_tbar
    def _(event: TBarEvent):
        print(f"  T-bar: {event.position:.2f} "
              f"{'TOP' if event.at_top else 'BOTTOM' if event.at_bottom else ''}")

    @panel.on_dial
    def _(event: DialEvent):
        print(f"  Dial:  {event.dial} = {event.value}")

    print('── Simulation (no hardware required) ─────────────────')
    panel.simulate(ButtonEvent(row='LIVE', button=1, label='CAM 1', held=True))
    panel.simulate(ButtonEvent(row='LIVE', button=1, label='CAM 1', held=False))
    panel.simulate(ButtonEvent(row='MINI', button=2, label='TAKE OVERLAY', held=True))
    panel.simulate(TBarEvent(raw=0x00, position=1.0, at_top=True, at_bottom=False))
    panel.simulate(TBarEvent(raw=0xFF, position=0.0, at_top=False, at_bottom=True))
    panel.simulate(DialEvent(dial='TRANSITION_SPEED', value=12))

    print(f"\n  {len(results)} button event(s) captured.\n")


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 7 — Light show
#
#  Multi-phase LED animation covering every group: LIVE, NEXT, MINI,
#  and fader.  No input handling — pure visuals.
#
#  Phases:
#   1. Mirror chase   — LIVE L→R while NEXT R→L simultaneously
#   2. Sync bounce    — both rows track the same position, bouncing
#   3. Squeeze        — fill from outside in, wipe from inside out
#   4. Zipper         — LIVE fills L→R as NEXT fills R→L at the same time
#   5. Mini + fader   — mini buttons cycle with fader alternating top/bottom
#   6. Cascade        — LIVE fills one beat ahead of NEXT, then drains
#   7. Finale         — triple flash, hold all-on, all off
# ═══════════════════════════════════════════════════════════════════

def light_show():
    print('── Light show ─────────────────────────────────────────')

    with TriCasterPanel(PORT) as panel:

        def p(t: float = 0.08) -> None:
            time.sleep(t)

        panel.all_off()
        REPS = 2   # how many times to repeat each looping phase

        while True:
            # ── Phase 1: Mirror chase ─────────────────────────────────
            # LIVE chases left-to-right; NEXT chases right-to-left.
            # The two lit pixels travel in opposite directions.
            print('  Phase 1: mirror chase')
            for _ in range(REPS):
                for n in list(range(1, 9)) + list(range(8, 0, -1)):
                    panel.live.set_only(n)
                    panel.next.set_only(9 - n)
                    p(0.07)

            # ── Phase 2: Sync bounce ──────────────────────────────────
            # Both rows light the same button and bounce back and forth.
            print('  Phase 2: sync bounce')
            for _ in range(REPS):
                for n in list(range(1, 9)) + list(range(7, 0, -1)):
                    panel.live.set_only(n)
                    panel.next.set_only(n)
                    p(0.07)

            # ── Phase 3: Squeeze ──────────────────────────────────────
            # Buttons fill from the outer edges inward, then clear from
            # the centre outward.
            print('  Phase 3: squeeze')
            panel.all_off()
            pairs = [(1, 8), (2, 7), (3, 6), (4, 5)]
            live_lit: list[int] = []
            next_lit: list[int] = []
            for a, b in pairs:
                live_lit += [a, b]
                next_lit += [a, b]
                panel.live.set(list(live_lit))
                panel.next.set(list(next_lit))
                p(0.14)
            p(0.25)
            for a, b in reversed(pairs):
                panel.live.clear([a, b])
                panel.next.clear([a, b])
                p(0.14)
            p(0.20)

            # ── Phase 4: Zipper ───────────────────────────────────────
            # LIVE accumulates left-to-right while NEXT accumulates
            # right-to-left — they zip toward each other and meet in
            # the middle.
            print('  Phase 4: zipper')
            panel.all_off()
            for n in range(1, 9):
                panel.live.set(n)
                panel.next.set(9 - n)
                p(0.09)
            p(0.30)
            panel.all_off()
            p(0.15)

            # ── Phase 5: Mini + fader dance ───────────────────────────
            # Each mini button gets its turn; the fader alternates
            # top/bottom on each step.  LIVE and NEXT do a slow ping-pong
            # in the background.
            print('  Phase 5: mini + fader dance')
            mini_seq = ['FADE OVERLAY', 'TAKE OVERLAY', 'FADE ALL', 'TAKE ALL']
            for _ in range(REPS):
                for i, label in enumerate(mini_seq):
                    panel.mini.set_only(label)
                    panel.fader.set_only('top' if i % 2 == 0 else 'bottom')
                    pos = (i % 4) + 1          # 1, 2, 3, 4
                    panel.live.set_only(pos)
                    panel.next.set_only(9 - pos)
                    p(0.13)
            panel.mini.clear()
            panel.fader.clear()

            # ── Phase 6: Cascade ──────────────────────────────────────
            # LIVE fills one tick ahead of NEXT, creating a trailing
            # fill effect; then both drain in the same staggered order.
            print('  Phase 6: cascade')
            panel.all_off()
            for n in range(1, 10):
                if n <= 8:
                    panel.live.set(n)
                if 1 < n <= 9:
                    panel.next.set(n - 1)
                p(0.09)
            p(0.25)
            for n in range(1, 10):
                if n <= 8:
                    panel.live.clear(n)
                if 1 < n <= 9:
                    panel.next.clear(n - 1)
                p(0.09)
            p(0.15)

            # ── Phase 7: Finale ───────────────────────────────────────
            # Triple flash of everything, then a long all-on hold before
            # killing every LED.
            print('  Phase 7: finale')
            all_btns = list(range(1, 9))
            for _ in range(3):
                panel.live.set(all_btns)
                panel.next.set(all_btns)
                panel.mini.set(list(range(1, 5)))
                panel.fader.set([1, 2])
                p(0.15)
                panel.all_off()
                p(0.10)
            panel.live.set(all_btns)
            panel.next.set(all_btns)
            panel.mini.set(list(range(1, 5)))
            panel.fader.set([1, 2])
            p(0.80)
            panel.all_off()

        print('  Done.\n')


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE 8 — Speed-controlled light show
#
#  Same phases as Example 7, but the TRANSITION_SPEED dial controls
#  animation speed in real-time — no upper or lower limit on the
#  accumulated dial position.
#
#  Dial right → faster    Dial left → slower
#  12 clicks  → 2× speed change (exponential; each detent is a
#               consistent percentage step, so the feel is uniform
#               across the full range)
#
#  DialTracker handles the 0→255→0 hardware wrap transparently:
#  crossing the boundary in either direction is detected and
#  corrected, so turning left past 0 continues to decrease the
#  speed level rather than jumping to the top.
#
#  Architecture:
#    panel.start()  — reader runs in a background thread
#    show loop      — runs in the main thread; reads tracker.position
#    on_dial cb     — fires in the background thread; writes position
#    (Python GIL makes the int write atomic — no lock needed here)
# ═══════════════════════════════════════════════════════════════════

def light_show_with_speed():
    print('── Speed-controlled light show (Ctrl-C to quit) ───────')
    print('  TRANSITION_SPEED dial → turn right to speed up,')
    print('                          turn left  to slow down.')
    print('  No upper or lower limit on speed level.\n')

    tracker = DialTracker()

    # 12 detents doubles or halves the speed — feels consistent
    # because each click is the same *percentage* change.
    CLICKS_PER_OCTAVE = 12

    def p(base_t: float = 0.08) -> None:
        """Sleep for base_t scaled by the current speed level."""
        factor = 2.0 ** (tracker.position / CLICKS_PER_OCTAVE)
        delay  = base_t / factor
        # Practical floor so the show doesn't freeze at extreme speeds;
        # tracker.position itself remains unbounded in both directions.
        time.sleep(max(0.005, delay))

    with TriCasterPanel(PORT) as panel:

        @panel.on_dial
        def _(event: DialEvent):
            if event.dial != 'TRANSITION_SPEED':
                return
            delta = tracker.update(event.value)
            if delta:
                factor = 2.0 ** (tracker.position / CLICKS_PER_OCTAVE)
                print(f"  Speed: level={tracker.position:+d}  ×{factor:.2f}")

        # Start reader in background so the show loop can run here.
        panel.start()
        panel.all_off()

        REPS = 2

        try:
            while True:

                # ── Phase 1: Mirror chase ─────────────────────────
                print('  Phase 1: mirror chase')
                for _ in range(REPS):
                    for n in list(range(1, 9)) + list(range(8, 0, -1)):
                        panel.live.set_only(n)
                        panel.next.set_only(9 - n)
                        p(0.07)

                # ── Phase 2: Sync bounce ──────────────────────────
                print('  Phase 2: sync bounce')
                for _ in range(REPS):
                    for n in list(range(1, 9)) + list(range(7, 0, -1)):
                        panel.live.set_only(n)
                        panel.next.set_only(n)
                        p(0.07)

                # ── Phase 3: Squeeze ──────────────────────────────
                print('  Phase 3: squeeze')
                panel.all_off()
                pairs = [(1, 8), (2, 7), (3, 6), (4, 5)]
                live_lit: list[int] = []
                next_lit: list[int] = []
                for a, b in pairs:
                    live_lit += [a, b]
                    next_lit += [a, b]
                    panel.live.set(list(live_lit))
                    panel.next.set(list(next_lit))
                    p(0.14)
                p(0.25)
                for a, b in reversed(pairs):
                    panel.live.clear([a, b])
                    panel.next.clear([a, b])
                    p(0.14)
                p(0.20)

                # ── Phase 4: Zipper ───────────────────────────────
                print('  Phase 4: zipper')
                panel.all_off()
                for n in range(1, 9):
                    panel.live.set(n)
                    panel.next.set(9 - n)
                    p(0.09)
                p(0.30)
                panel.all_off()
                p(0.15)

                # ── Phase 5: Mini + fader dance ───────────────────
                print('  Phase 5: mini + fader dance')
                mini_seq = ['FADE OVERLAY', 'TAKE OVERLAY', 'FADE ALL', 'TAKE ALL']
                for _ in range(REPS):
                    for i, label in enumerate(mini_seq):
                        panel.mini.set_only(label)
                        panel.fader.set_only('top' if i % 2 == 0 else 'bottom')
                        pos = (i % 4) + 1
                        panel.live.set_only(pos)
                        panel.next.set_only(9 - pos)
                        p(0.13)
                panel.mini.clear()
                panel.fader.clear()

                # ── Phase 6: Cascade ──────────────────────────────
                print('  Phase 6: cascade')
                panel.all_off()
                for n in range(1, 10):
                    if n <= 8:
                        panel.live.set(n)
                    if 1 < n <= 9:
                        panel.next.set(n - 1)
                    p(0.09)
                p(0.25)
                for n in range(1, 10):
                    if n <= 8:
                        panel.live.clear(n)
                    if 1 < n <= 9:
                        panel.next.clear(n - 1)
                    p(0.09)
                p(0.15)

                # ── Phase 7: Finale ───────────────────────────────
                print('  Phase 7: finale')
                all_btns = list(range(1, 9))
                for _ in range(3):
                    panel.live.set(all_btns)
                    panel.next.set(all_btns)
                    panel.mini.set(list(range(1, 5)))
                    panel.fader.set([1, 2])
                    p(0.15)
                    panel.all_off()
                    p(0.10)
                panel.live.set(all_btns)
                panel.next.set(all_btns)
                panel.mini.set(list(range(1, 5)))
                panel.fader.set([1, 2])
                p(0.80)
                panel.all_off()

        except KeyboardInterrupt:
            pass

    print('  Done.\n')


if __name__ == '__main__':

    examples = [
        ('LED demo sequence',            demo_sequence),
        ('Auto LED interactive',         auto_interactive),
        ('Manual callbacks',             manual_interactive),
        ('Mixed mode',                   mixed_interactive),
        ('State snapshot',               state_snapshot),
        ('Simulate without hardware',    simulate_without_hardware),
        ('Light show',                   light_show),
        ('Light show (speed-controlled)', light_show_with_speed),
    ]

    print()
    print('  TriCaster Panel — examples')
    print()
    for i, (name, _) in enumerate(examples, 1):
        print(f'  {i}.  {name}')
    print()

    choice = None
    while choice is None:
        try:
            raw = input('  Select example [1–8]: ').strip()
            n   = int(raw)
            if 1 <= n <= len(examples):
                choice = n
            else:
                print(f'  Enter a number between 1 and {len(examples)}.')
        except ValueError:
            print('  Please enter a number.')
        except KeyboardInterrupt:
            print()
            raise SystemExit(0)

    print()
    _, fn = examples[choice - 1]
    fn()
