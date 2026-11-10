# Air or rail from Stuttgart: open flight tracking data, analysis code and learning tool

**Learning tool online:** https://creatorlab-edu.github.io/flug-vs-bahn-stuttgart/ (German/English, runs in any browser)

This repository contains the data, code, results and learning tool for:

> Nepper, H. H. *Open flight tracking data show that framing drives the air to rail substitution potential.* Submitted to npj Sustainable Mobility and Transport (2026).

All 893 departures from Stuttgart Airport (EDDS) between 19 and 25 October 2026 were reconstructed from open ADS-B data of the OpenSky Network, CO₂ per flight was estimated with the open aircraft performance model OpenAP, and 24 destinations within 600 km were compared with rail. The analysis quantifies how much the CO₂ saving of replacing flights with rail depends on the substitution criterion, travellers' behaviour and the accounting of the saving.

## Contents

| Folder | Content |
|---|---|
| `code/` | `flug_vs_bahn_stuttgart.py` – data pipeline: OpenSky retrieval, classification, fuel and CO₂ per flight with OpenAP, door-to-door times, rail comparison |
| | `paper_analysen.py` – analysis questions Q1–Q5, scenario model, one-at-a-time and Monte Carlo sensitivity analysis, Sobol indices, statistics, tables and figures |
| | `paper_analysen_npj.py` – identical analysis; figures in the style of the journal (Okabe–Ito colours, Arial, separate files) |
| | `werkzeug_bauen.py` and `werkzeug/` – builds the learning tool from the results |
| | `requirements.txt` (pinned versions), `ANLEITUNG.md` (step-by-step instructions in German) |
| `data/input/` | Rail times (Deutsche Bahn journey planner, 2 November 2026), operator list (call-sign prefixes), hourly fuel table for aircraft without an OpenAP model, checklists used for manual verification |
| `data/processed/` | Derived from the OpenSky records: all classified flights, passenger flights with fuel and CO₂, destination summary, run report with the data funnel |
| `results/` | `stats.json` (every number reported in the article), tables (CSV, Markdown), figures (PDF, EPS, SVG, PNG); see `results/README.md` for the figure numbering |
| `docs/` | `index.html` – the learning tool as a single HTML file, published with GitHub Pages |

The model equations, each with the function that implements it, are given in Supplementary Note 1 of the article.

## Reproduce the analysis

From the archived processed data (reproduces every number in the article):

```bash
python -m pip install -r code/requirements.txt
cd code
python paper_analysen_npj.py --ergebnisse ../data/processed --ausgabe paper
python werkzeug_bauen.py --ergebnisse ../data/processed --stats paper/stats.json \
       --bahnzeiten ../data/input/bahnzeiten_ab_stuttgart.csv --ausgabe flug_bahn_werkzeug.html
```

Only one count needs the raw records: the classes of the 187 departures without an estimated destination (`classes_without_destination` in `results/stats.json`). Tested with Python 3.13.18; the Monte Carlo analysis uses a fixed seed (20261030).

## Raw data

The raw OpenSky departure records are not included, because the OpenSky Network terms of use govern their redistribution. To retrieve them:

1. Register at https://opensky-network.org, create an API client in your account settings and save the file `credentials.json` in `code/`. **Never share or commit this file** (it is listed in `.gitignore`).
2. Download the OpenSky aircraft database (`aircraft-database-complete-2025-08.csv`) from the OpenSky Network.
3. Run the full pipeline for the study week (UTC):

```bash
python flug_vs_bahn_stuttgart.py --quelle rest --start 2026-10-19 --ende 2026-10-25 \
       --zugang credentials.json --flugzeugdb aircraft-database-complete-2025-08.csv \
       --bahn ../data/input/bahnzeiten_ab_stuttgart.csv --ausgabe ergebnisse
```

The script calls the REST endpoint `/flights/departure` day by day and saves the raw records as `ergebnisse/fluege_roh.csv`. OpenSky may reprocess historical data, so a new download can differ slightly from the archived run; `data/processed/bericht.txt` documents its counts (893 departures). The default `--quelle` is a synthetic demo; always pass `--quelle rest` or `--quelle csv`.

The same method can be applied to any other airport and period by changing the constant `FLUGHAFEN` at the top of `flug_vs_bahn_stuttgart.py`, the options `--start` and `--ende`, and the rail table.

## Learning tool

`docs/index.html` contains the observed scheduled departures, fuel, seats, distances and flight times per destination, both rail times and the reference assumptions. Fifteen controls cover every assumption of the sensitivity analysis plus the substitution criterion, the accounting of the saving, access times and a non-CO₂ factor; each is labelled as a model assumption, a behavioural scenario or a value-laden framing. The observed data cannot be changed. The tool was designed for a two-session seminar module in technology teacher education (technology assessment following VDI 3780) and works offline after download.

## Citation

Please cite the article and this repository (see `CITATION.cff` or the Zenodo record). Flight data: Schäfer, M. et al. Bringing up OpenSky: a large-scale ADS-B sensor network for research. In *Proc. IPSN 2014*, 83–94 (IEEE, 2014). Aircraft performance: Sun, J., Hoekstra, J. M. & Ellerbroek, J. OpenAP. *Aerospace* **7**, 104 (2020).

## Licences

- Code (`code/`): MIT licence, see `LICENSE`.
- Data, results, figures and the learning tool (`data/`, `results/`, `docs/`): Creative Commons Attribution 4.0 (CC BY 4.0), see `LICENSE-CC-BY-4.0.md`.
- Derived flight data are based on data of the OpenSky Network (© OpenSky Network; terms of use for research and non-commercial purposes).
- The logos in `code/werkzeug/` belong to the University of Education Schwäbisch Gmünd and CreatorLab and are not covered by the licences above.

## Use of generative AI

The code was written with the support of the AI assistant Claude (Anthropic) and verified by the author (hand recomputation of single flights, reproduction of the analysis values by the tool, checks of all tables against their sources). The AI assistant did not use the OpenSky credentials and did not retrieve flight data.

---

## Kurzbeschreibung (Deutsch)

Dieses Repository enthält Daten, Code, Ergebnisse und das Lernwerkzeug zur Studie „Flug oder Bahn ab Stuttgart“: alle 893 Abflüge vom Flughafen Stuttgart in der Woche vom 19. bis 25. Oktober 2026, rekonstruiert aus offenen ADS-B-Daten des OpenSky Network, mit CO₂-Schätzung je Flug (OpenAP) und Bahnvergleich für 24 Ziele im Umkreis von 600 km. Das Lernwerkzeug (`docs/index.html`, online unter dem Link oben) wurde für einen Seminarbaustein zur Technikbewertung in der Techniklehrkräftebildung entwickelt. Eine ausführliche deutsche Anleitung zu den Skripten steht in `code/ANLEITUNG.md`.
