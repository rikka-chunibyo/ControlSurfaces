from __future__ import annotations

import json
import queue
import tkinter as tk
from copy import deepcopy
from datetime import datetime
from tkinter import messagebox, ttk

from .actions import ACTION_LABELS
from .config import default_config_path, save_config
from .engine import ControllerEngine
from .models import ActionSpec, AppConfig, LedRule, Mapping, PanelConfig
from .panels import (
    SURFACE_CLASSES, display_control_name, input_control_names, led_control_names,
    triggers_for_control,
)


COLORS = {
    "bg": "#101418", "panel": "#171d23", "field": "#202830",
    "text": "#e8edf2", "muted": "#91a0ad", "accent": "#56c2ff",
    "good": "#65d58a", "bad": "#ff6b75",
}

LED_CONDITIONS = {
    "always": "Always on",
    "obs_connected": "OBS connected",
    "program_scene": "Program scene is",
    "preview_scene": "Preview scene is",
    "current_transition": "Transition is",
    "input_muted": "Input is muted",
    "source_visible": "Scene source is visible",
    "studio_mode": "Studio Mode is on",
    "recording": "Recording is active",
    "streaming": "Streaming is active",
    "virtual_camera": "Virtual camera is active",
    "replay_buffer": "Replay buffer is active",
}

ACTION_DESCRIPTIONS = {
    "set_preview_scene": "Choose the scene OBS will transition to next in Studio Mode.",
    "set_program_scene": "Switch the live Program output to a scene.",
    "trigger_transition": "Set Preview and the transition, then run it to Program.",
    "transition_preview": "Use the current Preview scene, select a transition, then take it to Program.",
    "set_transition": "Change OBS's selected scene transition without running it.",
    "set_transition_duration": "Change the duration used by configurable transitions.",
    "set_tbar_position": "Follow the physical T-bar position in OBS Studio Mode.",
    "set_mute": "Toggle, mute, or unmute an OBS audio input.",
    "set_input_volume": "Move an OBS input volume relative to its current level. Every move stays within the configured minimum and maximum dB range.",
    "set_input_monitoring": "Toggle monitoring on/off, or choose Monitor Only or Monitor and Output explicitly.",
    "set_source_visibility": "Toggle, show, or hide one source in a scene.",
    "media_action": "Control playback for an OBS media input.",
    "set_studio_mode": "Toggle Studio Mode, or explicitly turn it on or off.",
    "recording": "Toggle recording, or explicitly start or stop it.",
    "toggle_record_pause": "Pause or resume the current recording.",
    "streaming": "Toggle streaming, or explicitly start or stop it.",
    "virtual_camera": "Toggle the virtual camera, or explicitly start or stop it.",
    "replay_buffer": "Toggle the replay buffer, or explicitly start or stop it.",
    "save_replay_buffer": "Save the current replay-buffer contents.",
    "raw_request": "Send an advanced OBS WebSocket request by name.",
}


def describe_action(action: ActionSpec) -> str:
    params = action.params
    kind = action.kind
    if kind in ("set_preview_scene", "set_program_scene"):
        return params.get("scene", "")
    if kind == "trigger_transition":
        return f"{params.get('scene', 'Current Preview')} via {params.get('transition', 'Current transition')}"
    if kind in ("transition_preview", "set_transition"):
        return params.get("transition", "Current transition")
    if kind == "set_transition_duration":
        return f"{params.get('duration_ms', '')} ms"
    if kind == "set_tbar_position":
        return str(params.get("position", "$event.position"))
    if kind == "set_mute":
        return f"{params.get('input', '')} - {params.get('mode', 'toggle').title()}"
    if kind == "set_input_volume":
        return (f"{params.get('input', '')} - {params.get('step_db', 1)} dB/step, "
                f"{params.get('min_db', -100)} to {params.get('max_db', 0)} dB")
    if kind == "set_input_monitoring":
        return f"{params.get('input', '')} - {params.get('mode', 'toggle').title()}"
    if kind == "set_source_visibility":
        return (f"{params.get('scene', '')} / {params.get('source', '')} - "
                f"{params.get('mode', 'toggle').title()}")
    if kind == "media_action":
        operation = params.get("media_action", "RESTART").split("_")[-1].title()
        return f"{params.get('input', '')} - {operation}"
    if kind in ("set_studio_mode", "recording", "streaming", "virtual_camera", "replay_buffer"):
        return params.get("mode", "toggle").title()
    if kind == "raw_request":
        return params.get("request_type", "")
    return "-"


