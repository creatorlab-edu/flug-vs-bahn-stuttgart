#!/usr/bin/env python3
"""
Analyses and figures for the article on air-rail substitution from Stuttgart (npj figure style)
===============================================================================================
Reads the output of flug_vs_bahn_stuttgart.py (folder with fluege_ausgewertet.csv and
ziele_flug_vs_bahn.csv) and produces:

  paper/tables/*.csv + tables.md     all tables and statistics reported in the article
  paper/stats.json                   every number reported in the article
  paper/figures/Fig1..Fig7 .pdf/eps/png/svg (600 dpi, 174 mm wide; numbering in the article: results/README.md)

Usage:
    python paper_analysen.py --ergebnisse ergebnisse --ausgabe paper [--demo]
--demo stamps every figure with "SYNTHETIC DEMO DATA" (set automatically if the run was a demo).

Analysis questions (labelled by evidence type; no significance tests on model output)
  Q1  substitution potential (scenario): reference = technical upper bound; one-at-a-time sensitivity centred on
      the reference, 10,000-draw Monte Carlo reported as "95 % range of simulated scenarios", first-order Sobol
      indices (given-data estimator), structural scenarios (in-vehicle 2.5-5 h, door-to-door +0/60/120 min,
      access times), whole-flight (capacity-response) accounting
  Q2  rail time vs. flight frequency (empirical, exploratory): Spearman with bootstrap CI, collinearity with distance
  Q3  distance vs. CO2 per passenger-km (model-based): log-log mixed model (random intercept per aircraft model)
  Q4  private/business vs. scheduled (model-based): ratio of medians at assumed and at equal load factors
  Q5  door-to-door time (scenario): scheduled flights only, access times varied
"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
RNG = np.random.default_rng(20261030)
MM = 1 / 25.4
W2 = 174 * MM   # double-column width (Springer large format)

# --------------------------------------------------------------------------- style
PAL = dict(air="#D55E00", rail="#0072B2", neutral="#6E7681", hub="#56B4E9", private="#CC79A7",
           ink="#1F2328", grid="#E6E8EB")


def style():
    import matplotlib as mpl
    mpl.rcParams.update({
        "font.family": ["Arial", "Liberation Sans"], "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
        "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "legend.fontsize": 7.5, "svg.fonttype": "none", "axes.edgecolor": PAL["ink"],
        "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6, "lines.linewidth": 1.0,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": PAL["grid"],
        "grid.linewidth": 0.5, "axes.axisbelow": True, "figure.dpi": 150, "savefig.dpi": 600,
        "pdf.fonttype": 42, "ps.fonttype": 42, "axes.titleweight": "bold", "axes.titlelocation": "left"})


def speichern(fig, ordner: Path, name: str, demo: bool):
    if demo:
        fig.text(0.5, 0.5, "SYNTHETIC DEMO DATA – NOT RESULTS", ha="center", va="center", rotation=22,
                 fontsize=20, color="#B00020", alpha=0.18, weight="bold", zorder=100)
    for ext in ["pdf", "eps", "png", "svg"]:
        fig.savefig(ordner / f"{name}.{ext}", bbox_inches="tight")


# --------------------------------------------------------------------------- statistics helpers
def cliffs_delta(x, y):
    x, y = np.asarray(x), np.asarray(y)
    gt = (x[:, None] > y[None, :]).mean()
    lt = (x[:, None] < y[None, :]).mean()
    return gt - lt


def boot_ci(f, *arrays, n=5000, alpha=0.05):
    stats_ = []
    for _ in range(n):
        res = [a[RNG.integers(0, len(a), len(a))] for a in arrays]
        try:
            stats_.append(f(*res))
        except Exception:
            pass
    stats_ = np.array(stats_)
    stats_ = stats_[np.isfinite(stats_)]
    return (float(np.quantile(stats_, alpha / 2)), float(np.quantile(stats_, 1 - alpha / 2))) if len(stats_) else (np.nan, np.nan)


def boot_ci_paired(f, x, y, n=5000):
    x, y = np.asarray(x), np.asarray(y)
    vals = []
    for _ in range(n):
        i = RNG.integers(0, len(x), len(x))
        try:
            vals.append(f(x[i], y[i]))
        except Exception:
            pass
    vals = np.array(vals)
    vals = vals[np.isfinite(vals)]
    return float(np.quantile(vals, .025)), float(np.quantile(vals, .975))


def holm(pvals: dict) -> dict:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def plain_log_ticks(axis, ticks):
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator
    axis.set_major_locator(FixedLocator(ticks))
    axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    axis.set_minor_locator(NullLocator())


def labels_ohne_ueberlappung(ax, texte):
    try:
        from adjustText import adjust_text
        adjust_text(texte, ax=ax, arrowprops=dict(arrowstyle="-", color="#9AA0A6", lw=0.4))
    except ImportError:
        pass


def fmt_p(p):
    return "< .001" if p < .001 else f"= {p:.3f}".replace("0.", ".")


# --------------------------------------------------------------------------- analyses
def lade(ordner: Path):
    df = pd.read_csv(ordner / "fluege_ausgewertet.csv")
    z = pd.read_csv(ordner / "ziele_flug_vs_bahn.csv")
    for c in ["privat", "typ_ersatz", "bahn_konkurrenzfaehig"]:
        if c in df:
            df[c] = df[c].astype(str).str.lower().isin(["true", "1"])
    bericht = (ordner / "bericht.txt").read_text(encoding="utf-8") if (ordner / "bericht.txt").exists() else ""
    return df, z, "DEMO" in bericht


# ---- English place names for figures and tables
NAMEN_EN = {"München": "Munich", "Wien": "Vienna", "Genf": "Geneva", "Prag": "Prague", "Zürich": "Zurich",
            "Köln/Bonn": "Cologne/Bonn", "Brüssel": "Brussels", "Kopenhagen": "Copenhagen", "Nürnberg": "Nuremberg",
            "Nurnberg": "Nuremberg", "Mailand": "Milan", "Venedig": "Venice", "Nizza": "Nice", "Luxemburg": "Luxembourg",
            "Milano Malpensa": "Milan", "Venezia Tessera": "Venice", "Nice/Cote D'Azur": "Nice", "Lyon Bron": "Lyon",
            "Dortmund": "Dortmund", "Bern": "Bern"}


def en(n):
    return NAMEN_EN.get(n, n)


# ---- destination-selection rule: (a) every destination with >= 1 scheduled flight within 600 km
# great-circle distance; (b) the airports of German cities above 500,000 inhabitants and of the capitals of
# Germany's neighbouring countries within 600 km, even without a flight in the study week.
GRENZE_KM = 600
PFLICHT = {"EDDB", "EDDH", "EDDM", "EDDK", "EDDF", "EDDL", "EDDP", "EDLW", "EDDW", "EDDC", "EDDV", "EDDN",
           "EHAM", "EBBR", "ELLX", "LFPG", "LSZB", "LOWW", "LKPR"}


def ziele_auswahl(z):
    lf = z["linienfluege"] if "linienfluege" in z else z["fluege"] - z["davon_privat"]
    nah = z["luftlinie_km"] <= GRENZE_KM
    return z[nah & ((lf > 0) | z["ziel"].isin(PFLICHT))].copy()


# ---- H1 scenario model
# Reference scenario = technical upper bound reported in the text and the tool: every passenger for whom rail is
# within the in-vehicle threshold switches, average-emission accounting.
REF = dict(load_factor=0.80, fuel_model_error=1.00, proxy_fuel_factor=1.00, rail_g_pkm=29.0, rail_detour=1.25,
           modal_shift_share=1.00, transfer_share_hubs=0.50, threshold_min=240.0, taxi_min=15.0)
RANGES = dict(load_factor=(0.65, 0.90), fuel_model_error=(0.85, 1.15), proxy_fuel_factor=(0.75, 1.25),
              rail_g_pkm=(5.0, 45.0), rail_detour=(1.15, 1.40), modal_shift_share=(0.5, 1.0),
              transfer_share_hubs=(0.3, 0.7), threshold_min=(180.0, 300.0), taxi_min=(10.0, 25.0))
LABEL = dict(load_factor="Load factor (0.65–0.90)", fuel_model_error="Fuel model error (±15 %)",
             proxy_fuel_factor="Substitute/default aircraft models (±25 %)", rail_g_pkm="Rail g CO₂/pkm (5–45)",
             rail_detour="Rail detour (1.15–1.40)", modal_shift_share="Share actually shifting (50–100 %)",
             transfer_share_hubs="Transfer share at hubs (30–70 %)",
             threshold_min="In-vehicle threshold (3–5 h)", taxi_min="Taxi time (10–25 min)")
ZUGANG = dict(air_city=150, rail_city=40, air_hub=120, rail_hub=110, taxi_half=7.5)


class H1Modell:
    def __init__(self, df):
        l = df[~df["privat"] & df["bahn_min"].notna()].copy()
        self.l, self.alle = l, df[~df["privat"]]
        self.fuel = l["kraftstoff_kg"].values
        self.roll = l["rollen_kg"].values if "rollen_kg" in l else np.zeros(len(l))
        self.proxy = l["typ_ersatz"].values.astype(bool)
        self.seats, self.km = l["sitze"].values, l["luftlinie_km"].values
        self.hub = (l["drehkreuz"] == "ja").values
        self.t_city = l["bahn_min"].values
        self.t_hub = (l["bahn_min_umst"] if "bahn_min_umst" in l else l["bahn_min"]).fillna(l["bahn_min"]).values
        # airborne time incl. half the taxi time (as in the pipeline)
        # per destination: median airborne time of its scheduled flights (criterion is a property of the route,
        # as in the learning tool)
        self.dur = (l["flug_tuer_min"] - ZUGANG["air_city"]).groupby(l["ziel"]).transform("median").values

    def ok(self, p, kriterium="in-vehicle", marge=0.0, zug=None):
        if kriterium == "in-vehicle":
            return self.t_city <= p["threshold_min"], self.t_hub <= p["threshold_min"]
        g = dict(ZUGANG, **(zug or {}))
        c = self.t_city + g["rail_city"] <= self.dur + g["air_city"] + marge
        h = self.t_hub + g["rail_hub"] <= self.dur + g["air_hub"] + marge
        return c, h

    def gewicht(self, p, **kw):
        c, h = self.ok(p, **kw)
        u = p["transfer_share_hubs"]
        return np.where(self.hub, (1 - u) * c + u * h, c.astype(float))

    def luft_co2(self, p):
        f = (self.fuel - self.roll + self.roll * p["taxi_min"] / 15.0) * p["fuel_model_error"]
        f = f * np.where(self.proxy, p["proxy_fuel_factor"], 1.0)
        return f * 3.16

    def bahn_co2_pax(self, p):
        return self.km * p["rail_detour"] * p["rail_g_pkm"] / 1000

    def einsparung(self, p, ganze_fluege=False, **kw):
        w = self.gewicht(p, **kw) * p["modal_shift_share"]
        pax = self.seats * p["load_factor"]
        air, rail = self.luft_co2(p), pax * self.bahn_co2_pax(p)
        if not ganze_fluege:           # average accounting: emissions allocated pro rata to shifting passengers
            return float((w * (air - rail)).sum() / 1000)
        # capacity response: per route, the airline consolidates the remaining passengers and cancels only whole
        # flights (floor of the shifted flight-equivalents); the remaining flights keep flying with fewer passengers
        g = pd.DataFrame(dict(r=self.l["ziel"].values, w=w, air=air, rail=w * rail))
        t = g.groupby("r").agg(fe=("w", "sum"), air=("air", "mean"), rail=("rail", "sum"))
        return float((np.floor(t["fe"] + 1e-9) * t["air"] - t["rail"]).sum() / 1000)

    def kennzahlen(self, p, **kw):
        w = self.gewicht(p, **kw)
        return dict(n_flights=int((w > 0).sum()),
                    share_flights=float((w > 0).sum() / max(len(self.alle), 1)),
                    share_passengers=float((w * self.seats).sum() / max(self.alle["sitze"].sum(), 1)),
                    share_co2=float((w * self.l["co2_kg"].values).sum() / max(self.alle["co2_kg"].sum(), 1)))


def sobol_erste_ordnung(X: dict, y: np.ndarray, bins=20):
    """Given-data estimator of first-order Sobol indices: Var(E[Y | X_i]) / Var(Y), X_i binned in quantiles."""
    out, vy = {}, float(np.var(y))
    for k, x in X.items():
        q = np.quantile(x, np.linspace(0, 1, bins + 1))
        idx = np.clip(np.searchsorted(q, x, side="right") - 1, 0, bins - 1)
        m = np.array([y[idx == b].mean() for b in range(bins)])
        nb = np.array([(idx == b).sum() for b in range(bins)])
        out[k] = float(np.sum(nb * (m - y.mean()) ** 2) / len(y) / vy) if vy > 0 else 0.0
    return out


def monte_carlo(df: pd.DataFrame, n=10000):
    M = H1Modell(df)
    if not len(M.l):
        return None
    basis = M.einsparung(REF)
    draws = {k: RNG.uniform(*v, n) for k, v in RANGES.items()}
    sims = np.array([M.einsparung({k: draws[k][i] for k in RANGES}) for i in range(n)])
    tornado = []
    for k, (lo, hi) in RANGES.items():       # one-at-a-time, centred on the reference scenario
        a = dict(REF); a[k] = lo; s_lo = M.einsparung(a)
        a = dict(REF); a[k] = hi; s_hi = M.einsparung(a)
        tornado.append(dict(parameter=k, label=LABEL[k], reference=REF[k], low=lo, high=hi,
                            saving_low=s_lo, saving_high=s_hi))
    sob = sobol_erste_ordnung(draws, sims)
    tor = pd.DataFrame(tornado)
    tor["sobol_first_order"] = tor["parameter"].map(sob)
    # structural scenarios: which criterion defines "rail is an alternative"
    zeilen = []
    def zeile(name, gruppe, **kw):
        k = M.kennzahlen(REF, **kw)
        zeilen.append(dict(group=gruppe, criterion=name, **k,
                           saving_t=M.einsparung(REF, **kw),
                           saving_t_whole_flights=M.einsparung(REF, ganze_fluege=True, **kw),
                           saving_t_transfer_30=M.einsparung(dict(REF, transfer_share_hubs=0.3), **kw),
                           saving_t_transfer_70=M.einsparung(dict(REF, transfer_share_hubs=0.7), **kw)))
    for g in [150, 180, 240, 300]:
        p = dict(REF, threshold_min=g)
        k = M.kennzahlen(p)
        zeilen.append(dict(group="in-vehicle", criterion=f"In-vehicle rail time ≤ {g / 60:g} h" + (" (reference)" if g == 240 else ""),
                           **k, saving_t=M.einsparung(p), saving_t_whole_flights=M.einsparung(p, ganze_fluege=True),
                           saving_t_transfer_30=M.einsparung(dict(p, transfer_share_hubs=0.3)),
                           saving_t_transfer_70=M.einsparung(dict(p, transfer_share_hubs=0.7))))
    for m in [0, 60, 120]:
        zeile(f"Door-to-door: rail ≤ air + {m} min", "door-to-door", kriterium="door", marge=m)
    zeile("Door-to-door + 60 min, air access 120 min", "access", kriterium="door", marge=60, zug=dict(air_city=120))
    zeile("Door-to-door + 60 min, air access 180 min", "access", kriterium="door", marge=60, zug=dict(air_city=180))
    zeile("Door-to-door + 60 min, rail access 20 min", "access", kriterium="door", marge=60, zug=dict(rail_city=20))
    zeile("Door-to-door + 60 min, rail access 60 min", "access", kriterium="door", marge=60, zug=dict(rail_city=60))
    szen = pd.DataFrame(zeilen)
    acc = []
    for ms in [1.0, 0.75, 0.5, 0.25]:
        p = dict(REF, modal_shift_share=ms)
        w = M.gewicht(p) * ms
        acc.append(dict(share_shifting=ms, average_accounting_t=M.einsparung(p),
                        whole_flights_cancelled_t=M.einsparung(p, ganze_fluege=True),
                        no_capacity_response_t=float(-(w * M.seats * p["load_factor"] * M.bahn_co2_pax(p)).sum() / 1000)))
    accounting = pd.DataFrame(acc)
    # share of the reference saving that rests on substitute/default aircraft models
    w = M.gewicht(REF); beitrag = w * (M.luft_co2(REF) - M.seats * REF["load_factor"] * M.bahn_co2_pax(REF))
    proxy_share = float(beitrag[M.proxy].sum() / beitrag.sum()) if beitrag.sum() else np.nan
    k = M.kennzahlen(REF)
    return dict(sims=sims, basis=basis, tornado=tor, ranges=RANGES, reference=REF, scenarios=szen, accounting=accounting,
                n_scheduled_all=int(len(M.alle)), n_dest_rail=int(M.l["ziel"].nunique()),
                share_flights_rail_dest=float(len(M.l) / max(len(M.alle), 1)),
                proxy_share_of_saving=proxy_share,
                n_proxy_shifted=int(((w > 0) & M.proxy).sum()),
                whole_flight_saving=M.einsparung(REF, ganze_fluege=True), **k)


def modellierungsweg(r):
    if r["openap_modell"] == "stundenverbrauch":
        return "hourly consumption"
    if not isinstance(r["typecode"], str) or not r["typecode"].strip():
        return "no type: default model"
    if not r["typ_ersatz"]:
        return "own OpenAP model"
    return "substitute model"


def datenbasis(df, roh_ordner):
    """Funnel, class of flights without destination, modelling route x class, seats per type."""
    S, T = {}, {}
    b = (roh_ordner / "bericht.txt").read_text(encoding="utf-8") if (roh_ordner / "bericht.txt").exists() else ""
    import re
    m = re.search(r"Datentrichter: (\d+) - (\d+) ohne Ziel - (\d+) Rückkehr.*? - (\d+) Zielflughafen.*?= (\d+)", b)
    if m:
        S["funnel"] = dict(zip(["raw", "no_destination", "return_to_origin", "airport_not_in_db", "with_destination"],
                               map(int, m.groups())))
    alle = pd.read_csv(roh_ordner / "fluege_alle_klassen.csv") if (roh_ordner / "fluege_alle_klassen.csv").exists() else None
    if alle is not None:
        S["classes_with_destination"] = alle["klasse"].value_counts().to_dict()
    # flights without an estimated destination: class by call sign (destination unknown -> distance not tested)
    # Rohdaten sind nicht im Archiv (OpenSky-Nutzungsbedingungen); ohne sie entfällt nur diese Auszählung
    roh = pd.read_csv(roh_ordner / "fluege_roh.csv") if (roh_ordner / "fluege_roh.csv").exists() else pd.DataFrame()
    ohne = roh[roh["estArrivalAirport"].isna()].copy() if "estArrivalAirport" in roh else roh.iloc[0:0]
    if len(ohne):
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("p", Path(__file__).parent / "flug_vs_bahn_stuttgart.py")
            p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
            liste = p.betreiber_laden(p.HIER / "betreiber.csv")
            def kl(cs):
                cs = str(cs).strip().upper() if isinstance(cs, str) else ""
                if cs[:3] in liste and cs[:3].isalpha():
                    return liste[cs[:3]]
                return "Privat/Geschäft" if p.ist_privatflug(None, cs) else "Linie/Charter"
            S["classes_without_destination"] = ohne["callsign"].map(kl).value_counts().to_dict()
        except Exception as e:
            S["classes_without_destination"] = dict(error=str(e))
    d = df.copy()
    d["route"] = d.apply(modellierungsweg, axis=1)
    d["class"] = np.where(d["privat"], "private/business", "scheduled/charter")
    ct = pd.crosstab(d["class"], d["route"], margins=True, margins_name="all")
    sh = d[(~d["privat"]) & (d["anteil_verlagerbar"] > 0)]
    ct.loc["of which shifted (H1)"] = pd.crosstab(sh["class"], sh["route"]).sum().reindex(ct.columns, fill_value=0)
    ct.loc["of which shifted (H1)", "all"] = len(sh)
    T["T_modelling_route"] = ct.reset_index()
    S["share_proxy_type"] = float(df["typ_ersatz"].mean())
    S["n_type_implausible"] = int(alle["typ_unplausibel"].astype(str).str.lower().eq("true").sum()) if alle is not None and "typ_unplausibel" in alle else 0
    sitz = (d.groupby(["typecode", "openap_modell"], dropna=False)
            .agg(flights=("icao24", "size"), seats=("sitze", "first"), route=("route", "first")).reset_index()
            .sort_values("flights", ascending=False))
    sitz["typecode"] = sitz["typecode"].fillna("(none)")
    sitz["seat_source"] = np.where(sitz["route"] == "hourly consumption", "ersatz_verbrauch.csv (author)",
                                   "OpenAP aircraft property 'pax' (high-density)")
    T["T_seats_by_type"] = sitz
    return S, T


def analysen(df, z):
    from scipy import stats
    import statsmodels.formula.api as smf

    S, tabellen = {}, {}
    linie = df[~df["privat"]].copy()
    priv = df[df["privat"]].copy()

    S["n_flights"] = int(len(df)); S["n_scheduled"] = int(len(linie)); S["n_private"] = int(len(priv))
    S["share_observed_duration"] = float((df["dauer_quelle"] == "beobachtete ADS-B-Flugdauer").mean())
    zs = ziele_auswahl(z)
    zs["zielname"] = zs["zielname"].map(en)
    zs["linienfluege"] = zs.get("linienfluege", zs["fluege"] - zs["davon_privat"])
    zs["shifted"] = np.where((zs["anteil_verlagerbar"].fillna(0) > 0) & (zs["linienfluege"] > 0), "yes", "no")
    zs.loc[zs["linienfluege"] == 0, ["flugdauer_median_min", "flug_tuer_min", "flug_tuer_umst_min"]] = np.nan
    zs["rail_pending"] = zs["bahn_min"].isna()
    S["n_destinations_rule"] = int(len(zs)); S["n_destinations_rail"] = int(zs["bahn_min"].notna().sum())
    S["destinations_rail_pending"] = sorted(zs.loc[zs["rail_pending"], "zielname"].tolist())
    tabellen["T3_destinations"] = zs.loc[:, [
        "zielname", "ziel", "luftlinie_km", "linienfluege", "davon_privat", "flugdauer_median_min", "co2_pro_pax_kg",
        "bahn_min", "bahn_co2_pro_pax_kg", "flug_tuer_min", "bahn_tuer_min", "flug_tuer_umst_min",
        "bahn_tuer_umst_min", "drehkreuz", "shifted"]].sort_values("luftlinie_km").round(1)

    # ----- Q2 (empirical, exploratory): rail time vs scheduled departures, destinations with a rail time
    zz = zs.dropna(subset=["bahn_min"]).copy()
    rho, _ = stats.spearmanr(zz["bahn_min"], zz["linienfluege"])
    ci = boot_ci_paired(lambda a, b: stats.spearmanr(a, b)[0], zz["bahn_min"].values, zz["linienfluege"].values)
    r_km, _ = stats.spearmanr(zz["bahn_min"], zz["luftlinie_km"])
    oh = zz[zz["drehkreuz"] != "ja"]
    rho_oh = stats.spearmanr(oh["bahn_min"], oh["linienfluege"])[0] if len(oh) > 4 else np.nan
    S["Q2"] = dict(label="empirical (exploratory)", n=len(zz), rho=float(rho), ci=ci, rho_rail_distance=float(r_km),
                   n_without_hubs=len(oh), rho_without_hubs=float(rho_oh),
                   no_flights=sorted(zz.loc[zz["linienfluege"] == 0, "zielname"].tolist()),
                   rail_rank=zz.sort_values("bahn_min")[["zielname", "bahn_min", "linienfluege"]].values.tolist())
    S["_h2_data"] = zz

    # ----- Q3 (model-based): distance vs CO2/pkm; describes the model, no inference
    linie["log_g"] = np.log(linie["co2_g_pkm"]); linie["log_km"] = np.log(linie["luftlinie_km"])
    try:
        mm = smf.mixedlm("log_g ~ log_km", linie, groups=linie["openap_modell"]).fit(reml=True)
        b, se = mm.params["log_km"], mm.bse["log_km"]
        S["Q3_mixed"] = dict(label="model-based", n=len(linie), groups=int(linie["openap_modell"].nunique()),
                             elasticity=float(b), ci=(float(b - 1.96 * se), float(b + 1.96 * se)))
        S["_h3_fit"] = (float(mm.params["Intercept"]), float(b),
                        mm.cov_params().loc[["Intercept", "log_km"], ["Intercept", "log_km"]].values)
    except Exception as e:
        S["Q3_mixed"] = dict(error=str(e))
    kurz = linie[linie["luftlinie_km"] < 500]
    lang = linie[linie["luftlinie_km"] >= 500]
    S["Q3_short_long"] = dict(n_short=len(kurz), n_long=len(lang),
                              n_short_in_rail_table=int(kurz["bahn_min"].notna().sum()),
                              short_destinations=kurz["zielname"].map(en).value_counts().to_dict(),
                              median_short=float(kurz["co2_g_pkm"].median()), median_long=float(lang["co2_g_pkm"].median()),
                              cliffs_delta=float(cliffs_delta(kurz["co2_g_pkm"].values, lang["co2_g_pkm"].values)))

    # ----- Q4 (model-based, assumption-dependent): private vs scheduled
    if len(priv) >= 5:
        x, y = priv["co2_g_pkm"].values, linie["co2_g_pkm"].values
        lf_p = 0.40
        ratio = lambda lf: float(np.median(x * lf_p / lf) / np.median(y))
        jets = priv[priv["openap_modell"] != "stundenverbrauch"]
        S["Q4"] = dict(label="model-based (load factor assumed)", n_private=len(x), n_scheduled=len(y),
                       median_private=float(np.median(x)), median_scheduled=float(np.median(y)),
                       ratio=ratio(lf_p), ratio_equal_lf=ratio(0.80), ratio_lf_030=ratio(0.30), ratio_lf_060=ratio(0.60),
                       cliffs_delta=float(cliffs_delta(x, y)), share_flights=float(len(x) / len(df)),
                       share_co2=float(priv["co2_kg"].sum() / df["co2_kg"].sum()),
                       n_jets=len(jets), n_light=int(len(priv) - len(jets)))

    # ----- Q5 (scenario): door-to-door, scheduled flights only, access times varied
    d5 = zs.dropna(subset=["bahn_tuer_min", "flug_tuer_min"])
    d5 = d5[d5["linienfluege"] > 0]
    rows = []
    dur = d5["flug_tuer_min"] - ZUGANG["air_city"]
    for aa in [120, 150, 180]:
        for ra in [20, 40, 60]:
            diff = (d5["bahn_min"] + ra) - (dur + aa)
            rows.append(dict(air_access=aa, rail_access=ra, n=len(d5), median_diff_min=float(diff.median()),
                             n_rail_faster=int((diff <= 0).sum()),
                             rail_faster=", ".join(d5.loc[diff <= 0, "zielname"])))
    hubs = d5[(d5["drehkreuz"] == "ja") & d5["bahn_tuer_umst_min"].notna()]
    dh = hubs["bahn_tuer_umst_min"] - hubs["flug_tuer_umst_min"]
    T5 = pd.DataFrame(rows)
    ref = T5[(T5.air_access == 150) & (T5.rail_access == 40)].iloc[0]
    S["Q5"] = dict(label="scenario", n=len(d5), destinations=d5["zielname"].tolist(),
                   median_diff_min=float(ref["median_diff_min"]), n_rail_faster=int(ref["n_rail_faster"]),
                   rail_faster=ref["rail_faster"],
                   range_n_rail_faster=(int(T5["n_rail_faster"].min()), int(T5["n_rail_faster"].max())),
                   range_median_diff=(float(T5["median_diff_min"].min()), float(T5["median_diff_min"].max())),
                   connecting_median_diff_min=float(dh.median()) if len(dh) else np.nan,
                   connecting_n_rail_faster=int((dh <= 0).sum()), n_hubs=len(hubs),
                   breakeven_rail_min=float((d5["flug_tuer_min"] - ZUGANG["rail_city"]).median()))
    tabellen["T5_door_to_door_access"] = T5
    # air/rail CO2 ratio per destination and its range over the rail factor (5-45 g)
    r = zs.dropna(subset=["bahn_min", "co2_pro_pax_kg"])
    r = r[r["linienfluege"] > 0]
    base = r["co2_pro_pax_kg"] / r["bahn_co2_pro_pax_kg"]
    S["ratio_air_rail"] = dict(min=float(base.min()), max=float(base.max()),
                               min_at_45g=float((base * 29 / 45).min()), max_at_5g=float((base * 29 / 5).max()),
                               at_45g={n: round(float(v * 29 / 45), 1) for n, v in zip(r["zielname"], base)})
    return S, tabellen



# --------------------------------------------------------------------------- figures
def fig1_framework(ordner, demo, anonym=False):
    """Didactic design: six teaching steps mapped onto the TA phases of VDI 3780, the problem-solving
    steps of the competence model and the use of the learning tool."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    fig, ax = plt.subplots(figsize=(W2, 150 * MM))
    ax.set_xlim(0, 101); ax.set_ylim(0, 91); ax.axis("off"); ax.grid(False)
    x0, w, gap = 15.2, 13.3, 1.0
    X = lambda i: x0 + i * (w + gap)
    FB, FH, FL = 5.6, 7.0, 6.4
    stufen = [("1 Question", "Sort claims:\nempirical,\nmodel-based,\nnormative;\nguiding\nquestion"),
              ("2 Data", "Inspect\nOpenSky data:\ngaps, classes,\nproxy\naircraft"),
              ("3 Model", "CO₂ of one\nflight by\nhand; compare\nwith the tool"),
              ("4 Compare", "Door-to-door\ntime and CO₂;\ncity trip vs.\nconnecting"),
              ("5 Test", "Classify\nQ1–Q5; vary\nassumptions;\nclaim as a\nrange"),
              ("6 Judge", "Weight\nVDI 3780\ncriteria;\nroles; policy\nbrief")]

    def label(y, txt):
        ax.text(0.5, y, txt, ha="left", va="center", fontsize=FL, weight="bold", color=PAL["ink"], linespacing=1.15)
    yb, hb = 43, 23
    label(yb + hb / 2, "Activity\nsequence")
    for i, (kopf, text) in enumerate(stufen):
        farbe = PAL["hub"] if i < 5 else PAL["rail"]
        ax.add_patch(FancyBboxPatch((X(i), yb), w, hb, boxstyle="round,pad=0.2,rounding_size=1.0",
                                    fc=farbe, ec="none", alpha=0.12))
        ax.text(X(i) + w / 2, yb + hb - 3.4, kopf, ha="center", va="center", weight="bold", color=PAL["rail"], fontsize=FH)
        ax.text(X(i) + w / 2, yb + 8.6, text, ha="center", va="center", fontsize=FB, color=PAL["ink"], linespacing=1.2)
        if i < 5:
            ax.add_patch(FancyArrowPatch((X(i) + w + 0.15, yb + hb / 2), (X(i + 1) - 0.15, yb + hb / 2),
                                         arrowstyle="-|>", mutation_scale=4.5, color=PAL["neutral"], lw=0.6))

    def band(y, spans, h=6.6):
        for (i0, i1, txt, farbe, alpha) in spans:
            a_, b_ = X(i0), X(i1) + w
            ax.add_patch(FancyBboxPatch((a_, y - h / 2), b_ - a_, h, boxstyle="round,pad=0.1,rounding_size=0.8",
                                        fc=farbe, ec="none", alpha=alpha))
            ax.text((a_ + b_) / 2, y, txt, ha="center", va="center", fontsize=FB, color=PAL["ink"], linespacing=1.15)
    label(71, "Setting")
    band(71, [(0, 3, "Reading at home (step 1), then session 1 (90 min)", PAL["ink"], 0.08),
              (4, 5, "Session 2 (90 min),\nthen policy brief at home", PAL["ink"], 0.08)])
    # reflection loop: from judgement back to the assumptions (steps 3-5)
    ax.annotate("", xy=(X(3) + w / 2, 76.0), xytext=(X(5) + w / 2, 76.0),
                arrowprops=dict(arrowstyle="-|>", color=PAL["neutral"], lw=0.7, connectionstyle="arc3,rad=0.28"))
    ax.annotate("", xy=(X(2) + w / 2, 76.0), xytext=(X(5) + w / 2, 76.0),
                arrowprops=dict(arrowstyle="-|>", color=PAL["neutral"], lw=0.7, connectionstyle="arc3,rad=0.22"))
    ax.text(X(3) + w, 88.4, "Reflection loop: after judging, learners revisit the assumptions of steps 3–5",
            ha="center", fontsize=7.3, color=PAL["neutral"], style="italic")
    label(36, "TA phase\n(VDI 3780)")
    band(36, [(0, 1, "Problem definition\n& information", PAL["hub"], 0.22),
              (2, 4, "Impact analysis: estimate consequences,\nquantify uncertainty", PAL["hub"], 0.22),
              (5, 5, "Evaluation\n& decision", PAL["rail"], 0.25)])
    label(27, "Problem-\nsolving step")
    band(27, [(0, 0, "Recognise\nthe technical\nproblem", PAL["neutral"], 0.16),
              (1, 4, "Generate information", PAL["neutral"], 0.16),
              (5, 5, "Make\ndecisions", PAL["neutral"], 0.16)], h=7.4)
    band(19.5, [(0, 4, "Know and understand sustainable development: built up across steps 1–5 …",
                 PAL["rail"], 0.10),
                (5, 5, "… consolidated\nin reflection", PAL["rail"], 0.22)], h=6.4)
    label(11.5, "Learning tool")
    band(11.5, [(0, 1, "Claim sorting,\ndata funnel", PAL["air"], 0.10),
                (2, 4, "Hand calculator, comparison, assumption sliders,\nscenario protocol", PAL["air"], 0.16),
                (5, 5, "Roles,\nweights, brief", PAL["air"], 0.10)])
    quelle = "Author, 2026" if anonym else "Stemmann et al., 2026"
    ax.text(50.5, 3.0,
            "Competence area: assessing the consequences of technology · problem and action field: transport and traffic", ha="center", va="center", fontsize=7.3, color=PAL["neutral"], style="italic",
            linespacing=1.2)
    speichern(fig, ordner, "Fig1_framework" + ("_anonymised" if anonym else ""), demo=False)
    plt.close(fig)


