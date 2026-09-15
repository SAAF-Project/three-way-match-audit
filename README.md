# Three-way Match Audit

Audit-tool voor het uitvoeren van een 3-way match tussen inkooporder, goederenontvangst en inkoopfactuur.

## Twee deploy-vormen

| Vorm | Waar | Best voor |
| --- | --- | --- |
| **[Live demo](https://saaf-project.github.io/three-way-match-audit/)** — client-side | GitHub Pages | Showcase op internet. Draait volledig in de browser, geen server, bestanden verlaten je machine niet. |
| **FastAPI webapp** — server-side | Lokaal of Render.com via `render.yaml` | "Echte" versie met JSON-API, uitbreidbaar met AI-parsing / PDF-export. |
| **PDF-generator** — CLI | Lokaal via `tools/scripts/generate_audit_report.py` | Genereert een audit-rapport (PDF) uit een `match_results.json`. |

## GitHub Pages activeren (client-side showcase)

1. Ga naar **Settings → Pages** in deze repo
2. Kies **Source: Deploy from a branch**
3. Selecteer branch **`master`** en folder **`/docs`**
4. Save — na ~1 min live op `https://saaf-project.github.io/three-way-match-audit/`

De statische versie in [`docs/`](docs/) is een JavaScript-port van [`webapp/app/services/`](webapp/app/services/) en heeft feature-pariteit voor CSV + JSON.

## FastAPI webapp lokaal draaien

```bash
cd webapp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py
# → http://127.0.0.1:8000
```

Zie [`webapp/README.md`](webapp/README.md) voor de API en dataschema's.

## FastAPI webapp deployen op Render.com

1. Maak account op [render.com](https://render.com)
2. Klik **New → Blueprint** en verbind deze repo
3. Render detecteert `render.yaml` automatisch en zet de webapp live op een `.onrender.com` URL
4. Free tier gaat in slaap na 15 min inactiviteit — eerste request duurt dan ~30s

## PDF audit-rapport genereren

```bash
cd tools/scripts
pip install reportlab matplotlib
python generate_audit_report.py match_results.json audit_rapport.pdf
```

Zie de docstring in [`tools/scripts/generate_audit_report.py`](tools/scripts/generate_audit_report.py) voor het verwachte JSON-schema.

## Structuur

```
three-way-match-audit/
  docs/                            # GitHub Pages showcase (client-side)
    index.html · app.js · style.css
    samples/                       # Voorbeeld-CSVs
  webapp/                          # FastAPI server (Python)
    app/services/{parsers,matcher}.py
    app/templates/                 # Jinja2 pagina's
    sample_data/                   # Idem, voor de server-side versie
  tools/scripts/
    generate_audit_report.py       # PDF-rapport generator
  render.yaml                      # Deploy config voor Render.com
```