class OBSControlApp:
    def __init__(self, root: tk.Tk, config: AppConfig) -> None:
        self.root = root
        self.config = config
        self.engine = ControllerEngine(config)
        self.messages: queue.Queue = queue.Queue()
        self.panel_status: dict[str, str] = {}

        self._style()
        self._build()
        self._seed_first_panel()
        self._load_settings()
        self._refresh_panel_tree()
        self._refresh_mapping_tree()
        self._refresh_led_tree()

        self.engine.on_log(lambda level, message: self.messages.put(("log", level, message)))
        self.engine.on_state(lambda state: self.messages.put(("state", state)))
        self.engine.on_panel_status(
            lambda panel_id, status: self.messages.put(("panel", panel_id, status))
        )
        self.engine.start()
        self.root.after(15, self._pump)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _style(self) -> None:
        self.root.title("OBSControl")
        self.root.geometry("1100x720")
        self.root.minsize(900, 600)
        self.root.configure(bg=COLORS["bg"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        self.root.option_add("*TCombobox*Listbox.background", COLORS["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", COLORS["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", COLORS["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#07131a")
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))
        style.configure(".", background=COLORS["panel"], foreground=COLORS["text"],
                        fieldbackground=COLORS["field"], bordercolor="#2a343d",
                        darkcolor="#2a343d", lightcolor="#2a343d")
        style.configure("TFrame", background=COLORS["panel"])
        style.configure("Card.TFrame", background=COLORS["panel"])
        style.configure("TLabel", background=COLORS["panel"], foreground=COLORS["text"])
        style.configure("Muted.TLabel", foreground=COLORS["muted"])
        style.configure("Title.TLabel", background=COLORS["panel"], font=("Segoe UI", 20, "bold"))
        style.configure("Status.TLabel", background=COLORS["panel"], foreground=COLORS["muted"])
        style.configure("TButton", padding=(10, 7), borderwidth=0, relief="flat",
                        background="#26313a", focuscolor=COLORS["accent"])
        style.map("TButton", background=[("active", "#34424d"), ("pressed", "#1d262d")])
        style.configure("Accent.TButton", foreground="#07131a", background=COLORS["accent"])
        style.map("Accent.TButton", background=[("active", "#83d3ff")])
        style.configure("Treeview", background=COLORS["panel"], fieldbackground=COLORS["panel"],
                        foreground=COLORS["text"], rowheight=30, borderwidth=0, relief="flat")
        style.configure("Treeview.Heading", background=COLORS["field"], foreground=COLORS["text"])
        style.map("Treeview", background=[("selected", "#28516a")])
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 9), borderwidth=0,
                        relief="flat", background="#1b2229", foreground=COLORS["muted"],
                        focuscolor=COLORS["accent"])
        style.map("TNotebook.Tab",
                  background=[("selected", COLORS["panel"]),
                              ("active", "#26313a"),
                              ("pressed", COLORS["field"]),
                              ("disabled", COLORS["bg"])],
                  foreground=[("selected", COLORS["accent"]),
                              ("active", COLORS["text"]),
                              ("disabled", "#5e6a74")],
                  lightcolor=[("selected", COLORS["panel"]), ("!selected", "#1b2229")],
                  darkcolor=[("selected", COLORS["panel"]), ("!selected", "#1b2229")],
                  bordercolor=[("selected", COLORS["panel"]), ("!selected", "#1b2229")])
        style.configure("TLabelframe", background=COLORS["panel"], borderwidth=1,
                        relief="solid", bordercolor="#273139")
        style.configure("TLabelframe.Label", background=COLORS["panel"], foreground=COLORS["accent"])
        style.configure("TCheckbutton", background=COLORS["panel"])
        style.configure("TEntry", padding=7, borderwidth=1, relief="flat",
                        foreground=COLORS["text"], fieldbackground=COLORS["field"])
        style.configure("TCombobox", padding=6, borderwidth=1, relief="flat",
                        foreground=COLORS["text"], fieldbackground=COLORS["field"],
                        background=COLORS["field"], arrowcolor=COLORS["muted"])
        style.map("TCombobox",
                  foreground=[("readonly", COLORS["text"]), ("disabled", COLORS["muted"])],
                  fieldbackground=[("readonly", COLORS["field"]), ("disabled", "#1a2026")],
                  background=[("readonly", COLORS["field"]), ("active", "#2a343d")],
                  selectbackground=[("readonly", COLORS["field"])],
                  selectforeground=[("readonly", COLORS["text"])])

    def _build(self) -> None:
        header = ttk.Frame(self.root, padding=(18, 14))
        header.pack(fill="x")
        ttk.Label(header, text="OBSControl", style="Title.TLabel").pack(side="left")
        self.obs_badge = ttk.Label(header, text="OBS: connecting", style="Status.TLabel")
        self.obs_badge.pack(side="left", padx=24)
        ttk.Button(header, text="Reconnect", command=self._apply_and_restart).pack(side="right")
        ttk.Button(header, text="Save", style="Accent.TButton", command=self.save).pack(side="right", padx=8)

        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.dashboard = ttk.Frame(self.tabs, style="Card.TFrame", padding=14)
        self.mapping_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=14)
        self.led_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=14)
        self.log_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=14)
        self.tabs.add(self.dashboard, text="Dashboard")
        self.tabs.add(self.mapping_tab, text="Mappings")
        self.tabs.add(self.led_tab, text="LED feedback")
        self.tabs.add(self.log_tab, text="Activity")
        self._build_dashboard()
        self._build_mappings()
        self._build_leds()
        self._build_log()

    def _build_dashboard(self) -> None:
        obs_box = ttk.LabelFrame(self.dashboard, text="OBS WebSocket", padding=12)
        obs_box.pack(fill="x")
        self.local_var = tk.BooleanVar(value=True)
        self.host_var, self.port_var, self.password_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Checkbutton(obs_box, text="Use this computer's OBS settings",
                        variable=self.local_var, command=self._toggle_obs_fields).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(obs_box, text="Host").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.host_entry = ttk.Entry(obs_box, textvariable=self.host_var, width=24)
        self.host_entry.grid(row=2, column=0, sticky="ew", padx=(0, 10))
        ttk.Label(obs_box, text="Port").grid(row=1, column=1, sticky="w", pady=(10, 0))
        self.port_entry = ttk.Entry(obs_box, textvariable=self.port_var, width=10)
        self.port_entry.grid(row=2, column=1, sticky="ew", padx=(0, 10))
        ttk.Label(obs_box, text="Password").grid(row=1, column=2, sticky="w", pady=(10, 0))
        self.password_entry = ttk.Entry(obs_box, textvariable=self.password_var, show="•", width=32)
        self.password_entry.grid(row=2, column=2, sticky="ew")
        obs_box.columnconfigure(2, weight=1)

        panels_box = ttk.LabelFrame(self.dashboard, text="Control surfaces", padding=12)
        panels_box.pack(fill="both", expand=True, pady=12)
        columns = ("name", "type", "port", "serial", "status")
        self.panel_tree = ttk.Treeview(panels_box, columns=columns, show="headings", height=7)
        for col, title, width in zip(columns, ("Name", "Device", "Port", "USB serial", "Status"),
                                     (180, 120, 90, 180, 120)):
            self.panel_tree.heading(col, text=title)
            self.panel_tree.column(col, width=width, anchor="w")
        self.panel_tree.pack(fill="both", expand=True)
        buttons = ttk.Frame(panels_box, style="Card.TFrame")
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Add panel", command=self._add_panel).pack(side="left")
        ttk.Button(buttons, text="Edit", command=self._edit_panel).pack(side="left", padx=6)
        ttk.Button(buttons, text="Remove", command=self._remove_panel).pack(side="left")
        ttk.Button(buttons, text="Rescan ports", command=self._refresh_panel_tree).pack(side="right")
        self.panel_tree.bind("<Double-1>", lambda _e: self._edit_panel())

        state_box = ttk.LabelFrame(self.dashboard, text="Live OBS state", padding=12)
        state_box.pack(fill="x")
        self.state_vars = {name: tk.StringVar(value="—") for name in
                           ("program", "preview", "transition", "studio", "version",
                            "recording", "streaming", "camera", "replay")}
        status_items = (
            ("Program", "program"), ("Preview", "preview"),
            ("Transition", "transition"), ("Studio mode", "studio"),
            ("OBS", "version"), ("Recording", "recording"),
            ("Streaming", "streaming"), ("Virtual camera", "camera"),
            ("Replay buffer", "replay"),
        )
        for index, (label, key) in enumerate(status_items):
            cell = ttk.Frame(state_box, style="Card.TFrame")
            row, column = divmod(index, 5)
            cell.grid(row=row, column=column, sticky="ew", padx=6, pady=4)
            ttk.Label(cell, text=label, style="Muted.TLabel").pack(anchor="w")
            ttk.Label(cell, textvariable=self.state_vars[key]).pack(anchor="w")
            state_box.columnconfigure(column, weight=1)

    def _build_mappings(self) -> None:
        ttk.Label(
            self.mapping_tab,
            text="Map a hardware input to one or more ordered OBS actions.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 10))
        columns = ("enabled", "name", "panel", "control", "trigger", "actions")
        self.mapping_tree = ttk.Treeview(self.mapping_tab, columns=columns, show="headings")
        specs = (("enabled", "On", 45), ("name", "Mapping", 180), ("panel", "Panel", 150),
                 ("control", "Control", 135), ("trigger", "Trigger", 75),
                 ("actions", "Actions", 310))
        for col, title, width in specs:
            self.mapping_tree.heading(col, text=title)
            self.mapping_tree.column(col, width=width, anchor="w")
        self.mapping_tree.pack(fill="both", expand=True)
        self.mapping_tree.bind("<Double-1>", lambda _e: self._edit_mapping())
        buttons = ttk.Frame(self.mapping_tab, style="Card.TFrame")
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Add mapping", style="Accent.TButton",
                   command=self._add_mapping).pack(side="left")
        ttk.Button(buttons, text="Edit", command=self._edit_mapping).pack(side="left", padx=6)
        ttk.Button(buttons, text="Duplicate", command=self._duplicate_mapping).pack(side="left")
        ttk.Button(buttons, text="Delete", command=self._remove_mapping).pack(side="left", padx=6)
        ttk.Button(buttons, text="Enable / disable", command=self._toggle_mapping).pack(side="left")

    def _build_leds(self) -> None:
        ttk.Label(
            self.led_tab,
            text="Drive hardware LEDs from OBS state, independently of input mappings.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 10))
        columns = ("enabled", "name", "panel", "led", "condition", "target", "invert")
        self.led_tree = ttk.Treeview(self.led_tab, columns=columns, show="headings")
        specs = (("enabled", "On", 45), ("name", "Rule", 170), ("panel", "Panel", 140),
                 ("led", "LED", 145), ("condition", "Lights when", 170),
                 ("target", "Target", 210), ("invert", "Invert", 60))
        for col, title, width in specs:
            self.led_tree.heading(col, text=title)
            self.led_tree.column(col, width=width, anchor="w")
        self.led_tree.pack(fill="both", expand=True)
        self.led_tree.bind("<Double-1>", lambda _e: self._edit_led_rule())
        buttons = ttk.Frame(self.led_tab, style="Card.TFrame")
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Add LED rule", style="Accent.TButton",
                   command=self._add_led_rule).pack(side="left")
        ttk.Button(buttons, text="Edit", command=self._edit_led_rule).pack(side="left", padx=6)
        ttk.Button(buttons, text="Duplicate", command=self._duplicate_led_rule).pack(side="left")
        ttk.Button(buttons, text="Delete", command=self._remove_led_rule).pack(side="left", padx=6)
        ttk.Button(buttons, text="Enable / disable", command=self._toggle_led_rule).pack(side="left")
        ttk.Label(buttons, text="Multiple rules targeting one LED are combined with OR.",
                  style="Muted.TLabel").pack(side="right")

    def _build_log(self) -> None:
        self.log_text = tk.Text(self.log_tab, bg="#0c1014", fg=COLORS["text"],
                                insertbackground=COLORS["text"], relief="flat",
                                font=("Cascadia Mono", 10), state="disabled")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("ERROR", foreground=COLORS["bad"])
        self.log_text.tag_configure("ACTION", foreground=COLORS["good"])
        self.log_text.tag_configure("OBS", foreground=COLORS["accent"])
        row = ttk.Frame(self.log_tab, style="Card.TFrame"); row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Clear activity", command=self._clear_log).pack(side="right")

    def _seed_first_panel(self) -> None:
        if self.config.panels:
            return
        candidates = [item for item in self.engine.panels.ports()
                      if "Bluetooth" not in item["description"]]
        if len(candidates) == 1:
            item = candidates[0]
            self.config.panels.append(PanelConfig(
                name="LC-11", device_type="lc11", port=item["port"],
                serial_number=item["serial_number"],
            ))

    def _load_settings(self) -> None:
        settings = self.config.obs
        self.local_var.set(settings.use_local_obs_config)
        self.host_var.set(settings.host)
        self.port_var.set(str(settings.port))
        self.password_var.set(settings.password)
        self._toggle_obs_fields()

    def _store_settings(self) -> bool:
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Invalid port", "OBS WebSocket port must be a number.")
            return False
        if not 1 <= port <= 65535:
            messagebox.showerror("Invalid port", "OBS WebSocket port must be between 1 and 65535.")
            return False
        self.config.obs.host = self.host_var.get().strip() or "127.0.0.1"
        self.config.obs.port = port
        self.config.obs.password = self.password_var.get()
        self.config.obs.use_local_obs_config = self.local_var.get()
        return True

    def _toggle_obs_fields(self) -> None:
        state = "disabled" if self.local_var.get() else "normal"
        for widget in (self.host_entry, self.port_entry, self.password_entry):
            widget.configure(state=state)

    def _apply_and_restart(self) -> None:
        if not self._store_settings():
            return
        self.save(restart=False)
        self.engine.update_config(self.config)

    def save(self, restart: bool = False) -> None:
        if not self._store_settings():
            return
        try:
            save_config(self.config)
            self._append_log("INFO", f"Saved {default_config_path()}")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def _refresh_panel_tree(self) -> None:
        self.panel_tree.delete(*self.panel_tree.get_children())
        ports = {item["serial_number"]: item["port"] for item in self.engine.panels.ports()
                 if item["serial_number"]}
        for panel in self.config.panels:
            live_port = ports.get(panel.serial_number, panel.port)
            self.panel_tree.insert("", "end", iid=panel.id, values=(
                panel.name, panel.device_type.upper(), live_port,
                panel.serial_number or "—", self.panel_status.get(panel.id, self.engine.panels.status(panel.id)),
            ))

    def _selected_id(self, tree) -> str | None:
        selection = tree.selection()
        return selection[0] if selection else None

    def _add_panel(self) -> None:
        panel = PanelConfig()
        if PanelDialog(self.root, panel, self.engine.panels.ports()).show():
            self.config.panels.append(panel)
            self._refresh_panel_tree()
            self._refresh_mapping_tree()
            self._apply_and_restart()

    def _edit_panel(self) -> None:
        panel_id = self._selected_id(self.panel_tree)
        panel = next((p for p in self.config.panels if p.id == panel_id), None)
        if panel and PanelDialog(self.root, panel, self.engine.panels.ports()).show():
            self._refresh_panel_tree()
            self._refresh_mapping_tree()
            self._apply_and_restart()

    def _remove_panel(self) -> None:
        panel_id = self._selected_id(self.panel_tree)
        if not panel_id:
            return
        if messagebox.askyesno("Remove panel", "Remove this panel and its mappings?"):
            self.config.panels = [p for p in self.config.panels if p.id != panel_id]
            self.config.mappings = [m for m in self.config.mappings if m.panel_id != panel_id]
            self.config.led_rules = [r for r in self.config.led_rules if r.panel_id != panel_id]
            self._refresh_panel_tree(); self._refresh_mapping_tree(); self._refresh_led_tree()
            self._apply_and_restart()

    def _refresh_mapping_tree(self) -> None:
        self.mapping_tree.delete(*self.mapping_tree.get_children())
        panels = {panel.id: panel.name for panel in self.config.panels}
        for mapping in self.config.mappings:
            actions = ", ".join(ACTION_LABELS.get(a.kind, a.kind) for a in mapping.actions)
            self.mapping_tree.insert("", "end", iid=mapping.id, values=(
                "✓" if mapping.enabled else "", mapping.name,
                panels.get(mapping.panel_id, "Missing panel"), mapping.control,
                mapping.trigger, actions,
            ))

    def _refresh_led_tree(self) -> None:
        self.led_tree.delete(*self.led_tree.get_children())
        panels = {panel.id: panel.name for panel in self.config.panels}
        for rule in self.config.led_rules:
            target = " / ".join(str(value) for value in rule.params.values()) or "-"
            self.led_tree.insert("", "end", iid=rule.id, values=(
                "yes" if rule.enabled else "", rule.name,
                panels.get(rule.panel_id, "Missing panel"), rule.led,
                LED_CONDITIONS.get(rule.condition, rule.condition), target,
                "Yes" if rule.invert else "",
            ))

    def _add_led_rule(self) -> None:
        if not self.config.panels:
            messagebox.showinfo("Add a panel", "Add a control surface first.")
            return
        rule = LedRule(panel_id=self.config.panels[0].id)
        if LedRuleDialog(self.root, rule, self.config, self.engine.state).show():
            self.config.led_rules.append(rule)
            self._refresh_led_tree(); self.save(); self.engine.request_refresh()

    def _edit_led_rule(self) -> None:
        rule_id = self._selected_id(self.led_tree)
        rule = next((r for r in self.config.led_rules if r.id == rule_id), None)
        if rule and LedRuleDialog(self.root, rule, self.config, self.engine.state).show():
            self._refresh_led_tree(); self.save(); self.engine.request_refresh()

    def _duplicate_led_rule(self) -> None:
        rule_id = self._selected_id(self.led_tree)
        rule = next((r for r in self.config.led_rules if r.id == rule_id), None)
        if rule:
            duplicate = deepcopy(rule)
            duplicate.id = __import__("uuid").uuid4().hex[:8]
            duplicate.name += " copy"
            self.config.led_rules.append(duplicate)
            self._refresh_led_tree(); self.save(); self.engine.request_refresh()

    def _remove_led_rule(self) -> None:
        rule_id = self._selected_id(self.led_tree)
        if rule_id:
            self.config.led_rules = [r for r in self.config.led_rules if r.id != rule_id]
            self._refresh_led_tree(); self.save(); self.engine.request_refresh()

    def _toggle_led_rule(self) -> None:
        rule_id = self._selected_id(self.led_tree)
        rule = next((r for r in self.config.led_rules if r.id == rule_id), None)
        if rule:
            rule.enabled = not rule.enabled
            self._refresh_led_tree(); self.save(); self.engine.request_refresh()

    def _add_mapping(self) -> None:
        if not self.config.panels:
            messagebox.showinfo("Add a panel", "Add a control surface first.")
            return
        mapping = Mapping(panel_id=self.config.panels[0].id)
        if MappingDialog(self.root, mapping, self.config, self.engine.state).show():
            self.config.mappings.append(mapping)
            self._refresh_mapping_tree(); self.save(); self.engine.request_refresh()

    def _edit_mapping(self) -> None:
        mapping_id = self._selected_id(self.mapping_tree)
        mapping = next((m for m in self.config.mappings if m.id == mapping_id), None)
        if mapping and MappingDialog(self.root, mapping, self.config, self.engine.state).show():
            self._refresh_mapping_tree(); self.save(); self.engine.request_refresh()

    def _duplicate_mapping(self) -> None:
        mapping_id = self._selected_id(self.mapping_tree)
        mapping = next((m for m in self.config.mappings if m.id == mapping_id), None)
        if mapping:
            duplicate = deepcopy(mapping)
            duplicate.id = __import__("uuid").uuid4().hex[:8]
            duplicate.name += " copy"
            self.config.mappings.append(duplicate)
            self._refresh_mapping_tree(); self.save()

    def _remove_mapping(self) -> None:
        mapping_id = self._selected_id(self.mapping_tree)
        if mapping_id:
            self.config.mappings = [m for m in self.config.mappings if m.id != mapping_id]
            self._refresh_mapping_tree(); self.save(); self.engine.request_refresh()

    def _toggle_mapping(self) -> None:
        mapping_id = self._selected_id(self.mapping_tree)
        mapping = next((m for m in self.config.mappings if m.id == mapping_id), None)
        if mapping:
            mapping.enabled = not mapping.enabled
            self._refresh_mapping_tree(); self.save(); self.engine.request_refresh()

    def _pump(self) -> None:
        try:
            self.engine.poll_panels()
        except Exception as exc:
            self._append_log("ERROR", str(exc))
        while True:
            try:
                kind, *values = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._append_log(values[0], values[1])
            elif kind == "state":
                self._show_state(values[0])
            elif kind == "panel":
                self.panel_status[values[0]] = values[1]
                self._refresh_panel_tree()
        self.root.after(15, self._pump)

    def _show_state(self, state) -> None:
        self.obs_badge.configure(
            text=(f"OBS {state.obs_version}: connected" if state.connected else "OBS: disconnected"),
            foreground=COLORS["good"] if state.connected else COLORS["bad"],
        )
        self.state_vars["program"].set(state.program_scene or "—")
        self.state_vars["preview"].set(state.preview_scene or "—")
        duration = f" · {state.transition_duration} ms" if state.transition_duration else ""
        self.state_vars["transition"].set((state.current_transition or "—") + duration)
        self.state_vars["studio"].set("On" if state.studio_mode else "Off")
        self.state_vars["recording"].set("Active" if state.recording else "Off")
        self.state_vars["streaming"].set("Active" if state.streaming else "Off")
        self.state_vars["camera"].set("Active" if state.virtual_camera else "Off")
        self.state_vars["replay"].set("Active" if state.replay_buffer else "Off")
        self.state_vars["version"].set(state.obs_version or "—")

    def _append_log(self, level: str, message: str) -> None:
        self.log_text.configure(state="normal")
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"{timestamp}  [{level:<6}] {message}\n", level)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def close(self) -> None:
        try:
            self.save()
            self.engine.stop()
        finally:
            self.root.destroy()