def fig_conjecture(ordner, demo):
    """Conjecture map of the design (after Sandoval, 2014)."""
    import textwrap
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    rows = [("Fixed data, open assumptions; each labelled as model, scenario or framing",
             "Learners vary assumptions, record scenarios and notice which dominate",
             "Claims stated as ranges with their main assumption (B)"),
            ("Hand calculation of CO\u2082 for one flight, compared with the model value (step 3)",
             "Learners explain the gap: climb, taxi, aircraft type",
             "Learners name the parts and limits of an emission model (A)"),
            ("Claim sorting (step 1); classification of Q1\u2013Q5 (step 5)",
             "Learners distinguish observation, model output and framing",
             "Briefs separate evidence from judgement and justify framings (C)"),
            ("Roles, VDI 3780 weighting and reflection loop (step 6)",
             "Learners argue from criteria and revisit assumptions after judging",
             "A reasoned decision with stated values and trade-offs (D)"),
            ("Meta-level reflection at the end of each session",
             "Learners plan how a step could be taught at school",
             "Planned adaptations for pupils (E)")]
    fig, ax = plt.subplots(figsize=(W2, 118 * MM))
    n = len(rows); top = 92; rh = 16.6; gap = 2.0
    ax.set_xlim(-1.5, 101.5); ax.set_ylim(0, 100); ax.axis("off"); ax.grid(False)
    cols = [(0, 21.5), (26, 48), (52.5, 74.5), (79, 100)]
    heads = ["High-level\nconjecture", "Design features\n(embodiment)", "Mediating\nprocesses", "Intended outcomes\n(rubric criterion)"]
    farben = [PAL["rail"], PAL["hub"], PAL["neutral"], PAL["air"]]
    FS = 6.2
    for (x0, x1), h, c in zip(cols, heads, farben):
        ax.text((x0 + x1) / 2, top + 4.2, h, ha="center", va="center", fontsize=7, weight="bold", color=c, linespacing=1.1)
    def box(x0, x1, y0, y1, txt, c, alpha, width):
        ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0.25,rounding_size=1.0",
                                    fc=c, ec="none", alpha=alpha))
        ax.text((x0 + x1) / 2, (y0 + y1) / 2, textwrap.fill(txt, width), ha="center", va="center", fontsize=FS,
                color=PAL["ink"], linespacing=1.2)
    y_bottom = top - n * rh
    box(cols[0][0], cols[0][1], y_bottom + gap / 2, top - gap / 2,
        "Pre-service teachers learn to judge a technology under uncertainty when they estimate a consequence "
        "themselves and see that assumptions, not data, move the result", PAL["rail"], 0.16, 16)
    for i, r in enumerate(rows):
        y1 = top - i * rh - gap / 2; y0 = y1 - rh + gap; yc = (y0 + y1) / 2
        for k in range(3):
            x0, x1 = cols[k + 1]
            box(x0, x1, y0, y1, r[k], farben[k + 1], 0.14, 20)
        for xa, xb in [(cols[0][1], cols[1][0]), (cols[1][1], cols[2][0]), (cols[2][1], cols[3][0])]:
            ax.add_patch(FancyArrowPatch((xa + 0.6, yc), (xb - 0.6, yc), arrowstyle="-|>", mutation_scale=6,
                                         color=PAL["neutral"], lw=0.7))
    ax.text(50, y_bottom - 4, "After Sandoval (2014). Letters refer to the criteria of the policy-brief rubric.",
            ha="center", fontsize=7.3, color=PAL["neutral"], style="italic")
    speichern(fig, ordner, "Fig2_conjecture_map", demo=False); plt.close(fig)


