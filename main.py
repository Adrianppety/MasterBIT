"""FastAPI backend for the MasterBIT TCG price reference."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError

LOGGER = logging.getLogger("masterbit.api")
POKEMON_TCG_API = os.getenv("POKEMON_TCG_API", "https://api.pokemontcg.io/v2")
TCGDEX_API = "https://api.tcgdex.net/v2/en"
POKEMON_TCG_API_KEY = os.getenv("POKEMON_TCG_API_KEY")
SETS_CACHE_TTL = int(os.getenv("SETS_CACHE_TTL_SECONDS", "43200"))
CARDS_CACHE_TTL = int(os.getenv("CARDS_CACHE_TTL_SECONDS", "3600"))
PACKS_FILE_TTL = int(os.getenv("PACKS_FILE_TTL_SECONDS", "43200"))
PACK_CARDS_FILE_TTL = int(os.getenv("PACK_CARDS_FILE_TTL_SECONDS", "86400"))
PACKS_CACHE_DIR = Path(
    os.getenv("MASTERBIT_PACKS_DIR", str(Path(__file__).resolve().parent / "API" / "packs"))
)
EXCHANGE_RATE_CACHE_TTL = int(os.getenv("EXCHANGE_RATE_CACHE_TTL_SECONDS", "3600"))
EXCHANGE_RATE_API = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=BRL"
MAX_CARD_RESULTS = int(os.getenv("MAX_CARD_RESULTS", "5000"))
SUPPORTED_LANGUAGES = {"br": "BR", "us": "US", "jp": "JP"}
VALID_PACK_ID = re.compile(r"^[a-zA-Z0-9_-]{1,50}$")


class Pack(BaseModel):
    id: str
    nome: str
    logo_url: str | None
    total_cartas: int
    idioma_nativo: str


class PackList(BaseModel):
    packs: list[Pack]


class Card(BaseModel):
    id: str
    nome: str
    colecao: str
    numero: str
    imagem_url: str
    imagem_detalhe_url: str
    raridade: str | None
    preco_usd: float | None
    preco_brl: float | None
    preco_brl_estimado: bool
    preco_fonte: str | None
    preco_data: str | None
    idioma: str


class CardList(BaseModel):
    cartas: list[Card]
    cotacao_usd_brl: float | None
    cotacao_data: str | None


class TTLCache:
    """Small process-local TTL cache with per-key single-flight loading."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._lock_guard = asyncio.Lock()

    async def get_or_load(
        self,
        key: str,
        ttl_seconds: int,
        loader: Callable[[], Awaitable[Any]],
    ) -> Any:
        now = time.monotonic()
        cached = self._entries.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]

        async with self._lock_guard:
            key_lock = self._locks.setdefault(key, asyncio.Lock())

        async with key_lock:
            now = time.monotonic()
            cached = self._entries.get(key)
            if cached is not None and cached[0] > now:
                return cached[1]

            value = await loader()
            self._entries[key] = (time.monotonic() + ttl_seconds, value)
            return value

    def clear(self) -> None:
        self._entries.clear()
        self._locks.clear()


sets_cache = TTLCache()
cards_cache = TTLCache()
exchange_rate_cache = TTLCache()


def _read_cache_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        LOGGER.warning("Ignoring invalid cache file %s", path)
        return None
    if not isinstance(payload, dict):
        LOGGER.warning("Ignoring cache file with invalid shape: %s", path)
        return None
    return payload


def _write_cache_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    cards = payload.get("cards")
    if isinstance(cards, list):
        fields = []
        for key, value in payload.items():
            encoded_key = json.dumps(key, ensure_ascii=False)
            if key == "cards":
                if cards:
                    encoded_value = "[\n" + ",\n".join(
                        f"    {json.dumps(card, ensure_ascii=False, separators=(',', ':'))}"
                        for card in cards
                    ) + "\n  ]"
                else:
                    encoded_value = "[]"
            else:
                encoded_value = json.dumps(value, ensure_ascii=False, indent=2).replace("\n", "\n  ")
            fields.append(f"  {encoded_key}: {encoded_value}")
        serialized = "{\n" + ",\n".join(fields) + "\n}\n"
    else:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    temporary_path.write_text(serialized, encoding="utf-8")
    os.replace(temporary_path, path)


def _cache_is_fresh(payload: dict[str, Any], ttl_seconds: int) -> bool:
    updated_at = payload.get("updated_at")
    return isinstance(updated_at, (int, float)) and time.time() - updated_at < ttl_seconds


