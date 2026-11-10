#!/usr/bin/env python3
"""
Flug vs. Bahn ab Stuttgart (EDDS) mit tatsächlich geflogenen Flügen aus ADS-B-Daten (OpenSky)
===============================================================================================

Was das Skript macht
--------------------
1. Holt alle Abflüge ab Stuttgart (EDDS) für einen Zeitraum aus dem OpenSky Network
   (REST-API für kurze Zeiträume, Trino-Datenbank für lange Zeiträume) oder nutzt Demo-Daten.
2. Ordnet jedem Flug den Flugzeugtyp zu (über die OpenSky-Flugzeugdatenbank, ICAO24-Adresse).
3. Schätzt Treibstoff und CO2 pro Flug mit dem offenen Leistungsmodell OpenAP.
   Die BEOBACHTETE Flugdauer aus den ADS-B-Daten geht in die Reiseflugphase ein.
4. Vergleicht jedes Ziel mit der Bahn (Fahrzeit, Tür-zu-Tür-Zeit, CO2 pro Person).
5. Prüft Hypothesen (H1 bis H4) und schreibt Tabellen, Grafiken und einen Bericht.

Aufrufbeispiele
---------------
    # Demo ohne Zugangsdaten (SYNTHETISCHE Daten, nur zum Testen der Pipeline!)
    python flug_vs_bahn_stuttgart.py --quelle demo

    # Eine Woche über die REST-API (OAuth2-Zugangsdaten als Umgebungsvariablen)
    export OPENSKY_CLIENT_ID=...
    export OPENSKY_CLIENT_SECRET=...
    python flug_vs_bahn_stuttgart.py --quelle rest --start 2026-10-19 --ende 2026-10-25 \
        --flugzeugdb aircraft-database-complete-2025-xx.csv

    # Lange Zeiträume (z. B. ein Jahr) über Trino (Forschungszugang bei OpenSky nötig)
    python flug_vs_bahn_stuttgart.py --quelle trino --start 2025-01-01 --ende 2025-12-31 \
        --flugzeugdb aircraft-database-complete-2025-xx.csv

    # Bereits gespeicherte Flugliste erneut auswerten (ohne neue Abfrage)
    python flug_vs_bahn_stuttgart.py --quelle csv --flugdatei ergebnisse/fluege_roh.csv

Benötigte Pakete:  pip install openap pandas numpy scipy statsmodels matplotlib requests
Für Trino zusätzlich: pip install pyopensky
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)  # OpenAP-Hinweise zu Ersatzmodellen

FLUGHAFEN = "EDDS"
HIER = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Annahmen (alle per Kommandozeile änderbar und im Bericht dokumentiert)
# ---------------------------------------------------------------------------
STANDARD = dict(
    auslastung=0.80,        # Sitzladefaktor Linienflug
    auslastung_privat=0.40,  # Privat-/Geschäftsjets sind oft schwach besetzt
    masse_anteil=0.80,      # Flugmasse als Anteil der max. Startmasse (MTOW)
    umweg=1.05,             # Umwegfaktor Luftlinie -> Flugstrecke, falls keine Dauer vorliegt
    rollzeit_min=15,        # Rollen am Boden (Taxi-out + Taxi-in) mit Leerlaufschub
    co2_je_kg_kerosin=3.16,  # kg CO2 je kg Kerosin
    bahn_g_pkm=29.0,        # g CO2 je Personenkilometer Bahn-Fernverkehr (UBA-Wert, prüfen!)
    bahn_umweg=1.25,        # Schienenkilometer im Verhältnis zur Luftlinie
    flug_zugang_min=150,    # Anfahrt Flughafen + Check-in/Sicherheit + Weg vom Zielflughafen
    bahn_zugang_min=40,     # Anfahrt Bahnhof + Weg vom Zielbahnhof
    bahn_grenze_min=240,    # "konkurrenzfähig" = Bahnfahrt bis 4 Stunden (UBA-Vorschlag)
    # Umsteiger an Drehkreuzen (Ziel ist der Anschlussflug, nicht die Stadt)
    flug_zugang_umst_min=120,  # Anfahrt + Check-in/Sicherheit in Stuttgart + Mindestumsteigezeit am Drehkreuz
    bahn_zugang_umst_min=110,  # Anfahrt Hbf + Check-in/Sicherheit am Drehkreuz (Puffer für Verspätung)
    umsteiger_anteil=-1.0,     # Anteil Umsteiger an Drehkreuzen; -1 = Werte aus der Bahntabelle nehmen
    min_entfernung_km=100.0,   # kürzere Flüge (Hubschrauber, Platzrunden, Schulflüge) sind kein Verlagerungsthema
)

# ---------------------------------------------------------------------------
# Flugzeugtypen: ICAO-Typcode -> OpenAP-Modell (Ersatztypen werden markiert)
# ---------------------------------------------------------------------------
OPENAP_TYPEN = {"a19n", "a20n", "a21n", "a318", "a319", "a320", "a321", "a332", "a333",
                "a343", "a359", "a388", "b37m", "b38m", "b39m", "b3xm", "b734", "b737",
                "b738", "b739", "b744", "b748", "b752", "b763", "b772", "b773", "b77w",
                "b788", "b789", "c550", "crj9", "e145", "e170", "e190", "e195", "e75l", "glf6"}

ERSATZ = {
    # Airbus A220 (bei Swiss, airBaltic u. a.): kein OpenAP-Modell -> ähnlich große Typen
    "BCS1": "e195", "BCS3": "a319",
    # Embraer E2 / weitere Regionaljets
    "E290": "e190", "E295": "e195", "E75S": "e75l", "E170": "e170", "E175": "e75l",
    "CRJ7": "crj9", "CRJX": "crj9", "CRJ2": "e145", "E135": "e145", "E35L": "e145",
    # Turboprops (ATR, Dash 8): kein Modell -> Regionaljet als OBERE Schätzung
    "AT72": "e145", "AT75": "e145", "AT76": "e145", "AT45": "e145", "AT46": "e145",
    "DH8D": "e145", "DH8C": "e145", "SF34": "e145",
    # Boeing / Airbus Varianten
    "B733": "b734", "B735": "b737", "B736": "b737", "A20N": "a20n", "A21N": "a21n",
    "B37M": "b37m", "B38M": "b38m", "B39M": "b39m",
}
# Geschäftsreise-/Privatjets: klein -> c550, groß -> glf6
BIZJET_KLEIN = {"C25A", "C25B", "C25C", "C25M", "C510", "C525", "C550", "C560", "C56X",
                "C680", "C68A", "C700", "E50P", "E55P", "LJ35", "LJ40", "LJ45", "LJ60",
                "LJ75", "PC24", "PRM1", "HA4T", "BE40", "H25B", "H25C", "FA20", "G150",
                "G280", "CL30", "CL35", "SF50", "EA50", "PC12", "TBM9", "TBM8", "TBM7"}
BIZJET_GROSS = {"GLF4", "GLF5", "GLF6", "GLEX", "GL5T", "GL7T", "GA6C", "GA7C", "F900",
                "FA7X", "FA8X", "F2TH", "FA6X", "CL60", "BBJ1", "BBJ2", "ACJ1"}


# ICAO-Rufzeichenpräfixe von Fluggesellschaften im Datensatz (Linie/Charter); dient nur der Plausibilitätsprüfung
# des Flugzeugtyps: Ein Leichtflugzeug unter einem dieser Präfixe ist eine falsche Typzuordnung.
FLUGGESELLSCHAFTEN = {"EWG", "SXS", "KLM", "PGT", "DLH", "AUA", "TUI", "THY", "SWR", "TKJ", "SAS", "VLG", "AEE",
                      "CFG", "LOT", "WZZ", "ASL", "WMT", "KLC", "CAI", "FHY", "LHX", "LGL", "FHM", "EUP", "MSC",
                      "SWT", "NVD", "TVS", "TYJ", "PVG", "BEL", "EZY", "EJU", "RYR", "BAW", "AFR", "IBE", "VLG"}


def openap_modell(typecode: str | float) -> tuple[str, bool]:
    """Liefert (OpenAP-Modell, ist_ersatz)."""
    if not isinstance(typecode, str) or not typecode.strip():
        return "a320", True
    t = typecode.strip().upper()
    if t.lower() in OPENAP_TYPEN:
        return t.lower(), False
    if t in ERSATZ:
        return ERSATZ[t], True
    if t in BIZJET_KLEIN:
        return "c550", True
    if t in BIZJET_GROSS:
        return "glf6", True
    return "a320", True


def ist_privatflug(typecode, callsign) -> bool:
    """Privat/Geschäftsreise, wenn Bizjet-Typ ODER kein Airline-Rufzeichen (3 Buchstaben + Ziffer)."""
    t = str(typecode).strip().upper() if isinstance(typecode, str) else ""
    if t in BIZJET_KLEIN or t in BIZJET_GROSS:
        return True
    cs = str(callsign).strip().upper() if isinstance(callsign, str) else ""
    airline_muster = len(cs) >= 4 and cs[:3].isalpha() and any(c.isdigit() for c in cs[3:])
    return not airline_muster


# ---------------------------------------------------------------------------
# Datenbeschaffung
# ---------------------------------------------------------------------------
TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
API = "https://opensky-network.org/api"


class OpenSkyREST:
    """Minimaler Client für die OpenSky-REST-API (OAuth2 Client Credentials)."""

    def __init__(self, cache: Path, zugang: str | None = None):
        import requests
        self.requests = requests
        self.cid = os.environ.get("OPENSKY_CLIENT_ID")
        self.secret = os.environ.get("OPENSKY_CLIENT_SECRET")
        datei = Path(zugang) if zugang else Path("credentials.json")
        if not (self.cid and self.secret) and datei.exists():
            # credentials.json von der OpenSky-Account-Seite (Schlüsselnamen in beiden Schreibweisen)
            j = json.loads(datei.read_text(encoding="utf-8"))
            self.cid = j.get("clientId") or j.get("client_id")
            self.secret = j.get("clientSecret") or j.get("client_secret")
        if not (self.cid and self.secret):
            sys.exit("Keine Zugangsdaten gefunden. credentials.json (OpenSky-Account-Seite) in den Ordner legen, "
                     "mit --zugang angeben oder OPENSKY_CLIENT_ID/OPENSKY_CLIENT_SECRET setzen.")
        self.token, self.token_zeit = None, 0.0
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)

    def _token(self) -> str:
        if self.token is None or time.time() - self.token_zeit > 25 * 60:  # Token gilt 30 min
            r = self.requests.post(TOKEN_URL, data={"grant_type": "client_credentials",
                                                    "client_id": self.cid,
                                                    "client_secret": self.secret}, timeout=30)
            r.raise_for_status()
            self.token, self.token_zeit = r.json()["access_token"], time.time()
        return self.token

    def abfluege_tag(self, tag: datetime) -> list[dict]:
        datei = self.cache / f"{FLUGHAFEN}_{tag:%Y-%m-%d}.json"
        if datei.exists():  # schont das Kontingent (Credits)
            return json.loads(datei.read_text())
        begin = int(tag.timestamp())
        end = int((tag + timedelta(days=1)).timestamp()) - 1
        for versuch in range(5):
            r = self.requests.get(f"{API}/flights/departure",
                                  params={"airport": FLUGHAFEN, "begin": begin, "end": end},
                                  headers={"Authorization": f"Bearer {self._token()}"}, timeout=60)
            if r.status_code == 404:          # keine Flüge gefunden
                daten = []
                break
            if r.status_code == 401:          # Token abgelaufen
                self.token = None
                continue
            if r.status_code == 429:          # Kontingent erschöpft
                warte = int(r.headers.get("X-Rate-Limit-Retry-After-Seconds", 60))
                print(f"  Kontingent erschöpft, warte {warte} s ...")
                time.sleep(min(warte, 3600))
                continue
            r.raise_for_status()
            daten = r.json()
            break
        else:
            raise RuntimeError(f"Abfrage für {tag:%Y-%m-%d} fehlgeschlagen")
        datei.write_text(json.dumps(daten))
        return daten

    def abfluege(self, start: datetime, ende: datetime) -> pd.DataFrame:
        zeilen, tag = [], start
        while tag <= ende:
            print(f"  hole {tag:%Y-%m-%d} ...")
            zeilen += self.abfluege_tag(tag)
            tag += timedelta(days=1)
        return pd.DataFrame(zeilen)


def abfluege_trino(start: datetime, ende: datetime) -> pd.DataFrame:
    """Historische Daten über die OpenSky-Trino-Datenbank (pyopensky, Forschungszugang)."""
    from pyopensky.trino import Trino
    df = Trino().flightlist(start, ende + timedelta(days=1), departure_airport=FLUGHAFEN)
    return df if df is not None else pd.DataFrame()


def demo_abfluege(seed: int = 1) -> pd.DataFrame:
    """SYNTHETISCHE Abflüge (eine Woche) nur zum Testen der Pipeline. KEINE echten Daten!"""
    rng = np.random.default_rng(seed)
    # Ziel, Flüge/Woche, typische Typen, Blockzeit in min (grob)
    plan = [("EDDB", 40, ["A20N", "A319", "A320"], 70), ("EDDH", 38, ["A319", "A20N", "BCS3"], 70),
            ("EDDL", 4, ["CRJ9"], 55), ("EDDK", 2, ["A319"], 50),
            ("EDDF", 20, ["CRJ9", "A320", "E190"], 40), ("EDDM", 0, [], 0),
            ("LFPG", 21, ["E190", "A318", "E170"], 75), ("EHAM", 28, ["E190", "E195", "B738"], 75),
            ("LOWW", 25, ["A20N", "E195", "DH8D"], 65), ("LSZH", 5, ["BCS1"], 40),
            ("EBBR", 6, ["A319"], 60), ("EDDC", 0, [], 0), ("EDDP", 0, [], 0),
            ("EKCH", 7, ["A20N"], 95), ("LKPR", 4, ["AT76"], 70), ("EDDV", 3, ["CRJ9"], 60)]
    zeilen, t0 = [], datetime(2030, 1, 7, tzinfo=timezone.utc)  # Jahr 2030 = erkennbar fiktiv
    for ziel, n, typen, dauer in plan:
        for i in range(n):
            start = t0 + timedelta(minutes=int(rng.uniform(5 * 60, 21 * 60)) + 1440 * int(rng.integers(0, 7)))
            d = dauer * rng.uniform(0.9, 1.2)
            zeilen.append(dict(icao24=f"demo{len(zeilen):04d}", callsign=f"DEM{100 + len(zeilen)}",
                               firstSeen=int(start.timestamp()),
                               lastSeen=int((start + timedelta(minutes=d)).timestamp()),
                               estDepartureAirport=FLUGHAFEN, estArrivalAirport=ziel,
                               typecode=rng.choice(typen)))
    for i in range(12):  # einige Privat-/Geschäftsjets
        start = t0 + timedelta(hours=int(rng.integers(8, 160)))
        ziel = rng.choice(["EDDB", "EDDH", "LSZH", "LFPG", "EDDM", "LSGG"])
        zeilen.append(dict(icao24=f"demob{i:03d}", callsign=f"DABC{i}", firstSeen=int(start.timestamp()),
                           lastSeen=int((start + timedelta(minutes=int(rng.integers(35, 80)))).timestamp()),
                           estDepartureAirport=FLUGHAFEN, estArrivalAirport=ziel,
                           typecode=rng.choice(["C56X", "C25A", "GLF5", "PC24"])))
    return pd.DataFrame(zeilen)


def vereinheitlichen(df: pd.DataFrame) -> pd.DataFrame:
    """Spaltennamen aus REST, Trino und CSV auf ein Schema bringen."""
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    umbenennen = {"estdepartureairport": "abflug", "departure": "abflug",
                  "estarrivalairport": "ziel", "arrival": "ziel",
                  "firstseen": "start", "lastseen": "ende"}
    df = df.rename(columns={k: v for k, v in umbenennen.items() if k in df.columns})
    for spalte in ["start", "ende"]:
        if spalte in df.columns:
            s = df[spalte]
            df[spalte] = (pd.to_datetime(s, unit="s", utc=True) if np.issubdtype(s.dtype, np.number)
                          else pd.to_datetime(s, utc=True))
    df["callsign"] = df.get("callsign", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    df["icao24"] = df["icao24"].astype(str).str.lower().str.strip()
    return df


def flugzeugtypen_laden(pfad: str | None) -> pd.Series | None:
    """OpenSky-Flugzeugdatenbank (CSV) -> Series icao24 -> typecode. Kommt mit beiden Quoting-Varianten klar."""
    if not pfad:
        return None
    try:
        db = pd.read_csv(pfad, quotechar="'", dtype=str, low_memory=False, on_bad_lines="skip")
        if "icao24" not in [c.strip("'\" ") for c in db.columns]:
            db = pd.read_csv(pfad, dtype=str, low_memory=False, on_bad_lines="skip")
    except Exception as e:
        print(f"  Flugzeugdatenbank nicht lesbar ({e}); alle Typen werden geschätzt.")
        return None
    db.columns = [c.strip("'\" ").lower() for c in db.columns]
    db["icao24"] = db["icao24"].astype(str).str.strip("'\" ").str.lower()
    db["typecode"] = db["typecode"].astype(str).str.strip("'\" ").str.upper()
    return db.drop_duplicates("icao24").set_index("icao24")["typecode"]


# ---------------------------------------------------------------------------
# Treibstoffmodell (OpenAP)
# ---------------------------------------------------------------------------
def luftlinie_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Treibstoffmodell:
    """
    Steig- und Sinkflug werden mit OpenAP (WRAP-Profile) simuliert, der Reiseflug mit
    konstantem Treibstofffluss. Liegt eine plausible beobachtete Flugdauer aus den ADS-B-Daten vor,
    bestimmt sie die Dauer des Reiseflugs (Umwege, Warteschleifen, Wind fließen so ein).
    """

    def __init__(self, a: dict):
        from openap import FlightGenerator, FuelFlow, prop
        warnings.filterwarnings("ignore", module="openap")
        self.FG, self.FF, self.prop, self.a = FlightGenerator, FuelFlow, prop, a
        self._profile: dict = {}

    def _profil(self, ac: str, dist_km: float) -> dict:
        # Reiseflughöhe an die Strecke anpassen: kurze Strecken -> niedrigere Höhe
        stufe = int(min(dist_km, 1500) // 50) * 50
        schluessel = (ac, stufe)
        if schluessel in self._profile:
            return self._profile[schluessel]
        p = self.prop.aircraft(ac)
        masse = self.a["masse_anteil"] * p["mtow"]
        fg, ff = self.FG(ac, use_synonym=True), self.FF(ac, use_synonym=True)

        def kraftstoff(d):  # OpenAP-Profil (SI-Einheiten) -> kg Kraftstoff, dt = 10 s
            f = ff.enroute(mass=masse, tas=d.v.values / 0.514444, alt=d.h.values / 0.3048,
                           vs=d.vs.values / 0.00508)
            return float(np.nansum(np.asarray(f, dtype=float)) * 10)

        steig_voll = fg.climb(dt=10)  # WRAP-Steigprofil bis zur typischen Reiseflughöhe
        ergebnis = None
        for hoehe in [37000, 35000, 33000, 31000, 29000, 27000, 25000, 22000, 19000, 16000,
                      13000, 10000, 8000, 6000]:
            if hoehe > steig_voll.h.max() / 0.3048 + 500:
                continue
            # Steigflug an der Zielhöhe abschneiden, Sinkflug ab dieser Höhe simulieren
            steig = steig_voll[steig_voll.h <= hoehe * 0.3048]
            try:
                sink = fg.descent(dt=10, alt_cr=hoehe)
            except Exception:
                continue
            s_km = (steig.s.iloc[-1] + sink.s.iloc[-1]) / 1000
            if s_km <= 0.85 * max(dist_km, 1) or hoehe == 6000:
                v_cr = float(steig.v.iloc[-1])  # m/s am Ende des Steigflugs
                ff_cr = float(np.nan_to_num(ff.enroute(mass=masse, tas=v_cr / 0.514444,
                                                       alt=float(hoehe), vs=0.0)))
                ergebnis = dict(hoehe_ft=hoehe, s_kd_km=s_km,
                                t_kd_s=float(steig.t.iloc[-1] + sink.t.iloc[-1]),
                                f_kd_kg=kraftstoff(steig) + kraftstoff(sink), ff_cr=ff_cr,
                                v_cr_kmh=v_cr * 3.6)
                break
        eng = self.prop.engine(p["engine"]["default"])
        n_trieb = p["engine"].get("number", 2)
        ergebnis["rollen_kg"] = eng["ff_idl"] * n_trieb * self.a["rollzeit_min"] * 60
        ergebnis["sitze"] = p["pax"].get("high") or p["pax"].get("max")
        self._profile[schluessel] = ergebnis
        return ergebnis

    def flug(self, ac: str, dist_km: float, dauer_min: float | None) -> dict:
        p = self._profil(ac, dist_km)
        cr_km_modell = max(dist_km * self.a["umweg"] - p["s_kd_km"], 0)
        t_cr_modell = cr_km_modell / p["v_cr_kmh"] * 3600
        t_modell_min = (p["t_kd_s"] + t_cr_modell) / 60
        quelle = "Modell (Luftlinie x Umwegfaktor)"
        t_cr = t_cr_modell
        if dauer_min and 0.7 < dauer_min / t_modell_min < 1.8:
            t_cr = max(dauer_min * 60 - p["t_kd_s"], 0)
            quelle = "beobachtete ADS-B-Flugdauer"
        kraftstoff = p["f_kd_kg"] + p["ff_cr"] * t_cr + p["rollen_kg"]
        return dict(kraftstoff_kg=kraftstoff, rollen_kg=p["rollen_kg"], sitze=p["sitze"], reiseflughoehe_ft=p["hoehe_ft"],
                    modell_dauer_min=t_modell_min, dauer_quelle=quelle)


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------
PASSAGIERKLASSEN = ("Linie/Charter", "Privat/Geschäft")


def stundenverbrauch_laden(pfad: Path) -> dict:
    """ersatz_verbrauch.csv: typecode -> kg_pro_h, sitze, reise_kmh (Näherungen für Typen ohne OpenAP-Modell)."""
    if not pfad.exists():
        return {}
    t = pd.read_csv(pfad)
    return {str(r.typecode).strip().upper(): dict(kg_pro_h=float(r.kg_pro_h), sitze=int(r.sitze),
                                                  reise_kmh=float(r.reise_kmh)) for r in t.itertuples()}


def betreiber_laden(pfad: Path) -> dict:
    if not pfad.exists():
        return {}
    b = pd.read_csv(pfad, dtype=str).fillna("")
    return {r.praefix.strip().upper(): r.klasse.strip() for r in b.itertuples()}


def klassifizieren(df: pd.DataFrame, a: dict) -> list[str]:
    """
    Linie/Charter, Privat/Geschäft, Fracht, Staat/Militär oder 'Unter 100 km'.
    Reihenfolge: Mindestentfernung -> Betreiberliste (betreiber.csv, Rufzeichen-Präfix) -> Bizjet-Typ /
    Rufzeichen ohne Airline-Muster (Privat/Geschäft) -> sonst Linie/Charter.
    """
    liste = betreiber_laden(HIER / "betreiber.csv")
    out = []
    for t, c, km in zip(df["typecode"], df["callsign"], df["luftlinie_km"]):
        cs = str(c).strip().upper() if isinstance(c, str) else ""
        if km < a["min_entfernung_km"]:
            out.append("Unter 100 km")
        elif cs[:3] in liste and cs[:3].isalpha():
            out.append(liste[cs[:3]])
        elif ist_privatflug(t, c):
            out.append("Privat/Geschäft")
        else:
            out.append("Linie/Charter")
    return out


def auswerten(roh: pd.DataFrame, typen: pd.Series | None, bahn: pd.DataFrame, a: dict) -> pd.DataFrame:
    from openap import nav
    df = vereinheitlichen(roh)
    df = df[df["ziel"].notna() & (df["ziel"].astype(str).str.len() == 4) & (df["ziel"] != FLUGHAFEN)].copy()
    if "typecode" not in df.columns:
        df["typecode"] = np.nan
    if typen is not None:
        df["typecode"] = df["typecode"].fillna(df["icao24"].map(typen))
    df["dauer_min"] = (df["ende"] - df["start"]).dt.total_seconds() / 60

    edds = nav.airport(FLUGHAFEN)
    koord = {}
    for z in df["ziel"].unique():
        try:
            ap = nav.airport(z)
            koord[z] = (ap["lat"], ap["lon"], ap.get("name", z))
        except Exception:
            koord[z] = None
    ohne_koord = df["ziel"].map(lambda z: koord.get(z) is None)
    auswerten.ohne_flughafen = df.loc[ohne_koord, ["callsign", "ziel"]].copy()  # fuer den Bericht (Datentrichter)
    df = df[~ohne_koord].copy()
    df["luftlinie_km"] = df["ziel"].map(lambda z: luftlinie_km(edds["lat"], edds["lon"], *koord[z][:2]))
    df["zielname"] = df["ziel"].map(lambda z: koord[z][2])

    modell = Treibstoffmodell(a)
    erg = []
    stunden = stundenverbrauch_laden(HIER / "ersatz_verbrauch.csv")
    # Klasse VOR der Verbrauchsschätzung bestimmen, damit Typ-Plausibilität und Ersatzmodelle davon abhängen
    df = df.reset_index(drop=True)
    df["klasse"] = klassifizieren(df, a)
    liste = betreiber_laden(HIER / "betreiber.csv")
    praefix = df["callsign"].fillna("").astype(str).str.strip().str.upper().str[:3]
    tc_all = df["typecode"].fillna("").astype(str).str.strip().str.upper()
    klein = tc_all.map(lambda t: t in stunden and stunden[t]["sitze"] < 20)
    gelistet = praefix.map(lambda p_: liste.get(p_) == "Linie/Charter" or p_ in FLUGGESELLSCHAFTEN)
    # (a) gelisteter Linienbetreiber, aber Leichtflugzeug laut Typdatenbank -> Typzuordnung unplausibel
    df["typ_unplausibel"] = (df["klasse"] == "Linie/Charter") & gelistet & klein
    df.loc[df["typ_unplausibel"], "typecode"] = np.nan
    # (b) kein gelisteter Betreiber und Leichtflugzeug -> Privat/Geschäft (z. B. Turboprop mit Fantasie-Rufzeichen)
    df.loc[(df["klasse"] == "Linie/Charter") & ~gelistet & klein, "klasse"] = "Privat/Geschäft"
    for _, r in df.iterrows():
        tc = str(r["typecode"]).strip().upper() if isinstance(r["typecode"], str) else ""
        dauer = r["dauer_min"] if pd.notna(r["dauer_min"]) else None
        if tc in stunden:
            # Typen ohne OpenAP-Modell (Kolben, Turboprop, einzelne Jets): typischer Stundenverbrauch
            sv = stunden[tc]
            t_min = dauer if dauer else r["luftlinie_km"] * a["umweg"] / sv["reise_kmh"] * 60 + 10
            f = dict(kraftstoff_kg=sv["kg_pro_h"] * (t_min + a["rollzeit_min"] / 3) / 60,
                     rollen_kg=sv["kg_pro_h"] * a["rollzeit_min"] / 3 / 60, sitze=sv["sitze"],
                     reiseflughoehe_ft=np.nan, modell_dauer_min=t_min,
                     dauer_quelle="beobachtete ADS-B-Flugdauer" if dauer else "Modell (Luftlinie x Umwegfaktor)",
                     openap_modell="stundenverbrauch", typ_ersatz=True)
        else:
            ac, ersatz = openap_modell(r["typecode"])
            if not tc and r["klasse"] == "Privat/Geschäft":
                ac = "c550"   # Privatflug ohne Typ: kleiner Geschäftsreisejet statt A320
            f = modell.flug(ac, r["luftlinie_km"], dauer)
            f.update(openap_modell=ac, typ_ersatz=ersatz)
        erg.append(f)
    df = pd.concat([df.reset_index(drop=True), pd.DataFrame(erg)], axis=1)

    df["privat"] = df["klasse"] == "Privat/Geschäft"
    lf = np.where(df["privat"], a["auslastung_privat"], a["auslastung"])
    df["passagiere"] = np.maximum(df["sitze"] * lf, 1)
    df["co2_kg"] = df["kraftstoff_kg"] * a["co2_je_kg_kerosin"]
    df["co2_pro_pax_kg"] = df["co2_kg"] / df["passagiere"]
    df["co2_g_pkm"] = df["co2_pro_pax_kg"] * 1000 / df["luftlinie_km"]
    df["co2_pro_pax_linie_kg"] = df["co2_pro_pax_kg"].where(~df["privat"])  # Bahnvergleich nur Linie/Charter

    bt = bahn_tabelle(bahn, a)
    df = df.merge(bt, left_on="ziel", right_on="icao", how="left")
    df["zielname"] = df["ziel_bahn"].fillna(df["zielname"])  # kurze Stadtnamen
    df["bahn_co2_pro_pax_kg"] = df["luftlinie_km"] * a["bahn_umweg"] * a["bahn_g_pkm"] / 1000
    flugzeit = df["dauer_min"].fillna(df["modell_dauer_min"]) + a["rollzeit_min"] / 2
    # Szenario Stadtreise: Hauptbahnhof -> Hauptbahnhof bzw. Flughafen -> Stadt
    df["flug_tuer_min"] = flugzeit + a["flug_zugang_min"]
    df["bahn_tuer_min"] = df["bahn_min"] + a["bahn_zugang_min"]
    # Szenario Umsteiger: Ziel ist der Anschlussflug am Drehkreuz, die Bahn muss bis zum Flughafenbahnhof
    df["flug_tuer_umst_min"] = flugzeit + a["flug_zugang_umst_min"]
    df["bahn_tuer_umst_min"] = df["bahn_min_umst"] + a["bahn_zugang_umst_min"]
    # Anteil der Passagiere eines Fluges, für die die Bahn innerhalb der Grenze liegt
    u = df["umsteiger_anteil"].fillna(0)
    stadt_ok = (df["bahn_min"] <= a["bahn_grenze_min"]).astype(float)
    umst_ok = (df["bahn_min_umst"] <= a["bahn_grenze_min"]).astype(float)
    df["anteil_verlagerbar"] = np.where(df["bahn_min"].isna(), 0.0, (1 - u) * stadt_ok + u * umst_ok)
    df["bahn_konkurrenzfaehig"] = df["anteil_verlagerbar"] > 0
    return df.drop(columns=["icao", "ziel_bahn"])


def bahn_tabelle(bahn: pd.DataFrame, a: dict) -> pd.DataFrame:
    """
    Bahntabelle -> eine Zeile je Ziel.
    szenario 'stadt'     : Stuttgart Hbf -> Hauptbahnhof der Zielstadt (Reisende in die Stadt)
    szenario 'flughafen' : Stuttgart Hbf -> Flughafenbahnhof des Drehkreuzes (Umsteiger zu Anschlussflügen)
    Ältere Tabellen ohne Spalte 'szenario'
    werden als reine Stadttabelle gelesen. Fehlt bei einem Drehkreuz die Flughafenzeile, gilt die
    Umsteigergruppe als nicht verlagerbar.
    """
    b = bahn.copy()
    if "szenario" not in b.columns:
        b["szenario"] = "stadt"
    for spalte, wert in [("bahnhof_ziel", ""), ("umsteiger_anteil", np.nan), ("umstiege", np.nan)]:
        if spalte not in b.columns:
            b[spalte] = wert
    stadt = b[b["szenario"] == "stadt"].drop_duplicates("icao").set_index("icao")
    fh = b[b["szenario"] == "flughafen"].drop_duplicates("icao").set_index("icao")
    t = pd.DataFrame(index=stadt.index)
    t["ziel_bahn"] = stadt["ziel"]
    t["bahn_min"] = stadt["bahn_min"]
    t["bahnhof_ziel"] = stadt["bahnhof_ziel"]
    t["umstiege"] = stadt["umstiege"]
    t["drehkreuz"] = stadt["drehkreuz"]
    # Drehkreuz ohne Flughafenzeile: keine Bahnzeit zum Flughafen bekannt -> Umsteiger gelten als nicht
    # verlagerbar (konservativ). Kein Drehkreuz: Umsteigeranteil 0, Spalte nur zur Vollständigkeit.
    ist_hub = t["drehkreuz"] == "ja"
    t["bahn_min_umst"] = fh["bahn_min"].reindex(t.index).where(ist_hub | fh["bahn_min"].reindex(t.index).notna(),
                                                               t["bahn_min"])
    t["bahnhof_umst"] = fh["bahnhof_ziel"].reindex(t.index).where(ist_hub, t["bahnhof_ziel"])
    anteil = pd.to_numeric(fh["umsteiger_anteil"], errors="coerce").reindex(t.index)
    if a.get("umsteiger_anteil") is not None and a["umsteiger_anteil"] >= 0:  # Kommandozeile überschreibt
        anteil = pd.Series(a["umsteiger_anteil"], index=t.index)
    t["umsteiger_anteil"] = np.where(t["drehkreuz"] == "ja", anteil.fillna(0.5), 0.0)
    return t.reset_index()


def ziele_zusammenfassen(df: pd.DataFrame, tage: float, bahn: pd.DataFrame, a: dict) -> pd.DataFrame:
    from openap import nav
    # Werte je Ziel nur aus Linien-/Charterfluegen (Privatfluege verfaelschen Dauer und CO2 je Person);
    # CO2 je Person gepoolt: Summe CO2 / Summe Passagiere (wie im Lernwerkzeug)
    lin = df[~df["privat"]]
    pool = (lin.groupby("ziel")["co2_kg"].sum() / lin.groupby("ziel")["passagiere"].sum())
    tuer_lin = lin.groupby("ziel")["flug_tuer_min"].median()
    tuer_umst_lin = lin.groupby("ziel")["flug_tuer_umst_min"].median()
    dauer_lin = lin.groupby("ziel")["dauer_min"].median()
    g = df.groupby(["ziel", "zielname"], as_index=False).agg(
        fluege=("icao24", "size"), davon_privat=("privat", "sum"),
        luftlinie_km=("luftlinie_km", "first"), flugdauer_median_min=("dauer_min", "median"),
        co2_t=("co2_kg", lambda s: s.sum() / 1000), co2_pro_pax_kg=("co2_pro_pax_linie_kg", "median"),
        bahn_min=("bahn_min", "first"), bahnhof_ziel=("bahnhof_ziel", "first"),
        bahn_min_umst=("bahn_min_umst", "first"), bahnhof_umst=("bahnhof_umst", "first"),
        umsteiger_anteil=("umsteiger_anteil", "first"), anteil_verlagerbar=("anteil_verlagerbar", "first"),
        bahn_co2_pro_pax_kg=("bahn_co2_pro_pax_kg", "first"),
        flug_tuer_min=("flug_tuer_min", "median"), bahn_tuer_min=("bahn_tuer_min", "first"),
        flug_tuer_umst_min=("flug_tuer_umst_min", "median"), bahn_tuer_umst_min=("bahn_tuer_umst_min", "first"),
        drehkreuz=("drehkreuz", "first"), anteil_ersatztyp=("typ_ersatz", "mean"))
    g["linienfluege"] = g["fluege"] - g["davon_privat"]
    g["co2_pro_pax_kg"] = g["ziel"].map(pool)
    g["flug_tuer_min"] = g["ziel"].map(tuer_lin)          # NaN, wenn nur Privatfluege
    g["flug_tuer_umst_min"] = g["ziel"].map(tuer_umst_lin)
    g["flugdauer_median_min"] = g["ziel"].map(dauer_lin).fillna(g["flugdauer_median_min"])
    # Ziele aus der Bahntabelle OHNE Flüge mit 0 aufnehmen: Sonst fehlen genau die Strecken,
    # auf denen die Bahn den Flug womöglich schon verdrängt hat (Selektionsverzerrung).
    edds = nav.airport(FLUGHAFEN)
    fehlend = []
    bt = bahn_tabelle(bahn, a)
    for _, b in bt[~bt["icao"].isin(g["ziel"])].iterrows():
        try:
            ap = nav.airport(b["icao"])
        except Exception:
            continue
        km = luftlinie_km(edds["lat"], edds["lon"], ap["lat"], ap["lon"])
        fehlend.append(dict(ziel=b["icao"], zielname=b["ziel_bahn"], fluege=0, davon_privat=0, luftlinie_km=km,
                            bahn_min=b["bahn_min"], bahnhof_ziel=b["bahnhof_ziel"],
                            bahn_min_umst=b["bahn_min_umst"], bahnhof_umst=b["bahnhof_umst"],
                            umsteiger_anteil=b["umsteiger_anteil"],
                            bahn_tuer_min=b["bahn_min"] + a["bahn_zugang_min"],
                            bahn_tuer_umst_min=b["bahn_min_umst"] + a["bahn_zugang_umst_min"],
                            bahn_co2_pro_pax_kg=km * a["bahn_umweg"] * a["bahn_g_pkm"] / 1000,
                            drehkreuz=b["drehkreuz"], co2_t=0.0, linienfluege=0))
    if fehlend:
        g = pd.concat([g, pd.DataFrame(fehlend)], ignore_index=True)
    g["fluege_pro_woche"] = g["fluege"] / tage * 7
    g["zeitvorteil_flug_min"] = g["bahn_tuer_min"] - g["flug_tuer_min"]
    g["co2_ersparnis_bahn_pro_pax_kg"] = g["co2_pro_pax_kg"] - g["bahn_co2_pro_pax_kg"]
    return g.sort_values("fluege", ascending=False)


def hypothesen(df: pd.DataFrame, ziele: pd.DataFrame, a: dict) -> list[str]:
    from scipy import stats
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    out = []
    linie = df[~df["privat"]]

    # H1 Verlagerungspotenzial (deskriptiv)
    mit_bahn = linie[linie["bahn_konkurrenzfaehig"] == True]
    w = linie["anteil_verlagerbar"]
    out.append("H1 Verlagerungspotenzial (deskriptiv)")
    out.append(f"   Szenarien: Stadtreisende Hbf -> Hbf, Umsteiger Hbf -> Flughafenbahnhof des Drehkreuzes, "
               f"Grenze {a['bahn_grenze_min']} min Bahnfahrt")
    out.append(f"   Linienflüge mit zumindest teilweise verlagerbaren Passagieren: {len(mit_bahn)} von {len(linie)}; "
               f"passagiergewichtet {(w * linie['passagiere']).sum() / max(linie['passagiere'].sum(), 1):.1%} der Passagiere, "
               f"CO2-Anteil {(w * linie['co2_kg']).sum() / max(linie['co2_kg'].sum(), 1):.1%}")
    if len(mit_bahn):
        ersp = (w * (linie["co2_pro_pax_kg"] - linie["bahn_co2_pro_pax_kg"]) * linie["passagiere"]).sum() / 1000
        out.append(f"   Rechnerische Einsparung bei vollständiger Verlagerung: {ersp:.1f} t CO2 im Zeitraum "
                   "(Obergrenze: Ausweichen aufs Auto und frei werdende Slots nicht berücksichtigt)")

    # H2 Bahnzeit und Flughäufigkeit
    z = ziele.dropna(subset=["bahn_min"]).copy()
    z["linienfluege"] = z["fluege"] - z["davon_privat"]  # Ziele ohne Flüge zählen mit 0
    out.append("\nH2 Je kürzer die Bahnfahrzeit, desto weniger Flüge (bei Kontrolle der Entfernung)")
    out.append("   H0: kein Zusammenhang; H1: positiver Zusammenhang Bahnzeit ~ Flüge (einseitig)")
    for label, teil in [("alle Ziele", z), ("ohne Drehkreuze", z[z["drehkreuz"] != "ja"])]:
        if len(teil) >= 5:
            rho, p = stats.spearmanr(teil["bahn_min"], teil["linienfluege"])
            p1 = p / 2 if rho > 0 else 1 - p / 2
            out.append(f"   Spearman ({label}, n={len(teil)}): rho={rho:.2f}, p(einseitig)={p1:.3f}")
        if len(teil) >= 6:
            try:
                m = smf.glm("linienfluege ~ np.log(bahn_min) + np.log(luftlinie_km)", data=teil,
                            family=sm.families.Poisson()).fit(scale="X2")  # Quasi-Poisson (Überdispersion)
                b, se = m.params["np.log(bahn_min)"], m.bse["np.log(bahn_min)"]
                p1 = 1 - stats.norm.cdf(b / se)
                out.append(f"   Quasi-Poisson ({label}): Elastizität Bahnzeit b={b:.2f} (SE {se:.2f}), "
                           f"p(einseitig)={p1:.3f}  -> +10 % Bahnzeit ~ {(1.1 ** b - 1):+.0%} Flüge")
            except Exception as e:
                out.append(f"   Quasi-Poisson ({label}) nicht schätzbar: {e}")
    out.append("   Achtung: Fallzahl = Anzahl Ziele (klein) -> geringe Teststärke, nur explorativ.")

    # H3 Kurzstrecken ineffizienter
    out.append("\nH3 Kurzstrecken verursachen mehr CO2 je Personenkilometer")
    if linie["luftlinie_km"].nunique() > 3:
        rho, p = stats.spearmanr(linie["luftlinie_km"], linie["co2_g_pkm"])
        p1 = p / 2 if rho < 0 else 1 - p / 2
        out.append(f"   Spearman Entfernung ~ g CO2/Pkm (n={len(linie)} Flüge): rho={rho:.2f}, p(einseitig)={p1:.4f}")
        kurz, lang = linie[linie["luftlinie_km"] < 500]["co2_g_pkm"], linie[linie["luftlinie_km"] >= 500]["co2_g_pkm"]
        if len(kurz) > 2 and len(lang) > 2:
            u, p = stats.mannwhitneyu(kurz, lang, alternative="greater")
            out.append(f"   Mann-Whitney <500 km (Median {kurz.median():.0f} g) vs. >=500 km "
                       f"(Median {lang.median():.0f} g): U={u:.0f}, p={p:.4f}")
    out.append("   Hinweis: Das Ergebnis hängt stark am Modell (Start/Steigflug fallen bei Kurzstrecken ins Gewicht) "
               "und an den Flugzeugtypen; Flüge sind nicht unabhängig (gleiche Strecken/Typen).")

    # H4 Privat- vs. Linienflüge
    priv = df[df["privat"]]
    out.append("\nH4 Privat-/Geschäftsflüge verursachen mehr CO2 pro Person als Linienflüge")
    if len(priv) >= 5 and len(linie) >= 5:
        u, p = stats.mannwhitneyu(priv["co2_g_pkm"], linie["co2_g_pkm"], alternative="greater")
        out.append(f"   Median g CO2/Pkm privat {priv['co2_g_pkm'].median():.0f} vs. Linie "
                   f"{linie['co2_g_pkm'].median():.0f}; Mann-Whitney U={u:.0f}, p={p:.4f}")
        out.append(f"   Anteil Privatflüge an Flügen {len(priv) / len(df):.1%}, an CO2 {priv['co2_kg'].sum() / df['co2_kg'].sum():.1%}")
    else:
        out.append("   Zu wenige Privatflüge im Zeitraum.")
    return out


def grafiken(ziele: pd.DataFrame, df: pd.DataFrame, a: dict, ordner: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    z = ziele.dropna(subset=["bahn_min"]).sort_values("fluege_pro_woche")
    farbe = np.where(z["bahn_min"] <= a["bahn_grenze_min"], "#2a7f62", "#8a8f98")

    fig, ax = plt.subplots(figsize=(8, max(3, 0.35 * len(z))))
    ax.barh(z["zielname"], z["fluege_pro_woche"], color=farbe)
    ax.set_xlabel("Abflüge pro Woche (ADS-B)")
    ax.set_title(f"Ziele ab Stuttgart – grün: Bahn ≤ {a['bahn_grenze_min'] // 60} h")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(ordner / "1_fluege_je_ziel.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(z["flug_tuer_min"] / 60, z["bahn_tuer_min"] / 60, s=20 + z["fluege_pro_woche"] * 4,
               color=farbe, alpha=0.8)
    for _, r in z.dropna(subset=["flug_tuer_min"]).iterrows():
        ax.annotate(r["zielname"], (r["flug_tuer_min"] / 60, r["bahn_tuer_min"] / 60), fontsize=8,
                    xytext=(4, 2), textcoords="offset points")
    m = max(z["flug_tuer_min"].max(), z["bahn_tuer_min"].max()) / 60 + 0.5
    ax.plot([0, m], [0, m], ls="--", color="#555", lw=1)
    ax.set_xlabel("Tür-zu-Tür Flug (h)"); ax.set_ylabel("Tür-zu-Tür Bahn (h)")
    ax.set_title("Unter der Linie: Bahn schneller (Punktgröße = Flüge/Woche)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(ordner / "2_tuer_zu_tuer.png", dpi=150); plt.close(fig)

    z2 = z.sort_values("luftlinie_km")
    x = np.arange(len(z2))
    fig, ax = plt.subplots(figsize=(max(7, 0.6 * len(z2)), 4.5))
    ax.bar(x - 0.2, z2["co2_pro_pax_kg"], 0.4, label="Flug (Median, ADS-B + OpenAP)", color="#c4553a")
    ax.bar(x + 0.2, z2["bahn_co2_pro_pax_kg"], 0.4, label="Bahn", color="#2a7f62")
    ax.set_xticks(x, z2["zielname"], rotation=45, ha="right")
    ax.set_ylabel("kg CO2 pro Person (einfache Fahrt)")
    ax.legend(frameon=False); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(ordner / "3_co2_pro_person.png", dpi=150); plt.close(fig)

    linie = df[~df["privat"]]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.scatter(linie["luftlinie_km"], linie["co2_g_pkm"], s=10, alpha=0.4, color="#3a6ea5", label="Linie")
    priv = df[df["privat"]]
    if len(priv):
        ax.scatter(priv["luftlinie_km"], priv["co2_g_pkm"], s=14, alpha=0.7, color="#c4553a", label="Privat/Geschäft")
    ax.axhline(a["bahn_g_pkm"], color="#2a7f62", ls="--", lw=1, label="Bahn")
    ax.set_yscale("log"); ax.set_xlabel("Luftlinie (km)"); ax.set_ylabel("g CO2 je Personen-km (log)")
    ax.legend(frameon=False); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(ordner / "4_effizienz_entfernung.png", dpi=150); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Flug vs. Bahn ab Stuttgart mit OpenSky-ADS-B-Daten")
    ap.add_argument("--quelle", choices=["demo", "rest", "trino", "csv"], default="demo")
    ap.add_argument("--start", help="JJJJ-MM-TT (UTC)")
    ap.add_argument("--ende", help="JJJJ-MM-TT (UTC, einschließlich)")
    ap.add_argument("--flugdatei", help="bei --quelle csv: gespeicherte Rohdaten")
    ap.add_argument("--zugang", help="credentials.json von der OpenSky-Account-Seite (Standard: ./credentials.json)")
    ap.add_argument("--flugzeugdb", help="OpenSky aircraft database (CSV) für Flugzeugtypen")
    ap.add_argument("--bahn", default=str(HIER / "bahnzeiten_ab_stuttgart.csv"))
    ap.add_argument("--ausgabe", default="ergebnisse")
    for k, v in STANDARD.items():
        ap.add_argument(f"--{k.replace('_', '-')}", type=type(v), default=v)
    args = ap.parse_args()
    a = {k: getattr(args, k) for k in STANDARD}

    ordner = Path(args.ausgabe); ordner.mkdir(parents=True, exist_ok=True)
    print(f"1) Abflüge holen ({args.quelle}) ...")
    if args.quelle == "demo":
        roh = demo_abfluege(); tage = 7
    elif args.quelle == "csv":
        roh = pd.read_csv(args.flugdatei)
        s = vereinheitlichen(roh)["start"]
        tage = max((s.max() - s.min()).total_seconds() / 86400, 1)
    else:
        if not (args.start and args.ende):
            sys.exit("--start und --ende angeben")
        start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        ende = datetime.strptime(args.ende, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        tage = (ende - start).days + 1
        roh = (OpenSkyREST(ordner / "cache", args.zugang).abfluege(start, ende) if args.quelle == "rest"
               else abfluege_trino(start, ende))
    if roh.empty:
        sys.exit("Keine Flüge gefunden.")
    roh.to_csv(ordner / "fluege_roh.csv", index=False)

    print("2) Flugzeugtypen, Treibstoff und CO2 schätzen ...")
    typen = flugzeugtypen_laden(args.flugzeugdb)
    bahn = pd.read_csv(args.bahn)
    alle = auswerten(roh, typen, bahn, a)
    alle.to_csv(ordner / "fluege_alle_klassen.csv", index=False)
    df = alle[alle["klasse"].isin(PASSAGIERKLASSEN)].reset_index(drop=True)
    ziele = ziele_zusammenfassen(df, tage, bahn, a)
    df.to_csv(ordner / "fluege_ausgewertet.csv", index=False)
    ziele.to_csv(ordner / "ziele_flug_vs_bahn.csv", index=False)

    print("3) Hypothesen prüfen und Grafiken zeichnen ...")
    bericht = []
    if args.quelle == "demo":
        bericht.append("!!! DEMO-MODUS: SYNTHETISCHE DATEN – Ergebnisse haben KEINE Aussagekraft !!!\n")
    ohne_bahn = sorted(df[df["bahn_min"].isna()]["ziel"].unique())
    roh_n = len(roh)
    ohne_ziel = int(vereinheitlichen(roh)["ziel"].isna().sum())
    klassen = alle["klasse"].value_counts().to_dict()
    cs = alle["callsign"].fillna("").str.strip().str.upper().str[:3]
    liste = betreiber_laden(HIER / "betreiber.csv")
    unbekannt = (alle.assign(p=cs)[(alle["klasse"] == "Linie/Charter") & ~cs.isin(list(liste))]
                 .groupby("p").size().sort_values(ascending=False))
    v = vereinheitlichen(roh)
    rueck = int((v["ziel"] == FLUGHAFEN).sum())
    ohne_fh = len(getattr(auswerten, "ohne_flughafen", []))
    bericht += [f"Rohdaten: {roh_n} Abflüge, davon ohne geschätztes Ziel: {ohne_ziel} ({ohne_ziel / max(roh_n, 1):.0%})",
                f"Datentrichter: {roh_n} - {ohne_ziel} ohne Ziel - {rueck} Rückkehr nach {FLUGHAFEN} - "
                f"{ohne_fh} Zielflughafen nicht in der OpenAP-Datenbank = {len(alle)} Flüge mit Ziel",
                "Klassen (mit Ziel): " + ", ".join(f"{k} {v}" for k, v in klassen.items()),
                "Fracht, Staat/Militär und Flüge unter 100 km sind aus der Passagieranalyse ausgeschlossen.",
                "Als Linie/Charter gezählte Präfixe (bitte in betreiber.csv prüfen, falls fraglich): "
                + ", ".join(f"{k} {v}" for k, v in unbekannt.head(40).items()),
                f"Flugzeugdatenbank: {Path(args.flugzeugdb).name if args.flugzeugdb else 'keine (alle Typen geschätzt)'}",
                f"Zeitraum: {tage:.0f} Tage, Passagierflüge mit bekanntem Ziel: {len(df)}",
                f"Davon Privat-/Geschäftsflüge: {int(df['privat'].sum())}",
                f"Flugtyp nur über Ersatzmodell geschätzt: {df['typ_ersatz'].mean():.0%} der Flüge",
                f"Reiseflugdauer aus ADS-B-Beobachtung: {(df['dauer_quelle'] == 'beobachtete ADS-B-Flugdauer').mean():.0%} der Flüge",
                f"Ziele ohne Bahn-Eintrag (nicht im Bahnvergleich): {', '.join(ohne_bahn) or '-'}",
                "\nAnnahmen: " + ", ".join(f"{k}={v}" for k, v in a.items()), ""]
    bericht += hypothesen(df, ziele, a)
    (ordner / "bericht.txt").write_text("\n".join(bericht), encoding="utf-8")
    grafiken(ziele, df, a, ordner)
    print("\n".join(bericht))
    print(f"\nFertig. Ergebnisse in: {ordner.resolve()}")


if __name__ == "__main__":
    main()
