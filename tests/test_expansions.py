from pulse import expansions
from pulse.expansions import derive_names, refresh_expansions
from conftest import sql


def sealed(*items):
    """items: (idExpansion, name, categoryName)"""
    return {'products': [
        {'idProduct': i, 'name': name, 'categoryName': category, 'idExpansion': exp}
        for i, (exp, name, category) in enumerate(items)
    ]}


def test_riftbound_names():
    names = derive_names(sealed(
        (6286, 'Origins Booster Box', 'Riftbound Display'),
        (6286, 'Origins Booster', 'Riftbound Booster'),
        (6286, 'Jinx Champion Deck', 'Riftbound Champion Decks'),
        (6587, 'Vendetta: Pre-Rift Event Kit', 'Riftbound Riftbound Box Sets'),
        (6587, 'Vendetta Vault', 'Riftbound Riftbound Box Sets'),
        (6587, 'Vendetta Sleeved Booster', 'Riftbound Booster'),
    ))
    assert names == {6286: 'Origins', 6587: 'Vendetta'}


def test_booster_box_case_with_parenthetical():
    names = derive_names(sealed(
        (6399, 'Spiritforged Case (6x Booster Box)', 'Riftbound Display'),
        (6399, 'Spiritforged Booster', 'Riftbound Booster'),
    ))
    assert names == {6399: 'Spiritforged'}


def test_falls_back_to_other_categories():
    assert derive_names(sealed((1, 'Unleashed: Pre-Rift Event Kit', 'Riftbound Box Sets'))) == {1: 'Unleashed'}


def test_expansion_without_products_absent():
    assert 999 not in derive_names(sealed((1, 'Origins Booster', 'Riftbound Booster')))


def test_overrides_win_and_unnamed_stays_null(session, monkeypatch):
    monkeypatch.setattr(expansions, 'load_overrides', lambda game: {6286: 'Origins (Fixed)'})
    sql(session, "INSERT INTO expansion (game, id_expansion) VALUES ('riftbound', 6286), ('riftbound', 42)")
    count = refresh_expansions(session, 'riftbound', sealed(
        (6286, 'Origins Booster', 'Riftbound Booster'),
        (6399, 'Spiritforged Booster', 'Riftbound Booster'),
    ))
    rows = dict(sql(session, "SELECT id_expansion, name FROM expansion WHERE game = 'riftbound'").fetchall())
    assert rows == {6286: 'Origins (Fixed)', 6399: 'Spiritforged', 42: None}
    assert count == 2


def test_load_overrides_reads_repo_file():
    assert isinstance(expansions.load_overrides('magic'), dict)


def test_generic_prefix_keeps_the_part_after_colon():
    names = derive_names(sealed(
        (6150, 'Starter Deck: Blue Buggy', 'One Piece Preconstructed Decks'),
        (6150, 'Starter Deck: Blue Buggy Deck Pack', 'One Piece Preconstructed Decks'),
    ))
    assert names == {6150: 'Starter Deck: Blue Buggy'}


def test_names_after_colon_are_kept():
    names = derive_names(sealed(
        (1, 'Innistrad: Crimson Vow Draft Booster Box', 'Magic Display'),
        (1, 'Innistrad: Crimson Vow Set Booster', 'Magic Booster'),
        (2, 'Innistrad: Midnight Hunt Draft Booster', 'Magic Booster'),
        (3, 'From the Vault: Dragons', 'MtG Set'),
        (4, 'Booster Box Case (6x Origins Booster Box)', 'Riftbound Display'),
    ))
    assert names[1] == 'Innistrad: Crimson Vow'
    assert names[2] == 'Innistrad: Midnight Hunt'
    assert names[3] == 'From the Vault: Dragons'


def test_edition_markers_in_parentheses_are_kept():
    names = derive_names(sealed(
        (5229, 'Romance Dawn Booster Box Case (12x Booster Box)', 'One Piece Booster Boxes'),
        (5229, 'Romance Dawn Booster', 'One Piece Booster'),
        (5484, 'Romance Dawn Booster Box Case (12x Booster Box) (Non-English)', 'One Piece Booster Boxes'),
        (5484, 'Romance Dawn Booster (Non-English)', 'One Piece Booster'),
        (5624, 'Romance Dawn Sleeved Booster (Pre-Errata)', 'One Piece Booster'),
    ))
    assert names == {5229: 'Romance Dawn', 5484: 'Romance Dawn (Non-English)', 5624: 'Romance Dawn (Pre-Errata)'}
