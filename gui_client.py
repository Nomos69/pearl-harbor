"""Native Tkinter desktop client for Pearl Harbor."""

from __future__ import annotations

import argparse
import math
import os
import queue
import subprocess
import threading
from typing import Any, Callable
from urllib.parse import urlparse

try:
    import tkinter as tk
    from tkinter import messagebox
except ImportError as exc:  # pragma: no cover - depends on the operating system
    raise SystemExit(
        "Tkinter is not installed. On Ubuntu run: sudo apt install python3-tk"
    ) from exc

from game import TEAMS, parse_coordinate
from historical_data import (
    BACKGROUND,
    HISTORICAL_NOTE,
    OPERATION_FACTS,
    SOURCE_LABEL,
    TEAM_DOSSIERS,
    WAR_QUOTES,
)
from naval_icons import NavalIcons
from network_client import NetworkWorker
from launch_host import server_is_ready, start_server, stop_process


COLORS = {
    "background": "#07131f",
    "header": "#091a27",
    "panel": "#0d2230",
    "panel_alt": "#102b3a",
    "line": "#244555",
    "text": "#edf8fb",
    "muted": "#8aa4b4",
    "cyan": "#51e1dc",
    "cyan_dark": "#17454b",
    "orange": "#ff754c",
    "yellow": "#f4c95d",
    "alert": "#d43b36",
    "alert_dark": "#651f21",
    "steel": "#344853",
    "gold": "#d7aa4f",
    "water": "#123142",
    "water_hover": "#1b4c5e",
}

LETTERS = "ABCDEFGHIJ"


