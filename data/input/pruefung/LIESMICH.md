# Betreiber und Verbrauch prüfen

> **Hinweis:** Diese Datei und die beiden Prüflisten dokumentieren den Arbeitsstand vor der manuellen Prüfung (Anfang November 2026). Die Prüfung ist abgeschlossen; ihre Ergebnisse sind in `betreiber.csv` und `ersatz_verbrauch.csv` eingearbeitet (z. B. PVG = Privilege Style, Linie/Charter). Die Zahlen in diesem Text beziehen sich auf den damaligen Zwischenstand und weichen von den Ergebnissen im Artikel ab.

Zwei Listen, beide öffnen sich in Numbers oder Excel. Die leeren Spalten am Ende sind zum Ausfüllen.

## 1. pruefliste_betreiber.csv (13 Präfixe, 23 Flüge)

Für jedes unsichere Rufzeichen-Präfix stehen dort die Flüge der Woche: Typ, Ziel, Rufzeichen, ICAO24-Adresse und ein Link.

So prüfst du ein Präfix:

1. Den Link in `link_flugzeug` öffnen (ADS-B Exchange). Oben links stehen Kennzeichen, Typ und meist der Halter bzw. Betreiber.
2. Das Präfix (die ersten drei Buchstaben des Rufzeichens) nachschlagen. Verbindlich ist ICAO Doc 8585 (Designators for Aircraft Operating Agencies). Für den Alltag reichen die Wikipedia-Liste „List of airline codes“ oder eine Suche nach „ICAO code PVG“.
3. In `klasse_richtig` eine der fünf Klassen eintragen: Linie/Charter, Privat/Geschäft, Fracht, Staat/Militär, Unter 100 km.
4. Danach in `betreiber.csv` den Namen und die Klasse eintragen und in `sicher` „ja“ setzen.

Wichtig ist vor allem **PVG**: zwei A321 nach Madrid und Valencia, bisher als Privat gezählt. Vermutlich ist das Privilege Style, eine spanische Charterairline. Wenn ja, gehören die Flüge zu Linie/Charter. Für H4 heißt das: der Median der Privatflüge steigt von 844 auf 876 g CO₂/pkm, und ihr CO₂-Anteil fällt von 4,5 % auf 3,9 %. Die Aussage von H4 bleibt gleich, die Zahlen im Artikel ändern sich aber.

Die übrigen Präfixe betreffen je ein bis fünf kleine Flüge. Ihr Einfluss auf die Ergebnisse ist gering.

## 2. pruefliste_verbrauch.csv (34 Typen, 38 Flüge, 0,6 % des CO₂)

Für Typen ohne OpenAP-Modell rechnet das Skript mit Stundenverbrauch × Flugdauer. In der Liste stehen je Typ die betroffenen Flüge, das CO₂ und eine Priorität.

So prüfst du einen Typ:

1. Die Spalte `prioritaet` „hoch“ zuerst prüfen: PC12, D328, BE20, B350, SBR1. Sie machen den größten Teil aus. Typen ohne Flug in der Woche kannst du auslassen.
2. Den Reiseverbrauch aus dem Herstellerdatenblatt oder dem Flughandbuch (POH) nehmen und in kg pro Stunde umrechnen:
   - Jet A-1: 1 Liter ≈ 0,80 kg; 1 US-Gallone ≈ 3,03 kg
   - AvGas (Kolbenmotoren): 1 Liter ≈ 0,72 kg; 1 US-Gallone ≈ 2,72 kg
   - Beispiel: 60 US-Gal/h Jet A-1 ≈ 182 kg/h
3. Sitze = typische Passagiersitze ohne Crew.
4. Den Wert und die Quelle in `kg_pro_h_geprueft` und `quelle` eintragen, danach in `ersatz_verbrauch.csv` übernehmen und dort „Näherung - bitte prüfen“ durch die Quelle ersetzen.

Eine Abweichung von ±20 % ist für das Ergebnis unkritisch, weil diese Flüge zusammen nur 0,6 % des CO₂ ausmachen. Im Artikel genügt dann der Satz, dass die Werte nach Herstellerangaben geprüft wurden.

## 3. Danach neu rechnen

```
cp ergebnisse/fluege_roh.csv fluege_roh_sicherung.csv     # vorher sichern
python flug_vs_bahn_stuttgart.py --quelle csv --flugdatei fluege_roh_sicherung.csv --flugzeugdb aircraft-database-complete-2025-08.csv
python paper_analysen.py --ergebnisse ergebnisse --ausgabe paper
python werkzeug_bauen.py --ergebnisse ergebnisse --stats paper/stats.json
```

Ohne `--quelle csv` würde das Skript nur Demodaten erzeugen. Die neu berechneten Werte stehen danach in `paper/stats.json` (`paper/` ist der Ausgabeordner, den das Skript anlegt).
