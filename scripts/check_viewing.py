"""Run the viewing flow against real providers, in one event loop."""
import argparse
import asyncio

import httpx

from backend.core.redis import close_redis
from main import app


async def check(query, anime_id):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://check") as client:
        async def get(path, **params):
            response = await client.get("/api/v1/anime/" + path, params=params)
            if response.status_code != 200:
                print(path, response.status_code, response.text[:500], flush=True)
                return None
            return response.json()

        cards = await get("animego/search", q=query)
        if cards is None:
            return 1
        card = next((item for item in cards if item["external_id"] == anime_id), None)
        if card is None:
            print("Requested title not found in search", flush=True)
            return 1
        print("Title:", card["original_title"], "ID:", card["external_id"], flush=True)
        episodes = await get("animego/episodes", anime_id=anime_id)
        print("Episodes:", len(episodes["episodes"]) if episodes else None, flush=True)
        if episodes is None or not episodes["episodes"]:
            return 1
        voices = await get("animego/voices", anime_id=anime_id, episode=1)
        if voices is None:
            return 1
        print("Translations:", [(v["id"], v["player"]) for v in voices["translations"]], flush=True)
        for voice in voices["translations"]:
            if voice["player"] not in {"aniboom", "cvh", "kodik", "sibnet"}:
                continue
            stream = await get("animego/player", anime_id=anime_id, episode=1,
                               translation_id=voice["id"], player=voice["player"])
            if stream:
                async with httpx.AsyncClient(follow_redirects=True, timeout=15) as external:
                    response = await external.get(stream["embed_url"])
                print("Embedded player:", voice["player"], "HTTP", response.status_code, flush=True)
                if response.status_code == 200:
                    print("PASS: search, episodes, translation, embedded player. Video playback requires browser verification.", flush=True)
                    return 0
        return 1


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="Naruto")
    parser.add_argument("--anime-id", default="103")
    args = parser.parse_args()
    try:
        return await check(args.query, args.anime_id)
    finally:
        await close_redis()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