class Modal:
    def __init__(self, parent, title, size="620x500"):
        self.window = tk.Toplevel(parent)
        self.window.title(title); self.window.geometry(size); self.window.transient(parent)
        self.window.grab_set(); self.window.configure(bg=COLORS["bg"])
        self.window.resizable(False, False)
        self.window.bind("<Escape>", lambda _event: self.window.destroy())
        self.window.after_idle(self._center)
        self.result = False

    def _center(self):
        self.window.update_idletasks()
        width, height = self.window.winfo_width(), self.window.winfo_height()
        parent = self.window.master
        if parent and parent.winfo_viewable():
            x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        else:
            x = (self.window.winfo_screenwidth() - width) // 2
            y = (self.window.winfo_screenheight() - height) // 2
        self.window.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.window.lift()

    def show(self):
        self.window.wait_window()
        return self.result


class PanelDialog(Modal):
    def __init__(self, parent, panel: PanelConfig, ports: list[dict]):
        super().__init__(parent, "Panel", "500x330")
        self.panel, self.ports = panel, ports
        body = ttk.Frame(self.window, padding=18); body.pack(fill="both", expand=True)
        self.name = tk.StringVar(value=panel.name)
        self.kind = tk.StringVar(value=panel.device_type)
        current = next((f"{p['port']} — {p['description']} — {p['serial_number']}" for p in ports
                        if p["port"] == panel.port or p["serial_number"] == panel.serial_number), "")
        self.port = tk.StringVar(value=current)
        for row, (label, variable) in enumerate((("Name", self.name), ("Device type", self.kind), ("Serial port", self.port))):
            ttk.Label(body, text=label).grid(row=row * 2, column=0, sticky="w", pady=(8, 2))
            if variable is self.kind:
                widget = ttk.Combobox(body, textvariable=variable, state="readonly", values=list(SURFACE_CLASSES))
            elif variable is self.port:
                widget = ttk.Combobox(body, textvariable=variable, state="readonly",
                                      values=[f"{p['port']} — {p['description']} — {p['serial_number']}" for p in ports])
            else:
                widget = ttk.Entry(body, textvariable=variable)
            widget.grid(row=row * 2 + 1, column=0, sticky="ew")
        body.columnconfigure(0, weight=1)
        ttk.Button(body, text="Cancel", command=self.window.destroy).grid(row=7, column=0, sticky="e", pady=16)
        ttk.Button(body, text="Save", style="Accent.TButton", command=self._save).grid(row=7, column=0, sticky="e", padx=(0, 80), pady=16)

    def _save(self):
        selected = self.port.get().split(" — ", 1)[0]
        info = next((p for p in self.ports if p["port"] == selected), None)
        if not self.name.get().strip() or not info:
            messagebox.showerror("Missing information", "Choose a name and serial port.", parent=self.window); return
        self.panel.name = self.name.get().strip(); self.panel.device_type = self.kind.get()
        self.panel.port = info["port"]; self.panel.serial_number = info["serial_number"]
        self.result = True; self.window.destroy()