def fig2_door(zs, ordner, demo):
    """Door-to-door time (scheduled flights only) and scheduled departures (raw counts) per destination."""
    import matplotlib.pyplot as plt
    d = zs.dropna(subset=["bahn_tuer_min"]).sort_values("luftlinie_km", ascending=False).copy()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(W2, (max(len(d), 6) * 6.0 + 30) * MM),
                                 gridspec_kw=dict(width_ratios=[2.2, 1], wspace=0.08), sharey=True)
    y = np.arange(len(d))
    hub = (d["drehkreuz"] == "ja").values
    has_t = hub & d["bahn_tuer_umst_min"].notna().values
    yc = np.where(has_t, y + 0.18, y); yt = y - 0.18
    fl = d["flug_tuer_min"].values; flu = d["flug_tuer_umst_min"].values
    for i in range(len(d)):
        if np.isfinite(fl[i]):
            a1.plot([fl[i] / 60, d["bahn_tuer_min"].iloc[i] / 60], [yc[i]] * 2, color=PAL["grid"], lw=2.2, zorder=1)
        if has_t[i] and np.isfinite(flu[i]):
            a1.plot([flu[i] / 60, d["bahn_tuer_umst_min"].iloc[i] / 60], [yt[i]] * 2, color=PAL["grid"],
                    lw=1.4, ls=(0, (2, 1.5)), zorder=1)
    a1.scatter(fl / 60, yc, color=PAL["air"], s=16, zorder=3, label="Air (scheduled flights), city trip")
    a1.scatter(d["bahn_tuer_min"] / 60, yc, color=PAL["rail"], s=16, zorder=3, marker="s",
               label="Rail, main station to main station")
    if has_t.any():
        t = d[has_t]
        a1.scatter(t["flug_tuer_umst_min"] / 60, yt[has_t], facecolor="none", edgecolor=PAL["air"], lw=0.9, s=16,
                   zorder=3, label="Air, connecting at hub")
        a1.scatter(t["bahn_tuer_umst_min"] / 60, yt[has_t], facecolor="none", edgecolor=PAL["rail"], lw=0.9, s=16,
                   marker="s", zorder=3, label="Rail to hub airport station")
    lab = [f"{n}{' (hub)' if h_ else ''}  {k:.0f} km" for n, k, h_ in zip(d["zielname"], d["luftlinie_km"], hub)]
    a1.set_yticks(y, lab)
    a1.set_xlabel("Door-to-door travel time (h)")
    a1.set_title("a  Door-to-door time from Stuttgart")
    h, l = a1.get_legend_handles_labels()
    fig.legend(h, l, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=2, fontsize=7.3)
    n = d["linienfluege"].values
    a2.barh(y[hub], n[hub], color=PAL["hub"], height=0.62, hatch="////", edgecolor="white", lw=0, label="Hub airport")
    a2.barh(y[~hub], n[~hub], color=PAL["neutral"], height=0.62, label="Point-to-point")
    for yi, ni in zip(y, n):
        a2.text(ni + 0.6, yi, f"{ni:.0f}", va="center", fontsize=7.3, color=PAL["ink"])
    a2.set_xlabel("Scheduled departures in the study week")
    a2.set_title("b  Frequency (counts)")
    a2.set_xlim(0, max(n.max(), 1) * 1.18)
    a2.legend(frameon=False, loc="center right", bbox_to_anchor=(1.0, 0.47), fontsize=7.3)
    a2.tick_params(axis="y", length=0)
    speichern(fig, ordner, "Fig5_door_to_door", demo); plt.close(fig)


