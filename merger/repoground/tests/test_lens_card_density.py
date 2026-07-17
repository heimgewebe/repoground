from __future__ import annotations

import json
import unittest

from merger.repoground.core.lens_cards import produce_lens_card_collection
from merger.repoground.core.lens_facets import DOES_NOT_ESTABLISH


PATHS = [
    "merger/repoground/core/lens_cards.py",
    "merger/repoground/core/lens_facets.py",
    "docs/proofs/lens-card-v1-proof.md",
]


def _encoded(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class LensCardDensityTests(unittest.TestCase):
    def test_verbose_density_preserves_self_contained_cards(self) -> None:
        collection = produce_lens_card_collection(PATHS)

        self.assertEqual(collection["density"], "verbose")
        self.assertEqual(
            collection["does_not_establish"],
            list(DOES_NOT_ESTABLISH),
        )
        self.assertTrue(
            all(
                card["does_not_establish"] == list(DOES_NOT_ESTABLISH)
                for card in collection["cards"]
            )
        )

    def test_compact_density_deduplicates_non_claims_at_collection_level(self) -> None:
        collection = produce_lens_card_collection(PATHS, density="compact")

        self.assertEqual(collection["density"], "compact")
        self.assertEqual(
            collection["does_not_establish"],
            list(DOES_NOT_ESTABLISH),
        )
        self.assertTrue(
            all(
                "does_not_establish" not in card
                for card in collection["cards"]
            )
        )

    def test_compact_cards_match_verbose_cards_except_for_non_claims(self) -> None:
        verbose = produce_lens_card_collection(PATHS, density="verbose")
        compact = produce_lens_card_collection(PATHS, density="compact")
        expected_cards = [
            {
                key: value
                for key, value in card.items()
                if key != "does_not_establish"
            }
            for card in verbose["cards"]
        ]

        self.assertEqual(compact["cards"], expected_cards)

    def test_compact_density_reduces_serialized_size(self) -> None:
        verbose = produce_lens_card_collection(PATHS, density="verbose")
        compact = produce_lens_card_collection(PATHS, density="compact")

        self.assertLess(len(_encoded(compact)), len(_encoded(verbose)))

    def test_invalid_density_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "density must be one of"):
            produce_lens_card_collection(PATHS, density="tiny")


if __name__ == "__main__":
    unittest.main()
