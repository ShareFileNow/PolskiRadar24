import json
import os
import threading
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from urllib.request import Request, urlopen


# ============================================================
# SERVER CONFIG
# ============================================================

# 0.0.0.0 = pozwala serwerowi przyjmować połączenia z internetu
HOST = "0.0.0.0"

# Hosting zwykle daje własny PORT przez zmienną środowiskową.
# Lokalnie nadal będzie działać na 8080.
PORT = int(os.environ.get("PORT", 8080))


# ============================================================
# ADS-B API
# ============================================================

OPENSKY_URL = (
    "https://api.adsb.lol/v2/"
    "lat/52.23/"
    "lon/21.01/"
    "dist/300"
)

UPDATE_SECONDS = 3

# ============================================================
# ROUTE API
# ============================================================

ROUTE_URL = "https://api.adsb.lol/api/0/routeset"
ROUTE_CACHE_SECONDS = 900

route_cache = {}


# ============================================================
# GLOBAL DATA
# ============================================================

states = []
last_update = 0
last_error = ""

data_lock = threading.Lock()


# ============================================================
# HELPERS
# ============================================================

def to_bool(value):
    """Normalizuje flagi API: bool, liczby oraz teksty 0/1."""

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        return value.strip().lower() in {
            "true",
            "1",
            "yes",
            "y",
            "on"
        }

    return False


def is_ground_altitude(value):
    """adsb.lol może oznaczyć wysokość jako 'ground'."""

    return (
        isinstance(value, str)
        and value.strip().lower() == "ground"
    )


# ============================================================
# ROUTE LOOKUP
# ============================================================

def clean_callsign(value):
    if value is None:
        return ""
    return str(value).strip().upper()


def safe_route_value(value):
    if value is None:
        return "N/A"

    value = str(value).strip()

    if not value or value in {"...", "…", "null", "None"}:
        return "N/A"

    return value


def route_from_item(item):
    airports = item.get("_airports") or []
    names = []

    for airport in airports:
        if not isinstance(airport, dict):
            continue

        location = str(
            airport.get("location") or ""
        ).strip()

        if location:
            names.append(location)

    if len(names) >= 2:
        return f"{names[0]}-{names[-1]}"

    codes = str(
        item.get("_airport_codes_iata") or ""
    ).strip()

    return codes if codes else "N/A"


def fetch_routes(aircraft_list):
    """Pobiera trasy z ADSB.lol. Maksymalnie 100 samolotów na request."""

    if not aircraft_list:
        return {}

    planes = []

    for aircraft in aircraft_list:
        callsign = clean_callsign(
            aircraft.get("callsign")
        )

        lat = aircraft.get("lat")
        lon = aircraft.get("lon")

        if not callsign or lat is None or lon is None:
            continue

        planes.append({
            "callsign": callsign,
            "lat": lat,
            "lng": lon,
        })

    result = {}

    for start in range(0, len(planes), 100):
        chunk = planes[start:start + 100]

        try:
            body = json.dumps({
                "planes": chunk
            }).encode("utf-8")

            request = Request(
                ROUTE_URL,
                data=body,
                headers={
                    "User-Agent": "MyFlightRadar/Ultimate",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                method="POST",
            )

            with urlopen(request, timeout=12) as response:
                raw = response.read()

            data = json.loads(
                raw.decode("utf-8")
            )

            if not isinstance(data, list):
                continue

            for item in data:
                if not isinstance(item, dict):
                    continue

                callsign = clean_callsign(
                    item.get("callsign")
                )

                if not callsign:
                    continue

                route = safe_route_value(
                    route_from_item(item)
                )

                if route != "N/A":
                    result[callsign] = route

        except Exception as e:
            # Awaria route API NIE może wyłączyć ADS-B.
            print(
                "[ROUTE] Błąd:",
                type(e).__name__,
                str(e),
            )

    return result


def apply_routes(aircraft_list):
    """Dodaje trasy, używając cache i zachowując poprzednią trasę."""

    now = time.time()
    lookup = []

    for aircraft in aircraft_list:
        callsign = clean_callsign(
            aircraft.get("callsign")
        )

        if not callsign:
            aircraft["route"] = "N/A"
            continue

        cached = route_cache.get(callsign)

        if cached:
            cached_route = safe_route_value(
                cached.get("route")
            )

            cached_time = cached.get("time", 0)

            if (
                cached_route != "N/A"
                and now - cached_time < ROUTE_CACHE_SECONDS
            ):
                aircraft["route"] = cached_route
                continue

        lookup.append(aircraft)

    if not lookup:
        return

    fresh_routes = fetch_routes(lookup)

    for aircraft in lookup:
        callsign = clean_callsign(
            aircraft.get("callsign")
        )

        if callsign in fresh_routes:
            route = safe_route_value(
                fresh_routes[callsign]
            )

            route_cache[callsign] = {
                "route": route,
                "time": now,
            }

            aircraft["route"] = route

        else:
            # Błąd routeset nie kasuje poprzedniej dobrej trasy.
            old = route_cache.get(callsign)

            aircraft["route"] = (
                safe_route_value(old.get("route"))
                if old
                else "N/A"
            )


def route_worker(cleaned):
    try:
        apply_routes(cleaned)

        # Aktualizujemy listę dopiero po zakończeniu route lookup.
        with data_lock:
            if states is cleaned:
                states = list(cleaned)

    except Exception as e:
        print(
            "[ROUTE] Worker error:",
            type(e).__name__,
            str(e),
        )


# ============================================================
# FETCH ADS-B
# ============================================================

def fetch_opensky():

    global states
    global last_update
    global last_error

    print("[ADS-B] Pobieranie danych...")

    try:

        request = Request(
            OPENSKY_URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "MyFlightRadar/Ultimate"
                ),
                "Accept": "application/json"
            }
        )

        with urlopen(request, timeout=25) as response:
            raw = response.read()

        data = json.loads(
            raw.decode("utf-8")
        )

        new_states = data.get("ac") or []

        cleaned = []

        for item in new_states:

            if not item:
                continue

            lat = item.get("lat")
            lon = item.get("lon")

            if lat is None or lon is None:
                continue

            # Rejestracja
            reg_val = (
                item.get("r")
                or item.get("registration")
                or ""
            )

            if not isinstance(reg_val, str):
                reg_val = str(reg_val)

            # Wysokość
            baro_altitude = item.get(
                "alt_baro",
                item.get("alt_geom")
            )

            aircraft = {

                "icao24":
                    item.get("hex", ""),

                "callsign":
                    (item.get("flight") or "").strip(),

                "country":
                    item.get("t", ""),

                "reg":
                    reg_val.strip(),

                "type":
                    item.get("t", ""),

                "lon":
                    lon,

                "lat":
                    lat,

                "altitude":
                    baro_altitude,

                "on_ground":
                    (
                        is_ground_altitude(baro_altitude)
                        or
                        to_bool(
                            item.get(
                                "ground",
                                item.get(
                                    "on_ground",
                                    False
                                )
                            )
                        )
                    ),

                "speed":
                    item.get("gs"),

                "heading":
                    item.get("track"),

                "vertical_rate":
                    item.get(
                        "baro_rate",
                        item.get("geom_rate")
                    ),

                "geo_altitude":
                    item.get("alt_geom"),

                "squawk":
                    item.get("squawk"),

                "category":
                    item.get(
                        "category",
                        "A0"
                    ),

                "route":
                    "N/A"
            }

            cleaned.append(aircraft)

        # Aktualizacja danych
        with data_lock:

            states = cleaned
            last_update = time.time()
            last_error = ""

        print(
            "[ADS-B] OK - aktywne samoloty: {}".format(
                len(cleaned)
            )
        )

        # Route API działa osobno, więc nie blokuje odświeżania ADS-B.
        threading.Thread(
            target=route_worker,
            args=(cleaned,),
            daemon=True,
        ).start()

    except Exception as e:

        message = "{}: {}".format(
            type(e).__name__,
            str(e)
        )

        with data_lock:
            last_error = message

        print(
            "[ADS-B] BŁĄD:",
            message
        )


