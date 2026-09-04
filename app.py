"""
Cygan Flight Radar — mini backend (Flask)
==========================================

Po co to jest?
---------------
GitHub Pages (i każdy inny hosting statyczny) nie potrafi uruchomić
Pythona ani żadnego serwera — umie tylko wysyłać gotowe pliki
(HTML/CSS/JS). Strona flight radaru natomiast musi CO KILKA SEKUND
pobierać świeże dane o samolotach z zewnętrznego źródła (ADS-B).

Część publicznych API z danymi ADS-B (adsb.lol, airplanes.live,
adsb.one) nie zawsze pozwala, żeby przeglądarka pytała je
BEZPOŚREDNIO (blokada CORS) — ale nie ma z tym żadnego problemu,
kiedy pyta je SERWER (bo CORS dotyczy tylko przeglądarek).

Dlatego ten mały serwer:
1) sam, po stronie Pythona, pyta po kolei kilka publicznych API
   o samoloty w okolicy Polski,
2) zwraca gotowy wynik Twojej stronie w formacie, jakiego ona
   oczekuje,
3) dokłada nagłówek CORS, żeby Twoja strona (na GitHub Pages,
   na dowolnej domenie) mogła go bez przeszkód odpytywać.

Jak uruchomić lokalnie
-----------------------
    pip install -r requirements.txt
    python app.py

Domyślnie wystartuje na http://127.0.0.1:8000/api/flights

Jak wystawić w internecie (za darmo)
-------------------------------------
Patrz plik DEPLOY.md w tym samym folderze — krok po kroku dla Render.com.
"""

import os
import time

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)

# Zezwalamy każdej stronie (dowolna domena, w tym GitHub Pages)
# na odpytywanie tego backendu.
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Środek Polski + promień w milach morskich (250 nm to maksimum,
# jakie akceptują te API). Można nadpisać zmienną środowiskową,
# gdybyś chciał inny region.
CENTER_LAT = float(os.environ.get("RADAR_LAT", "51.92"))
CENTER_LON = float(os.environ.get("RADAR_LON", "19.15"))
RADIUS_NM = float(os.environ.get("RADAR_RADIUS_NM", "250"))

# Kilka niezależnych, kompatybilnych ze sobą API (ten sam format
# odpowiedzi: {"ac": [...]}). Próbujemy po kolei, aż któreś odpowie.
PROVIDERS = [
    "https://api.airplanes.live/v2/point/{lat}/{lon}/{radius}",
    "https://api.adsb.lol/v2/point/{lat}/{lon}/{radius}",
    "https://api.adsb.one/v2/point/{lat}/{lon}/{radius}",
]

REQUEST_TIMEOUT_S = 8


def fetch_raw_aircraft():
    """Pyta po kolei zewnętrzne API, zwraca listę surowych rekordów 'ac'."""

    last_error = None

    for template in PROVIDERS:
        url = template.format(
            lat=CENTER_LAT,
            lon=CENTER_LON,
            radius=RADIUS_NM,
        )

        try:
            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT_S,
                headers={"User-Agent": "cygan-flight-radar/1.0"},
            )
            response.raise_for_status()

            payload = response.json()
            aircraft = payload.get("ac")

            if isinstance(aircraft, list):
                return aircraft

        except Exception as error:  # noqa: BLE001 - celowo łapiemy wszystko
            last_error = error
            continue

    raise RuntimeError(
        f"Żadne źródło ADS-B nie odpowiedziało poprawnie "
        f"(ostatni błąd: {last_error})"
    )


def to_frontend_shape(ac):
    """
    Tłumaczy jeden rekord z surowego API (adsb.lol / airplanes.live / adsb.one)
    na format, jakiego oczekuje strona (index.html): wysokość w stopach,
    prędkość w węzłach, prędkość pionowa w ft/min — front sam przelicza
    to na metry.
    """

    alt_baro = ac.get("alt_baro")
    is_ground = isinstance(alt_baro, str) and alt_baro.strip().lower() == "ground"

    return {
        "icao24": ac.get("hex"),
        "callsign": (ac.get("flight") or "").strip(),
        "reg": ac.get("r"),
        "type": ac.get("t"),
        "model": ac.get("desc"),
        "manufacturer": None,
        "operator": ac.get("ownOp"),
        "country": None,
        "lat": ac.get("lat"),
        "lon": ac.get("lon"),
        # "ground" jako string oznacza samolot na ziemi — front to rozumie.
        "altitude": "ground" if is_ground else alt_baro,
        "speed": ac.get("gs"),
        "heading": ac.get("track"),
        "vertical_rate": ac.get("baro_rate"),
        "squawk": ac.get("squawk"),
        "category": ac.get("category"),
        "last_contact": int(time.time() - float(ac.get("seen") or 0)),
        "source": "ADS-B",
    }


@app.get("/api/flights")
def get_flights():

    try:
        raw = fetch_raw_aircraft()

        flights = [
            to_frontend_shape(ac)
            for ac in raw
            if ac.get("lat") is not None and ac.get("lon") is not None
        ]

        return jsonify({"ok": True, "flights": flights})

    except Exception as error:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(error)}), 502


@app.get("/")
def health():
    return jsonify({
        "status": "ok",
        "info": "Backend działa. Dane lotów pod /api/flights",
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
