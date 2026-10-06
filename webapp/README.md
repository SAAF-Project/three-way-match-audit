# Three-way Match Webapp

FastAPI-webapp voor het uitvoeren van een 3-way match audit op inkooporder, goederenontvangst en factuur.

## Snel starten

```bash
cd webapp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Wat het doet

Vergelijkt drie documenten op:

- **Header** — PO-nummer consistentie, leveranciernaam
- **Regelniveau** — per SKU: aantallen (PO ↔ GRN ↔ factuur), stukprijzen (PO ↔ factuur), regeltotalen
- **Documenttotaal** — PO vs factuur binnen tolerantie

En geeft per regel én overall een oordeel: `MATCH` / `WARNING` / `FAIL`.

## Ondersteunde formaten

CSV en JSON. Kolomnamen worden flexibel herkend: `quantity`/`qty`, `unit_price`/`price`, `line_total`/`amount`, etc.

### Voorbeeldstructuur — JSON

```json
{
  "po_number": "PO-2025-0142",
  "supplier": "ACME Industrial BV",
  "date": "2025-08-14",
  "lines": [
    { "line_number": 1, "sku": "SKU-A100", "description": "Widget A", "quantity": 50, "unit_price": 24.50, "line_total": 1225.00 }
  ],
  "total": 1225.00
}
```

### Voorbeeldstructuur — CSV (twee blokken)

```csv
field,value
po_number,PO-2025-0142
supplier,ACME Industrial BV

line_number,sku,description,quantity,unit_price,line_total
1,SKU-A100,Widget A,50,24.50,1225.00
```

Voorbeeldbestanden staan in [`sample_data/`](sample_data/).

## API

Er is ook een JSON-endpoint voor programmatische matches:

```bash
curl -X POST http://127.0.0.1:8000/api/match \
  -F po_file=@sample_data/po_sample.csv \
  -F grn_file=@sample_data/grn_sample.csv \
  -F invoice_file=@sample_data/invoice_sample.csv
```

## Structuur

```
webapp/
  app/
    main.py                 # FastAPI routes
    services/
      parsers.py            # CSV/JSON → canonieke shape
      matcher.py            # Header + regel + totaal check
    templates/              # Jinja2 (index + result)
    static/style.css
  sample_data/              # Voorbeeld-PO, GRN, factuur (+ variant met afwijkingen)
  run.py                    # Launcher
```

## Tolerantie-instellingen

Op de startpagina zijn vier tolerantievelden instelbaar. Elke tolerantie is een aparte, onafhankelijke drempel — ze overrulen elkaar niet.

| Veld | Default | Betekenis | Check in de matcher |
| --- | --- | --- | --- |
| **Stukprijs (€)** | 0,01 | Toegestane afwijking op *unit price* tussen PO en factuur | per regel |
| **Aantal (eenheden)** | 0 | Toegestane afwijking op *quantity* tussen PO, GRN en factuur | per regel, in alle drie de paren |
| **Regeltotaal (€)** | 0,01 | Toegestane afwijking op *line amount* tussen PO en factuur | per regel (vangt afrondings- of herberekeningsverschillen op) |
| **Documenttotaal (€)** | 0,05 | Toegestane afwijking op *grand total* tussen PO en factuur | document-niveau |

### Snelkeuze-presets

Onder de velden zitten drie knoppen die alle vier de waardes in één klik zetten:

| Preset | Stukprijs | Aantal | Regeltotaal | Documenttotaal | Wanneer |
| --- | --- | --- | --- | --- | --- |
| **Strikt** | 0 | 0 | 0 | 0 | Alle afrondings- en herberekeningsverschillen tellen mee. Voor forensische/juridische reviews. |
| **Standaard** | 0,01 | 0 | 0,01 | 0,05 | De defaults. Standaard-cent-afrondingen worden toegestaan. |
| **Soepel** | 0,10 | 1 | 1,00 | 5,00 | Grove triage, voor eerste-pas sweeps door historische data. |

### Overridebaar per request

Alle vier zijn ook `Form`-parameters op `/match` en `/api/match`, dus je kunt ze per curl/script-call overridden:

```bash
curl -X POST http://127.0.0.1:8000/api/match \
  -F po_file=@sample_data/po_sample.csv \
  -F grn_file=@sample_data/grn_sample.csv \
  -F invoice_file=@sample_data/invoice_mismatch.csv \
  -F price_tolerance=0.05 \
  -F qty_tolerance=0 \
  -F line_total_tolerance=0.10 \
  -F total_tolerance=1.00
```