class LedRuleDialog(Modal):
    def __init__(self, parent, rule: LedRule, config: AppConfig, state):
        super().__init__(parent, "LED feedback rule", "620x500")
        self.rule, self.config, self.state = rule, config, state
        self.condition_names = {label: key for key, label in LED_CONDITIONS.items()}
        self.panel_names = {panel.name: panel.id for panel in config.panels}
        selected_panel = next((name for name, panel_id in self.panel_names.items()
                               if panel_id == rule.panel_id), next(iter(self.panel_names)))
        self.name = tk.StringVar(value=rule.name)
        self.panel = tk.StringVar(value=selected_panel)
        self.led = tk.StringVar(value=rule.led)
        self.led_choices: dict[str, str] = {}
        self.condition = tk.StringVar(value=LED_CONDITIONS.get(rule.condition, rule.condition))
        self.target_a = tk.StringVar()
        self.target_b = tk.StringVar()
        self.invert = tk.BooleanVar(value=rule.invert)

        body = ttk.Frame(self.window, padding=18); body.pack(fill="both", expand=True)
        for label, variable in (("Rule name", self.name), ("Panel", self.panel),
                                ("Hardware LED", self.led)):
            ttk.Label(body, text=label).pack(anchor="w")
            if variable is self.name:
                widget = ttk.Entry(body, textvariable=variable)
            else:
                widget = ttk.Combobox(body, textvariable=variable, state="readonly")
                if variable is self.panel:
                    widget.configure(values=list(self.panel_names))
                    widget.bind("<<ComboboxSelected>>", lambda _e: self._update_leds())
                    self.panel_box = widget
                else:
                    self.led_box = widget
            widget.pack(fill="x", pady=(3, 12))
        ttk.Label(body, text="Lights when").pack(anchor="w")
        condition_box = ttk.Combobox(body, textvariable=self.condition, state="readonly",
                                     values=list(LED_CONDITIONS.values()))
        condition_box.pack(fill="x", pady=(3, 12))
        condition_box.bind("<<ComboboxSelected>>", lambda _e: self._configure_condition())
        self.a_label = ttk.Label(body)
        self.a_box = ttk.Combobox(body, textvariable=self.target_a, state="readonly")
        self.a_box.bind("<<ComboboxSelected>>", lambda _e: self._update_source_values())
        self.b_label = ttk.Label(body)
        self.b_box = ttk.Combobox(body, textvariable=self.target_b, state="readonly")
        self.invert_box = ttk.Checkbutton(body, text="Invert condition", variable=self.invert)
        self.invert_box.pack(anchor="w")
        self.rule_hint = ttk.Label(
            body, text="If several active rules target the same LED, the LED stays on.",
            style="Muted.TLabel",
        )
        self.rule_hint.pack(anchor="w", pady=(6, 0))
        self.row_led_hint = ttk.Label(
            body,
            text="Entries use the physical label followed by the internal control name in brackets.",
            style="Muted.TLabel", wraplength=570,
        )
        self.row_led_hint.pack(anchor="w", pady=(3, 0))
        footer = ttk.Frame(body, style="Card.TFrame"); footer.pack(side="bottom", fill="x")
        ttk.Button(footer, text="Cancel", command=self.window.destroy).pack(side="right")
        ttk.Button(footer, text="Save rule", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=8)
        self._update_leds()
        self._configure_condition(load=True)

    def _update_leds(self):
        panel_id = self.panel_names.get(self.panel.get())
        panel = next((p for p in self.config.panels if p.id == panel_id), None)
        leds = led_control_names(panel.device_type) if panel else ()
        selected = self.led_choices.get(self.led.get(), self.rule.led)
        self.led_choices = {display_control_name(led): led for led in leds}
        labels = tuple(self.led_choices)
        self.led_box.configure(values=labels)
        matching_label = next((label for label, led in self.led_choices.items()
                               if led == selected), None)
        if matching_label:
            self.led.set(matching_label)
        elif labels:
            self.led.set(labels[0])

    def _configure_condition(self, load=False):
        condition = self.condition_names.get(self.condition.get(), self.rule.condition)
        label_a, values_a, label_b, values_b = "No target required", (), "", ()
        if condition in ("program_scene", "preview_scene"):
            label_a, values_a = "Scene", self.state.scenes
        elif condition == "current_transition":
            label_a, values_a = "Transition", self.state.transitions
        elif condition == "input_muted":
            label_a, values_a = "Input", self.state.inputs
        elif condition == "source_visible":
            label_a, values_a = "Scene", self.state.scenes
            label_b = "Source"
        if not load:
            self.target_a.set(""); self.target_b.set("")
        if load:
            params = self.rule.params
            self.target_a.set(params.get("scene", params.get("transition", params.get("input", ""))))
            self.target_b.set(params.get("source", ""))
        if (values_a and self.target_a.get() not in values_a
                and not (load and self.target_a.get())):
            preferred = (self.state.program_scene if condition in ("program_scene", "source_visible")
                         else self.state.preview_scene if condition == "preview_scene"
                         else self.state.current_transition if condition == "current_transition"
                         else "")
            self.target_a.set(preferred if preferred in values_a else values_a[0])
        self.a_label.configure(text=label_a); self.a_box.configure(values=values_a)
        self.b_label.configure(text=label_b); self.b_box.configure(values=values_b)
        for widget in (self.a_label, self.a_box, self.b_label, self.b_box):
            widget.pack_forget()
        if values_a:
            self.a_label.pack(anchor="w", before=self.invert_box)
            self.a_box.pack(fill="x", pady=(3, 12), before=self.invert_box)
        if condition == "source_visible":
            self._update_source_values()
            self.b_label.pack(anchor="w", before=self.invert_box)
            self.b_box.pack(fill="x", pady=(3, 12), before=self.invert_box)

    def _update_source_values(self):
        condition = self.condition_names.get(self.condition.get(), self.rule.condition)
        if condition != "source_visible":
            return
        sources = tuple(dict.fromkeys(
            source for scene, source, _enabled in self.state.scene_items
            if scene == self.target_a.get()
        ))
        self.b_box.configure(values=sources)
        if self.target_b.get() not in sources:
            self.target_b.set(sources[0] if sources else "")

    def _save(self):
        if not self.name.get().strip() or not self.led.get():
            messagebox.showerror("Incomplete rule", "A name and hardware LED are required.", parent=self.window)
            return
        condition = self.condition_names[self.condition.get()]
        params = {}
        if condition in ("program_scene", "preview_scene", "source_visible"):
            params["scene"] = self.target_a.get()
        elif condition == "current_transition":
            params["transition"] = self.target_a.get()
        elif condition == "input_muted":
            params["input"] = self.target_a.get()
        if condition == "source_visible":
            params["source"] = self.target_b.get()
        if any(not str(value).strip() for value in params.values()):
            messagebox.showerror(
                "Incomplete rule", "Select every target required by this condition.",
                parent=self.window,
            )
            return
        self.rule.name = self.name.get().strip()
        self.rule.panel_id = self.panel_names[self.panel.get()]
        self.rule.led = self.led_choices[self.led.get()]; self.rule.condition = condition
        self.rule.params = params; self.rule.invert = self.invert.get()
        self.result = True; self.window.destroy()


