from game import TEAM_FLEETS
from historical_data import OPERATION_FACTS, TEAM_DOSSIERS, WAR_QUOTES


def test_historical_dossiers_cover_the_game_fleets_and_leaders():
    assert dict(OPERATION_FACTS)["JAPANESE PLAN"] == "Hawaii Operation"
    assert set(TEAM_DOSSIERS) == set(TEAM_FLEETS)
    for team, game_fleet in TEAM_FLEETS.items():
        dossier = TEAM_DOSSIERS[team]
        dossier_names = {name.split(" (")[0] for name, _fact in dossier["ships"]}
        assert dossier_names == set(game_fleet)
        assert dossier["government"]


def test_loading_quotes_have_unique_text_and_full_attribution():
    assert len(WAR_QUOTES) >= 6
    assert len({quote for quote, _speaker, _context in WAR_QUOTES}) == len(WAR_QUOTES)
    assert all(quote and speaker and context for quote, speaker, context in WAR_QUOTES)