# ============================================================
# BACKGROUND UPDATER
# ============================================================

def updater():

    while True:

        fetch_opensky()

        time.sleep(
            UPDATE_SECONDS
        )


# ============================================================
# HTTP HANDLER
# ============================================================

class Handler(SimpleHTTPRequestHandler):

    def log_message(
        self,
        format_string,
        *args
    ):
        # Wyłączamy spam z logów HTTP.
        pass


    # --------------------------------------------------------
    # JSON RESPONSE
    # --------------------------------------------------------

    def send_json(
        self,
        data,
        status=200
    ):

        body = json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":")
        ).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        # CORS:
        # pozwala frontendowi z GitHub Pages
        # pytać ten backend.
        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, OPTIONS"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.send_header(
            "Cache-Control",
            "no-cache, no-store, must-revalidate"
        )

        self.end_headers()

        self.wfile.write(body)


    # --------------------------------------------------------
    # OPTIONS / CORS
    # --------------------------------------------------------

    def do_OPTIONS(self):

        self.send_response(204)

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, OPTIONS"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type"
        )

        self.end_headers()


    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    def do_GET(self):

        parsed = urlparse(
            self.path
        )

        path = parsed.path


        # ====================================================
        # FLIGHTS API
        # ====================================================

        if path == "/api/flights":

            with data_lock:

                response = {

                    "ok":
                        True,

                    "updated":
                        last_update,

                    "count":
                        len(states),

                    "error":
                        last_error,

                    "flights":
                        states
                }

            self.send_json(
                response
            )

            return


        # ====================================================
        # HEALTH CHECK
        # ====================================================

        if path == "/api/health":

            with data_lock:

                response = {

                    "ok":
                        True,

                    "updated":
                        last_update,

                    "count":
                        len(states),

                    "error":
                        last_error
                }

            self.send_json(
                response
            )

            return


        # ====================================================
        # FRONTEND
        # ====================================================

        if path == "/":

            self.path = "/index.html"


        return super().do_GET()


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "======================================"
    )

    print(
        "     MY FLIGHT RADAR ULTIMATE PRO"
    )

    print(
        "======================================"
    )

    print(
        "HOST: {}".format(HOST)
    )

    print(
        "PORT: {}".format(PORT)
    )

    print(
        "ADS-B: {}".format(OPENSKY_URL)
    )

    print(
        "ROUTES: {}".format(ROUTE_URL)
    )

    print(
        "======================================"
    )


    # --------------------------------------------------------
    # START ADS-B UPDATER
    # --------------------------------------------------------

    thread = threading.Thread(
        target=updater,
        daemon=True
    )

    thread.start()


    # --------------------------------------------------------
    # START HTTP SERVER
    # --------------------------------------------------------

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Handler
    )

    print(
        "SERWER URUCHOMIONY."
    )

    print(
        "API: /api/flights"
    )

    print(
        "Health: /api/health"
    )

    print(
        "======================================"
    )


    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print(
            "\nZatrzymywanie..."
        )

    finally:

        server.server_close()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
