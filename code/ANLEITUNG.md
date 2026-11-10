# Flug vs. Bahn ab Stuttgart – Auswertung mit OpenSky-ADS-B-Daten

## 1. Ordner und Vorbereitung

So sieht der Projektordner aus (z. B. `~/Desktop/flug_vs_bahn`):

```
flug_vs_bahn/
├── flug_vs_bahn_stuttgart.py     Auswertung (OpenSky-Abruf, CO2, Bahnvergleich, Hypothesen)
├── paper_analysen.py             Analysen, Statistik und Abbildungen für den Artikel
├── paper_analysen_npj.py         dieselben Analysen, Abbildungen im Stil der Zeitschrift (npj)
├── werkzeug_bauen.py             baut das Lernwerkzeug aus den Ergebnissen
├── bahnzeiten_ab_stuttgart.csv   geprüfte Bahnzeiten (DB-Auskunft, 2.11.2026)
├── betreiber.csv                 Rufzeichen-Präfix -> Fracht / Staat/Militär / Privat/Geschäft
├── ersatz_verbrauch.csv          Stundenverbrauch für Typen ohne OpenAP-Modell (Kolben, Turboprop)
├── requirements.txt              benötigte Python-Pakete
├── ANLEITUNG.md                  diese Anleitung
├── credentials.json              DEINE OpenSky-Zugangsdatei (selbst hineinlegen, nie weitergeben)
├── aircraft-database-….csv       OpenSky-Flugzeugdatenbank (selbst herunterladen, siehe 3.)
└── werkzeug/
    └── vorlage.html              Vorlage des Lernwerkzeugs
```

Die Ordner `ergebnisse/` und `paper/` legen die Skripte selbst an.

Im Terminal in den Ordner wechseln und die Pakete einmalig installieren:

```bash
cd ~/Desktop/flug_vs_bahn
python3 -m pip install -r requirements.txt
```

**Erst testen:** `python3 flug_vs_bahn_stuttgart.py --quelle demo`
Das läuft ohne Zugangsdaten mit **synthetischen** Flügen und zeigt nur, ob alles funktioniert. Die Demo-Ergebnisse haben keine Aussagekraft.

## 2. OpenSky-Zugang