def fig3_co2(df, zs, ordner, demo):
    import matplotlib.pyplot as plt
    linie = df[~df["privat"]].copy(); linie["zielname"] = linie["zielname"].map(en)
    g = linie.groupby("zielname")["co2_pro_pax_kg"].agg(
        q1=lambda s: s.quantile(.25), q3=lambda s: s.quantile(.75), n="size")
    zz = zs.set_index("zielname")[["co2_pro_pax_kg", "bahn_co2_pro_pax_kg", "luftlinie_km", "bahn_min"]]
    g = g.join(zz, how="inner").rename(columns={"co2_pro_pax_kg": "pooled"})
    g = g[g["bahn_min"].notna()].dropna(subset=["pooled"]).sort_values("luftlinie_km")
    fig, ax = plt.subplots(figsize=(W2, 84 * MM))
    x = np.arange(len(g))
    lo = g["bahn_co2_pro_pax_kg"] * 5 / 29; hi = g["bahn_co2_pro_pax_kg"] * 45 / 29
    ax.vlines(x, lo, hi, color=PAL["rail"], lw=5, alpha=0.18, label="Rail range 5–45 g/pkm")
    ax.vlines(x, g["q1"], g["q3"], color=PAL["air"], lw=2.4, alpha=0.35)
    ax.scatter(x, g["pooled"], color=PAL["air"], s=18, zorder=3, label="Air: pooled value and IQR across flights")
    ax.scatter(x, g["bahn_co2_pro_pax_kg"], color=PAL["rail"], marker="s", s=16, zorder=3, label="Rail, 29 g/pkm")
    for xi, (_, r) in zip(x, g.iterrows()):
        ax.text(xi, max(r["q3"], r["pooled"]) * 1.08, f"×{r['pooled'] / r['bahn_co2_pro_pax_kg']:.1f}",
                ha="center", fontsize=7.3, color=PAL["ink"])
    ax.set_yscale("log")
    plain_log_ticks(ax.yaxis, [1, 2, 5, 10, 20, 50, 100, 200, 500])
    ax.set_ylim(lo.min() * 0.7, max(g["q3"].max(), g["pooled"].max()) * 1.6)
    ax.set_xticks(x, [f"{n} ({k:.0f} km, n = {c})" for n, k, c in zip(g.index, g["luftlinie_km"], g["n"])],
                  fontsize=7.3, rotation=35, ha="right", rotation_mode="anchor")
    ax.set_ylabel("kg CO₂ per passenger, one way (log scale)")
    ax.set_title("CO₂ per passenger, air vs. rail", pad=16)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0.0, 0.99), ncol=3, borderaxespad=0)
    speichern(fig, ordner, "Fig6_co2_per_passenger", demo); plt.close(fig)


