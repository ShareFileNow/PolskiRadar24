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

UPDATE_SECONDS = 5


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
                    )
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
