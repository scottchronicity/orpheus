"""Shared taxonomy constants for corvid species detection.

Centralises corvid species codes so that agents (BirdNET, Crow Classifier)
and the UI all agree on the same set of identifiers.  Every code listed in
``CORVID_SPECIES`` is the **first six lowercase characters** of the
scientific name — the format produced by the BirdNET label parser.

``CROW_UI_CODES`` is the union of codes the frontend should use when
filtering for "crow" entities (includes the generic ``crow`` code
emitted by the dedicated Crow Classifier agent).
"""

# 6-character lowercase scientific-name prefixes that match parser output.
CORVID_SPECIES: set[str] = {
    # Crows & Ravens (Corvus sp.)
    "corvus",
    # Jackdaws (Coloeus sp.)
    "coloeu",
    # Eurasian Jays (Garrulus sp.)
    "garrul",
    # Magpies (Pica pica -> picapi)
    "picapi",
    # Blue & Steller's Jays (Cyanocitta sp.)
    "cyanoc",
    # Scrub-Jays (Aphelocoma sp.)
    "aphelo",
    # Nutcrackers (Nucifraga sp.)
    "nucifr",
    # Gray Jays (Perisoreus sp.)
    "periso",
    # Pinyon Jay (Gymnorhinus sp.)
    "gymnor",
    # Choughs (Pyrrhocorax sp.)
    "pyrrho",
    # Blue Magpies (Urocissa sp.)
    "urocis",
    # Green Magpies (Cissa sp.)
    "cissa",
    # Treepies (Dendrocitta sp.)
    "dendro",
}

# Codes the UI should use when querying for crow/corvid entities.
# Includes the generic "crow" code emitted by the Crow Classifier agent.
CROW_UI_CODES: set[str] = {"corvus", "crow"}