def fig4_efficiency(df, S, ordner, demo):
    import matplotlib.pyplot as plt
    linie, priv = df[~df["privat"]], df[df["privat"]]
    fig, ax = plt.subplots(figsize=(W2 * 0.68, 100 * MM))
    jit = np.exp(RNG.normal(0, 0.012, len(linie)))
    ax.scatter(linie["luftlinie_km"] * jit, linie["co2_g_pkm"], s=7, color=PAL["hub"], alpha=0.45, lw=0,
               label="Scheduled/charter flight")
    if len(priv):
        ax.scatter(priv["luftlinie_km"], priv["co2_g_pkm"], s=15, color=PAL["private"], marker="D", alpha=0.85,
                   edgecolor="white", lw=0.4, label="Private/business (jets and light aircraft)")
    if "_h3_fit" in S:
        a, b, V = S["_h3_fit"]
        xs = np.linspace(np.log(linie["luftlinie_km"].min()), np.log(linie["luftlinie_km"].max()), 100)
        X = np.column_stack([np.ones_like(xs), xs])
        yhat = X @ np.array([a, b]); se = np.sqrt(np.einsum("ij,jk,ik->i", X, V, X))
        ax.fill_between(np.exp(xs), np.exp(yhat - 1.96 * se), np.exp(yhat + 1.96 * se), color=PAL["ink"], alpha=0.12, lw=0)
        ax.plot(np.exp(xs), np.exp(yhat), color=PAL["ink"], lw=1,
                label=f"Mixed model, scheduled only (slope {b:.2f})".replace("-", "−"))
    rail_gc = S.get("_rail_g", 29) * 1.25
    ax.axhline(rail_gc, color=PAL["rail"], ls="--", lw=0.9, label=f"Rail, {rail_gc:.0f} g per great-circle km")
    ax.set_xscale("log"); ax.set_yscale("log")
    xmax = df["luftlinie_km"].max()
    ticks = [t for t in [100, 200, 300, 500, 1000, 2000, 3000, 5000, 8000] if t <= xmax * 1.1]
    plain_log_ticks(ax.xaxis, ticks)
    plain_log_ticks(ax.yaxis, [20, 50, 100, 200, 500, 1000, 2000, 5000])
    ax.set_xlim(df["luftlinie_km"].min() * 0.85, xmax * 1.15)
    ax.set_xlabel("Great-circle distance (km, log scale)"); ax.set_ylabel("g CO₂ per passenger-km (log scale)")
    ax.set_title("Emission intensity by distance (Q3, Q4)")
    ax.set_ylim(rail_gc * 0.8, None)
    leg = ax.legend(frameon=False, fontsize=7.3, loc="upper center", bbox_to_anchor=(0.45, -0.17), ncol=2,
                    columnspacing=1.5, handlelength=2.2)
    for h in leg.legend_handles:
        h.set_alpha(1)
    speichern(fig, ordner, "Fig4_efficiency_distance", demo); plt.close(fig)