class MappingDialog(Modal):
    def __init__(self, parent, mapping: Mapping, config: AppConfig, obs_state):
        super().__init__(parent, "Mapping", "760x650")
        self.mapping, self.config, self.obs_state = mapping, config, obs_state
        self.actions = deepcopy(mapping.actions)
        body = ttk.Frame(self.window, padding=16); body.pack(fill="both", expand=True)
        self.name = tk.StringVar(value=mapping.name)
        panel_names = {p.name: p.id for p in config.panels}; self.panel_names = panel_names
        selected_panel = next((name for name, pid in panel_names.items() if pid == mapping.panel_id), next(iter(panel_names)))
        self.panel = tk.StringVar(value=selected_panel); self.control = tk.StringVar(value=mapping.control)
        self.control_choices: dict[str, str] = {}
        self.trigger = tk.StringVar(value=mapping.trigger)

        form = ttk.Frame(body, style="Card.TFrame"); form.pack(fill="x")
        for col, (label, variable) in enumerate((("Name", self.name), ("Panel", self.panel),
                                                 ("Control", self.control), ("Trigger", self.trigger))):
            ttk.Label(form, text=label).grid(row=0, column=col, sticky="w")
            if variable is self.panel:
                widget = ttk.Combobox(form, textvariable=variable, state="readonly", values=list(panel_names))
                widget.bind("<<ComboboxSelected>>", lambda _e: self._update_controls())
            elif variable is self.control:
                self.control_box = ttk.Combobox(form, textvariable=variable, state="readonly")
                self.control_box.bind("<<ComboboxSelected>>", lambda _e: self._update_triggers())
                widget = self.control_box
            elif variable is self.trigger:
                self.trigger_box = ttk.Combobox(form, textvariable=variable, state="readonly")
                widget = self.trigger_box
            else:
                widget = ttk.Entry(form, textvariable=variable)
            widget.grid(row=1, column=col, sticky="ew", padx=(0, 8)); form.columnconfigure(col, weight=1)
        self._update_controls()

        action_box = ttk.LabelFrame(body, text="Action sequence", padding=10); action_box.pack(fill="both", expand=True, pady=14)
        self.action_tree = ttk.Treeview(action_box, columns=("action", "parameters", "delay"), show="headings", height=9)
        for col, title, width in (("action", "Action", 220), ("parameters", "Parameters", 330), ("delay", "Delay", 80)):
            self.action_tree.heading(col, text=title); self.action_tree.column(col, width=width, anchor="w")
        self.action_tree.pack(fill="both", expand=True)
        row = ttk.Frame(action_box, style="Card.TFrame"); row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Add", command=self._add_action).pack(side="left")
        ttk.Button(row, text="Edit", command=self._edit_action).pack(side="left", padx=5)
        ttk.Button(row, text="Remove", command=self._remove_action).pack(side="left")
        ttk.Button(row, text="Move up", command=lambda: self._move_action(-1)).pack(side="right")
        ttk.Button(row, text="Move down", command=lambda: self._move_action(1)).pack(side="right", padx=5)
        self._refresh_actions()

        footer = ttk.Frame(body, style="Card.TFrame"); footer.pack(fill="x", pady=(14, 0))
        ttk.Button(footer, text="Cancel", command=self.window.destroy).pack(side="right")
        ttk.Button(footer, text="Save mapping", style="Accent.TButton", command=self._save).pack(side="right", padx=8)

    def _update_controls(self):
        panel_id = self.panel_names.get(self.panel.get())
        panel = next((p for p in self.config.panels if p.id == panel_id), None)
        controls = input_control_names(panel.device_type) if panel else ()
        selected = self.control_choices.get(self.control.get(), self.mapping.control)
        self.control_choices = {display_control_name(control): control for control in controls}
        labels = tuple(self.control_choices)
        self.control_box.configure(values=labels)
        matching_label = next((label for label, control in self.control_choices.items()
                               if control == selected), None)
        if matching_label:
            self.control.set(matching_label)
        elif labels:
            self.control.set(labels[0])
        self._update_triggers()

    def _update_triggers(self):
        panel_id = self.panel_names.get(self.panel.get())
        panel = next((p for p in self.config.panels if p.id == panel_id), None)
        control = self.control_choices.get(self.control.get(), self.control.get())
        triggers = triggers_for_control(panel.device_type, control) if panel else ()
        self.trigger_box.configure(values=triggers)
        if self.trigger.get() not in triggers and triggers:
            self.trigger.set(triggers[0])

    def _refresh_actions(self):
        self.action_tree.delete(*self.action_tree.get_children())
        for index, action in enumerate(self.actions):
            self.action_tree.insert("", "end", iid=str(index), values=(
                ACTION_LABELS.get(action.kind, action.kind),
                describe_action(action), f"{action.delay_ms} ms",
            ))

    def _add_action(self):
        action = ActionSpec("set_preview_scene")
        if ActionDialog(self.window, action, self.obs_state).show():
            self.actions.append(action); self._refresh_actions()

    def _edit_action(self):
        selection = self.action_tree.selection()
        if selection:
            action = self.actions[int(selection[0])]
            if ActionDialog(self.window, action, self.obs_state).show(): self._refresh_actions()

    def _remove_action(self):
        selection = self.action_tree.selection()
        if selection:
            self.actions.pop(int(selection[0])); self._refresh_actions()

    def _move_action(self, direction):
        selection = self.action_tree.selection()
        if not selection: return
        index = int(selection[0]); target = index + direction
        if 0 <= target < len(self.actions):
            self.actions[index], self.actions[target] = self.actions[target], self.actions[index]
            self._refresh_actions(); self.action_tree.selection_set(str(target))

    def _save(self):
        if not self.name.get().strip() or not self.control.get() or not self.trigger.get() or not self.actions:
            messagebox.showerror(
                "Incomplete mapping", "A name, control, valid trigger, and at least one action are required.",
                parent=self.window,
            )
            return
        self.mapping.name = self.name.get().strip(); self.mapping.panel_id = self.panel_names[self.panel.get()]
        self.mapping.control = self.control_choices[self.control.get()]
        self.mapping.trigger = self.trigger.get(); self.mapping.actions = self.actions
        self.result = True; self.window.destroy()


