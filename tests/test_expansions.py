from pulse import expansions
from pulse.expansions import derive_names, refresh_expansions


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


def test_overrides_win_and_unnamed_stays_null(conn, monkeypatch):
    monkeypatch.setattr(expansions, 'load_overrides', lambda game: {6286: 'Origins (Fixed)'})
    conn.execute("INSERT INTO expansion (game, id_expansion) VALUES ('riftbound', 6286), ('riftbound', 42)")
    count = refresh_expansions(conn, 'riftbound', sealed(
        (6286, 'Origins Booster', 'Riftbound Booster'),
        (6399, 'Spiritforged Booster', 'Riftbound Booster'),
    ))
    rows = dict(conn.execute("SELECT id_expansion, name FROM expansion WHERE game = 'riftbound'").fetchall())
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
