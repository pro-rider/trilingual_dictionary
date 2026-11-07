"""Text analysis engine: paragraph/sentence → segmented trilingual meanings.

Handles single words, compound words (水果 → fruit, not 水+果), phrases and
idioms (each gets its own meaning), with local-dictionary-first lookup and a
single batched AI call as the fallback.
"""