def _schedule_cache_refresh(request: Request, key: str, loader: Callable[[], Awaitable[None]]) -> None:
    tasks: dict[str, asyncio.Task[None]] = request.app.state.cache_refresh_tasks
    task = tasks.get(key)
    if task is not None and not task.done():
        return

    async def refresh() -> None:
        try:
            await loader()
        except Exception:
            LOGGER.exception("Background cache refresh failed for %s", key)

    task = asyncio.create_task(refresh())
    tasks[key] = task

    def remove_completed_task(completed: asyncio.Task[None]) -> None:
        if tasks.get(key) is completed:
            tasks.pop(key, None)

    task.add_done_callback(remove_completed_task)


def _pack_name_from_index(pack_id: str) -> str | None:
    cached_index = _read_cache_file(PACKS_CACHE_DIR / "index.json")
    packs = cached_index.get("packs") if cached_index else None
    if not isinstance(packs, list):
        return None
    for pack in packs:
        if isinstance(pack, dict) and pack.get("id") == pack_id:
            name = pack.get("nome")
            return name if isinstance(name, str) and name.strip() else None
    return None


def _pack_filename_slug(pack_name: str) -> str:
    normalized_name = unicodedata.normalize("NFKD", pack_name)
    ascii_name = normalized_name.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.casefold()).strip("-") or "colecao"


def _pack_cards_path(pack_id: str, pack_name: str | None = None) -> Path:
    if not VALID_PACK_ID.fullmatch(pack_id):
        raise ValueError("Invalid pack identifier for cache file")

    legacy_path = PACKS_CACHE_DIR / f"{pack_id}.json"
    matches = sorted(PACKS_CACHE_DIR.glob(f"*--{pack_id}.json"))
    if matches:
        return matches[0]
    if legacy_path.is_file():
        return legacy_path

    resolved_name = pack_name or _pack_name_from_index(pack_id)
    if resolved_name:
        return PACKS_CACHE_DIR / f"{_pack_filename_slug(resolved_name)}--{pack_id}.json"
    return legacy_path


class PokemonTCGClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        headers = {"X-Api-Key": POKEMON_TCG_API_KEY} if POKEMON_TCG_API_KEY else {}
        for attempt in range(3):
            try:
                response = await self.client.get(
                    f"{POKEMON_TCG_API}/{path}",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500 and attempt < 2:
                    LOGGER.warning(
                        "Pokémon TCG API returned HTTP %s; retrying (%s/3)",
                        exc.response.status_code,
                        attempt + 2,
                    )
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                LOGGER.error("Pokémon TCG API returned HTTP %s", exc.response.status_code)
                raise HTTPException(
                    status_code=502,
                    detail="A API de cartas está temporariamente indisponível.",
                ) from exc
            except httpx.RequestError as exc:
                if attempt < 2:
                    LOGGER.warning("Pokémon TCG API request failed; retrying (%s/3)", attempt + 2)
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                LOGGER.error("Could not reach Pokémon TCG API: %s", exc)
                raise HTTPException(
                    status_code=502,
                    detail="Não foi possível consultar a API de cartas.",
                ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            LOGGER.error("Pokémon TCG API returned invalid JSON")
            raise HTTPException(
                status_code=502,
                detail="A API de cartas retornou uma resposta inválida.",
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="Resposta inválida da API de cartas.")
        return payload


async def get_pokemon_client(request: Request) -> PokemonTCGClient:
    return request.app.state.pokemon_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        follow_redirects=True,
    ) as client:
        app.state.http_client = client
        app.state.pokemon_client = PokemonTCGClient(client)
        app.state.cache_refresh_tasks = {}
        try:
            yield
        finally:
            refresh_tasks = list(app.state.cache_refresh_tasks.values())
            for task in refresh_tasks:
                task.cancel()
            if refresh_tasks:
                await asyncio.gather(*refresh_tasks, return_exceptions=True)


app = FastAPI(
    title="MasterBIT TCG API",
    description="API de consulta de cartas e valores de referência Pokémon TCG.",
    version="1.0.0",
    lifespan=lifespan,
)

# Development setting for local front ends. Restrict this to known origins in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/packs", response_model=PackList)
async def list_packs(
    request: Request,
    client: PokemonTCGClient = Depends(get_pokemon_client),
) -> PackList:
    async def load_sets() -> list[dict[str, Any]]:
        page = 1
        page_size = 50
        valid_sets: list[dict[str, Any]] = []
        while True:
            try:
                payload = await client.get("sets", page=page, pageSize=page_size)
            except HTTPException:
                if page_size == 25:
                    raise
                LOGGER.warning("Retrying Pokémon set listing with smaller pages")
                page_size = 25
                page = 1
                valid_sets.clear()
                continue
            batch = payload.get("data")
            if not isinstance(batch, list):
                raise HTTPException(
                    status_code=502,
                    detail="A API retornou uma lista de coleções inválida.",
                )
            valid_sets.extend(item for item in batch if isinstance(item, dict) and item.get("id"))
            total_count = int(payload.get("totalCount") or len(valid_sets))
            if not batch or len(valid_sets) >= total_count or len(batch) < page_size:
                break
            page += 1
        return sorted(
            valid_sets,
            key=lambda item: str(item.get("releaseDate") or ""),
            reverse=True,
        )

    async def load_tcgdex_sets() -> list[dict[str, Any]]:
        try:
            response = await request.app.state.http_client.get(f"{TCGDEX_API}/sets")
            response.raise_for_status()
            source_sets = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            LOGGER.error("Could not retrieve sets from TCGdex: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="Não foi possível carregar as coleções das fontes disponíveis.",
            ) from exc
        if not isinstance(source_sets, list):
            raise HTTPException(status_code=502, detail="A TCGdex retornou uma lista de coleções inválida.")

        sets_from_tcgdex: list[dict[str, Any]] = []
        for item in source_sets:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            counts = item.get("cardCount") if isinstance(item.get("cardCount"), dict) else {}
            sets_from_tcgdex.append(
                {
                    "id": _tcgdex_set_id_to_pokemon_id(str(item["id"])),
                    "name": item.get("name") or item["id"],
                    "total": counts.get("total") or counts.get("official") or 0,
                    "images": {"logo": item.get("logo")},
                    "releaseDate": item.get("releaseDate") or "",
                }
            )
        return sets_from_tcgdex

    async def load_sets_with_fallback() -> list[dict[str, Any]]:
        try:
            sets = await load_sets()
            if sets:
                return sets
        except HTTPException as exc:
            LOGGER.warning("Pokémon TCG set list unavailable; using TCGdex fallback: %s", exc.detail)
        LOGGER.warning("Using TCGdex fallback for collection list")
        return await load_tcgdex_sets()

    def map_packs(sets: list[dict[str, Any]]) -> list[Pack]:
        packs: list[Pack] = []
        for item in sets:
            images = item.get("images") if isinstance(item.get("images"), dict) else {}
            packs.append(
                Pack(
                    id=str(item["id"]),
                    nome=str(item.get("name") or item["id"]),
                    logo_url=images.get("logo"),
                    total_cartas=int(item.get("total") or item.get("printedTotal") or 0),
                    idioma_nativo="US",
                )
            )
        return packs

    index_path = PACKS_CACHE_DIR / "index.json"

    async def refresh_index() -> None:
        sets = await load_sets_with_fallback()
        _write_cache_file(
            index_path,
            {
                "updated_at": time.time(),
                "packs": [pack.model_dump() for pack in map_packs(sets)],
            },
        )

    cached_index = _read_cache_file(index_path)
    if cached_index is not None:
        try:
            cached_packs = [Pack.model_validate(pack) for pack in cached_index["packs"]]
        except (KeyError, TypeError, ValidationError):
            LOGGER.warning("Ignoring invalid pack index cache: %s", index_path)
        else:
            if not _cache_is_fresh(cached_index, PACKS_FILE_TTL):
                _schedule_cache_refresh(request, "pack-index", refresh_index)
            return PackList(packs=cached_packs)

    sets = await sets_cache.get_or_load("all-sets", SETS_CACHE_TTL, load_sets_with_fallback)
    packs = map_packs(sets)
    _write_cache_file(
        index_path,
        {
            "updated_at": time.time(),
            "packs": [pack.model_dump() for pack in packs],
        },
    )
    return PackList(packs=packs)


def _escape_query_term(term: str) -> str:
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", term)


def _tcgdex_set_id_to_pokemon_id(set_id: str) -> str:
    match = re.fullmatch(r"sv0*(\d+)(?:\.(\d+))?", set_id, re.IGNORECASE)
    if not match:
        return set_id
    set_number, subset = match.groups()
    return f"sv{int(set_number)}" + (f"pt{subset}" if subset else "")


def _pokemon_set_id_to_tcgdex_set_id(set_id: str) -> str:
    match = re.fullmatch(r"sv(\d+)pt(\d+)", set_id, re.IGNORECASE)
    if not match:
        return set_id
    set_number, subset = match.groups()
    return f"sv{int(set_number):02d}.{subset}"


def _build_card_query(pack_id: str | None, search: str | None) -> str | None:
    clauses: list[str] = []
    if pack_id:
        clauses.append(f"set.id:{pack_id}")
    if search:
        clauses.append(f"name:*{_escape_query_term(search.strip())}*")
    return " ".join(clauses) or None


async def _fetch_cards_from_api(
    client: PokemonTCGClient,
    pack_id: str | None,
    search: str | None,
) -> list[dict[str, Any]]:
    query = _build_card_query(pack_id, search)
    page = 1
    cards: list[dict[str, Any]] = []

    while len(cards) < MAX_CARD_RESULTS:
        params: dict[str, Any] = {"page": page, "pageSize": 250}
        if query:
            params["q"] = query
        payload = await client.get("cards", **params)
        batch = payload.get("data")
        if not isinstance(batch, list):
            raise HTTPException(status_code=502, detail="A API retornou uma lista de cartas inválida.")
        cards.extend(item for item in batch if isinstance(item, dict))
        total_count = int(payload.get("totalCount") or len(cards))
        if not pack_id or not batch or len(cards) >= total_count or len(batch) < 250:
            break
        page += 1

    return cards[:MAX_CARD_RESULTS]


async def _fetch_cards_from_tcgdex(request: Request, pack_id: str) -> list[dict[str, Any]]:
    tcgdex_pack_id = _pokemon_set_id_to_tcgdex_set_id(pack_id)
    url = f"{TCGDEX_API}/sets/{tcgdex_pack_id}"
    try:
        response = await request.app.state.http_client.get(url)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        LOGGER.error("TCGdex card lookup failed for pack %s: %s", pack_id, exc)
        raise HTTPException(
            status_code=502,
            detail="A fonte alternativa de cartas também está indisponível.",
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("cards"), list):
        raise HTTPException(
            status_code=502,
            detail="A fonte alternativa retornou uma lista de cartas inválida.",
        )

    set_name = str(payload.get("name") or pack_id)
    cards: list[dict[str, Any]] = []
    for item in payload["cards"]:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        local_id = str(item.get("localId") or "")
        image_base = item.get("image")
        image_base = image_base.rstrip("/") if isinstance(image_base, str) else ""
        image_number = local_id.lstrip("0") or local_id
        cards.append(
            {
                "id": f"{pack_id}-{local_id}",
                "name": str(item["name"]),
                "number": image_number,
                "rarity": None,
                "set": {"id": pack_id, "name": set_name},
                "images": {
                    "small": f"{image_base}/low.png" if image_base else "",
                    "large": f"{image_base}/high.png" if image_base else "",
                },
                "tcgplayer": {"prices": {}},
            }
        )
    return cards


def _filter_cards_by_search(cards: list[dict[str, Any]], search: str | None) -> list[dict[str, Any]]:
    if not search:
        return cards
    normalized_search = search.casefold()
    return [
        card for card in cards
        if normalized_search in str(card.get("name") or "").casefold()
    ]


async def _load_pack_cards(
    request: Request,
    client: PokemonTCGClient,
    pack_id: str,
) -> list[dict[str, Any]]:
    cache_path = _pack_cards_path(pack_id)

    def write_pack_cache(cards: list[dict[str, Any]]) -> None:
        pack_name = _pack_name_from_index(pack_id)
        if not pack_name and cards:
            set_data = cards[0].get("set")
            if isinstance(set_data, dict) and isinstance(set_data.get("name"), str):
                pack_name = set_data["name"]
        destination = _pack_cards_path(pack_id, pack_name)
        payload: dict[str, Any] = {
            "pack_id": pack_id,
            "updated_at": time.time(),
            "cards": cards,
        }
        if pack_name:
            payload["pack_name"] = pack_name
        _write_cache_file(destination, payload)

    async def fetch_pack_cards() -> list[dict[str, Any]]:
        try:
            cards = await _fetch_cards_from_api(client, pack_id, None)
            if cards:
                return cards
            LOGGER.warning("Pokémon TCG API returned no cards for pack %s; using TCGdex", pack_id)
        except HTTPException as primary_error:
            LOGGER.warning(
                "Pokémon TCG API card lookup failed for pack %s; using TCGdex: %s",
                pack_id,
                primary_error.detail,
            )

        try:
            return await _fetch_cards_from_tcgdex(request, pack_id)
        except HTTPException as fallback_error:
            LOGGER.error(
                "Both card sources failed for pack %s: %s",
                pack_id,
                fallback_error.detail,
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "Não foi possível carregar as cartas: a fonte principal e a fonte "
                    "alternativa estão indisponíveis. Tente novamente mais tarde."
                ),
            ) from fallback_error

    async def refresh_pack_cache() -> None:
        cards = await fetch_pack_cards()
        if cached_cards is not None:
            cards = _preserve_cached_prices(cards, cached_cards)
        write_pack_cache(cards)

    cached_pack = _read_cache_file(cache_path)
    cached_cards = cached_pack.get("cards") if cached_pack is not None else None
    if not isinstance(cached_cards, list) or not all(isinstance(card, dict) for card in cached_cards):
        cached_cards = None
    if cached_pack is not None and cached_pack.get("pack_id") != pack_id:
        cached_cards = None
    if cached_pack is not None:
        if (
            cached_pack.get("pack_id") == pack_id
            and cached_cards is not None
        ):
            if not _cache_is_fresh(cached_pack, PACK_CARDS_FILE_TTL):
                _schedule_cache_refresh(request, f"pack:{pack_id}", refresh_pack_cache)
            return cached_cards
        LOGGER.warning("Ignoring invalid card pack cache: %s", cache_path)

    async def fetch_and_cache() -> list[dict[str, Any]]:
        cards = await fetch_pack_cards()
        if cached_cards is not None:
            cards = _preserve_cached_prices(cards, cached_cards)
        write_pack_cache(cards)
        return cards

    return await cards_cache.get_or_load(
        f"pack-file:{pack_id}",
        CARDS_CACHE_TTL,
        fetch_and_cache,
    )