class BattleshipGUI:
    def __init__(self, root: tk.Tk, args: argparse.Namespace) -> None:
        self.root = root
        self.args = args
        remote_x11 = bool(os.environ.get("SSH_CONNECTION")) and os.environ.get(
            "DISPLAY", ""
        ).startswith("localhost:")
        self.low_bandwidth = getattr(args, "low_bandwidth", False) or (
            remote_x11 and not getattr(args, "full_graphics", False)
        )
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.worker: NetworkWorker | None = None
        self.server_process: subprocess.Popen[bytes] | None = None
        self.owns_server = False
        self.closing = False
        self.player_name = ""
        self.fleet_spec: dict[str, int] = {}
        self.fleet_assets: dict[str, str] = {}
        self.placements: dict[str, dict[str, Any]] = {}
        self.selected_ship = ""
        self.team_choice = tk.StringVar(value=args.team or "")
        self.orientation = tk.StringVar(value="horizontal")
        self.placement_allowed = False
        self.can_attack = False
        self.latest_state: dict[str, Any] | None = None
        self.latest_event = "Awaiting first strike."
        self.assignment_note = ""
        self.connection_mode = ""
        self.lobby_code = ""
        self.server_uri = args.uri
        parsed_uri = urlparse(args.uri)
        self.host_port = parsed_uri.port or 8765
        self.offset_text = "—"
        self.round_trip_text = "—"
        self.current_screen = ""
        self.quote_index = 0
        self.quote_after_id: str | None = None
        self.quote_text_label: tk.Label | None = None
        self.quote_source_label: tk.Label | None = None
        self.radar_after_id: str | None = None
        self.radar_canvas: tk.Canvas | None = None
        self.radar_status_label: tk.Label | None = None
        self.radar_contacts: list[tuple[int, int, int, float]] = []
        self.radar_sweep_degrees = 35.0
        self.placement_buttons: dict[tuple[int, int], tk.Button] = {}
        self.fleet_button_widgets: dict[str, tk.Button] = {}
        self.game_own_buttons: dict[tuple[int, int], tk.Button] = {}
        self.game_target_buttons: dict[tuple[int, int], tk.Button] = {}
        self.game_turn_status: tk.Label | None = None
        self.game_own_status: tk.Label | None = None
        self.game_target_status: tk.Label | None = None
        self.game_report_label: tk.Label | None = None
        self.game_network_label: tk.Label | None = None

        self.root.title("Pearl Harbor")
        self.root.geometry("1180x780")
        self.root.minsize(940, 680)
        self.root.configure(bg=COLORS["background"])
        self.icons = NavalIcons(root, low_bandwidth=self.low_bandwidth)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._configure_styles()
        self._build_header()
        self.body = tk.Frame(root, bg=COLORS["background"])
        self.body.pack(fill="both", expand=True, padx=34, pady=14)
        self.show_main_menu()
        self.root.after(50, self.poll_messages)

    def _configure_styles(self) -> None:
        self.font_small = ("DejaVu Sans", 9)
        self.font_label = ("DejaVu Sans", 9, "bold")
        self.font_body = ("DejaVu Sans", 11)
        self.font_title = ("DejaVu Sans Condensed", 32, "bold")
        self.font_hero = ("DejaVu Sans Condensed", 46, "bold")
        self.font_mono = ("DejaVu Sans Mono", 9)

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["header"], height=68)
        header.pack(fill="x")
        header.pack_propagate(False)
        logo = tk.Label(
            header,
            text=" PH  PEARL HARBOR",
            bg=COLORS["header"],
            fg=COLORS["alert"],
            font=("DejaVu Sans Mono", 13, "bold"),
        )
        logo.pack(side="left", padx=34)
        tk.Label(
            header,
            text="TACTICAL OPERATIONS NETWORK  •  1941",
            bg=COLORS["header"],
            fg=COLORS["muted"],
            font=("DejaVu Sans Mono", 8),
        ).pack(side="left", padx=12)
        self.connection_label = tk.Label(
            header,
            text="●  OFFLINE",
            bg=COLORS["header"],
            fg=COLORS["muted"],
            font=self.font_label,
        )
        self.connection_label.pack(side="right", padx=34)
        tk.Frame(self.root, bg=COLORS["alert"], height=3).pack(fill="x")

    def clear_body(self) -> None:
        if self.quote_after_id is not None:
            self.root.after_cancel(self.quote_after_id)
            self.quote_after_id = None
        if self.radar_after_id is not None:
            self.root.after_cancel(self.radar_after_id)
            self.radar_after_id = None
        self.quote_text_label = None
        self.quote_source_label = None
        self.radar_canvas = None
        self.radar_status_label = None
        self.radar_contacts = []
        self.placement_buttons = {}
        self.fleet_button_widgets = {}
        self.game_own_buttons = {}
        self.game_target_buttons = {}
        self.game_turn_status = None
        self.game_own_status = None
        self.game_target_status = None
        self.game_report_label = None
        self.game_network_label = None
        for sequence in ("<Return>", "<Escape>", "1", "2", "3", "4"):
            self.root.unbind(sequence)
        for child in self.body.winfo_children():
            child.destroy()

    def make_button(
        self,
        parent: tk.Widget,
        text: str,
        command: Callable[[], None],
        primary: bool = True,
        width: int | None = None,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=COLORS["alert"] if primary else "#17242b",
            fg="#ffffff" if primary else COLORS["text"],
            activebackground=COLORS["alert_dark"],
            activeforeground="#ffffff",
            disabledforeground=COLORS["muted"],
            relief="flat",
            bd=0,
            padx=18,
            pady=12,
            cursor="hand2",
            font=self.font_label,
        )
        if width is not None:
            button.configure(width=width)
        return button

    def section_label(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=parent.cget("bg"),
            fg=COLORS["alert"],
            font=("DejaVu Sans Mono", 8, "bold"),
        )

    def command_button(
        self, parent: tk.Widget, number: str, text: str, command: Callable[[], None]
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=f"{number}   {text}",
            command=command,
            anchor="w",
            bg="#17242b",
            fg=COLORS["text"],
            activebackground=COLORS["alert_dark"],
            activeforeground="#ffffff",
            highlightbackground=COLORS["steel"],
            highlightcolor=COLORS["alert"],
            highlightthickness=1,
            relief="flat",
            bd=0,
            padx=22,
            pady=16,
            cursor="hand2",
            font=("DejaVu Sans Mono", 11, "bold"),
        )
        button.bind(
            "<Enter>",
            lambda _event: button.configure(bg=COLORS["alert_dark"], fg="#ffffff"),
        )
        button.bind(
            "<Leave>",
            lambda _event: button.configure(bg="#17242b", fg=COLORS["text"]),
        )
        return button

    def alert_stripe(self, parent: tk.Widget) -> tk.Frame:
        stripe = tk.Frame(parent, bg=COLORS["panel"], height=8)
        stripe.pack(fill="x")
        stripe.pack_propagate(False)
        for index in range(24):
            tk.Frame(
                stripe,
                bg=COLORS["alert"] if index % 2 == 0 else "#191f22",
            ).pack(side="left", fill="both", expand=True)
        return stripe

    def tactical_backdrop(self) -> None:
        """Place the shared dark command-map artwork behind a screen."""
        if self.low_bandwidth:
            background = tk.Frame(
                self.body,
                bg="#08151c",
                highlightbackground=COLORS["steel"],
                highlightthickness=1,
            )
            background.place(relx=0, rely=0, relwidth=1, relheight=1)
            return
        backdrop = self.icons.command_map(1110, 650)
        background = tk.Label(
            self.body,
            image=backdrop,
            bg=COLORS["background"],
            bd=0,
        )
        background.image = backdrop
        background.place(relx=0, rely=0, relwidth=1, relheight=1)

    def status_plate(
        self,
        parent: tk.Widget,
        text: str,
        active: bool = False,
    ) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=COLORS["alert_dark"] if active else "#17242b",
            fg="#ffffff" if active else COLORS["muted"],
            highlightbackground=COLORS["alert"] if active else COLORS["steel"],
            highlightthickness=1,
            padx=15,
            pady=9,
            font=("DejaVu Sans Mono", 9, "bold"),
        )

    def show_main_menu(self) -> None:
        self.current_screen = "main_menu"
        self.clear_body()
        self.tactical_backdrop()

        title_panel = tk.Frame(self.body, bg="#09161d", padx=30, pady=25)
        title_panel.place(relx=0.035, rely=0.12, relwidth=0.55)
        tk.Label(
            title_panel,
            text="PACIFIC COMMAND // PRIORITY ONE",
            bg="#09161d",
            fg=COLORS["alert"],
            font=("DejaVu Sans Mono", 9, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_panel,
            text="PEARL HARBOR",
            bg="#09161d",
            fg="#f5f0e7",
            font=("DejaVu Sans Condensed", 43, "bold"),
        ).pack(anchor="w", pady=(7, 0))
        tk.Label(
            title_panel,
            text="DECEMBER 7, 1941  //  OAHU",
            bg="#09161d",
            fg=COLORS["gold"],
            font=("DejaVu Sans Mono", 11, "bold"),
        ).pack(anchor="w", pady=(2, 13))
        tk.Label(
            title_panel,
            text="A two-command WebSocket engagement\nover the waters of Oahu.",
            justify="left",
            bg="#09161d",
            fg=COLORS["muted"],
            font=self.font_body,
        ).pack(anchor="w")
        factions = tk.Frame(title_panel, bg="#09161d")
        factions.pack(anchor="w", pady=(16, 0))
        for team, label in (("US", "UNITED STATES"), ("Japan", "JAPAN")):
            unit = tk.Frame(factions, bg="#111f24", padx=7, pady=5)
            unit.pack(side="left", padx=(0, 10))
            flag = self.icons.team_flag(team, 58, 34, False)
            flag_label = tk.Label(unit, image=flag, bg="#111f24", bd=0)
            flag_label.image = flag
            flag_label.pack(side="left", padx=(0, 7))
            tk.Label(
                unit,
                text=label,
                bg="#111f24",
                fg=COLORS["text"],
                font=("DejaVu Sans Mono", 7, "bold"),
            ).pack(side="left")

        menu = tk.Frame(
            self.body,
            bg=COLORS["panel"],
            highlightbackground=COLORS["steel"],
            highlightthickness=2,
        )
        menu.place(relx=0.64, rely=0.10, relwidth=0.32, relheight=0.76)
        self.alert_stripe(menu)
        inner = tk.Frame(menu, bg=COLORS["panel"], padx=22, pady=20)
        inner.pack(fill="both", expand=True)
        tk.Label(
            inner,
            text="OPERATION MENU",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("DejaVu Sans Mono", 15, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            inner,
            text="SELECT COMMAND",
            bg=COLORS["panel"],
            fg=COLORS["alert"],
            font=("DejaVu Sans Mono", 8, "bold"),
        ).pack(anchor="w", pady=(0, 22))
        self.command_button(inner, "[01]", "HOST OPERATION", self.show_briefing).pack(fill="x", pady=5)
        self.command_button(inner, "[02]", "JOIN OPERATION", self.show_join_setup).pack(fill="x", pady=5)
        self.command_button(inner, "[03]", "MISSION DOSSIER", self.show_briefing).pack(fill="x", pady=5)
        self.command_button(inner, "[04]", "EXIT TO DESKTOP", self.on_close).pack(fill="x", pady=5)
        tk.Frame(inner, bg=COLORS["line"], height=1).pack(fill="x", pady=(24, 13))
        tk.Label(
            inner,
            text="SYSTEM: READY\nNETWORK: WEBSOCKET\nTHEATER: OAHU",
            justify="left",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=("DejaVu Sans Mono", 8),
        ).pack(anchor="w")

        tk.Label(
            self.body,
            text="HISTORICALLY INSPIRED • BALANCED GAMEPLAY • NOT A LITERAL SIMULATION",
            bg="#09161d",
            fg=COLORS["muted"],
            font=("DejaVu Sans Mono", 8),
            padx=14,
            pady=7,
        ).place(relx=0.035, rely=0.88)
        self.root.bind("1", lambda _event: self.show_briefing())
        self.root.bind("2", lambda _event: self.show_join_setup())
        self.root.bind("3", lambda _event: self.show_briefing())
        self.root.bind("4", lambda _event: self.on_close())
        self.root.bind("<Return>", lambda _event: self.show_briefing())

    def show_briefing(self) -> None:
        self.current_screen = "briefing"
        self.clear_body()
        self.tactical_backdrop()
        shell = tk.Frame(
            self.body,
            bg="#101b20",
            highlightbackground=COLORS["steel"],
            highlightthickness=3,
        )
        shell.place(relx=.5, rely=.5, anchor="center", relwidth=.97, relheight=.97)
        self.alert_stripe(shell)
        content = tk.Frame(shell, bg="#101b20", padx=18, pady=8)
        content.pack(fill="both", expand=True)

        heading = tk.Frame(content, bg="#101b20")
        heading.pack(fill="x")
        title = tk.Frame(heading, bg="#101b20")
        title.pack(side="left")
        tk.Label(
            title,
            text="DECLASSIFIED HISTORICAL INTELLIGENCE",
            bg="#101b20",
            fg=COLORS["alert"],
            font=("DejaVu Sans Mono", 8, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title,
            text="PEARL HARBOR // OPERATION DOSSIER",
            bg="#101b20",
            fg=COLORS["text"],
            font=("DejaVu Sans Condensed", 25, "bold"),
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(
            heading,
            text="READ DOSSIERS // SELECT A COUNTRY BELOW",
            bg=COLORS["alert_dark"],
            fg="#ffffff",
            font=("DejaVu Sans Mono", 9, "bold"),
            padx=14,
            pady=9,
        ).pack(side="right", pady=5)

        facts = tk.Frame(content, bg="#101b20")
        facts.pack(fill="x", pady=(10, 8))
        for index, (label, value) in enumerate(OPERATION_FACTS):
            fact = tk.Frame(
                facts,
                bg="#15242a",
                highlightbackground=COLORS["steel"],
                highlightthickness=1,
                padx=8,
                pady=5,
            )
            fact.grid(
                row=index // 3,
                column=index % 3,
                sticky="nsew",
                padx=(0, 6) if index % 3 < 2 else 0,
                pady=(0, 5) if index < 3 else 0,
            )
            facts.columnconfigure(index % 3, weight=1)
            tk.Label(fact, text=label, bg="#15242a", fg=COLORS["alert"], font=("DejaVu Sans Mono", 7, "bold")).pack(anchor="w")
            tk.Label(fact, text=value, bg="#15242a", fg="#d7e0e3", font=("DejaVu Sans", 8), wraplength=310, justify="left").pack(anchor="w")

        tk.Label(
            content,
            text=BACKGROUND,
            bg="#101b20",
            fg="#b6c3c7",
            font=("DejaVu Sans", 9),
            wraplength=1010,
            justify="left",
        ).pack(fill="x", pady=(0, 8))

        dossiers = tk.Frame(content, bg="#101b20")
        dossiers.pack(fill="both", expand=True)
        dossiers.columnconfigure(0, weight=1)
        dossiers.columnconfigure(1, weight=1)
        self.historical_dossier(dossiers, "US", 0)
        self.historical_dossier(dossiers, "Japan", 1)

        footer = tk.Frame(content, bg="#101b20")
        footer.pack(fill="x", pady=(8, 0))
        notes = tk.Frame(footer, bg="#101b20")
        notes.pack(side="left", fill="x", expand=True)
        tk.Label(
            notes,
            text=HISTORICAL_NOTE,
            bg="#101b20",
            fg=COLORS["gold"],
            font=("DejaVu Sans Mono", 7, "bold"),
            wraplength=600,
            justify="left",
        ).pack(anchor="w")
        tk.Label(
            notes,
            text=SOURCE_LABEL,
            bg="#101b20",
            fg=COLORS["muted"],
            font=("DejaVu Sans", 7),
            wraplength=600,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))
        chosen_team = self.team_choice.get()
        proceed = self.make_button(
            footer,
            f"CONTINUE WITH {chosen_team.upper()}  →"
            if chosen_team in TEAMS
            else "SELECT A COUNTRY TO CONTINUE",
            self.show_host_setup,
        )
        proceed.configure(state="normal" if chosen_team in TEAMS else "disabled")
        proceed.pack(side="right", padx=(12, 0))
        self.make_button(
            footer,
            "RETURN",
            self.show_main_menu,
            primary=False,
        ).pack(side="right")
        self.root.bind("<Escape>", lambda _event: self.show_main_menu())
        if chosen_team in TEAMS:
            self.root.bind("<Return>", lambda _event: self.show_host_setup())

    def historical_dossier(
        self,
        parent: tk.Widget,
        team: str,
        column: int,
    ) -> None:
        data = TEAM_DOSSIERS[team]
        selected = self.team_choice.get() == team
        panel = tk.Frame(
            parent,
            bg=COLORS["panel"],
            highlightbackground=(
                COLORS["gold"]
                if selected
                else COLORS["cyan"] if team == "US" else COLORS["alert"]
            ),
            highlightthickness=4 if selected else 2,
            padx=13,
            pady=10,
        )
        panel.grid(
            row=0,
            column=column,
            sticky="nsew",
            padx=(0, 5) if column == 0 else (5, 0),
        )
        header = tk.Frame(panel, bg=COLORS["panel"])
        header.pack(fill="x", pady=(0, 7))
        flag = self.icons.team_flag(team, 68, 40, selected)
        flag_label = tk.Label(header, image=flag, bg=COLORS["panel"], bd=0)
        flag_label.image = flag
        flag_label.pack(side="left", padx=(0, 10))
        tk.Label(
            header,
            text="UNITED STATES // DEFENDER" if team == "US" else "JAPAN // ATTACK FORCE",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("DejaVu Sans Mono", 10, "bold"),
        ).pack(side="left")
        tk.Button(
            header,
            text="✓ SELECTED" if selected else "SELECT",
            command=lambda: self.select_dossier_team(team),
            bg=COLORS["gold"] if selected else "#17242b",
            fg="#111111" if selected else COLORS["text"],
            activebackground=COLORS["alert"],
            activeforeground="#ffffff",
            highlightbackground=COLORS["gold"] if selected else COLORS["steel"],
            highlightthickness=1,
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
            font=("DejaVu Sans Mono", 8, "bold"),
        ).pack(side="right")

        government = "\n".join(str(value) for value in data["government"])
        tk.Label(
            panel,
            text=government,
            bg=COLORS["panel"],
            fg="#b9c7cb",
            font=("DejaVu Sans", 8),
            justify="left",
        ).pack(anchor="w")
        tk.Label(
            panel,
            text=str(data["fleet_note"]).upper(),
            bg=COLORS["panel"],
            fg=COLORS["gold"],
            font=("DejaVu Sans Mono", 7, "bold"),
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(7, 3))
        for name, fact in data["ships"]:
            row = tk.Frame(panel, bg="#142630", padx=7, pady=2)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=str(name), width=22, anchor="w", bg="#142630", fg=COLORS["text"], font=("DejaVu Sans Mono", 7, "bold")).pack(side="left")
            tk.Label(row, text=str(fact), anchor="w", bg="#142630", fg=COLORS["muted"], font=("DejaVu Sans", 7), wraplength=270, justify="left").pack(side="left", fill="x", expand=True)
        tk.Label(
            panel,
            text=str(data["historical_note"]),
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=("DejaVu Sans", 7, "italic"),
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(5, 0))

    def select_dossier_team(self, team: str) -> None:
        self.team_choice.set(team)
        self.show_briefing()

    def show_host_setup(self) -> None:
        if self.team_choice.get() not in TEAMS:
            self.show_briefing()
            return
        self.current_screen = "connect"
        self.clear_body()
        self.tactical_backdrop()
        shell = tk.Frame(
            self.body,
            bg="#111b20",
            highlightbackground="#52626a",
            highlightthickness=3,
        )
        shell.place(relx=.5, rely=.5, anchor="center", relwidth=.94, relheight=.91)
        self.alert_stripe(shell)
        layout = tk.Frame(shell, bg="#111b20", padx=12, pady=12)
        layout.pack(fill="both", expand=True)
        layout.columnconfigure(0, weight=5)
        layout.columnconfigure(1, weight=4)
        layout.rowconfigure(0, weight=1)

        hero = tk.Frame(
            layout,
            bg="#091419",
            padx=30,
            pady=28,
            highlightbackground=COLORS["steel"],
            highlightthickness=2,
        )
        hero.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        tk.Label(
            hero,
            text="// SECURE PACIFIC OPERATIONS TERMINAL //",
            bg="#091419",
            fg=COLORS["alert"],
            font=("DejaVu Sans Mono", 9, "bold"),
        ).pack(anchor="w")
        tk.Frame(hero, bg=COLORS["alert"], height=4).pack(fill="x", pady=(11, 28))
        tk.Label(
            hero,
            text="HOST NEW\nOPERATION",
            justify="left",
            bg="#091419",
            fg="#f1eee6",
            font=("DejaVu Sans Condensed", 38, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hero,
            text="OPERATION  PH-41",
            bg=COLORS["alert_dark"],
            fg="#ffffff",
            font=("DejaVu Sans Mono", 11, "bold"),
            padx=14,
            pady=7,
        ).pack(anchor="w", pady=(18, 22))
        tk.Label(
            hero,
            text=(
                "HOST  //  Selects the first national command\n"
                "GUEST //  Receives the opposing command\n\n"
                "Create a lobby directly on the operation server.\n"
                "Share only the lobby code with your opponent."
            ),
            justify="left",
            bg="#091419",
            fg="#aab8bd",
            font=("DejaVu Sans Mono", 10),
        ).pack(anchor="w")
        diagnostic = tk.Frame(hero, bg="#131f24", highlightbackground=COLORS["steel"], highlightthickness=1)
        diagnostic.pack(side="bottom", fill="x")
        for label, value in (
            ("NETWORK", "WEBSOCKET"),
            ("THEATER", "OAHU"),
            ("HOST ACCESS", "DIRECT"),
        ):
            row = tk.Frame(diagnostic, bg="#131f24", padx=12, pady=5)
            row.pack(fill="x")
            tk.Label(row, text=label, width=12, anchor="w", bg="#131f24", fg=COLORS["muted"], font=("DejaVu Sans Mono", 8)).pack(side="left")
            tk.Label(row, text=value, bg="#131f24", fg=COLORS["cyan"], font=("DejaVu Sans Mono", 8, "bold")).pack(side="right")

        card = tk.Frame(layout, bg=COLORS["panel"], highlightbackground=COLORS["alert"], highlightthickness=2)
        card.grid(row=0, column=1, sticky="nsew")
        inner = tk.Frame(card, bg=COLORS["panel"])
        inner.pack(fill="both", expand=True, padx=22, pady=18)
        tk.Label(inner, text="HOST CONTROL", bg=COLORS["panel"], fg=COLORS["alert"], font=("DejaVu Sans Mono", 9, "bold")).pack(anchor="w")
        tk.Label(
            inner,
            text="CREATE MULTIPLAYER LOBBY",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("DejaVu Sans Condensed", 25, "bold"),
        ).pack(anchor="w", pady=(3, 10))

        selected_team = self.team_choice.get()
        selection = tk.Frame(
            inner,
            bg="#17242b",
            highlightbackground=COLORS["gold"],
            highlightthickness=2,
            padx=12,
            pady=9,
        )
        selection.pack(fill="x", pady=(0, 2))
        flag = self.icons.team_flag(selected_team, 86, 50, True)
        flag_label = tk.Label(selection, image=flag, bg="#17242b", bd=0)
        flag_label.image = flag
        flag_label.pack(side="left", padx=(0, 12))
        tk.Label(
            selection,
            text=f"REQUESTED COMMAND\n{selected_team.upper()}",
            justify="left",
            bg="#17242b",
            fg=COLORS["text"],
            font=("DejaVu Sans Mono", 10, "bold"),
        ).pack(side="left")
        tk.Button(
            selection,
            text="CHANGE",
            command=self.show_briefing,
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            activebackground=COLORS["alert_dark"],
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=9,
            pady=5,
            cursor="hand2",
            font=("DejaVu Sans Mono", 7, "bold"),
        ).pack(side="right")
        self.host_port_entry = self._labeled_entry(
            inner, "LOCAL SERVER PORT", str(self.host_port)
        )
        tk.Label(
            inner,
            text=(
                "THIS MACHINE BECOMES SERVER + PLAYER // NO HOST KEY REQUIRED\n"
                "SERVER GENERATES A SHAREABLE 6-CHARACTER CODE."
            ),
            bg=COLORS["panel"],
            fg=COLORS["gold"],
            font=("DejaVu Sans Mono", 7, "bold"),
            justify="left",
        ).pack(anchor="w", pady=(8, 0))
        self.connect_button = self.make_button(
            inner, "CREATE LOBBY  →", self.host_lobby
        )
        self.connect_button.configure(
            bg=COLORS["alert"],
            fg="#ffffff",
            activebackground=COLORS["alert_dark"],
            activeforeground="#ffffff",
        )
        self.connect_button.pack(fill="x", pady=(14, 0))
        self.command_button(inner, "[ESC]", "RETURN TO COUNTRY DOSSIERS", self.show_briefing).pack(fill="x", pady=(7, 0))
        self.root.bind("<Return>", lambda _event: self.host_lobby())
        self.root.bind("<Escape>", lambda _event: self.show_briefing())

    def show_join_setup(self) -> None:
        self.current_screen = "join_setup"
        self.clear_body()
        self.tactical_backdrop()
        shell = tk.Frame(
            self.body,
            bg="#111b20",
            highlightbackground="#52626a",
            highlightthickness=3,
        )
        shell.place(relx=.5, rely=.5, anchor="center", relwidth=.94, relheight=.91)
        self.alert_stripe(shell)
        layout = tk.Frame(shell, bg="#111b20", padx=12, pady=12)
        layout.pack(fill="both", expand=True)
        layout.columnconfigure(0, weight=5)
        layout.columnconfigure(1, weight=4)
        layout.rowconfigure(0, weight=1)

        hero = tk.Frame(
            layout,
            bg="#091419",
            padx=30,
            pady=28,
            highlightbackground=COLORS["steel"],
            highlightthickness=2,
        )
        hero.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        tk.Label(
            hero,
            text="// INCOMING FIELD COMMAND //",
            bg="#091419",
            fg=COLORS["alert"],
            font=("DejaVu Sans Mono", 9, "bold"),
        ).pack(anchor="w")
        tk.Frame(hero, bg=COLORS["alert"], height=4).pack(fill="x", pady=(11, 28))
        tk.Label(
            hero,
            text="JOIN ACTIVE\nOPERATION",
            justify="left",
            bg="#091419",
            fg="#f1eee6",
            font=("DejaVu Sans Condensed", 38, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hero,
            text="LOBBY INTERCEPT  //  PH-41",
            bg=COLORS["alert_dark"],
            fg="#ffffff",
            font=("DejaVu Sans Mono", 11, "bold"),
            padx=14,
            pady=7,
        ).pack(anchor="w", pady=(18, 22))
        tk.Label(
            hero,
            text=(
                "Enter the six-character code transmitted by the host.\n\n"
                "COUNTRY ASSIGNMENT // AUTOMATIC\n"
                "Japan host  →  You command the United States\n"
                "US host     →  You command Japan"
            ),
            justify="left",
            bg="#091419",
            fg="#aab8bd",
            font=("DejaVu Sans Mono", 10),
            wraplength=510,
        ).pack(anchor="w")
        diagnostic = tk.Frame(
            hero,
            bg="#131f24",
            highlightbackground=COLORS["steel"],
            highlightthickness=1,
        )
        diagnostic.pack(side="bottom", fill="x")
        for label, value in (
            ("ROLE", "GUEST COMMANDER"),
            ("FACTION", "SERVER ASSIGNED"),
            ("AUTH", "LOBBY CODE"),
        ):
            row = tk.Frame(diagnostic, bg="#131f24", padx=12, pady=5)
            row.pack(fill="x")
            tk.Label(
                row,
                text=label,
                width=12,
                anchor="w",
                bg="#131f24",
                fg=COLORS["muted"],
                font=("DejaVu Sans Mono", 8),
            ).pack(side="left")
            tk.Label(
                row,
                text=value,
                bg="#131f24",
                fg=COLORS["cyan"],
                font=("DejaVu Sans Mono", 8, "bold"),
            ).pack(side="right")

        card = tk.Frame(
            layout,
            bg=COLORS["panel"],
            highlightbackground=COLORS["alert"],
            highlightthickness=2,
        )
        card.grid(row=0, column=1, sticky="nsew")
        inner = tk.Frame(card, bg=COLORS["panel"])
        inner.pack(fill="both", expand=True, padx=24, pady=23)
        tk.Label(
            inner,
            text="REMOTE COMMAND LINK",
            bg=COLORS["panel"],
            fg=COLORS["alert"],
            font=("DejaVu Sans Mono", 9, "bold"),
        ).pack(anchor="w")
        tk.Label(
            inner,
            text="ENTER LOBBY CODE",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("DejaVu Sans Condensed", 25, "bold"),
        ).pack(anchor="w", pady=(3, 14))
        self.lobby_code_entry = self._labeled_entry(
            inner, "OPERATION CODE", self.lobby_code
        )
        self.join_uri_entry = self._labeled_entry(
            inner, "SERVER WEBSOCKET ADDRESS", self.server_uri
        )
        tk.Label(
            inner,
            text="NO COUNTRY SELECTION REQUIRED // OPPOSING FLEET ASSIGNED",
            bg=COLORS["panel"],
            fg=COLORS["gold"],
            font=("DejaVu Sans Mono", 7, "bold"),
            wraplength=380,
            justify="left",
        ).pack(anchor="w", pady=(12, 0))
        self.join_button = self.make_button(
            inner, "JOIN HOSTED LOBBY  →", self.join_lobby
        )
        self.join_button.pack(fill="x", pady=(20, 0))
        self.command_button(
            inner, "[ESC]", "RETURN TO OPERATION MENU", self.show_main_menu
        ).pack(fill="x", pady=(7, 0))
        self.lobby_code_entry.focus_set()
        self.root.bind("<Return>", lambda _event: self.join_lobby())
        self.root.bind("<Escape>", lambda _event: self.show_main_menu())

    def _labeled_entry(self, parent: tk.Widget, label: str, value: str, show: str = "") -> tk.Entry:
        tk.Label(parent, text=label, bg=COLORS["panel"], fg=COLORS["muted"], font=self.font_label).pack(anchor="w", pady=(13, 6))
        entry = tk.Entry(
            parent,
            bg="#071821",
            fg=COLORS["text"],
            insertbackground=COLORS["cyan"],
            relief="flat",
            highlightbackground=COLORS["line"],
            highlightcolor=COLORS["cyan"],
            highlightthickness=1,
            font=self.font_body,
            show=show,
        )
        entry.insert(0, value)
        entry.pack(fill="x", ipady=10)
        return entry

    def host_lobby(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        preferred_team = self.team_choice.get()
        port_text = self.host_port_entry.get().strip()
        if preferred_team not in TEAMS or not port_text:
            messagebox.showwarning(
                "Missing information",
                "Choose US or Japan and enter a local server port.",
            )
            return
        try:
            port = int(port_text)
        except ValueError:
            messagebox.showwarning("Invalid port", "The server port must be a number.")
            return
        if not 1 <= port <= 65535:
            messagebox.showwarning(
                "Invalid port", "The server port must be between 1 and 65535."
            )
            return
        self.connect_button.configure(state="disabled", text="STARTING SERVER…")
        self.connection_label.configure(text="●  STARTING HOST", fg=COLORS["yellow"])
        self.connection_mode = "host"
        self.host_port = port
        self.server_uri = f"ws://127.0.0.1:{port}/ws"
        self.lobby_code = ""
        self.player_name = ""
        self.show_lobby(
            "Starting local operation server",
            "This command station is becoming the server and preparing its player link.",
        )
        threading.Thread(
            target=self._prepare_host_server,
            args=(port, preferred_team),
            daemon=True,
        ).start()

    def _prepare_host_server(self, port: int, preferred_team: str) -> None:
        process: subprocess.Popen[bytes] | None = None
        reused_server = False
        try:
            if server_is_ready(port):
                reused_server = True
            else:
                process = start_server(
                    argparse.Namespace(
                        listen_host="0.0.0.0",
                        port=port,
                        startup_timeout=5.0,
                    )
                )
            if self.closing:
                if process is not None:
                    stop_process(process)
                return
            self.messages.put(
                {
                    "type": "local_server_ready",
                    "port": port,
                    "preferred_team": preferred_team,
                    "process": process,
                    "reused_server": reused_server,
                }
            )
        except (OSError, RuntimeError) as exc:
            self.messages.put(
                {
                    "type": "local_server_error",
                    "message": str(exc),
                }
            )

    def join_lobby(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        lobby_code = self.lobby_code_entry.get().strip().upper()
        uri = self.join_uri_entry.get().strip()
        if not lobby_code or not uri:
            messagebox.showwarning(
                "Missing information", "Enter the host's lobby code and server address."
            )
            return
        if not uri.startswith(("ws://", "wss://")):
            messagebox.showwarning(
                "Invalid address", "The server address must begin with ws:// or wss://"
            )
            return
        self.join_button.configure(state="disabled", text="CONNECTING…")
        self.connection_label.configure(text="●  CONNECTING", fg=COLORS["yellow"])
        self.connection_mode = "join"
        self.server_uri = uri
        self.lobby_code = lobby_code
        self.player_name = ""
        self.worker = NetworkWorker(
            uri,
            self.messages,
            mode="join",
            lobby_code=lobby_code,
        )
        self.worker.start()
        self.show_lobby(
            "Locating hosted operation",
            f"Requesting entry to lobby {lobby_code} and synchronizing clocks.",
        )

    def loading_quote_panel(self, parent: tk.Widget) -> None:
        quote_panel = tk.Frame(
            parent,
            bg="#07161a",
            highlightbackground=COLORS["steel"],
            highlightthickness=1,
            padx=11,
            pady=8,
        )
        quote_panel.pack(fill="x", pady=(12, 0))
        tk.Label(
            quote_panel,
            text="HISTORICAL SIGNAL // QUOTATION ROTATION 03 SEC",
            bg="#07161a",
            fg=COLORS["alert"],
            font=("DejaVu Sans Mono", 7, "bold"),
        ).pack(anchor="w")
        self.quote_text_label = tk.Label(
            quote_panel,
            text="",
            bg="#07161a",
            fg="#edf1e9",
            font=("DejaVu Sans", 9, "italic"),
            wraplength=420,
            justify="left",
        )
        self.quote_text_label.pack(anchor="w", pady=(4, 2))
        self.quote_source_label = tk.Label(
            quote_panel,
            text="",
            bg="#07161a",
            fg=COLORS["gold"],
            font=("DejaVu Sans Mono", 7, "bold"),
            wraplength=420,
            justify="left",
        )
        self.quote_source_label.pack(anchor="w")
        self.rotate_loading_quote()

    def rotate_loading_quote(self) -> None:
        if (
            self.current_screen != "lobby"
            or self.quote_text_label is None
            or self.quote_source_label is None
            or not self.quote_text_label.winfo_exists()
        ):
            self.quote_after_id = None
            return
        quote, speaker, context = WAR_QUOTES[self.quote_index % len(WAR_QUOTES)]
        self.quote_text_label.configure(text=f'“{quote}”')
        self.quote_source_label.configure(text=f"— {speaker} // {context}")
        self.quote_index = (self.quote_index + 1) % len(WAR_QUOTES)
        self.quote_after_id = self.root.after(3000, self.rotate_loading_quote)

    def show_lobby(self, title: str, message: str) -> None:
        self.current_screen = "lobby"
        self.clear_body()
        self.tactical_backdrop()
        panel = tk.Frame(
            self.body,
            bg=COLORS["panel"],
            highlightbackground=COLORS["steel"],
            highlightthickness=2,
        )
        panel.place(relx=.5, rely=.5, anchor="center", relwidth=.80, relheight=.82)
        self.alert_stripe(panel)
        layout = tk.Frame(panel, bg=COLORS["panel"], padx=30, pady=22)
        layout.pack(fill="both", expand=True)

        radar_panel = tk.Frame(
            layout,
            bg="#07161a",
            highlightbackground=COLORS["alert"],
            highlightthickness=1,
            padx=18,
            pady=18,
        )
        radar_panel.pack(side="left", fill="y", padx=(0, 30))
        tk.Label(
            radar_panel,
            text="PACIFIC RADAR // OAHU",
            bg="#07161a",
            fg=COLORS["alert"],
            font=self.font_mono,
        ).pack()
        radar = tk.Canvas(
            radar_panel,
            width=220,
            height=220,
            bg="#061416",
            highlightthickness=0,
        )
        radar.pack(pady=(16, 8))
        for margin in (8, 43, 78):
            radar.create_oval(
                margin,
                margin,
                220 - margin,
                220 - margin,
                outline=COLORS["steel"],
            )
        radar.create_line(110, 8, 110, 212, fill=COLORS["steel"])
        radar.create_line(8, 110, 212, 110, fill=COLORS["steel"])
        self.radar_canvas = radar
        self.radar_contacts = []
        for x, y in ((175, 51), (74, 82), (151, 158)):
            angle = math.degrees(math.atan2(110 - y, x - 110)) % 360
            contact = radar.create_oval(
                x - 3,
                y - 3,
                x + 3,
                y + 3,
                fill=COLORS["cyan_dark"],
                outline=COLORS["cyan"],
            )
            self.radar_contacts.append((contact, x, y, angle))
        self.radar_status_label = tk.Label(
            radar_panel,
            text="SCAN 000°  //  INITIALIZING",
            bg="#07161a",
            fg=COLORS["cyan"],
            font=("DejaVu Sans Mono", 8, "bold"),
        )
        self.radar_status_label.pack()
        self.animate_lobby_radar()

        briefing = tk.Frame(layout, bg=COLORS["panel"])
        briefing.pack(side="left", fill="both", expand=True, pady=10)
        self.section_label(briefing, "COMMAND STATUS // STANDBY").pack(anchor="w")
        identity = tk.Frame(briefing, bg=COLORS["panel"])
        identity.pack(anchor="w", fill="x", pady=(14, 8))
        if self.player_name in TEAMS:
            flag = self.icons.team_flag(self.player_name, 76, 44, True)
            flag_label = tk.Label(identity, image=flag, bg=COLORS["panel"], bd=0)
            flag_label.image = flag
            flag_label.pack(side="left", padx=(0, 14))
        tk.Label(
            identity,
            text=title.upper(),
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("DejaVu Sans Condensed", 25, "bold"),
            wraplength=340,
            justify="left",
        ).pack(side="left", anchor="w")
        tk.Frame(briefing, bg=COLORS["alert"], height=3).pack(fill="x", pady=(0, 16))
        self.lobby_message = tk.Label(
            briefing,
            text=message,
            bg=COLORS["panel"],
            fg="#c8d3d6",
            font=self.font_body,
            wraplength=430,
            justify="left",
        )
        self.lobby_message.pack(anchor="w")
        if self.lobby_code:
            code_panel = tk.Frame(
                briefing,
                bg="#071821",
                highlightbackground=COLORS["gold"],
                highlightthickness=2,
                padx=14,
                pady=9,
            )
            code_panel.pack(anchor="w", fill="x", pady=(14, 0))
            tk.Label(
                code_panel,
                text="LOBBY CODE",
                bg="#071821",
                fg=COLORS["muted"],
                font=("DejaVu Sans Mono", 8, "bold"),
            ).pack(side="left")
            tk.Label(
                code_panel,
                text=self.lobby_code,
                bg="#071821",
                fg=COLORS["gold"],
                font=("DejaVu Sans Mono", 19, "bold"),
            ).pack(side="left", padx=18)
            if self.connection_mode == "host":
                self.make_button(
                    code_panel,
                    "COPY CODE",
                    self.copy_lobby_code,
                    primary=False,
                ).pack(side="right")
        self.status_plate(briefing, "AWAITING COMMAND EVENT", active=True).pack(
            anchor="w", fill="x", pady=(16, 0)
        )
        self.loading_quote_panel(briefing)
        tk.Label(
            briefing,
            text=f"CLOCK OFFSET  {self.offset_text}\nROUND TRIP   {self.round_trip_text}",
            justify="left",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=self.font_mono,
        ).pack(anchor="w", pady=(10, 0))

    def animate_lobby_radar(self) -> None:
        radar = self.radar_canvas
        if (
            self.current_screen != "lobby"
            or radar is None
            or not radar.winfo_exists()
        ):
            self.radar_after_id = None
            return

        radar.delete("sweep")
        center = 110
        radius = 101
        trail_colors = (
            COLORS["cyan"],
            "#3bb9b7",
            "#2a8587",
            "#205e64",
            "#173f48",
            "#102b34",
        )
        for trail, color in reversed(tuple(enumerate(trail_colors))):
            angle = math.radians(self.radar_sweep_degrees - trail * 4)
            end_x = center + radius * math.cos(angle)
            end_y = center - radius * math.sin(angle)
            radar.create_line(
                center,
                center,
                end_x,
                end_y,
                fill=color,
                width=3 if trail == 0 else 2,
                tags="sweep",
            )
        radar.create_oval(
            center - 4,
            center - 4,
            center + 4,
            center + 4,
            fill=COLORS["alert"],
            outline=COLORS["gold"],
            tags="sweep",
        )

        for contact, x, y, contact_angle in self.radar_contacts:
            separation = abs(
                (self.radar_sweep_degrees - contact_angle + 180) % 360 - 180
            )
            illuminated = separation < 13
            size = 6 if illuminated else 3
            radar.coords(contact, x - size, y - size, x + size, y + size)
            radar.itemconfigure(
                contact,
                fill=COLORS["gold"] if illuminated else COLORS["cyan_dark"],
                outline=COLORS["orange"] if illuminated else COLORS["cyan"],
                width=2 if illuminated else 1,
            )
            radar.tag_raise(contact)

        if self.radar_status_label is not None:
            operation = (
                "BROADCASTING LOBBY"
                if self.connection_mode == "host"
                else "SEARCHING FOR HOST"
                if self.connection_mode == "join"
                else "TACTICAL SCAN"
            )
            self.radar_status_label.configure(
                text=f"SCAN {int(self.radar_sweep_degrees):03d}°  //  {operation}"
            )
        step = 9.0 if self.low_bandwidth else 3.5
        interval = 180 if self.low_bandwidth else 50
        self.radar_sweep_degrees = (self.radar_sweep_degrees + step) % 360
        self.radar_after_id = self.root.after(interval, self.animate_lobby_radar)

    def copy_lobby_code(self) -> None:
        if not self.lobby_code:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.lobby_code)
        self.root.update_idletasks()

    def show_placement(self) -> None:
        self.current_screen = "placement"
        self.clear_body()
        self.tactical_backdrop()
        heading = tk.Frame(
            self.body,
            bg="#09161d",
            padx=20,
            pady=12,
            highlightbackground=COLORS["steel"],
            highlightthickness=1,
        )
        heading.pack(fill="x", pady=(0, 14))
        title = tk.Frame(heading, bg="#09161d")
        title.pack(side="left", fill="x", expand=True)
        self.section_label(title, "PHASE 01 // FLEET DEPLOYMENT").pack(anchor="w")
        tk.Label(
            title,
            text="POSITION YOUR FLEET",
            bg="#09161d",
            fg=COLORS["text"],
            font=("DejaVu Serif", 25, "bold"),
        ).pack(anchor="w", pady=(4, 0))
        tk.Label(
            title,
            text="Separate classified grids // enemy coordinates do not block deployment",
            bg="#09161d",
            fg=COLORS["muted"],
            font=self.font_mono,
        ).pack(anchor="w", pady=(4, 0))
        self.status_plate(
            heading,
            f"{self.player_name.upper()} COMMAND\nDEPLOYMENT AUTHORIZED",
            active=True,
        ).pack(side="right", padx=(20, 0))
        if self.player_name in TEAMS:
            flag = self.icons.team_flag(self.player_name, 70, 42, True)
            flag_label = tk.Label(heading, image=flag, bg="#09161d", bd=0)
            flag_label.image = flag
            flag_label.pack(side="right")

        layout = tk.Frame(self.body, bg=COLORS["background"])
        layout.pack(fill="both", expand=True)
        layout.columnconfigure(0, weight=3)
        layout.columnconfigure(1, weight=2)
        board_panel = tk.Frame(layout, bg=COLORS["panel"], padx=22, pady=15, highlightbackground=COLORS["steel"], highlightthickness=2)
        board_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        self.alert_stripe(board_panel)
        tk.Label(
            board_panel,
            text="TACTICAL MAP  //  YOUR WATERS  //  CLASSIFIED",
            bg=COLORS["panel"],
            fg=COLORS["alert"],
            font=self.font_mono,
        ).pack(anchor="w", pady=(10, 8))
        self.placement_board = tk.Frame(board_panel, bg=COLORS["panel"])
        self.placement_board.pack(expand=True)
        self.draw_placement_board()

        controls = tk.Frame(layout, bg=COLORS["panel"], padx=24, pady=17, highlightbackground=COLORS["steel"], highlightthickness=2)
        controls.grid(row=0, column=1, sticky="nsew")
        self.alert_stripe(controls)
        tk.Label(
            controls,
            text="NAVAL COMMAND // UNIT ROSTER",
            bg=COLORS["panel"],
            fg=COLORS["alert"],
            font=self.font_mono,
        ).pack(anchor="w", pady=(10, 4))
        self.fleet_heading = tk.Label(controls, text="AVAILABLE FLEET", bg=COLORS["panel"], fg=COLORS["text"], font=self.font_label)
        self.fleet_heading.pack(anchor="w", pady=(0, 10))
        self.fleet_buttons = tk.Frame(controls, bg=COLORS["panel"])
        self.fleet_buttons.pack(fill="x")
        self.draw_fleet_buttons()
        tk.Label(controls, text="DEPLOYMENT VECTOR", bg=COLORS["panel"], fg=COLORS["muted"], font=self.font_label).pack(anchor="w", pady=(15, 8))
        directions = tk.Frame(controls, bg=COLORS["panel"])
        directions.pack(fill="x")
        for text, value in (("HORIZONTAL", "horizontal"), ("VERTICAL", "vertical")):
            tk.Radiobutton(
                directions, text=text, value=value, variable=self.orientation,
                indicatoron=False, bg="#17242b", selectcolor=COLORS["alert_dark"],
                fg=COLORS["text"], activebackground=COLORS["alert_dark"], activeforeground=COLORS["text"],
                relief="flat", bd=0, padx=12, pady=9, font=self.font_small,
            ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.lock_button = self.make_button(controls, "CONFIRM DEPLOYMENT  →", self.submit_fleet)
        self.lock_button.pack(fill="x", pady=(18, 8))
        self.make_button(controls, "CLEAR TACTICAL MAP", self.reset_fleet, primary=False).pack(fill="x")
        self.update_placement_controls()

    def draw_grid_labels(self, parent: tk.Widget) -> None:
        tk.Label(parent, text="", bg=parent.cget("bg"), width=2).grid(row=0, column=0)
        for column, letter in enumerate(LETTERS, start=1):
            tk.Label(parent, text=letter, bg=parent.cget("bg"), fg=COLORS["muted"], font=self.font_mono, width=3).grid(row=0, column=column)
        for row in range(10):
            tk.Label(parent, text=str(row + 1), bg=parent.cget("bg"), fg=COLORS["muted"], font=self.font_mono, width=2).grid(row=row + 1, column=0)

    def draw_placement_board(self) -> None:
        if not self.placement_buttons:
            self.draw_grid_labels(self.placement_board)
            initial_icon = self.icons.water(0, 0)
            for row in range(10):
                for column in range(10):
                    button = tk.Button(
                        self.placement_board,
                        image=initial_icon,
                        bg=COLORS["water"],
                        activebackground=COLORS["water_hover"],
                        relief="flat",
                        bd=0,
                        width=32,
                        height=29,
                        cursor="crosshair",
                        command=lambda r=row, c=column: self.place_ship(r, c),
                    )
                    button.image = initial_icon
                    button.grid(
                        row=row + 1,
                        column=column + 1,
                        padx=2,
                        pady=2,
                        sticky="nsew",
                    )
                    self.placement_buttons[(row, column)] = button
        segments: dict[tuple[int, int], Any] = {}
        for name, placement in self.placements.items():
            cells = self.placement_cells(placement)
            for index, cell in enumerate(cells):
                segments[cell] = self.icons.ship_segment(
                    self.fleet_assets.get(name, "Battleship"),
                    placement["orientation"],
                    index,
                    placement["length"],
                    row=cell[0],
                    column=cell[1],
                )
        for row in range(10):
            for column in range(10):
                icon = segments.get((row, column), self.icons.water(row, column))
                button = self.placement_buttons[(row, column)]
                background = (
                    COLORS["cyan_dark"]
                    if (row, column) in segments
                    else COLORS["water"]
                )
                display_state = (str(icon), background)
                if getattr(button, "_display_state", None) == display_state:
                    continue
                button.configure(
                    image=icon,
                    bg=background,
                    activebackground=COLORS["water_hover"],
                )
                button.image = icon
                button._display_state = display_state

    def placement_cells(self, placement: dict[str, Any]) -> list[tuple[int, int]]:
        return [
            (
                placement["row"] + (index if placement["orientation"] == "vertical" else 0),
                placement["column"] + (index if placement["orientation"] == "horizontal" else 0),
            )
            for index in range(placement["length"])
        ]

    def occupied_cells(self, except_ship: str | None = None) -> set[tuple[int, int]]:
        return {
            cell
            for name, placement in self.placements.items()
            if name != except_ship
            for cell in self.placement_cells(placement)
        }

    def own_ship_at(self, row: int, column: int, except_ship: str | None = None) -> str | None:
        for name, placement in self.placements.items():
            if name != except_ship and (row, column) in self.placement_cells(placement):
                return name
        return None

    def place_ship(self, row: int, column: int) -> None:
        if not self.placement_allowed:
            return
        candidate = {
            "row": row,
            "column": column,
            "orientation": self.orientation.get(),
            "length": self.fleet_spec[self.selected_ship],
        }
        cells = self.placement_cells(candidate)
        outside = next(((r, c) for r, c in cells if r > 9 or c > 9), None)
        if outside is not None:
            direction = "vertically" if candidate["orientation"] == "vertical" else "horizontally"
            messagebox.showwarning(
                "Ship leaves the board",
                f"{self.selected_ship} needs {candidate['length']} cells. Starting at "
                f"{self.coordinate(row, column)} {direction} would go beyond the 10 × 10 board.",
            )
            return
        overlap = next(
            (
                (r, c, self.own_ship_at(r, c, self.selected_ship))
                for r, c in cells
                if self.own_ship_at(r, c, self.selected_ship) is not None
            ),
            None,
        )
        if overlap is not None:
            overlap_row, overlap_column, other_ship = overlap
            messagebox.showwarning(
                "Your ships overlap",
                f"{self.selected_ship} overlaps your {other_ship} at "
                f"{self.coordinate(overlap_row, overlap_column)}. Choose another starting cell.\n\n"
                "The opponent's fleet is on a separate hidden board and does not affect your placement.",
            )
            return
        self.placements[self.selected_ship] = candidate
        self.selected_ship = next(
            (name for name in self.fleet_spec if name not in self.placements),
            self.selected_ship,
        )
        self.draw_placement_board()
        self.draw_fleet_buttons()
        self.update_placement_controls()

    def draw_fleet_buttons(self) -> None:
        if not self.fleet_button_widgets:
            for name in self.fleet_spec:
                button = tk.Button(
                    self.fleet_buttons,
                    compound="right",
                    anchor="w",
                    command=lambda ship=name: self.select_ship(ship),
                    activebackground=COLORS["alert_dark"],
                    activeforeground="#ffffff",
                    relief="flat",
                    bd=0,
                    padx=12,
                    pady=9,
                    font=self.font_mono,
                    cursor="hand2",
                )
                button.pack(fill="x", pady=3)
                self.fleet_button_widgets[name] = button
        for name, length in self.fleet_spec.items():
            placed = name in self.placements
            selected = name == self.selected_ship
            asset = self.fleet_assets.get(name, "Battleship")
            icon = self.icons.fleet_ship(asset, length, selected or placed)
            button = self.fleet_button_widgets[name]
            button.configure(
                text=f"{'DEPLOYED' if placed else 'SELECT'}   {name}",
                image=icon,
                bg=COLORS["alert_dark"] if selected else "#17242b",
                fg=COLORS["gold"] if placed else "#ffffff" if selected else COLORS["text"],
                highlightbackground=COLORS["alert"] if selected else COLORS["steel"],
                highlightthickness=1,
            )
            button.image = icon

    def select_ship(self, name: str) -> None:
        self.selected_ship = name
        self.draw_fleet_buttons()

    def reset_fleet(self) -> None:
        self.placements.clear()
        self.selected_ship = next(iter(self.fleet_spec), "")
        self.draw_placement_board()
        self.draw_fleet_buttons()
        self.update_placement_controls()

    def update_placement_controls(self) -> None:
        count = len(self.placements)
        self.fleet_heading.configure(
            text=f"{self.player_name.upper()} FLEET  //  {count} OF {len(self.fleet_spec)} DEPLOYED"
        )
        self.lock_button.configure(
            state="normal"
            if count == len(self.fleet_spec) and self.placement_allowed
            else "disabled"
        )

    @staticmethod
    def coordinate(row: int, column: int) -> str:
        return f"{LETTERS[column]}{row + 1}"

    def submit_fleet(self) -> None:
        if len(self.placements) != len(self.fleet_spec) or not self.worker:
            return
        ships = []
        for name in self.fleet_spec:
            placement = self.placements[name]
            cells = self.placement_cells(placement)
            ships.append(
                {
                    "name": name,
                    "start": self.coordinate(*cells[0]),
                    "end": self.coordinate(*cells[-1]),
                }
            )
        self.placement_allowed = False
        self.update_placement_controls()
        self.worker.send({"type": "place_fleet", "ships": ships})

    def show_game(self) -> None:
        if not self.latest_state:
            return
        if (
            self.current_screen == "game"
            and self.game_own_buttons
            and self.game_target_buttons
        ):
            self.refresh_game()
            return
        self.current_screen = "game"
        state = self.latest_state
        self.clear_body()
        self.tactical_backdrop()
        header = tk.Frame(
            self.body,
            bg="#09161d",
            padx=18,
            pady=11,
            highlightbackground=COLORS["steel"],
            highlightthickness=1,
        )
        header.pack(fill="x", pady=(0, 12))
        left = tk.Frame(header, bg="#09161d")
        left.pack(side="left")
        self.section_label(left, "PHASE 02 // LIVE ENGAGEMENT").pack(anchor="w")
        enemy = "Japan" if state["you"] == "US" else "US"
        forces = tk.Frame(left, bg="#09161d")
        forces.pack(anchor="w", pady=(4, 0))
        own_flag = self.icons.team_flag(str(state["you"]), 54, 32, True)
        own_flag_label = tk.Label(forces, image=own_flag, bg="#09161d", bd=0)
        own_flag_label.image = own_flag
        own_flag_label.pack(side="left", padx=(0, 8))
        tk.Label(
            forces,
            text=f"{state['you'].upper()}  //  PEARL HARBOR  //  {enemy.upper()}",
            bg="#09161d",
            fg=COLORS["text"],
            font=("DejaVu Sans Condensed", 20, "bold"),
        ).pack(side="left")
        enemy_flag = self.icons.team_flag(enemy, 54, 32, False)
        enemy_flag_label = tk.Label(forces, image=enemy_flag, bg="#09161d", bd=0)
        enemy_flag_label.image = enemy_flag
        enemy_flag_label.pack(side="left", padx=(8, 0))
        your_turn = state.get("current_turn") == state.get("you")
        self.game_turn_status = self.status_plate(
            header,
            "●  FIRE AUTHORIZED // SELECT TARGET"
            if your_turn
            else f"●  STANDBY // {str(state.get('current_turn') or 'WAITING').upper()} COMMAND",
            active=your_turn,
        )
        self.game_turn_status.pack(side="right", pady=5)

        boards = tk.Frame(self.body, bg=COLORS["background"])
        boards.pack(fill="both", expand=True)
        boards.columnconfigure(0, weight=1)
        boards.columnconfigure(1, weight=1)
        own_panel, self.game_own_status = self.board_panel(
            boards,
            "FRIENDLY NAVAL GRID",
            f"{state['own_ships_remaining']} UNITS AFLOAT",
            0,
            COLORS["cyan"],
        )
        target_panel, self.game_target_status = self.board_panel(
            boards,
            "HOSTILE TARGET GRID",
            f"{state['opponent_ships_remaining']} CONTACTS REMAIN",
            1,
            COLORS["alert"],
        )
        self.draw_game_board(
            own_panel,
            state["own_board"],
            target=False,
            fleet=state.get("own_fleet"),
            buttons=self.game_own_buttons,
        )
        self.draw_game_board(
            target_panel,
            state["target_board"],
            target=True,
            buttons=self.game_target_buttons,
        )

        intel = tk.Frame(self.body, bg=COLORS["panel"], highlightbackground=COLORS["steel"], highlightthickness=2)
        intel.pack(fill="x", pady=(12, 0))
        tk.Frame(intel, bg=COLORS["alert"], width=7).pack(side="left", fill="y")
        report = tk.Frame(intel, bg=COLORS["panel"], padx=16, pady=10)
        report.pack(side="left", fill="both", expand=True)
        tk.Label(report, text="FIELD REPORT // LATEST INTELLIGENCE", bg=COLORS["panel"], fg=COLORS["alert"], font=self.font_mono).pack(anchor="w")
        self.game_report_label = tk.Label(report, text=self.latest_event.upper(), bg=COLORS["panel"], fg=COLORS["text"], font=self.font_body)
        self.game_report_label.pack(anchor="w", pady=(3, 0))
        self.game_network_label = tk.Label(
            intel,
            text=f"NET {self.round_trip_text}\nSYNC {self.offset_text}",
            justify="right",
            bg="#17242b",
            fg=COLORS["muted"],
            font=self.font_mono,
            padx=16,
            pady=10,
        )
        self.game_network_label.pack(side="right", fill="y")

    def refresh_game(self) -> None:
        if not self.latest_state:
            return
        state = self.latest_state
        your_turn = state.get("current_turn") == state.get("you")
        if self.game_turn_status is not None:
            self.game_turn_status.configure(
                text=(
                    "●  FIRE AUTHORIZED // SELECT TARGET"
                    if your_turn
                    else f"●  STANDBY // {str(state.get('current_turn') or 'WAITING').upper()} COMMAND"
                ),
                bg=COLORS["alert_dark"] if your_turn else "#17242b",
                fg="#ffffff" if your_turn else COLORS["muted"],
                highlightbackground=COLORS["alert"] if your_turn else COLORS["steel"],
            )
        if self.game_own_status is not None:
            self.game_own_status.configure(
                text=f"{state['own_ships_remaining']} UNITS AFLOAT"
            )
        if self.game_target_status is not None:
            self.game_target_status.configure(
                text=f"{state['opponent_ships_remaining']} CONTACTS REMAIN"
            )
        if self.game_report_label is not None:
            self.game_report_label.configure(text=self.latest_event.upper())
        if self.game_network_label is not None:
            self.game_network_label.configure(
                text=f"NET {self.round_trip_text}\nSYNC {self.offset_text}"
            )
        self.update_game_board(
            self.game_own_buttons,
            state["own_board"],
            target=False,
            fleet=state.get("own_fleet"),
        )
        self.update_game_board(
            self.game_target_buttons,
            state["target_board"],
            target=True,
        )

    def board_panel(
        self,
        parent: tk.Widget,
        title: str,
        status: str,
        column: int,
        accent: str,
    ) -> tuple[tk.Frame, tk.Label]:
        outer = tk.Frame(parent, bg=COLORS["panel"], padx=16, pady=12, highlightbackground=accent, highlightthickness=2)
        outer.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column == 0 else (8, 0))
        topline = tk.Frame(outer, bg=COLORS["panel"])
        topline.pack(fill="x", pady=(0, 8))
        tk.Label(topline, text=title, bg=COLORS["panel"], fg=accent, font=self.font_mono).pack(side="left")
        status_label = tk.Label(topline, text=status, bg=COLORS["panel"], fg=COLORS["text"], font=self.font_label)
        status_label.pack(side="right")
        tk.Frame(outer, bg=accent, height=2).pack(fill="x", pady=(0, 7))
        board = tk.Frame(outer, bg=COLORS["panel"])
        board.pack(expand=True)
        return board, status_label

    def fleet_segments(
        self, fleet: list[dict[str, Any]] | None
    ) -> dict[tuple[int, int], tuple[str, str, int, int]]:
        segments: dict[tuple[int, int], tuple[str, str, int, int]] = {}
        for ship in fleet or []:
            cells = [parse_coordinate(str(value)) for value in ship["cells"]]
            for index, cell in enumerate(cells):
                segments[cell] = (
                    str(ship.get("asset", self.fleet_assets.get(str(ship["name"]), "Battleship"))),
                    str(ship["orientation"]),
                    index,
                    len(cells),
                )
        return segments

    def draw_game_board(
        self,
        parent: tk.Widget,
        rows: list[str],
        target: bool,
        fleet: list[dict[str, Any]] | None = None,
        buttons: dict[tuple[int, int], tk.Button] | None = None,
    ) -> None:
        if buttons is None:
            buttons = {}
        self.draw_grid_labels(parent)
        initial_icon = self.icons.water(0, 0)
        for row in range(10):
            for column in range(10):
                button = tk.Button(
                    parent,
                    image=initial_icon,
                    bg=COLORS["water"],
                    fg=COLORS["muted"],
                    activeforeground=COLORS["text"],
                    disabledforeground=COLORS["muted"],
                    relief="flat",
                    bd=0,
                    width=32,
                    height=29,
                    state="disabled",
                    cursor="arrow",
                    command=lambda r=row, c=column: self.attack(r, c),
                )
                button.image = initial_icon
                button.grid(
                    row=row + 1,
                    column=column + 1,
                    padx=2,
                    pady=2,
                    sticky="nsew",
                )
                buttons[(row, column)] = button
        self.update_game_board(buttons, rows, target, fleet)

    def update_game_board(
        self,
        buttons: dict[tuple[int, int], tk.Button],
        rows: list[str],
        target: bool,
        fleet: list[dict[str, Any]] | None = None,
    ) -> None:
        segments = self.fleet_segments(fleet)
        for row in range(10):
            for column in range(10):
                value = rows[row][column]
                background = COLORS["water"]
                foreground = COLORS["muted"]
                segment = segments.get((row, column))
                icon = self.icons.water(row, column)
                if value == "S":
                    background = COLORS["cyan_dark"]
                    if segment:
                        icon = self.icons.ship_segment(
                            *segment, row=row, column=column
                        )
                elif value == "X":
                    background = "#542b29"
                    icon = (
                        self.icons.ship_segment(
                            *segment, hit=True, row=row, column=column
                        )
                        if segment
                        else self.icons.hit(row, column)
                    )
                elif value == "o":
                    icon = self.icons.miss(row, column)
                attackable = target and self.can_attack and value == "."
                visually_attackable = (
                    target and value == "." and (self.can_attack or self.low_bandwidth)
                )
                if visually_attackable:
                    icon = self.icons.target(row, column)
                button = buttons[(row, column)]
                enabled = attackable or (
                    self.low_bandwidth and target and value == "."
                )
                active_background = (
                    COLORS["alert"] if visually_attackable else background
                )
                cursor = "crosshair" if visually_attackable else "arrow"
                display_state = (
                    str(icon),
                    background,
                    foreground,
                    active_background,
                    enabled,
                    cursor,
                )
                if getattr(button, "_display_state", None) == display_state:
                    continue
                button.configure(
                    image=icon,
                    bg=background,
                    fg=foreground,
                    activebackground=active_background,
                    activeforeground=COLORS["text"],
                    disabledforeground=foreground,
                    state="normal" if enabled else "disabled",
                    cursor=cursor,
                )
                button.image = icon
                button._display_state = display_state

    def attack(self, row: int, column: int) -> None:
        if not self.can_attack or not self.worker:
            return
        self.can_attack = False
        target = self.coordinate(row, column)
        self.latest_event = f"Firing on {target}…"
        self.worker.send({"type": "attack", "coordinate": target})
        self.show_game()

    def show_result(self, winner: str) -> None:
        self.current_screen = "result"
        self.clear_body()
        won = winner == self.player_name
        self.tactical_backdrop()
        panel = tk.Frame(
            self.body,
            bg=COLORS["panel"],
            highlightbackground=COLORS["alert"],
            highlightthickness=3,
        )
        panel.place(relx=.5, rely=.5, anchor="center", relwidth=.76, relheight=.74)
        self.alert_stripe(panel)
        content = tk.Frame(panel, bg=COLORS["panel"], padx=42, pady=35)
        content.pack(fill="both", expand=True)

        insignia = tk.Frame(
            content,
            bg=COLORS["alert_dark"] if won else "#261c1c",
            highlightbackground=COLORS["alert"],
            highlightthickness=2,
            width=220,
        )
        insignia.pack(side="left", fill="y", padx=(0, 38))
        insignia.pack_propagate(False)
        tk.Label(
            insignia,
            text="★" if won else "✕",
            bg=insignia.cget("bg"),
            fg=COLORS["gold"] if won else COLORS["alert"],
            font=("DejaVu Sans", 72, "bold"),
        ).pack(expand=True)
        result_team = self.player_name if won else winner
        if result_team in TEAMS:
            flag = self.icons.team_flag(result_team, 112, 64, won)
            flag_label = tk.Label(insignia, image=flag, bg=insignia.cget("bg"), bd=0)
            flag_label.image = flag
            flag_label.pack(pady=(0, 14))
        tk.Label(
            insignia,
            text="PACIFIC\nCOMMAND",
            justify="center",
            bg=insignia.cget("bg"),
            fg=COLORS["text"],
            font=("DejaVu Sans Mono", 10, "bold"),
        ).pack(pady=(0, 32))

        debrief = tk.Frame(content, bg=COLORS["panel"])
        debrief.pack(side="left", fill="both", expand=True)
        self.section_label(debrief, "OPERATION COMPLETE // FINAL REPORT").pack(anchor="w")
        tk.Label(
            debrief,
            text="MISSION\nACCOMPLISHED" if won else "OPERATION\nFAILED",
            justify="left",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("DejaVu Serif", 34, "bold"),
        ).pack(anchor="w", pady=(14, 8))
        tk.Label(
            debrief,
            text=(
                f"{self.player_name.upper()} COMMAND HOLDS THE THEATER"
                if won
                else f"{winner.upper()} COMMAND CONTROLS THE WATERS"
            ),
            bg=COLORS["panel"],
            fg=COLORS["gold"] if won else COLORS["alert"],
            font=("DejaVu Sans Mono", 10, "bold"),
        ).pack(anchor="w", pady=(0, 20))
        tk.Frame(debrief, bg=COLORS["alert"], height=3).pack(fill="x", pady=(0, 18))
        tk.Label(
            debrief,
            text=(
                "OBJECTIVE SECURED\nEnemy naval contacts neutralized."
                if won
                else "FLEET LOST\nAll friendly vessels have been neutralized."
            ),
            justify="left",
            bg=COLORS["panel"],
            fg="#c8d3d6",
            font=self.font_body,
        ).pack(anchor="w")
        self.command_button(
            debrief,
            "[↵]",
            "ACKNOWLEDGE REPORT // MAIN MENU",
            self.return_to_main_menu,
        ).pack(fill="x", side="bottom")
        self.root.bind("<Return>", lambda _event: self.return_to_main_menu())
        self.root.bind("<Escape>", lambda _event: self.return_to_main_menu())

    def return_to_main_menu(self) -> None:
        self.connection_mode = ""
        if self.worker:
            self.worker.close()
        self.worker = None
        self.stop_owned_server()

        # Detach from any late messages emitted while the old socket is closing.
        self.messages = queue.Queue()
        self.player_name = ""
        self.fleet_spec.clear()
        self.fleet_assets.clear()
        self.placements.clear()
        self.selected_ship = ""
        self.team_choice.set(self.args.team or "")
        self.orientation.set("horizontal")
        self.placement_allowed = False
        self.can_attack = False
        self.latest_state = None
        self.latest_event = "Awaiting first strike."
        self.assignment_note = ""
        self.lobby_code = ""
        self.offset_text = "—"
        self.round_trip_text = "—"
        self.connection_label.configure(text="●  OFFLINE", fg=COLORS["muted"])
        self.show_main_menu()

    def stop_owned_server(self) -> None:
        if self.owns_server and self.server_process is not None:
            stop_process(self.server_process)
        self.server_process = None
        self.owns_server = False

    def poll_messages(self) -> None:
        try:
            while True:
                self.handle_message(self.messages.get_nowait())
        except queue.Empty:
            pass
        self.root.after(50, self.poll_messages)

    def handle_message(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "local_server_ready":
            process = message.get("process")
            if isinstance(process, subprocess.Popen):
                self.server_process = process
                self.owns_server = True
            else:
                self.server_process = None
                self.owns_server = False
            port = int(message["port"])
            preferred_team = str(message["preferred_team"])
            self.server_uri = f"ws://127.0.0.1:{port}/ws"
            self.connection_label.configure(
                text="●  SERVER ONLINE", fg=COLORS["yellow"]
            )
            self.worker = NetworkWorker(
                self.server_uri,
                self.messages,
                mode="host",
                preferred_team=preferred_team,
            )
            self.worker.start()
            source = (
                "Using the operation server already active on this machine."
                if message.get("reused_server")
                else "Local operation server online. Requesting a new lobby code."
            )
            self.show_lobby("Creating operation lobby", source)
        elif message_type == "local_server_error":
            self.connection_label.configure(
                text="●  HOST START FAILED", fg=COLORS["orange"]
            )
            self.connection_mode = ""
            messagebox.showerror(
                "Could not start host server",
                f"{message['message']}\n\nTry another port or close the program using that port.",
            )
            self.show_host_setup()
        elif message_type == "clock_sync":
            self.offset_text = f"{message['offset_ms']:+.1f} ms"
            self.round_trip_text = f"{message['round_trip_ms']:.1f} ms"
            self.connection_label.configure(text="●  LINK ACTIVE", fg=COLORS["cyan"])
        elif message_type == "joined":
            self.player_name = str(message["team"])
            self.lobby_code = str(message.get("lobby_code", self.lobby_code)).upper()
            automatic = message.get("assignment") == "automatic"
            self.assignment_note = (
                f"Lobby assignment confirmed: you command {self.player_name}, "
                "the country opposing the host."
                if automatic
                else f"You host the operation as {self.player_name}."
            )
            self.fleet_spec = {
                str(name): int(length) for name, length in message["fleet"].items()
            }
            self.fleet_assets = {
                str(name): str(asset)
                for name, asset in message.get("fleet_assets", {}).items()
            }
            self.selected_ship = next(iter(self.fleet_spec))
            self.show_lobby(
                f"{self.player_name} command online",
                f"{self.assignment_note} Waiting for the opposing side.",
            )
        elif message_type in {"waiting", "opponent_left"}:
            if message.get("lobby_code"):
                self.lobby_code = str(message["lobby_code"]).upper()
            self.placements.clear()
            self.placement_allowed = False
            self.show_lobby("Waiting for opponent", str(message["message"]))
        elif message_type == "players_ready":
            self.show_lobby(
                " vs ".join(message["players"]),
                f"{self.assignment_note} Both commanders connected. Prepare your fleet.",
            )
        elif message_type == "action_required":
            if message["action"] == "place_fleet":
                self.placement_allowed = True
                self.show_placement()
            else:
                self.can_attack = True
                self.show_game()
        elif message_type == "fleet_ready":
            self.placement_allowed = False
            self.show_lobby("Fleet locked", "Your coordinates are classified. Waiting for the opponent's deployment.")
        elif message_type == "player_ready" and self.current_screen == "lobby":
            self.lobby_message.configure(text=f"{message['player']} is ready — {message['ready_count']} of 2 fleets deployed.")
        elif message_type == "game_started":
            self.latest_event = f"{message['first_player']} has the first strike."
        elif message_type == "state":
            self.latest_state = message
            self.show_game()
        elif message_type == "attack_result":
            result = "DIRECT HIT" if message["result"] == "hit" else "miss"
            sunk = f" — {message['ship']} sunk" if message.get("sunk") else ""
            self.latest_event = f"{message['attacker']} fired on {message['coordinate']}: {result}{sunk}."
        elif message_type == "game_over":
            self.show_result(str(message["winner"]))
        elif message_type == "error":
            messagebox.showerror("Server message", str(message["message"]))
        elif message_type == "lobby_closed":
            self.connection_label.configure(text="●  LINK CLOSED", fg=COLORS["orange"])
            messagebox.showwarning("Lobby closed", str(message["message"]))
            self.return_to_main_menu()
        elif message_type in {"network_error", "connection_closed"}:
            self.connection_label.configure(text="●  LINK CLOSED", fg=COLORS["orange"])
            if self.current_screen != "result" and self.connection_mode:
                messagebox.showerror("Connection problem", str(message["message"]))
                if self.connection_mode == "host" and self.team_choice.get() in TEAMS:
                    self.show_host_setup()
                else:
                    self.show_join_setup()

    def on_close(self) -> None:
        self.closing = True
        if self.worker:
            self.worker.close()
        self.stop_owned_server()
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pearl Harbor")
    parser.add_argument("--uri", default="ws://127.0.0.1:8765/ws")
    parser.add_argument("--team", choices=TEAMS)
    parser.add_argument(
        "--host",
        action="store_true",
        help="Open directly in the Host Operation country-selection flow.",
    )
    parser.add_argument(
        "--low-bandwidth",
        action="store_true",
        help="Reduce image and animation traffic for remote X11 displays.",
    )
    parser.add_argument(
        "--full-graphics",
        action="store_true",
        help="Disable automatic low-bandwidth mode on a remote X11 display.",
    )
    parser.add_argument("--token", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = tk.Tk()
    application = BattleshipGUI(root, args)
    if args.host:
        root.after_idle(application.show_briefing)
    root.mainloop()


if __name__ == "__main__":
    main()
