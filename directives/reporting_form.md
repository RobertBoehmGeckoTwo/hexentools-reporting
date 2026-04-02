# Directive: Start-up Reporting Form

## Ziel
Eine öffentlich erreichbare Web-App, über die Start-ups ihr monatliches Reporting einreichen können. Daten landen direkt in Airtable.

## Architektur
- **app.py** — Flask-App (Routing, Airtable API, Datei-Upload)
- **templates/form.html** — HTML-Formular (kein JS-Framework, reines HTML/CSS)
- **Hosting** — Railway (kostenlos, HTTPS, automatisches Deploy via GitHub)

## Airtable-Struktur

| Tabelle | ID |
|---|---|
| Start-up | `tbljVyJ1i44R7maW4` |
| Monate | `tblMrv2mRwamnlwlm` |
| Reporting | `tblvpG23ye8TTGsLA` |

**Reporting-Felder:**
- `Start-up` — multipleRecordLinks → `fldy6gpYiF1OsyLDw`
- `Monat` — multipleRecordLinks → `fldNYmecH5vbD0eRB`
- `Allgemein` — multilineText → `fldotsSvC8nMZCm5r`
- `Progress Product` — multilineText → `fldJQ6Qw5xilKFItr`
- `Progress Company` — multilineText → `fldmVI8EaN4MyXhxz`
- `Progress Community` — multilineText → `fldB49JEaAWCoSPkC`
- `Releases` — multilineText → `flddZnXm6rW7DnHId`
- `Herausforderungen` — multilineText → `fldCaeWKMr2nhPQv1`
- `Anhang 01` — multipleAttachments → `fldp8MM4aGDjSAjNn`
- `Anhang 02` — multipleAttachments → `flddegQHaWK7KQlxs`
- `Anhang 03` — multipleAttachments → `fldBXLzOOpQP6lfkZ`

## Datei-Upload Flow
Airtable unterstützt keinen direkten Attachment-Upload beim Record-Create. Daher:
1. Record ohne Attachments erstellen → Record-ID erhalten
2. Pro Datei: `POST /v0/{BASE_ID}/{TABLE_ID}/{RECORD_ID}/uploadAttachment/{FIELD_ID}` mit `Content-Type: application/octet-stream`

## Umgebungsvariablen (.env)
```
AIRTABLE_TOKEN=pat...
AIRTABLE_BASE_ID=appzBpxytiCHNnM75
```

## Railway Deploy (einmalig)

1. GitHub-Repo erstellen und Code pushen
2. railway.app → New Project → Deploy from GitHub Repo
3. Environment Variables setzen: `AIRTABLE_TOKEN` und `AIRTABLE_BASE_ID`
4. Deploy läuft automatisch — öffentliche URL wird generiert

## Lokaler Test
```bash
pip3 install -r requirements.txt
python3 app.py
# → http://localhost:5000
```

## Bekannte Constraints
- Max. Upload-Größe: 50 MB (konfiguriert in app.py)
- Airtable Rate Limit: 5 req/sec — bei gleichzeitigen Submissions könnte es zu 429-Fehlern kommen (aktuell kein Retry implementiert)
- Datei-Uploads nutzen den Airtable Upload-Endpoint (Beta), Token benötigt `data.records:write`