def _market_price(prices: Any) -> float | None:
    if not isinstance(prices, dict):
        return None
    preferred = ("holofoil", "normal", "reverseHolofoil", "1stEditionHolofoil", "unlimitedHolofoil")
    for variant in preferred:
        data = prices.get(variant)
        if not isinstance(data, dict):
            continue
        value = data.get("market")
        if value is None:
            value = data.get("marketPrice")
        if value is None:
            value = data.get("midPrice")
        if isinstance(value, (int, float)) and value >= 0:
            return round(float(value), 2)
    return None


def _normalized_collector_number(value: Any) -> str:
    number = str(value or "").strip()
    match = re.fullmatch(r"0*(\d+)", number)
    return str(int(match.group(1))) if match else number


def _card_price_identity(card: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
    set_data = card.get("set") if isinstance(card.get("set"), dict) else {}
    card_id = str(card.get("id") or "").strip()
    set_id = str(set_data.get("id") or "").strip()
    name = str(card.get("name") or "").strip().casefold()
    number = _normalized_collector_number(card.get("number"))
    # The integrated Pokémon TCG API and the current TCGdex fallback are English datasets.
    language = str(card.get("language") or "US").strip().upper()
    if not all((card_id, set_id, name, number, language)):
        return None
    return card_id, set_id, name, number, language


def _preserve_cached_prices(
    cards: list[dict[str, Any]],
    cached_cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep a valid stored quote when a refresh omits or invalidates it."""
    cached_prices: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for cached_card in cached_cards:
        identity = _card_price_identity(cached_card)
        tcgplayer = cached_card.get("tcgplayer")
        if identity and isinstance(tcgplayer, dict) and _market_price(tcgplayer.get("prices")) is not None:
            cached_prices[identity] = tcgplayer

    merged_cards: list[dict[str, Any]] = []
    for card in cards:
        identity = _card_price_identity(card)
        current_tcgplayer = card.get("tcgplayer")
        stored_tcgplayer = cached_prices.get(identity) if identity else None
        if stored_tcgplayer is None:
            merged_cards.append(card)
            continue

        merged_card = dict(card)
        merged_tcgplayer = dict(stored_tcgplayer)
        if isinstance(current_tcgplayer, dict):
            merged_tcgplayer.update(current_tcgplayer)
        # A valid stored quote is authoritative under the pack data update rule.
        # Keep its original timestamp even if a refresh carries a newer quote.
        merged_tcgplayer["prices"] = stored_tcgplayer.get("prices")
        if isinstance(stored_tcgplayer.get("updatedAt"), str):
            merged_tcgplayer["updatedAt"] = stored_tcgplayer["updatedAt"]
        else:
            merged_tcgplayer.pop("updatedAt", None)
        merged_card["tcgplayer"] = merged_tcgplayer
        merged_cards.append(merged_card)
    return merged_cards


async def _fetch_usd_brl_rate(client: httpx.AsyncClient) -> tuple[float | None, str | None]:
    try:
        response = await client.get(EXCHANGE_RATE_API, timeout=3.0)
        response.raise_for_status()
        payload = response.json()
        rate = payload.get("rates", {}).get("BRL")
        rate_date = payload.get("date")
        if not isinstance(rate, (int, float)) or rate <= 0 or not isinstance(rate_date, str):
            raise ValueError("Invalid USD-BRL exchange-rate response")
        return float(rate), rate_date
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        LOGGER.warning("Could not load the USD-BRL exchange rate: %s", exc)
        return None, None


async def _get_usd_brl_rate(client: httpx.AsyncClient) -> tuple[float | None, str | None]:
    return await exchange_rate_cache.get_or_load(
        "USD-BRL",
        EXCHANGE_RATE_CACHE_TTL,
        lambda: _fetch_usd_brl_rate(client),
    )


def _card_language(data: dict[str, Any]) -> str:
    # The upstream Pokémon TCG API currently exposes the English card dataset.
    return "US"


def _make_card(data: dict[str, Any], usd_brl_rate: float | None) -> Card:
    set_data = data.get("set") if isinstance(data.get("set"), dict) else {}
    images = data.get("images") if isinstance(data.get("images"), dict) else {}
    tcgplayer = data.get("tcgplayer") if isinstance(data.get("tcgplayer"), dict) else {}
    usd_price = _market_price(tcgplayer.get("prices"))
    estimated_brl = usd_price is not None and usd_brl_rate is not None
    quote_date = tcgplayer.get("updatedAt")
    return Card(
        id=str(data.get("id") or ""),
        nome=str(data.get("name") or "Carta sem nome"),
        colecao=str(set_data.get("name") or ""),
        numero=str(data.get("number") or ""),
        imagem_url=str(images.get("small") or images.get("large") or ""),
        imagem_detalhe_url=str(images.get("large") or images.get("small") or ""),
        raridade=data.get("rarity"),
        preco_usd=usd_price,
        preco_brl=round(usd_price * usd_brl_rate, 2) if estimated_brl else None,
        preco_brl_estimado=estimated_brl,
        preco_fonte="TCGplayer" if usd_price is not None else None,
        preco_data=quote_date if usd_price is not None and isinstance(quote_date, str) else None,
        idioma=_card_language(data),
    )


@app.get("/api/cards", response_model=CardList)
async def list_cards(
    request: Request,
    pack_id: str | None = Query(default=None, max_length=50),
    search: str | None = Query(default=None, max_length=100),
    lang: str | None = Query(default=None, pattern="^(br|us|jp)$"),
    sort: str | None = Query(default=None, pattern="^(price_asc|price_desc|name)$"),
    client: PokemonTCGClient = Depends(get_pokemon_client),
) -> CardList:
    if pack_id and not VALID_PACK_ID.fullmatch(pack_id):
        raise HTTPException(status_code=422, detail="Identificador de coleção inválido.")

    normalized_search = search.strip() if search and search.strip() else None
    if pack_id:
        card_data_task = _load_pack_cards(request, client, pack_id)
    else:
        cards_key = f"cards:*:{normalized_search or '*'}"
        card_data_task = cards_cache.get_or_load(
            cards_key,
            CARDS_CACHE_TTL,
            lambda: _fetch_cards_from_api(client, None, normalized_search),
        )
    cards_data, (rate, rate_date) = await asyncio.gather(
        card_data_task,
        _get_usd_brl_rate(request.app.state.http_client),
    )
    if pack_id:
        cards_data = _filter_cards_by_search(cards_data, normalized_search)

    requested_language = SUPPORTED_LANGUAGES.get(lang or "")
    if requested_language:
        cards_data = [item for item in cards_data if _card_language(item) == requested_language]

    cards = [_make_card(item, rate) for item in cards_data]
    if sort == "price_asc":
        cards.sort(
            key=lambda card: (
                card.preco_brl is None,
                card.preco_brl if card.preco_brl is not None else 0,
            )
        )
    elif sort == "price_desc":
        cards.sort(
            key=lambda card: (
                card.preco_brl is None,
                -(card.preco_brl if card.preco_brl is not None else 0),
            )
        )
    elif sort == "name":
        cards.sort(key=lambda card: card.nome.casefold())
    return CardList(cartas=cards, cotacao_usd_brl=rate, cotacao_data=rate_date)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
