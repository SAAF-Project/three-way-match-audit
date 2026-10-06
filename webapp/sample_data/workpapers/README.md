# Audit workpaper — schema en voorbeeld

Het auditbestand is één JSON-document dat als bewijs bij het auditdossier wordt gevoegd. Het is zo opgezet dat een reviewer alle drie de zaken onafhankelijk kan verifiëren: **welke brondata werd gebruikt**, **welke matchregels werden toegepast**, en **welk resultaat eruit kwam**.

## Waar het over gaat

| Sectie | Bewijst |
| --- | --- |
| `audit_workpaper` | Wanneer, met welke tool-versie, en met welke toleranties het is uitgevoerd. |
| `source_data` | **Volledigheid en herkomst** — SHA-256 per bronbestand, plus de geparste inhoud. Een reviewer die dezelfde CSV's ontvangt kan de hash zelf berekenen en zo aantonen dat de bytes niet gewijzigd zijn. |
| `match_result` | **Juistheid** — het volledige verdict, per-regel resultaten, alle issue-berichten en totale afwijking. |
| `attestation` | Ruimte voor reviewer sign-off (`reviewed_by`, `reviewed_at`, `notes`). |

## Structuur

```jsonc
{
  "audit_workpaper": {
    "schema_version": "1.0",
    "generated_at": "2026-10-06T07:11:17+00:00",
    "tool": { "name": "SAAF Three-way Match", "version": "0.1.0" },
    "match_parameters": {
      "price_tolerance": 0.01,       // € — max. afwijking op unit price (PO ↔ factuur)
      "qty_tolerance": 0.0,          // eenheden — max. afwijking op quantity (PO ↔ GRN ↔ factuur)
      "line_total_tolerance": 0.01,  // € — max. afwijking op regeltotaal (PO ↔ factuur)
      "total_tolerance": 0.05        // € — max. afwijking op documenttotaal (PO ↔ factuur)
    }
  },
  "source_data": {
    "purchase_order":   { "filename": "...", "size_bytes": 312, "sha256": "e314...", "parsed": { /* canonieke shape */ } },
    "goods_receipt":    { /* idem */ },
    "purchase_invoice": { /* idem */ }
  },
  "match_result": {
    "verdict": "FAIL",             // MATCH / WARNING / FAIL
    "summary": { "MATCH": 1, "WARNING": 0, "FAIL": 2 },
    "header_issues": [ "..." ],
    "line_results": [
      {
        "line_number": 1,
        "sku": "SKU-A100",
        "description": "...",
        "po_qty": 50, "grn_qty": 50, "inv_qty": 50,
        "po_price": 24.5, "inv_price": 26.0,
        "po_total": 1225.0, "inv_total": 1300.0,
        "result": "FAIL",
        "issues": [ "Stukprijs wijkt af: PO €24.50 → factuur €26.00." ]
      }
    ],
    "totals": { "po_total": 3380.0, "grn_total": null, "inv_total": 3633.0, "discrepancy": 253.0 }
  },
  "attestation": {
    "reviewed_by": "",             // in te vullen door de reviewer
    "reviewed_at": "",
    "notes": ""
  }
}
```

## Hash verifiëren

Op elk platform is de SHA-256 van een bestand controleerbaar zonder de tool zelf:

```bash
# macOS / Linux
shasum -a 256 po_sample.csv

# Windows PowerShell
Get-FileHash po_sample.csv -Algorithm SHA256
```

Die uitkomst moet exact overeenkomen met het `sha256`-veld in het auditbestand. Als hij afwijkt: het bronbestand is gewijzigd tussen match en review.

## Reproduceren van het resultaat

De `source_data[*].parsed` blokken vormen een **volledige** invoer voor `three_way_match()`. Een reviewer kan de matcher lokaal draaien met alleen die blokken plus de `match_parameters` — geen toegang tot het originele CSV/JSON nodig — en het `match_result` blok moet bit-voor-bit terugkomen.

## Voorbeeld

[`example_workpaper_FAIL.json`](example_workpaper_FAIL.json) — het uitgeschreven bestand voor de PO/GRN/mismatch-invoice combinatie uit `sample_data/`. Bevat 2 FAIL-regels (prijsafwijking + over-facturering) en €253 totaalafwijking.