ART = dict(threshold_min="framing", modal_shift_share="scenario")
ARTFARBE = dict(model=PAL["hub"], scenario=PAL["private"], framing=PAL["air"])


def fig5_sensitivity(mc, ordner, demo):
    import matplotlib.pyplot as plt
    if mc is None:
        return
    t = mc["tornado"].copy()
    t["span"] = (t["saving_high"] - t["saving_low"]).abs()
    t = t.sort_values("span")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(W2, 82 * MM), gridspec_kw=dict(width_ratios=[1.45, 1], wspace=0.55))
    y = np.arange(len(t))
    for i, (_, r) in enumerate(t.iterrows()):
        lo, hi = sorted([r["saving_low"], r["saving_high"]])
        art = ART.get(r["parameter"], "model")
        a1.barh(i, max(hi - lo, 0.8), left=lo if hi - lo >= 0.8 else lo - 0.4, color=ARTFARBE[art], alpha=0.85,
                height=0.55, hatch="////" if art == "framing" else None, edgecolor="white", lw=0)
        a1.text(max(hi, mc["basis"]) + 4, i, f"S₁ {r['sobol_first_order']:.2f}", va="center", fontsize=7.3,
                color=PAL["neutral"])
    a1.axvline(mc["basis"], color=PAL["ink"], lw=0.8)
    a1.text(mc["basis"] + 4, -0.9, f"reference {mc['basis']:.0f} t", ha="left", va="center", fontsize=7.3)
    a1.set_ylim(-1.4, len(t) - 0.5)
    a1.set_yticks(y, list(t["label"]))
    a1.set_xlim(0, max(t[["saving_low", "saving_high"]].max().max(), mc["basis"]) * 1.25)
    a1.set_xlabel("Saving (t CO₂ per week)"); a1.set_title("a  One at a time, around the reference", pad=10)
    from matplotlib.patches import Patch
    a1.legend(handles=[Patch(fc=ARTFARBE["model"], label="Model assumption"),
                       Patch(fc=ARTFARBE["scenario"], label="Behavioural scenario"),
                       Patch(fc=ARTFARBE["framing"], hatch="////", ec="white", label="Value-laden framing")],
              frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.35, -0.2), ncol=3,
              handlelength=1.6, columnspacing=1.2)
    s = mc["sims"]; lo, md, hi = np.quantile(s, [.025, .5, .975])
    a2.hist(s, bins=50, color=PAL["rail"], alpha=0.8)
    for v, ls in [(lo, ":"), (md, "-"), (hi, ":")]:
        a2.axvline(v, color=PAL["ink"], ls=ls, lw=0.8)
    a2.axvline(mc["basis"], color=PAL["air"], lw=1.0)
    a2.set_xlim(0, None)
    a2.set_xlabel("Saving (t CO₂ per week)\norange: reference · black: median and 95 % range")
    a2.set_ylabel("Simulated scenarios")
    a2.set_title(f"b  10,000 simulated scenarios\n    median {md:.0f} t, 95 % range {lo:.0f}–{hi:.0f} t", pad=10)
    speichern(fig, ordner, "Fig7_sensitivity", demo); plt.close(fig)