1. Auf opensky-network.org einloggen und die Account-Seite öffnen (https://opensky-network.org/my-opensky/account).
2. Einen **API-Client** anlegen und die Datei **`credentials.json`** herunterladen.
3. `credentials.json` in den Projektordner legen. Das Skript liest sie automatisch; liegt sie woanders: `--zugang pfad/zu/credentials.json`.

**Zwei Wege zu den Daten:**

| | REST-API (`--quelle rest`) | Trino-Datenbank (`--quelle trino`) |
|---|---|---|
| Geeignet für | Tage bis wenige Wochen | Monate, Jahre, Vorher-nachher-Vergleiche |
| Zugang | API-Client, sofort | Forschungszugang bei OpenSky beantragen (für Hochschulen kostenlos) |
| Grenzen | Tageskontingent („Credits“), Daten erst ab dem Vortag | kaum |

Das Skript fragt tageweise ab und speichert jeden Tag im Ordner `ergebnisse/cache`. Wird das Kontingent knapp, einfach später erneut starten: Bereits geholte Tage werden nicht noch einmal abgefragt.

## 3. Flugzeugtypen (wichtig für die CO2-Schätzung)

Die Flugdaten enthalten nur die ICAO24-Adresse, nicht den Typ. Den liefert die **OpenSky-Flugzeugdatenbank** (CSV, auf der OpenSky-Website unter „Datasets → Metadata“). Herunterladen und übergeben:

```bash
python3 flug_vs_bahn_stuttgart.py --quelle rest --start 2026-10-19 --ende 2026-10-25 \
    --flugzeugdb aircraft-database-complete-JJJJ-MM.csv
```

Ohne Datenbank werden Linienflüge als A320 und Privatflüge als Cessna Citation II gerechnet, und im Bericht steht dann „Ersatzmodell 100 %“.

Für Typen ohne OpenAP-Modell (z. B. Cirrus SR22, King Air, Pilatus PC-12, ATR 72) nutzt das Skript `ersatz_verbrauch.csv`: typischer Stundenverbrauch × beobachtete Flugdauer. Die Werte stammen aus Hersteller- und Betreiberangaben und wurden geprüft; die Spalte `hinweis` nennt Prüfung und Datum.

## 3a. Flugklassen (betreiber.csv)

Nicht jeder Abflug ist ein Passagierflug. Das Skript ordnet jeden Flug einer Klasse zu: **Linie/Charter**, **Privat/Geschäft**, **Fracht**, **Staat/Militär** oder **Unter 100 km** (Hubschrauber, Schul- und Platzflüge). Nur Linie/Charter und Privat/Geschäft gehen in die Passagieranalyse; alle Flüge mit Klasse stehen in `ergebnisse/fluege_alle_klassen.csv`.

Grundlage ist der Rufzeichen-Präfix (die ersten drei Buchstaben, z. B. `TAY` = ASL Airlines Belgium, Fracht) in `betreiber.csv`. Alle Einträge wurden geprüft (`sicher = ja`). Neue, unsichere Präfixe trägst du mit `sicher = nein` ein. Der Bericht listet alle Präfixe, die als Linie/Charter gezählt wurden; fragliche Präfixe in `betreiber.csv` ergänzen und das Skript mit `--quelle csv --flugdatei ergebnisse/fluege_roh.csv` erneut laufen lassen (kein neuer Abruf nötig).

## 4. Bahnzeiten prüfen (zwei Szenarien)

`bahnzeiten_ab_stuttgart.csv` enthält die mit der DB-Auskunft geprüften Fahrzeiten (Montag, 2. 11. 2026, schnellste Verbindung am Vormittag). Abfragezeit und Link stehen in den Spalten `quelle` und `url`; bei einer neuen Abfrage diese beiden Spalten mit aktualisieren. Jede Zeile nennt Start- und Zielbahnhof:

- `szenario = stadt`: Stuttgart Hbf → Hauptbahnhof der Zielstadt. Vergleich für Reisende in die Stadt; der Weg vom Zielflughafen in die Stadt steckt in der Zugangszeit des Flugs.
- `szenario = flughafen` (nur Drehkreuze): Stuttgart Hbf → Flughafenbahnhof (z. B. Frankfurt (M) Flughafen Fernbf, Schiphol). Vergleich für Umsteiger zu Anschlussflügen.

`umsteiger_anteil` (in der Flughafenzeile) ist eine **Annahme**: ADS-B-Daten zeigen nicht, wer am Drehkreuz weiterfliegt. Standard 0,5; mit `--umsteiger-anteil 0.3` für alle Drehkreuze überschreibbar. Die Analyse für den Artikel variiert ihn zwischen 30 und 70 %.

Zugangszeiten für Umsteiger: `--flug-zugang-umst-min` (Standard 120: Anfahrt, Sicherheit, Mindestumsteigezeit) und `--bahn-zugang-umst-min` (Standard 110: Anfahrt Hbf, Check-in und Sicherheit am Drehkreuz, Puffer).

## 5. Ergebnisse (Ordner `ergebnisse/`)

| Datei | Inhalt |
|---|---|
| `fluege_roh.csv` | Rohdaten von OpenSky (zum erneuten Auswerten mit `--quelle csv --flugdatei ...`) |
| `fluege_ausgewertet.csv` | jeder Flug mit Typ, Entfernung, beobachteter Dauer, Kraftstoff, CO2 |
| `ziele_flug_vs_bahn.csv` | pro Ziel: Flüge/Woche, CO2, Tür-zu-Tür-Zeiten, Bahnvergleich |
| `bericht.txt` | Annahmen, Datenqualität und Hypothesentests |
| `1_…` bis `4_….png` | Grafiken |

## 6. Hypothesen im Skript

- **H1** (deskriptiv): Anteil der Flüge und Emissionen auf Strecken mit Bahn ≤ 4 h; rechnerisches Einsparpotenzial (Obergrenze).
- **H2**: Je kürzer die Bahnfahrzeit, desto weniger Flüge, bei Kontrolle der Entfernung. Spearman-Korrelation und Quasi-Poisson-Regression. Ziele aus der Bahntabelle ohne Flüge zählen mit 0, sonst fehlen genau die Strecken, auf denen die Bahn schon gewonnen hat. Fallzahl = Anzahl der Ziele, also nur explorativ.
- **H3**: Kurzstrecken verursachen mehr CO2 je Personenkilometer (Spearman, Mann-Whitney).
- **H4**: Privat-/Geschäftsflüge verursachen mehr CO2 pro Person als Linienflüge (Mann-Whitney).

## 7. Methodische Grenzen

- **CO2 ist modelliert, nicht gemessen.** OpenAP schätzt den Treibstoff aus Flugzeugtyp und Flugprofil. Die beobachtete ADS-B-Flugdauer bestimmt die Reiseflugphase (Umwege, Warteschleifen, Wind). Masse, Auslastung und Sitzzahl sind Annahmen. Für einige Typen (A220, ATR, Dash 8, viele Bizjets) gibt es kein eigenes Modell; sie werden über ähnliche Typen geschätzt und in `typ_ersatz` markiert. Turboprops werden damit eher überschätzt.
- **Nur CO2.** Nicht-CO2-Effekte (Kondensstreifen, Stickoxide) fehlen. Sie können die Klimawirkung des Fliegens deutlich erhöhen; das UBA rechnet dafür mit Aufschlagfaktoren. Wenn du sie berücksichtigst, gib den Faktor als Annahme an.
- **Ziel-Flughafen** wird von OpenSky geschätzt (`estArrivalAirport`) und fehlt bei manchen Flügen. Diese Flüge fallen heraus.
- **Bahn-CO2** (Standard 29 g/Pkm) hängt stark am Strommix. Die DB rechnet im Fernverkehr mit Ökostrom deutlich niedriger, das UBA mit dem deutschen Strommix. Wert mit `--bahn-g-pkm` anpassen und als Sensitivitätsanalyse beide Varianten rechnen.
- **Tür-zu-Tür-Zeiten** sind Pauschalannahmen (`--flug-zugang-min`, `--bahn-zugang-min`).
- **Verlagerung ≠ Einsparung.** Umsteiger zu Langstrecken, Ausweichen aufs Auto und frei werdende Start-/Landerechte (Slots) für andere Flüge werden nicht abgebildet. Darauf weisen Reiter et al. (2022) und die Evaluation des französischen Verbots (Txapartegi et al. 2024) ausdrücklich hin.

Alle Annahmen lassen sich per Kommandozeile ändern, z. B. `--auslastung 0.75 --bahn-g-pkm 10`. Mit `python3 flug_vs_bahn_stuttgart.py -h` siehst du alle Optionen.

## 8. Analysen und Abbildungen für den Artikel

```bash
python3 paper_analysen_npj.py --ergebnisse ergebnisse --ausgabe paper
```

`paper_analysen.py` rechnet genau dasselbe, nur mit dem ursprünglichen Abbildungsstil.

Erzeugt:
- `paper/stats.json`: alle Zahlen, die im Artikel berichtet werden
- `paper/tables/`: Ziele des Bahnvergleichs, Sensitivitätsanalyse mit Sobol-Indizes, Tür-zu-Tür-Zeiten, strukturelle Szenarien, Bilanzierung der Einsparung, Modellierungswege und Sitzplätze
- `paper/figures/Fig1–Fig7`: als PDF, EPS, PNG und SVG (600 dpi, 174 mm breit)

Welche Datei welcher Abbildung im Artikel entspricht, steht in `results/README.md`. Läuft die Analyse auf Demo-Daten, tragen alle Abbildungen den Stempel „SYNTHETIC DEMO DATA“.

## 9. Lernwerkzeug bauen

```bash
python3 werkzeug_bauen.py --ergebnisse ergebnisse --stats paper/stats.json --ausgabe werkzeug/flug_bahn_werkzeug.html
```

Bettet die Analyseergebnisse (je Ziel) und die Basisannahmen in `werkzeug/vorlage.html` ein. Die Studierenden laden nichts hoch und prüfen die Daten nicht erneut; sie verändern nur die Annahmen. Bei den Referenzannahmen liefert das Werkzeug dieselbe Einsparung wie das Referenzszenario der Analyse (222 t CO₂ pro Woche).

## 10. Mögliche Erweiterung: natürliches Experiment

Mit dem Trino-Zugang lässt sich ein Vorher-nachher-Vergleich rechnen: Wie entwickelten sich die Flüge Stuttgart–München nach der Eröffnung der Neubaustrecke Wendlingen–Ulm (Dezember 2022), im Vergleich zu Kontrollstrecken ohne Bahnverbesserung (Differenz-von-Differenzen-Ansatz)? Genauso können künftige Fahrzeitverkürzungen im Bahnknoten Stuttgart untersucht werden, sobald sie in Betrieb sind.