class _LegacyActionDialog(Modal):
    def __init__(self, parent, action: ActionSpec, state):
        super().__init__(parent, "OBS action", "580x500")
        self.action, self.state = action, state
        reverse = {label: kind for kind, label in ACTION_LABELS.items()}; self.reverse = reverse
        self.kind = tk.StringVar(value=ACTION_LABELS.get(action.kind, action.kind))
        self.a = tk.StringVar(); self.b = tk.StringVar(); self.c = tk.StringVar()
        self.delay = tk.StringVar(value=str(action.delay_ms))
        body = ttk.Frame(self.window, padding=18); body.pack(fill="both", expand=True)
        ttk.Label(body, text="Action").pack(anchor="w")
        box = ttk.Combobox(body, textvariable=self.kind, state="readonly", values=list(ACTION_LABELS.values()))
        box.pack(fill="x", pady=(3, 12)); box.bind("<<ComboboxSelected>>", lambda _e: self._configure())
        self.a_label = ttk.Label(body); self.a_label.pack(anchor="w"); self.a_box = ttk.Combobox(body, textvariable=self.a)
        self.a_box.pack(fill="x", pady=(3, 12))
        self.b_label = ttk.Label(body); self.b_label.pack(anchor="w"); self.b_box = ttk.Combobox(body, textvariable=self.b)
        self.b_box.pack(fill="x", pady=(3, 12))
        self.c_label = ttk.Label(body); self.c_label.pack(anchor="w"); self.c_box = ttk.Combobox(body, textvariable=self.c)
        self.c_box.pack(fill="x", pady=(3, 12))
        ttk.Label(body, text="Delay before action (ms)").pack(anchor="w")
        ttk.Entry(body, textvariable=self.delay).pack(fill="x", pady=(3, 12))
        ttk.Label(body, text="For the T-bar, use $event.position as the position.", style="Muted.TLabel").pack(anchor="w")
        footer = ttk.Frame(body, style="Card.TFrame"); footer.pack(side="bottom", fill="x")
        ttk.Button(footer, text="Cancel", command=self.window.destroy).pack(side="right")
        ttk.Button(footer, text="Save action", style="Accent.TButton", command=self._save).pack(side="right", padx=8)
        self._configure(load=True)

    def _configure(self, load=False):
        kind = self.reverse.get(self.kind.get(), self.action.kind)
        label_a, values_a, label_b, values_b = "Parameter", (), "Additional parameter", ()
        label_c, values_c = "", ()
        params = self.action.params if load else {}
        if not load:
            self.a.set(""); self.b.set(""); self.c.set("")
        if kind in ("set_preview_scene", "set_program_scene"):
            label_a, values_a = "Scene", self.state.scenes
            if load: self.a.set(params.get("scene", ""))
        elif kind == "set_transition":
            label_a, values_a = "Transition", self.state.transitions
            if load: self.a.set(params.get("transition", ""))
        elif kind == "set_transition_duration":
            label_a = "Duration (milliseconds)"
            if load: self.a.set(str(params.get("duration_ms", 300)))
        elif kind == "set_tbar_position":
            label_a = "Position (0–1 or $event.position)"
            self.a.set(str(params.get("position", "$event.position")))
        elif kind in ("set_mute", "media_action"):
            label_a, values_a = "OBS input", self.state.inputs
            if load: self.a.set(params.get("input", ""))
            if kind == "set_mute":
                label_b, values_b = "Mode", ("toggle", "on", "off")
                self.b.set(params.get("mode", "toggle"))
            elif kind == "media_action":
                label_b, values_b = "Media operation", ("restart", "play", "pause", "stop", "next", "previous")
                if load: self.b.set(params.get("media_action", "restart").split("_")[-1].lower())
        elif kind == "set_source_visibility":
            label_a, values_a, label_b = "Scene", self.state.scenes, "Source name"
            values_b = self.state.scene_item_names
            label_c, values_c = "Mode", ("toggle", "on", "off")
            if load: self.a.set(params.get("scene", "")); self.b.set(params.get("source", ""))
            self.c.set(params.get("mode", "toggle"))
        elif kind == "set_studio_mode":
            label_a, values_a = "Mode", ("toggle", "on", "off")
            self.a.set(params.get("mode", "toggle"))
        elif kind in ("recording", "streaming", "virtual_camera", "replay_buffer"):
            label_a, values_a = "Mode", ("toggle", "on", "off")
            self.a.set(params.get("mode", "toggle"))
        elif kind == "raw_request":
            label_a, label_b = "Request type", "Request data (JSON object)"
            if load: self.a.set(params.get("request_type", "")); self.b.set(json.dumps(params.get("request_data", {})))
        else:
            label_a = "No parameters"
            if not load: self.a.set("")
        self.a_label.configure(text=label_a); self.a_box.configure(values=values_a)
        self.b_label.configure(text=label_b); self.b_box.configure(values=values_b)
        self.c_label.configure(text=label_c); self.c_box.configure(values=values_c)

    def _save(self):
        try: delay = max(0, int(self.delay.get() or 0))
        except ValueError:
            messagebox.showerror("Invalid delay", "Delay must be a whole number.", parent=self.window); return
        kind = self.reverse[self.kind.get()]; params = {}
        try:
            if kind in ("set_preview_scene", "set_program_scene"): params["scene"] = self.a.get()
            elif kind == "set_transition": params["transition"] = self.a.get()
            elif kind == "set_transition_duration": params["duration_ms"] = int(self.a.get())
            elif kind == "set_tbar_position":
                value = self.a.get(); params["position"] = value if value.startswith("$event.") else float(value)
                params["release"] = "$event.at_endpoint"
            elif kind in ("set_mute", "media_action"):
                params["input"] = self.a.get()
                if kind == "set_mute": params["mode"] = self.b.get()
                elif kind == "media_action": params["media_action"] = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_" + self.b.get().upper()
            elif kind == "set_source_visibility":
                params.update(scene=self.a.get(), source=self.b.get(), mode=self.c.get())
            elif kind == "set_studio_mode": params["mode"] = self.a.get()
            elif kind in ("recording", "streaming", "virtual_camera", "replay_buffer"):
                params["mode"] = self.a.get()
            elif kind == "raw_request":
                params["request_type"] = self.a.get(); params["request_data"] = json.loads(self.b.get() or "{}")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("Invalid action", str(exc), parent=self.window); return
        self.action.kind = kind; self.action.params = params; self.action.delay_ms = delay
        self.result = True; self.window.destroy()