def fig6_h2(S, ordner, demo):
    import matplotlib.pyplot as plt
    zz = S["_h2_data"].copy().sort_values("bahn_min")
    fig, ax = plt.subplots(figsize=(W2, 92 * MM))
    hub = (zz["drehkreuz"] == "ja").values
    y = zz["linienfluege"].values.astype(float)
    x = zz["bahn_min"].values / 60
    ax.set_yscale("function", functions=(lambda v: np.sqrt(np.clip(v, 0, None)), lambda v: v ** 2))
    ax.scatter(x[~hub], y[~hub], color=PAL["neutral"], s=26, label="Point-to-point", zorder=3, clip_on=False)
    ax.scatter(x[hub], y[hub], color=PAL["hub"], s=26, marker="s", label="Hub airport", zorder=3, clip_on=False)
    # labels: destinations without scheduled flights are labelled below the axis line, alternating depth
    nul_i = 0
    texte = []
    for xi, yi, n in zip(x, y, zz["zielname"]):
        if yi == 0:
            ax.annotate(n, (xi, 0), xytext=(0, -9 - 9 * (nul_i % 3)), textcoords="offset points", ha="center",
                        va="top", fontsize=7.3, color=PAL["ink"],
                        arrowprops=dict(arrowstyle="-", color="#9AA0A6", lw=0.4, shrinkA=0, shrinkB=3))
            nul_i += 1
        else:
            texte.append(ax.text(xi, yi, " " + n, fontsize=7.3, color=PAL["ink"], va="center"))
    ax.axvline(4, color=PAL["rail"], ls="--", lw=0.8)
    ax.text(4.06, 0.97, "4 h in-vehicle", transform=ax.get_xaxis_transform(), fontsize=7.3, color=PAL["rail"], va="top")
    labels_ohne_ueberlappung(ax, texte)
    ax.set_yticks([0, 1, 2, 5, 10, 20, 30]); ax.set_yticklabels(["0", "1", "2", "5", "10", "20", "30"])
    ax.set_ylim(0, 40)
    ax.spines["bottom"].set_position(("outward", 44))
    ax.set_title("Rail time vs. flight frequency (Q2)")
    ax.set_xlabel("Fastest rail journey, in-vehicle, main station to main station (h)")
    ax.set_ylabel("Scheduled departures per week (square-root scale)")
    ax.legend(frameon=False, loc="upper right")
    speichern(fig, ordner, "Fig3_rail_time_frequency", demo); plt.close(fig)


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ergebnisse", default="ergebnisse")
    ap.add_argument("--ausgabe", default="paper")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--bahn-g-pkm", type=float, default=29.0)
    args = ap.parse_args()
    style()
    df, z, demo_run = lade(Path(args.ergebnisse))
    demo = args.demo or demo_run
    out = Path(args.ausgabe); (out / "figures").mkdir(parents=True, exist_ok=True); (out / "tables").mkdir(exist_ok=True)

    S, T = analysen(df, z)
    S["_rail_g"] = args.bahn_g_pkm
    S2, T2 = datenbasis(df, Path(args.ergebnisse)); S.update(S2); T.update(T2)
    mc = monte_carlo(df)
    if mc:
        q = np.quantile(mc["sims"], [.025, .5, .975])
        S["Q1"] = dict(label="scenario (technical upper bound)", n_flights=mc["n_flights"],
                       share_flights=mc["share_flights"], share_co2=mc["share_co2"],
                       share_passengers=mc["share_passengers"], n_scheduled_all=mc["n_scheduled_all"],
                       share_flights_rail_dest=mc["share_flights_rail_dest"],
                       saving_t_reference=mc["basis"], saving_t_whole_flights=mc["whole_flight_saving"],
                       mc_median=float(q[1]), mc_95_range=(float(q[0]), float(q[2])),
                       proxy_share_of_saving=mc["proxy_share_of_saving"], n_proxy_shifted=mc["n_proxy_shifted"],
                       reference=mc["reference"], ranges=mc["ranges"],
                       sobol=dict(zip(mc["tornado"]["parameter"], mc["tornado"]["sobol_first_order"].round(3))))
        T["T4_sensitivity_oat_sobol"] = mc["tornado"].round(3)
        T["T6_structural_scenarios"] = mc["scenarios"].round(3)
        T["T7_accounting"] = mc["accounting"].round(1)

    zs = ziele_auswahl(z); zs["zielname"] = zs["zielname"].map(en)
    zs["linienfluege"] = zs.get("linienfluege", zs["fluege"] - zs["davon_privat"])
    fig1_framework(out / "figures", demo); fig1_framework(out / "figures", demo, anonym=True); fig_conjecture(out / "figures", demo)
    fig2_door(zs, out / "figures", demo); fig3_co2(df, zs, out / "figures", demo)
    fig4_efficiency(df, S, out / "figures", demo); fig5_sensitivity(mc, out / "figures", demo); fig6_h2(S, out / "figures", demo)

    md = []
    for name, t in T.items():
        t.to_csv(out / "tables" / f"{name}.csv", index=False)
        md += [f"## {name}", "", t.to_markdown(index=False), ""]
    (out / "tables" / "tables.md").write_text("\n".join(md), encoding="utf-8")
    clean = {k: v for k, v in S.items() if not k.startswith("_")}
    clean["demo"] = demo
    (out / "stats.json").write_text(json.dumps(clean, indent=2, ensure_ascii=False,
                                               default=lambda o: float(o) if hasattr(o, "__float__") else str(o)),
                                    encoding="utf-8")
    print(json.dumps(clean, indent=1, ensure_ascii=False, default=str)[:6000])
    print(f"\nFigures, tables and stats.json written to {out.resolve()}")


if __name__ == "__main__":
    main()
