"""Expansion names, derived from the names of Cardmarket's sealed products.

Cardmarket's singles list carries only an expansion id. Sealed products of the same expansion are
named after it ("Origins Booster Box", "Vendetta: Pre-Rift Event Kit"), so stripping the product
part gives the expansion name. expansion_overrides.json corrects names by hand and always wins.
"""

import json
import re
from collections import Counter, defaultdict
from importlib.resources import files

SUFFIXES = sorted(
    [
        'Booster Box Case', 'Booster Box', 'Collector Booster', 'Set Booster', 'Play Booster',
        'Draft Booster', 'Sleeved Booster', 'Dash Pack', 'Booster', 'Display', 'Case', 'Bundle',
        'Elite Trainer Box', 'Prerelease Pack', 'Prerelease Kit', 'Pre-Rift Event Kit', 'Vault',
        'Theme Deck', 'Starter Deck', 'Fat Pack', 'Tin', 'Pack', 'Box',
    ],
    key=len,
    reverse=True,
)
SUFFIX_RE = re.compile(r'(?:^|\s+)(?:' + '|'.join(re.escape(s) for s in SUFFIXES) + r')$', re.IGNORECASE)
PARENTHETICAL_RE = re.compile(r'\s*\([^)]*\)\s*$')


def strip_product(name):
    name = PARENTHETICAL_RE.sub('', name)
    while True:
        stripped = SUFFIX_RE.sub('', name)
        if stripped == name:
            return name.strip()
        name = stripped


def candidate(name):
    """"Vendetta: Pre-Rift Event Kit" -> "Vendetta"; a generic prefix ("Starter Deck: Blue Buggy") is kept whole."""
    return strip_product(name.split(':', 1)[0]) or strip_product(name)


def derive_names(nonsingles):
    """Map idExpansion -> name, for expansions that have at least one sealed product."""
    preferred, other = defaultdict(list), defaultdict(list)
    for product in nonsingles['products']:
        exp = product.get('idExpansion')
        name = candidate(product.get('name') or '')
        if not exp or not name:
            continue
        category = product.get('categoryName') or ''
        target = preferred if ('Booster' in category or 'Display' in category) else other
        target[exp].append(name)
    names = {}
    for exp in preferred.keys() | other.keys():
        counts = Counter(preferred.get(exp) or other[exp])
        names[exp] = min(counts, key=lambda n: (-counts[n], len(n), n))
    return names


def load_overrides(game):
    data = json.loads((files('pulse') / 'expansion_overrides.json').read_text())
    return {int(k): v for k, v in data.get(game, {}).items()}


def refresh_expansions(conn, game, nonsingles):
    """Store derived names (overrides win) for the game's expansions; returns how many were named."""
    names = derive_names(nonsingles) | load_overrides(game)
    with conn.cursor() as cur:
        cur.executemany(
            'INSERT INTO expansion (game, id_expansion, name) VALUES (%s, %s, %s) '
            'ON CONFLICT (game, id_expansion) DO UPDATE SET name = EXCLUDED.name',
            [(game, exp, name) for exp, name in names.items()],
        )
    conn.commit()
    return len(names)
