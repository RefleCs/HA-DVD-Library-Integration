import json
import urllib.parse
import urllib.request

BASE_URL = "https://www.omdbapi.com/"

def fetch_omdb(api_key: str, title: str | None = None, imdb_id: str | None = None, year: str | None = None):
    if not api_key:
        return None
    params = {"apikey": api_key, "type": "movie"}
    if imdb_id:
        params["i"] = imdb_id
    elif title:
        params["t"] = title
        if year:
            params["y"] = year
    else:
        return None

    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if data.get("Response") != "True":
        return None
    return {
        "title": data.get("Title"),
        "year": data.get("Year"),
        "imdb_id": data.get("imdbID"),
        "runtime": data.get("Runtime"),
        "genres": data.get("Genre"),
        "director": data.get("Director"),
        "actors": data.get("Actors"),
        "plot": data.get("Plot"),
        "poster": data.get("Poster") if data.get("Poster") and data.get("Poster") != "N/A" else None,
        "imdb_rating": data.get("imdbRating"),
        "rated": data.get("Rated"),
        "released": data.get("Released"),
        "language": data.get("Language"),
        "country": data.get("Country"),
        "awards": data.get("Awards"),
    }