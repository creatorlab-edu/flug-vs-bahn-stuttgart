#!/usr/bin/env python3
"""
Baut das Lernwerkzeug "Flug oder Bahn ab Stuttgart" aus den Analyseergebnissen
============================================================================
Das Werkzeug ist ein Ergebnis der Analyse: Es enthält genau die Daten, die
flug_vs_bahn_stuttgart.py für den Artikel erzeugt hat (je Ziel aggregiert), und die
Referenzannahmen der Analyse. Die Studierenden laden nichts hoch und prüfen die Daten
nicht erneut; sie verändern nur die Annahmen.

    python werkzeug_bauen.py --ergebnisse ergebnisse --stats paper/stats.json --ausgabe werkzeug/flug_bahn_werkzeug.html

Die Vorlage liegt in werkzeug/vorlage.html; der Platzhalter /*__DATEN__*/null wird ersetzt.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HIER = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ergebnisse", default="ergebnisse")
    ap.add_argument("--vorlage", default=str(HIER / "werkzeug" / "vorlage.html"))
    ap.add_argument("--ausgabe", default=str(HIER / "werkzeug" / "flug_bahn_werkzeug.html"))
    ap.add_argument("--bahnzeiten", default=str(HIER / "bahnzeiten_ab_stuttgart.csv"))
    ap.add_argument("--stats", help="stats.json aus paper_analysen.py (Standard: <ergebnisse>/../paper/stats.json)")
    args = ap.parse_args()

    e = Path(args.ergebnisse)
    df = pd.read_csv(e / "fluege_ausgewertet.csv")
    bericht = (e / "bericht.txt").read_text(encoding="utf-8") if (e / "bericht.txt").exists() else ""
    demo = "DEMO" in bericht
    df["privat"] = df["privat"].astype(str).str.lower().isin(["true", "1"])
    linie = df[~df["privat"]].copy()
    start = pd.to_datetime(df["start"], utc=True, errors="coerce")
    tage = max(1, round((start.max() - start.min()).total_seconds() / 86400)) if start.notna().any() else 7

    def first(s):
        s = s.dropna()
        return s.iloc[0] if len(s) else None

    zeilen = []
    for (icao, name), g in linie.groupby(["ziel", "zielname"]):
        bahn = first(g["bahn_min"])
        zeilen.append(dict(
            icao=icao, name=name, n=int(len(g)),
            fuel=round(float(g["kraftstoff_kg"].sum())), seats=int(g["sitze"].sum()),
            km=round(float(g["luftlinie_km"].iloc[0])), dur=round(float(g["dauer_min"].fillna(g["modell_dauer_min"]).median()), 1),
            rail=None if bahn is None else int(bahn),
            railStation=first(g.get("bahnhof_ziel", pd.Series(dtype=object))),
            railHub=None if first(g.get("bahn_min_umst", pd.Series(dtype=float))) is None
            else int(first(g["bahn_min_umst"])),
            hubStation=first(g.get("bahnhof_umst", pd.Series(dtype=object))),
            hub=first(g["drehkreuz"]) == "ja",
            transfer=float(first(g.get("umsteiger_anteil", pd.Series(dtype=float))) or 0.0),
        ))
    # Referenzannahmen der Analyse (Basiswerte) aus dem Bericht übernehmen, sonst Standard
    basis = dict(crit=0, dm=60, acc=0, thr=240, ms=1.0, lf=0.8, fe=1.0, nc=1.0, rg=29, rd=1.25, aa=150, ra=40, aat=120, rat=110)
    schluessel = dict(bahn_grenze_min="thr", auslastung="lf", bahn_g_pkm="rg", bahn_umweg="rd",
                      flug_zugang_min="aa", bahn_zugang_min="ra", flug_zugang_umst_min="aat",
                      bahn_zugang_umst_min="rat")
    for teil in bericht.split("Annahmen:")[-1].split("\n")[0].split(","):
        if "=" in teil:
            k, v = [x.strip() for x in teil.split("=", 1)]
            if k in schluessel:
                try:
                    basis[schluessel[k]] = float(v)
                except ValueError:
                    pass
    hubs = [z["transfer"] for z in zeilen if z["hub"]]
    basis["tr"] = round(float(np.mean(hubs)), 2) if hubs else 0.5

    # Ziele der Bahntabelle ohne Linien-/Charterflug im Zeitraum (z. B. Frankfurt, Paris): nur als Hinweis
    ohne_flug = []
    if Path(args.bahnzeiten).exists():
        bz = pd.read_csv(args.bahnzeiten)
        mit_flug = {z["icao"] for z in zeilen}
        for icao, g in bz.groupby("icao", sort=False):
            if icao in mit_flug:
                continue
            st = g[g["szenario"] == "stadt"]
            ohne_flug.append(dict(icao=icao, name=str(g["ziel"].iloc[0]),
                                  rail=int(st["bahn_min"].iloc[0]) if len(st) else None,
                                  privat=int(df[(df["ziel"] == icao) & df["privat"]].shape[0])))
        ohne_flug.sort(key=lambda z: (z["rail"] is None, z["rail"] or 0))
    # Für den Unterrichtsablauf: Datentrichter aus dem Bericht und Hypothesenergebnisse aus stats.json
    import re
    trichter = {}
    m = re.search(r"Rohdaten: (\d+) Abflüge, davon ohne geschätztes Ziel: (\d+)", bericht)
    if m:
        trichter.update(raw=int(m.group(1)), noDest=int(m.group(2)))
    m = re.search(r"Datentrichter: \d+ - \d+ ohne Ziel - (\d+) Rückkehr.*? - (\d+) Zielflughafen", bericht)
    if m:
        trichter.update(back=int(m.group(1)), noAirport=int(m.group(2)))
    m = re.search(r"Klassen \(mit Ziel\): (.*)", bericht)
    if m:
        for teil in m.group(1).split(","):
            name, _, zahl = teil.strip().rpartition(" ")
            if zahl.isdigit():
                trichter[{"Linie/Charter": "scheduled", "Privat/Geschäft": "private", "Fracht": "cargo",
                          "Unter 100 km": "short", "Staat/Militär": "state"}.get(name, name)] = int(zahl)
    for schluessel_, muster in (("proxy", r"Ersatzmodell geschätzt: (\d+)%"), ("observed", r"ADS-B-Beobachtung: (\d+)%")):
        m = re.search(muster, bericht)
        if m:
            trichter[schluessel_] = int(m.group(1))
    hyp = None
    sp = Path(args.stats) if args.stats else e.parent / "paper" / "stats.json"
    if sp.exists():
        s = json.loads(sp.read_text(encoding="utf-8"))
        sc = pd.read_csv(sp.parent / "tables" / "T6_structural_scenarios.csv") if (sp.parent / "tables" / "T6_structural_scenarios.csv").exists() else None
        dd = float(sc.loc[sc["criterion"].str.contains(r"\+ 60 min$"), "saving_t"].iloc[0]) if sc is not None else None
        en = {"Munich": "München", "Cologne/Bonn": "Köln/Bonn", "Nuremberg": "Nürnberg", "Brussels": "Brüssel",
              "Prague": "Prag", "Zurich": "Zürich", "Vienna": "Wien"}
        hyp = dict(
            h1=dict(pax=s["Q1"]["share_passengers"], co2=s["Q1"]["share_co2"], ref=s["Q1"]["saving_t_reference"],
                    lo=s["Q1"]["mc_95_range"][0], hi=s["Q1"]["mc_95_range"][1], dd=dd),
            h2=dict(rho=s["Q2"]["rho"], lo=s["Q2"]["ci"][0], hi=s["Q2"]["ci"][1],
                    none=", ".join(en.get(n, n) for n, m, f in s["Q2"]["rail_rank"] if f == 0 and m <= 240)),
            h3=dict(el=s["Q3_mixed"]["elasticity"], short=s["Q3_short_long"]["median_short"], long=s["Q3_short_long"]["median_long"]),
            h4=dict(priv=s["Q4"]["median_private"], sched=s["Q4"]["median_scheduled"], ratio=s["Q4"]["ratio"],
                    eq=s["Q4"]["ratio_equal_lf"], share=s["Q4"]["share_flights"], co2=s["Q4"]["share_co2"]),
            h5=dict(diff=s["Q5"]["median_diff_min"], faster=s["Q5"]["n_rail_faster"], n=s["Q5"]["n"],
                    names=s["Q5"]["rail_faster"], lo=s["Q5"]["range_n_rail_faster"][0], hi=s["Q5"]["range_n_rail_faster"][1]))
    daten = dict(funnel=trichter, hyp=hyp, noFlight=ohne_flug,demo=demo, days=int(tage), period=f"{start.min():%d.%m.%Y}–{start.max():%d.%m.%Y}"
                 if start.notna().any() and not demo else None,
                 nFlights=int(len(linie)), basis=basis,
                 rows=sorted([z for z in zeilen if z["rail"] is not None], key=lambda z: z["km"]),
                 # Ziele ohne Bahnalternative (Urlaubs- und Fernziele): nur als Summe, zählen bei den Anteilen mit
                 other=dict(n=sum(z["n"] for z in zeilen if z["rail"] is None),
                            seats=sum(z["seats"] for z in zeilen if z["rail"] is None),
                            dests=sum(1 for z in zeilen if z["rail"] is None)))
    html = Path(args.vorlage).read_text(encoding="utf-8")
    if "/*__DATEN__*/null" not in html:
        raise SystemExit("Platzhalter /*__DATEN__*/null fehlt in der Vorlage.")
    html = html.replace("/*__DATEN__*/null", json.dumps(daten, ensure_ascii=False))
    # Logos (CreatorLab als PNG/base64, PH Gmünd als einfarbiges SVG) aus dem Ordner werkzeug/
    w = Path(args.vorlage).parent
    if (w / "cl_logo.b64").exists():
        html = html.replace("/*__CL_LOGO__*/", (w / "cl_logo.b64").read_text().strip())
    if (w / "ph_logo.svg").exists():
        html = html.replace("/*__PH_LOGO__*/", (w / "ph_logo.svg").read_text().replace("<svg", '<svg class="ph"', 1))
    Path(args.ausgabe).write_text(html, encoding="utf-8")
    print(f"Werkzeug geschrieben: {Path(args.ausgabe).resolve()}  ({len(zeilen)} Ziele, {tage} Tage, demo={demo})")


if __name__ == "__main__":
    main()
