"""Pure Battleship game rules shared by the server and terminal client."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable


BOARD_SIZE = 10
FLEET = {
    "Carrier": 5,
    "Battleship": 4,
    "Cruiser": 3,
    "Submarine": 3,
    "Destroyer": 2,
}

TEAMS = ("US", "Japan")

# Historically present Pearl Harbor forces, mapped to balanced game lengths and the
# closest available illustration class. Lengths are gameplay values, not scale data.
TEAM_FLEETS: dict[str, dict[str, dict[str, object]]] = {
    "US": {
        "USS Arizona": {"length": 5, "asset": "Battleship"},
        "USS Oklahoma": {"length": 4, "asset": "Battleship"},
        "USS Helena": {"length": 3, "asset": "Cruiser"},
        "USS Shaw": {"length": 3, "asset": "Destroyer"},
        "USS Nevada": {"length": 2, "asset": "Battleship"},
    },
    "Japan": {
        "Akagi": {"length": 5, "asset": "Carrier"},
        "Kaga": {"length": 4, "asset": "Carrier"},
        "Shokaku": {"length": 3, "asset": "Carrier"},
        "Soryu": {"length": 3, "asset": "Carrier"},
        "I-22": {"length": 2, "asset": "Submarine"},
    },
}


def team_fleet(team: str) -> dict[str, int]:
    return {
        name: int(details["length"])
        for name, details in TEAM_FLEETS[team].items()
    }


def team_assets(team: str) -> dict[str, str]:
    return {
        name: str(details["asset"])
        for name, details in TEAM_FLEETS[team].items()
    }

Coordinate = tuple[int, int]
_COORDINATE_RE = re.compile(r"^([A-J])(10|[1-9])$", re.IGNORECASE)


class GameError(ValueError):
    """A rule violation that can safely be shown to a player."""


def parse_coordinate(value: str) -> Coordinate:
    """Convert A1..J10 into a zero-based (row, column) tuple."""
    match = _COORDINATE_RE.fullmatch(value.strip())
    if not match:
        raise GameError("Coordinate must be between A1 and J10 (for example, B7).")
    column = ord(match.group(1).upper()) - ord("A")
    row = int(match.group(2)) - 1
    return row, column


def format_coordinate(coordinate: Coordinate) -> str:
    row, column = coordinate
    return f"{chr(ord('A') + column)}{row + 1}"


def cells_between(start: Coordinate, end: Coordinate) -> list[Coordinate]:
    """Return all cells in a horizontal or vertical line, inclusive."""
    start_row, start_column = start
    end_row, end_column = end
    if start_row != end_row and start_column != end_column:
        raise GameError("Ships must be horizontal or vertical, not diagonal.")

    row_step = 0 if start_row == end_row else (1 if end_row > start_row else -1)
    column_step = 0 if start_column == end_column else (1 if end_column > start_column else -1)
    length = max(abs(end_row - start_row), abs(end_column - start_column)) + 1
    return [
        (start_row + index * row_step, start_column + index * column_step)
        for index in range(length)
    ]


@dataclass
class Board:
    """A private board. Only sanitized views leave the server."""

    ship_cells: dict[Coordinate, str]
    ships: dict[str, set[Coordinate]]
    fleet_spec: dict[str, int] = field(default_factory=lambda: dict(FLEET))
    ship_assets: dict[str, str] = field(default_factory=dict)
    shots: dict[Coordinate, str] = field(default_factory=dict)

    @classmethod
    def from_placements(
        cls,
        placements: Iterable[dict[str, str]],
        fleet_spec: dict[str, int] | None = None,
        ship_assets: dict[str, str] | None = None,
    ) -> "Board":
        placements = list(placements)
        fleet_spec = dict(fleet_spec or FLEET)
        ship_assets = dict(ship_assets or {name: name for name in fleet_spec})
        expected_names = set(fleet_spec)
        supplied_names = {str(item.get("name", "")) for item in placements}
        if len(placements) != len(fleet_spec) or supplied_names != expected_names:
            raise GameError("Place each ship exactly once: " + ", ".join(fleet_spec))

        occupied: dict[Coordinate, str] = {}
        ships: dict[str, set[Coordinate]] = {}
        for item in placements:
            name = str(item.get("name", ""))
            try:
                start = parse_coordinate(str(item["start"]))
                end = parse_coordinate(str(item["end"]))
            except KeyError as exc:
                raise GameError(f"{name or 'A ship'} needs start and end coordinates.") from exc

            cells = cells_between(start, end)
            required_length = fleet_spec[name]
            if len(cells) != required_length:
                raise GameError(f"{name} must occupy exactly {required_length} cells.")
            overlap = next((cell for cell in cells if cell in occupied), None)
            if overlap is not None:
                raise GameError(
                    f"{name} overlaps {occupied[overlap]} at {format_coordinate(overlap)}."
                )
            ships[name] = set(cells)
            for cell in cells:
                occupied[cell] = name
        return cls(
            ship_cells=occupied,
            ships=ships,
            fleet_spec=fleet_spec,
            ship_assets=ship_assets,
        )

    def fire(self, coordinate_text: str) -> dict[str, object]:
        coordinate = parse_coordinate(coordinate_text)
        if coordinate in self.shots:
            raise GameError(f"{format_coordinate(coordinate)} was already attacked.")

        ship_name = self.ship_cells.get(coordinate)
        result = "hit" if ship_name else "miss"
        self.shots[coordinate] = result
        sunk = bool(
            ship_name
            and all(self.shots.get(cell) == "hit" for cell in self.ships[ship_name])
        )
        return {
            "coordinate": format_coordinate(coordinate),
            "result": result,
            "ship": ship_name if sunk else None,
            "sunk": sunk,
        }

    @property
    def all_sunk(self) -> bool:
        return all(self.shots.get(cell) == "hit" for cell in self.ship_cells)

    @property
    def ships_remaining(self) -> int:
        return sum(
            not all(self.shots.get(cell) == "hit" for cell in cells)
            for cells in self.ships.values()
        )

    def own_view(self) -> list[str]:
        rows: list[str] = []
        for row in range(BOARD_SIZE):
            values = []
            for column in range(BOARD_SIZE):
                coordinate = (row, column)
                if self.shots.get(coordinate) == "hit":
                    values.append("X")
                elif self.shots.get(coordinate) == "miss":
                    values.append("o")
                elif coordinate in self.ship_cells:
                    values.append("S")
                else:
                    values.append(".")
            rows.append("".join(values))
        return rows

    def target_view(self) -> list[str]:
        rows: list[str] = []
        for row in range(BOARD_SIZE):
            rows.append(
                "".join(
                    "X" if self.shots.get((row, column)) == "hit"
                    else "o" if self.shots.get((row, column)) == "miss"
                    else "."
                    for column in range(BOARD_SIZE)
                )
            )
        return rows

    def own_fleet_view(self) -> list[dict[str, object]]:
        """Describe ship geometry for its owner without exposing it to the opponent."""
        fleet = []
        for name in self.fleet_spec:
            cells = self.ships[name]
            horizontal = len({row for row, _column in cells}) == 1
            ordered = sorted(cells, key=lambda cell: cell[1] if horizontal else cell[0])
            fleet.append(
                {
                    "name": name,
                    "asset": self.ship_assets.get(name, name),
                    "orientation": "horizontal" if horizontal else "vertical",
                    "cells": [format_coordinate(cell) for cell in ordered],
                }
            )
        return fleet
