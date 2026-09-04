# Jak wystawić ten backend w internecie (za darmo, Render.com)

Zajmie to ok. 5 minut. Render ma darmowy plan (aplikacja "usypia" po
15 min bezczynności i budzi się przy pierwszym żądaniu — pierwsze
odświeżenie po dłuższej przerwie może potrwać kilkanaście sekund,
kolejne już nie).

## 1. Wrzuć folder `backend/` do GitHuba

Możesz go wrzucić do TEGO SAMEGO repozytorium co `index.html`
(np. w podfolderze `backend/`) albo do osobnego repo — nie ma
znaczenia.

## 2. Załóż konto na render.com

https://render.com — logowanie przez GitHub jest najszybsze.

## 3. New + → Web Service

- Connect a repository → wybierz swoje repo z plikiem `app.py`
- **Root Directory**: `backend` (jeśli wrzuciłeś do podfolderu)
- **Runtime**: Python 3
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn app:app`
- **Plan**: Free

Kliknij **Create Web Service**.

## 4. Poczekaj na deploy

Po chwili Render poda Ci adres w stylu:

    https://TWOJA-NAZWA.onrender.com

Sprawdź, czy działa, wchodząc w przeglądarce w:

    https://TWOJA-NAZWA.onrender.com/api/flights

Powinieneś zobaczyć JSON z listą samolotów (`"ok": true, "flights": [...]`).

## 5. Podepnij adres w index.html

Na samej górze pliku `index.html`, w sekcji `<script>`, znajdź linię:

```js
const FLIGHTS_API_URL = "";
```

i wstaw tam swój adres (z `/api/flights` na końcu):

```js
const FLIGHTS_API_URL = "https://TWOJA-NAZWA.onrender.com/api/flights";
```

Zapisz, wrzuć zaktualizowany `index.html` na GitHub Pages — gotowe.

---

### Alternatywy zamiast Render.com

Dokładnie ten sam `app.py` zadziała też (z drobnymi różnicami w
konfiguracji Start Command) na:

- **PythonAnywhere** (darmowy plan, trochę bardziej ręczna konfiguracja)
- **Railway.app**
- **Fly.io**

Zasada wszędzie ta sama: musisz mieć GDZIEŚ uruchomiony ten skrypt
jako serwer 24/7 (albo "na żądanie" jak w Render), a stronę
(`index.html`) możesz zostawić na GitHub Pages tak jak jest.