class ActionDialog(Modal):
    """Action editor that renders only the parameters required by an action."""

    MODES = ("toggle", "on", "off")
    MONITORING_MODES = ("toggle", "off", "monitor only", "monitor and output")
    MEDIA_ACTIONS = ("restart", "play", "pause", "stop", "next", "previous")

    def __init__(self, parent, action: ActionSpec, state):
        super().__init__(parent, "OBS action", "600x420")
        self.action, self.state = action, state
        self.reverse = {label: kind for kind, label in ACTION_LABELS.items()}
        self.kind = tk.StringVar(value=ACTION_LABELS.get(action.kind, action.kind))
        self.values = [tk.StringVar() for _ in range(4)]
        self.delay = tk.StringVar(value=str(action.delay_ms))

        body = ttk.Frame(self.window, padding=20); body.pack(fill="both", expand=True)
        ttk.Label(body, text="Action").pack(anchor="w")
        self.kind_box = ttk.Combobox(
            body, textvariable=self.kind, state="readonly",
            values=list(ACTION_LABELS.values()),
        )
        self.kind_box.pack(fill="x", pady=(3, 6))
        self.kind_box.bind("<<ComboboxSelected>>", lambda _e: self._configure())
        self.description = ttk.Label(body, style="Muted.TLabel", wraplength=550)
        self.description.pack(fill="x", pady=(0, 14))

        self.param_frame = ttk.Frame(body)
        self.param_frame.pack(fill="x")
        self.param_rows = []
        for variable in self.values:
            row = ttk.Frame(self.param_frame)
            label = ttk.Label(row)
            box = ttk.Combobox(row, textvariable=variable)
            label.pack(anchor="w")
            box.pack(fill="x", pady=(3, 11))
            self.param_rows.append((row, label, box))
        self.param_rows[0][2].bind(
            "<<ComboboxSelected>>", lambda _e: self._update_source_choices(),
        )

        self.tbar_hint = ttk.Label(
            body, text="$event.position follows the physical T-bar; it is released at either endpoint.",
            style="Muted.TLabel", wraplength=550,
        )
        self.delay_label = ttk.Label(body, text="Delay before action (milliseconds)")
        self.delay_label.pack(anchor="w", pady=(3, 0))
        self.delay_entry = ttk.Entry(body, textvariable=self.delay)
        self.delay_entry.pack(fill="x", pady=(3, 12))

        footer = ttk.Frame(body, style="Card.TFrame"); footer.pack(side="bottom", fill="x")
        ttk.Button(footer, text="Cancel", command=self.window.destroy).pack(side="right")
        ttk.Button(footer, text="Save action", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=8)
        self._configure(load=True)

    def _field(self, index: int, label: str, choices=(), value="", editable=False):
        row, label_widget, box = self.param_rows[index]
        label_widget.configure(text=label)
        box.configure(values=choices, state="normal" if editable else "readonly")
        self.values[index].set(str(value))
        row.pack(fill="x")

    @staticmethod
    def _choice(saved, choices, preferred=""):
        if saved:
            return saved
        if preferred in choices:
            return preferred
        return choices[0] if choices else saved or ""

    def _configure(self, load=False):
        kind = self.reverse.get(self.kind.get(), self.action.kind)
        params = self.action.params if load and kind == self.action.kind else {}
        for row, _label, _box in self.param_rows:
            row.pack_forget()
        self.tbar_hint.pack_forget()
        self.description.configure(text=ACTION_DESCRIPTIONS.get(kind, ""))

        if kind in ("set_preview_scene", "set_program_scene"):
            preferred = self.state.preview_scene if kind == "set_preview_scene" else self.state.program_scene
            self._field(0, "Scene", self.state.scenes,
                        self._choice(params.get("scene"), self.state.scenes, preferred))
        elif kind == "trigger_transition":
            self._field(0, "Destination scene", self.state.scenes,
                        self._choice(params.get("scene"), self.state.scenes,
                                     self.state.preview_scene))
            self._field(1, "Transition", self.state.transitions,
                        self._choice(params.get("transition"), self.state.transitions,
                                     self.state.current_transition))
        elif kind in ("transition_preview", "set_transition"):
            self._field(0, "Transition", self.state.transitions,
                        self._choice(params.get("transition"), self.state.transitions,
                                     self.state.current_transition))
        elif kind == "set_transition_duration":
            self._field(0, "Duration (milliseconds)", value=params.get("duration_ms", 300), editable=True)
        elif kind == "set_tbar_position":
            self._field(0, "Position (0-1 or $event.position)",
                        value=params.get("position", "$event.position"), editable=True)
            self.tbar_hint.pack(fill="x", pady=(0, 10), before=self.delay_label)
        elif kind in ("set_mute", "set_input_volume", "set_input_monitoring", "media_action"):
            self._field(0, "OBS input", self.state.inputs,
                        self._choice(params.get("input"), self.state.inputs))
            if kind == "set_mute":
                self._field(1, "Mode", self.MODES,
                            self._choice(params.get("mode"), self.MODES, "toggle"))
            elif kind == "set_input_volume":
                self._field(1, "Step per dial tick (dB)",
                            value=params.get("step_db", 1), editable=True)
                self._field(2, "Minimum volume (dB)",
                            value=params.get("min_db", -100), editable=True)
                self._field(3, "Maximum volume (dB; 0 = unity gain)",
                            value=params.get("max_db", 0), editable=True)
            elif kind == "set_input_monitoring":
                self._field(1, "Monitoring mode", self.MONITORING_MODES,
                            self._choice(params.get("mode"), self.MONITORING_MODES, "toggle"))
            else:
                saved = params.get("media_action", "").split("_")[-1].lower()
                self._field(1, "Playback action", self.MEDIA_ACTIONS,
                            self._choice(saved, self.MEDIA_ACTIONS, "restart"))
        elif kind == "set_source_visibility":
            scene = self._choice(params.get("scene"), self.state.scenes, self.state.program_scene)
            self._field(0, "Scene", self.state.scenes, scene)
            sources = self._sources_for_scene(scene)
            self._field(1, "Source", sources, self._choice(params.get("source"), sources))
            self._field(2, "Mode", self.MODES,
                        self._choice(params.get("mode"), self.MODES, "toggle"))
        elif kind in ("set_studio_mode", "recording", "streaming", "virtual_camera", "replay_buffer"):
            self._field(0, "Mode", self.MODES,
                        self._choice(params.get("mode"), self.MODES, "toggle"))
        elif kind == "raw_request":
            self._field(0, "Request type", value=params.get("request_type", ""), editable=True)
            self._field(1, "Request data (JSON object)",
                        value=json.dumps(params.get("request_data", {})), editable=True)

        visible = sum(row.winfo_manager() == "pack" for row, _label, _box in self.param_rows)
        self.window.geometry(f"600x{390 + visible * 58}")
        self.window.after_idle(self._center)

    def _sources_for_scene(self, scene_name):
        return tuple(dict.fromkeys(
            source for scene, source, _enabled in self.state.scene_items
            if scene == scene_name
        ))

    def _update_source_choices(self):
        kind = self.reverse.get(self.kind.get(), self.action.kind)
        if kind != "set_source_visibility":
            return
        sources = self._sources_for_scene(self.values[0].get())
        box = self.param_rows[1][2]
        box.configure(values=sources)
        if self.values[1].get() not in sources:
            self.values[1].set(sources[0] if sources else "")

    def _required(self, value: str, label: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{label} is required.")
        return value

    def _save(self):
        try:
            delay = max(0, int(self.delay.get() or 0))
            kind = self.reverse[self.kind.get()]
            a, b, c, d = (value.get() for value in self.values)
            params = {}
            if kind in ("set_preview_scene", "set_program_scene"):
                params["scene"] = self._required(a, "Scene")
            elif kind == "trigger_transition":
                params["scene"] = self._required(a, "Destination scene")
                params["transition"] = self._required(b, "Transition")
            elif kind in ("transition_preview", "set_transition"):
                params["transition"] = self._required(a, "Transition")
            elif kind == "set_transition_duration":
                duration = int(a)
                if duration < 1:
                    raise ValueError("Transition duration must be at least 1 millisecond.")
                params["duration_ms"] = duration
            elif kind == "set_tbar_position":
                value = self._required(a, "T-bar position")
                if value == "$event.position":
                    params["position"] = value
                    params["release"] = "$event.at_endpoint"
                else:
                    position = float(value)
                    if not 0 <= position <= 1:
                        raise ValueError("T-bar position must be between 0 and 1.")
                    params["position"] = position
                    params["release"] = True
            elif kind in ("set_mute", "set_input_volume", "set_input_monitoring", "media_action"):
                params["input"] = self._required(a, "OBS input")
                if kind == "set_mute":
                    params["mode"] = self._required(b, "Mode")
                elif kind == "set_input_volume":
                    step_db = float(self._required(b, "Step per dial tick"))
                    min_db = float(self._required(c, "Minimum volume"))
                    max_db = float(self._required(d, "Maximum volume"))
                    if not 0.01 <= step_db <= 26:
                        raise ValueError("Step per dial tick must be between 0.01 and 26 dB.")
                    if not -100 <= min_db <= 26 or not -100 <= max_db <= 26:
                        raise ValueError("Volume range must stay between -100 and 26 dB.")
                    if min_db > max_db:
                        raise ValueError("Minimum volume cannot be greater than maximum volume.")
                    params.update(mode="relative", step_db=step_db,
                                  min_db=min_db, max_db=max_db)
                elif kind == "set_input_monitoring":
                    params["mode"] = self._required(b, "Monitoring mode")
                else:
                    params["media_action"] = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_" + self._required(b, "Playback action").upper()
            elif kind == "set_source_visibility":
                params = {"scene": self._required(a, "Scene"),
                          "source": self._required(b, "Source"),
                          "mode": self._required(c, "Mode")}
            elif kind in ("set_studio_mode", "recording", "streaming", "virtual_camera", "replay_buffer"):
                params["mode"] = self._required(a, "Mode")
            elif kind == "raw_request":
                params["request_type"] = self._required(a, "Request type")
                request_data = json.loads(b or "{}")
                if not isinstance(request_data, dict):
                    raise ValueError("Request data must be a JSON object.")
                params["request_data"] = request_data
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("Invalid action", str(exc), parent=self.window)
            return
        self.action.kind = kind; self.action.params = params; self.action.delay_ms = delay
        self.result = True; self.window.destroy()
