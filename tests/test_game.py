import pytest

from game import Board, GameError, TEAM_FLEETS, format_coordinate, parse_coordinate, team_assets, team_fleet


VALID_FLEET = [
    {"name": "Carrier", "start": "A1", "end": "A5"},
    {"name": "Battleship", "start": "C1", "end": "C4"},
    {"name": "Cruiser", "start": "E1", "end": "E3"},
    {"name": "Submarine", "start": "G1", "end": "G3"},
    {"name": "Destroyer", "start": "I1", "end": "I2"},
]

US_FLEET = [
    {"name": "USS Arizona", "start": "A1", "end": "A5"},
    {"name": "USS Oklahoma", "start": "C1", "end": "C4"},
    {"name": "USS Helena", "start": "E1", "end": "E3"},
    {"name": "USS Shaw", "start": "G1", "end": "G3"},
    {"name": "USS Nevada", "start": "I1", "end": "I2"},
]

JAPAN_FLEET = [
    {"name": "Akagi", "start": "A1", "end": "A5"},
    {"name": "Kaga", "start": "C1", "end": "C4"},
    {"name": "Shokaku", "start": "E1", "end": "E3"},
    {"name": "Soryu", "start": "G1", "end": "G3"},
    {"name": "I-22", "start": "I1", "end": "I2"},
]


def test_coordinate_round_trip():
    assert parse_coordinate("j10") == (9, 9)
    assert format_coordinate((9, 9)) == "J10"


@pytest.mark.parametrize("coordinate", ["A0", "K1", "A11", "1A", ""])
def test_invalid_coordinate(coordinate):
    with pytest.raises(GameError):
        parse_coordinate(coordinate)


def test_fleet_and_sanitized_views():
    board = Board.from_placements(VALID_FLEET)
    assert board.own_view()[0][0] == "S"
    assert board.target_view()[0][0] == "."
    assert board.fire("A1")["result"] == "hit"
    assert board.target_view()[0][0] == "X"
    assert board.fire("B10")["result"] == "miss"
    fleet = board.own_fleet_view()
    assert fleet[0] == {
        "name": "Carrier",
        "asset": "Carrier",
        "orientation": "vertical",
        "cells": ["A1", "A2", "A3", "A4", "A5"],
    }


def test_duplicate_attack_is_rejected():
    board = Board.from_placements(VALID_FLEET)
    board.fire("A1")
    with pytest.raises(GameError, match="already attacked"):
        board.fire("A1")


def test_overlap_is_rejected():
    invalid = [dict(item) for item in VALID_FLEET]
    invalid[-1] = {"name": "Destroyer", "start": "A1", "end": "B1"}
    with pytest.raises(GameError, match="overlaps"):
        Board.from_placements(invalid)


def test_historical_team_fleets_use_private_asset_metadata():
    board = Board.from_placements(
        US_FLEET,
        fleet_spec=team_fleet("US"),
        ship_assets=team_assets("US"),
    )
    assert set(TEAM_FLEETS) == {"US", "Japan"}
    assert board.own_fleet_view()[0]["name"] == "USS Arizona"
    assert board.own_fleet_view()[0]["asset"] == "Battleship"
