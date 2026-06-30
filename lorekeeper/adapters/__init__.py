"""Adapters — concrete implementations of the ports.

Each adapter is the *only* place a vendor SDK or transport detail appears
(LINE API, Notion client, OpenRouter SDK, filesystem). The pipeline depends on
`lorekeeper.ports`, never on anything in here.
"""
