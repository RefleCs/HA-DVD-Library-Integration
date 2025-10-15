
from __future__ import annotations

import json
import urllib.parse
import urllib.request

BASE_URL = "https://www.omdbapi.com/"

def fetch_omdb(api_key: str | None, title: str | None, imdb_id: str | None, year: str | None) -> dict | None:
    """Blocking HTTP fetch to OMDb (called in an executor)."""
    if not api_key:
        return None

    params: dict[str, str] = {"apikey": api_key, "type": "movie"}

    if imdb_id:
        params["i"] = imdb_id
    elif title:
        params["t"] = title
    else:
        return None

    if year:
        params["y"] = str(year)

    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if str(data.get("Response")) != "True":
        return None

    poster = data.get("Poster")
    if poster == "N/A":
        poster = None

    return {
        "title": data.get("Title"),
        "year": data.get("Year"),
        "imdb_id": data.get("imdbID"),
        "runtime": data.get("Runtime"),
        "genres": data.get("Genre"),
        "director": data.get("Director"),
        "actors": data.get("Actors"),
        "plot": data.get("Plot"),
        "poster": poster,
        "imdb_rating": data.get("imdbRating"),
        "rated": data.get("Rated"),
        "released": data.get("Released"),
        "language": data.get("Language"),
        "country": data.get("Country"),
        "awards": data.get("Awards"),
    }
