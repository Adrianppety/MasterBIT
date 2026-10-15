from __future__ import annotations

import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

import main


class FakePokemonTCGClient:
    def __init__(self) -> None:
        self.card_requests = 0

    async def get(self, path: str, **params):
        if path == "sets":
            return {
                "data": [
                    {
                        "id": "sv3pt5",
                        "name": "151",
                        "total": 207,
                        "images": {"logo": "https://example.test/151.png"},
                    }
                ]
            }

        if path == "cards":
            self.card_requests += 1
            query = params.get("q", "")
            pack_id = (
                query.split("set.id:", 1)[1].split(" ", 1)[0]
                if "set.id:" in query
                else "sv3pt5"
            )
            pack_name = "151" if pack_id == "sv3pt5" else f"Collection {pack_id}"
            cards = [
                {
                    "id": f"{pack_id}-6",
                    "name": "Charizard ex",
                    "number": "6",
                    "rarity": "Double Rare",
                    "set": {"id": pack_id, "name": pack_name},
                    "images": {
                        "small": "https://example.test/card-small.png",
                        "large": "https://example.test/card-large.png",
                    },
                    "tcgplayer": {
                        "updatedAt": "2026/10/15",
                        "prices": {"holofoil": {"market": 115.25}}
                    },
                },
                {
                    "id": f"{pack_id}-7",
                    "name": "Wartortle",
                    "number": "7",
                    "rarity": "Uncommon",
                    "set": {"id": pack_id, "name": pack_name},
                    "images": {"small": "https://example.test/card-2.png"},
                    "tcgplayer": {"prices": {}},
                },
            ]
            if "Charizard" in params.get("q", ""):
                cards = cards[:1]
            return {
                "totalCount": len(cards),
                "data": cards,
            }
        raise AssertionError(f"Unexpected API resource: {path}")


class FakeTCGdexHttpClient:
    async def get(self, url: str):
        if url.endswith("/sets/sv03.5"):
            return httpx.Response(
                200,
                json={
                    "name": "151",
                    "cards": [
                        {
                            "id": "sv03.5-006",
                            "localId": "006",
                            "name": "Charizard ex",
                            "image": "https://assets.example.test/sv03.5/006",
                        },
                        {
                            "id": "sv03.5-007",
                            "localId": "007",
                            "name": "Squirtle",
                            "image": "https://assets.example.test/sv03.5/007",
                        },
                    ],
                },
                request=httpx.Request("GET", url),
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": "sv03.5",
                    "name": "151",
                    "logo": "https://example.test/151-logo.png",
                    "cardCount": {"total": 207, "official": 165},
                }
            ],
            request=httpx.Request("GET", url),
        )


class BackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache_directory = tempfile.TemporaryDirectory()
        self.cache_directory_patcher = patch.object(
            main,
            "PACKS_CACHE_DIR",
            Path(self.cache_directory.name),
        )
        self.cache_directory_patcher.start()
        main.sets_cache.clear()
        main.cards_cache.clear()
        main.exchange_rate_cache.clear()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()
        self.pokemon_client = FakePokemonTCGClient()
        self.client.app.state.pokemon_client = self.pokemon_client

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        main.sets_cache.clear()
        main.cards_cache.clear()
        main.exchange_rate_cache.clear()
        self.cache_directory_patcher.stop()
        self.cache_directory.cleanup()

    def test_packs_are_mapped_from_upstream_sets(self) -> None:
        response = self.client.get("/api/packs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["packs"],
            [
                {
                    "id": "sv3pt5",
                    "nome": "151",
                    "logo_url": "https://example.test/151.png",
                    "total_cartas": 207,
                    "idioma_nativo": "US",
                }
            ],
        )
        self.assertTrue((Path(self.cache_directory.name) / "index.json").is_file())

    def test_pack_cache_uses_readable_filename_and_one_card_per_line(self) -> None:
        cache_dir = Path(self.cache_directory.name)
        main._write_cache_file(
            cache_dir / "index.json",
            {
                "updated_at": 1,
                "packs": [{"id": "sv3pt5", "nome": "151"}],
            },
        )
        cache_path = main._pack_cards_path("sv3pt5")
        self.assertEqual(cache_path.name, "151--sv3pt5.json")

        payload = {
            "pack_id": "sv3pt5",
            "pack_name": "151",
            "updated_at": 1,
            "cards": [{"id": "sv3pt5-1", "name": "Bulbasaur"}, {"id": "sv3pt5-2", "name": "Ivysaur"}],
        }
        main._write_cache_file(cache_path, payload)

        lines = cache_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(cache_path.read_text(encoding="utf-8")), payload)
        self.assertEqual(
            [line.strip().rstrip(",") for line in lines if line.strip().startswith('{"id"')],
            [json.dumps(card, ensure_ascii=False, separators=(",", ":")) for card in payload["cards"]],
        )

    def test_packs_fall_back_to_tcgdex_when_pokemon_tcg_sets_are_unavailable(self) -> None:
        self.client.app.state.http_client = FakeTCGdexHttpClient()
        self.client.app.state.pokemon_client.get = AsyncMock(
            side_effect=main.HTTPException(status_code=502, detail="upstream unavailable")
        )

        response = self.client.get("/api/packs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["packs"][0]["id"], "sv3pt5")
        self.assertEqual(response.json()["packs"][0]["nome"], "151")

    @patch("main._fetch_usd_brl_rate", return_value=(5.0, "2026-10-15"))
    def test_cards_fall_back_to_tcgdex_when_pokemon_tcg_cards_are_unavailable(self, exchange_rate) -> None:
        self.client.app.state.http_client = FakeTCGdexHttpClient()
        self.client.app.state.pokemon_client.get = AsyncMock(
            side_effect=main.HTTPException(status_code=502, detail="upstream unavailable")
        )

        response = self.client.get("/api/cards?pack_id=sv3pt5&search=Charizard")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["cartas"],
            [
                {
                    "id": "sv3pt5-006",
                    "nome": "Charizard ex",
                    "colecao": "151",
                    "numero": "6",
                    "imagem_url": "https://assets.example.test/sv03.5/006/low.png",
                    "imagem_detalhe_url": "https://assets.example.test/sv03.5/006/high.png",
                    "raridade": None,
                    "preco_usd": None,
                    "preco_brl": None,
                    "preco_brl_estimado": False,
                    "preco_fonte": None,
                    "preco_data": None,
                    "idioma": "US",
                }
            ],
        )
        self.assertTrue((Path(self.cache_directory.name) / "151--sv3pt5.json").is_file())
        exchange_rate.assert_called_once()

        response = self.client.get("/api/packs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["packs"],
            [
                {
                    "id": "sv3pt5",
                    "nome": "151",
                    "logo_url": "https://example.test/151-logo.png",
                    "total_cartas": 207,
                    "idioma_nativo": "US",
                }
            ],
        )

    @patch("main._fetch_usd_brl_rate", return_value=(5.0, "2026-10-15"))
    def test_cards_return_usd_brl_conversion_and_language(self, exchange_rate) -> None:
        response = self.client.get("/api/cards?pack_id=sv3pt5&search=Charizard")
        cached_response = self.client.get("/api/cards?pack_id=sv3pt5&search=Charizard")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(cached_response.status_code, 200)
        self.assertEqual(cached_response.json(), response.json())
        self.assertEqual(response.json()["cotacao_usd_brl"], 5.0)
        self.assertEqual(response.json()["cotacao_data"], "2026-10-15")
        self.assertEqual(
            response.json()["cartas"],
            [
                {
                    "id": "sv3pt5-6",
                    "nome": "Charizard ex",
                    "colecao": "151",
                    "numero": "6",
                    "imagem_url": "https://example.test/card-small.png",
                    "imagem_detalhe_url": "https://example.test/card-large.png",
                    "raridade": "Double Rare",
                    "preco_usd": 115.25,
                    "preco_brl": 576.25,
                    "preco_brl_estimado": True,
                    "preco_fonte": "TCGplayer",
                    "preco_data": "2026/10/15",
                    "idioma": "US",
                }
            ],
        )
        exchange_rate.assert_called_once()
        self.assertEqual(self.pokemon_client.card_requests, 1)
        self.assertTrue((Path(self.cache_directory.name) / "151--sv3pt5.json").is_file())

    @patch("main._fetch_usd_brl_rate", return_value=(5.0, "2026-10-15"))
    def test_pack_search_uses_persisted_cards_without_another_upstream_request(self, exchange_rate) -> None:
        first_response = self.client.get("/api/cards?pack_id=sv3pt5")
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(self.pokemon_client.card_requests, 1)

        main.cards_cache.clear()
        search_response = self.client.get("/api/cards?pack_id=sv3pt5&search=Charizard")

        self.assertEqual(search_response.status_code, 200)
        self.assertEqual([card["nome"] for card in search_response.json()["cartas"]], ["Charizard ex"])
        self.assertEqual(self.pokemon_client.card_requests, 1)

    @patch("main._fetch_usd_brl_rate", return_value=(5.0, "2026-10-15"))
    def test_card_cache_is_separate_for_each_pack(self, exchange_rate) -> None:
        first = self.client.get("/api/cards?pack_id=sv3pt5")
        second = self.client.get("/api/cards?pack_id=me55")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["cartas"][0]["colecao"], "151")
        self.assertEqual(second.json()["cartas"][0]["colecao"], "Collection me55")
        self.assertEqual(self.pokemon_client.card_requests, 2)
        self.assertTrue((Path(self.cache_directory.name) / "151--sv3pt5.json").is_file())
        self.assertTrue((Path(self.cache_directory.name) / "collection-me55--me55.json").is_file())

    def test_valid_cached_quote_is_preserved_only_for_the_same_printing(self) -> None:
        stored = {
            "id": "me55-157",
            "name": "Mewtwo ex",
            "number": "157",
            "language": "US",
            "set": {"id": "me55", "name": "30th Celebration"},
            "tcgplayer": {
                "updatedAt": "2026/10/14",
                "prices": {"holofoil": {"market": 41.06}},
            },
        }
        refreshed = [
            {
                **stored,
                "number": "157",
                "tcgplayer": {"updatedAt": "2026/10/15", "prices": {"holofoil": {"market": 99.0}}},
            },
            {
                **stored,
                "tcgplayer": {"updatedAt": "2026/10/15", "prices": {"holofoil": {"market": -1}}},
            },
            {
                **stored,
                "id": "me5-157",
                "set": {"id": "me5", "name": "Pitch Black"},
                "tcgplayer": {"prices": {}},
            },
            {
                **stored,
                "id": "me55-156",
                "number": "156",
                "tcgplayer": {"prices": {}},
            },
            {
                **stored,
                "language": "JP",
                "tcgplayer": {"prices": {}},
            },
        ]

        merged = main._preserve_cached_prices(refreshed, [stored])

        self.assertEqual(main._market_price(merged[0]["tcgplayer"]["prices"]), 41.06)
        self.assertEqual(merged[0]["tcgplayer"]["updatedAt"], "2026/10/14")
        self.assertEqual(main._market_price(merged[1]["tcgplayer"]["prices"]), 41.06)
        self.assertEqual(merged[1]["tcgplayer"]["updatedAt"], "2026/10/14")
        self.assertTrue(all(main._market_price(card["tcgplayer"].get("prices")) is None for card in merged[2:]))

    def test_30th_card_without_a_source_quote_remains_unavailable(self) -> None:
        card = main._make_card(
            {
                "id": "me55-157",
                "name": "Mewtwo ex",
                "number": "157",
                "set": {"id": "me55", "name": "30th Celebration"},
                "tcgplayer": {"url": "https://prices.pokemontcg.io/tcgplayer/me55-157"},
            },
            5.0,
        )

        self.assertEqual((card.id, card.colecao, card.numero, card.idioma),
                         ("me55-157", "30th Celebration", "157", "US"))
        self.assertIsNone(card.preco_usd)
        self.assertIsNone(card.preco_brl)
        self.assertFalse(card.preco_brl_estimado)
        self.assertIsNone(card.preco_fonte)
        self.assertIsNone(card.preco_data)

    @patch("main._fetch_usd_brl_rate", return_value=(5.0, "2026-10-15"))
    def test_stale_pack_cache_still_serves_when_both_card_sources_fail(self, exchange_rate) -> None:
        cached_card = {
            "id": "me55-157",
            "name": "Mewtwo ex",
            "number": "157",
            "set": {"id": "me55", "name": "30th Celebration"},
            "images": {"small": "https://example.test/mewtwo.png"},
            "tcgplayer": {
                "updatedAt": "2026/10/14",
                "prices": {"holofoil": {"market": 41.06}},
            },
        }
        main._write_cache_file(
            Path(self.cache_directory.name) / "me55.json",
            {"pack_id": "me55", "updated_at": 1, "cards": [cached_card]},
        )
        self.client.app.state.pokemon_client.get = AsyncMock(
            side_effect=main.HTTPException(status_code=429, detail="rate limit")
        )
        self.client.app.state.http_client.get = AsyncMock(side_effect=httpx.ConnectError("offline"))

        response = self.client.get("/api/cards?pack_id=me55")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cartas"][0]["preco_usd"], 41.06)
        self.assertEqual(response.json()["cartas"][0]["preco_fonte"], "TCGplayer")
        self.assertEqual(response.json()["cartas"][0]["preco_data"], "2026/10/14")
        exchange_rate.assert_called_once()

    def test_card_details_show_price_source_and_date(self) -> None:
        app_js = (Path(__file__).resolve().parents[1] / "src" / "app.js").read_text(encoding="utf-8")
        index_html = (Path(__file__).resolve().parents[1] / "src" / "index.html").read_text(encoding="utf-8")

        self.assertIn("id=\"details-price-provenance\"", index_html)
        self.assertIn("card.preco_fonte", app_js)
        self.assertIn("card.preco_data", app_js)

    @patch("main._fetch_usd_brl_rate", return_value=(5.0, "2026-10-15"))
    def test_card_without_usd_price_does_not_receive_an_estimated_brl_price(self, exchange_rate) -> None:
        response = self.client.get("/api/cards?pack_id=sv3pt5")

        self.assertEqual(response.status_code, 200)
        wartortle = next(card for card in response.json()["cartas"] if card["nome"] == "Wartortle")
        self.assertIsNone(wartortle["preco_usd"])
        self.assertIsNone(wartortle["preco_brl"])
        self.assertFalse(wartortle["preco_brl_estimado"])
        self.assertIsNone(wartortle["preco_fonte"])
        self.assertIsNone(wartortle["preco_data"])
        exchange_rate.assert_called_once()

    def test_unsupported_language_returns_no_english_cards(self) -> None:
        response = self.client.get("/api/cards?pack_id=sv3pt5&lang=jp")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cartas"], [])

    def test_invalid_pack_id_is_rejected(self) -> None:
        response = self.client.get("/api/cards?pack_id=../../cards")

        self.assertEqual(response.status_code, 422)

    def test_card_query_does_not_add_invalid_empty_name_wildcard(self) -> None:
        self.assertEqual(main._build_card_query("sv3pt5", None), "set.id:sv3pt5")
        self.assertEqual(
            main._build_card_query("sv3pt5", "Charizard"),
            "set.id:sv3pt5 name:*Charizard*",
        )

    @patch("main._fetch_usd_brl_rate", return_value=(None, None))
    def test_missing_exchange_rate_leaves_brl_price_unavailable(self, exchange_rate) -> None:
        response = self.client.get("/api/cards?pack_id=sv3pt5&search=Charizard")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["cartas"][0]["preco_brl"])
        self.assertFalse(response.json()["cartas"][0]["preco_brl_estimado"])
        exchange_rate.assert_called_once()

    def test_cors_allows_local_development_frontend(self) -> None:
        response = self.client.get("/api/packs", headers={"Origin": "http://localhost:5500"})

        self.assertEqual(response.headers["access-control-allow-origin"], "*")

if __name__ == "__main__":
    unittest.main()
