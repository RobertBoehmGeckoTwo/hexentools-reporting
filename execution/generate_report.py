"""
generate_report.py

Fetches all relevant data from Airtable for a given startup + month (or full year),
calls Claude API to write the report content, creates a PDF with ReportLab,
uploads the PDF to Airtable Berichte table, and returns the PDF bytes.
"""

import os
import base64
import requests
import anthropic
from datetime import datetime, date
from io import BytesIO
from dotenv import load_dotenv

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

load_dotenv()

TOKEN = os.getenv("AIRTABLE_TOKEN")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

TABLES = {
    "startup": "tbljVyJ1i44R7maW4",
    "monate": "tblMrv2mRwamnlwlm",
    "reporting": "tblvpG23ye8TTGsLA",
    "milestones": "tblioZRPWXi0idCTC",
    "berichte": "tbli6e9i9WDkJvzH3",
}

BERICHTE_FIELDS = {
    "Name": "fld729DdSAMyWqzwt",
    "Start-up": "fldx1VaHINFIbMQXn",
    "Monat": "fldLicRI00KTfqyWV",
    "Bericht": "fldSgtTssxJik4SpW",
}

MONTH_ORDER = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember"
]


# ── Airtable helpers ─────────────────────────────────────────────────────────

def airtable_get(table_id, params=None):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{table_id}"
    records = []
    offset = None
    while True:
        p = dict(params or {})
        if offset:
            p["offset"] = offset
        resp = requests.get(url, headers=HEADERS, params=p)
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
    return records


def fetch_startup(startup_id):
    records = airtable_get(TABLES["startup"], {"filterByFormula": f"RECORD_ID()='{startup_id}'"})
    return records[0] if records else None


def fetch_monate_all():
    records = airtable_get(TABLES["monate"])
    records.sort(key=lambda r: MONTH_ORDER.index(r["fields"].get("Name", "")) if r["fields"].get("Name", "") in MONTH_ORDER else 99)
    return records


def fetch_reportings_for_startup(startup_id, monat_ids=None):
    """Fetch all reportings for a startup, optionally filtered to specific month IDs."""
    all_reportings = airtable_get(TABLES["reporting"])
    result = []
    for r in all_reportings:
        fields = r.get("fields", {})
        startup_links = fields.get("Start-up", [])
        monat_links = fields.get("Monat", [])
        if startup_id in startup_links:
            if monat_ids is None or any(m in monat_links for m in monat_ids):
                result.append(r)
    return result


def fetch_milestones_for_startup(startup_id):
    all_milestones = airtable_get(TABLES["milestones"])
    return [m for m in all_milestones if startup_id in m.get("fields", {}).get("Start-up", [])]


def fetch_previous_reports(startup_id):
    """Fetch text content of previously generated reports for this startup."""
    all_berichte = airtable_get(TABLES["berichte"])
    return [b for b in all_berichte if startup_id in b.get("fields", {}).get("Start-up", [])]


def upload_report_to_airtable(pdf_bytes, startup_id, monat_id, report_name):
    """Create a record in Berichte and upload the PDF as attachment."""
    fields = {"Name": report_name, "Start-up": [startup_id]}
    if monat_id:
        fields["Monat"] = [monat_id]

    create_resp = requests.post(
        f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['berichte']}",
        headers=HEADERS,
        json={"fields": fields},
    )
    create_resp.raise_for_status()
    record_id = create_resp.json()["id"]

    # Upload PDF using hardcoded field ID
    upload_url = f"https://content.airtable.com/v0/{BASE_ID}/{record_id}/{BERICHTE_FIELDS['Bericht']}/uploadAttachment"
    upload_headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    payload = {
        "contentType": "application/pdf",
        "file": base64.b64encode(pdf_bytes).decode("utf-8"),
        "filename": f"{report_name}.pdf",
    }
    upload_resp = requests.post(upload_url, headers=upload_headers, json=payload)
    upload_resp.raise_for_status()

    return record_id


# ── Claude API ───────────────────────────────────────────────────────────────

def generate_report_with_claude(startup_name, scope_label, reportings, milestones, previous_reports):
    """Call Claude to write the full report text. Returns structured dict."""

    # Build reporting context
    reporting_text = ""
    for r in reportings:
        f = r.get("fields", {})
        monat_name = f.get("Monat_Name", "Unbekannter Monat")
        reporting_text += f"\n### Reporting – {monat_name}\n"
        for key in ["Allgemein", "Progress Product", "Progress Company", "Progress Community", "Releases", "Herausforderungen"]:
            val = f.get(key, "").strip()
            if val:
                reporting_text += f"**{key}:** {val}\n"

    # Build milestones context
    milestone_text = ""
    for m in milestones:
        f = m.get("fields", {})
        name = f.get("Name Meilenstein", "").strip()
        desc = f.get("Beschreibung (optional)", "").strip()
        ziel = f.get("Zieldatum (optional)", "")
        milestone_text += f"- **{name}**"
        if desc:
            milestone_text += f": {desc}"
        if ziel:
            milestone_text += f" (Zieldatum: {ziel})"
        milestone_text += "\n"

    # Previous reports context
    prev_text = ""
    for b in previous_reports:
        f = b.get("fields", {})
        prev_text += f"- Bericht '{f.get('Name', '')}' bereits erstellt\n"

    today = datetime.now().strftime("%d.%m.%Y")

    prompt = f"""Du bist ein Experte für die Erstellung von Förderberichten für die Sächsische Aufbaubank (SAB).

Du erstellst einen Förderbericht für das Start-up **{startup_name}** im Rahmen des **R42 Games Accelerator** der R42 GmbH Leipzig. Der R42 Games Accelerator ist ein Förderprogramm für Spieleentwicklungs-Start-ups in Sachsen, finanziert durch die SAB. Die Start-ups erhalten Coaching, Mentoring, Infrastruktur und Netzwerkzugang.

**Berichtszeitraum:** {scope_label}
**Erstellungsdatum:** {today}

---

**REPORTING-DATEN AUS AIRTABLE:**
{reporting_text if reporting_text else "Keine Reportings für diesen Zeitraum hinterlegt."}

---

**HINTERLEGTE MEILENSTEINE FÜR DIESES START-UP:**
{milestone_text if milestone_text else "Keine Meilensteine hinterlegt."}

---

**BEREITS ERSTELLTE BERICHTE FÜR DIESES START-UP:**
{prev_text if prev_text else "Keine vorherigen Berichte."}

---

Erstelle jetzt einen professionellen Förderbericht. Gib deine Antwort als strukturierten Text mit folgenden Abschnitten zurück. Verwende exakt diese Überschriften:

## Einleitung
(Kurze Einleitung zum Start-up und dem Berichtszeitraum)

## Fortschritte und Ergebnisse
(Beschreibe die konkreten Fortschritte auf Basis der Reporting-Daten. Gehe auf Produkt, Unternehmensentwicklung, Community und Releases ein, sofern Daten vorhanden.)

## Meilensteinbewertung
(Gehe auf die hinterlegten Meilensteine ein. Prüfe ob Meilensteine mit Zieldatum im Berichtszeitraum fällig waren und ob sie erreicht wurden. Beziehe dich auf Fortschritte, die auf Meilensteine einzahlen, und auf Herausforderungen, die Meilensteine gefährden könnten. Falls keine Meilensteine hinterlegt sind, schreibe einen entsprechenden Hinweis.)

## Herausforderungen
(Beschreibe die berichteten Herausforderungen und ihre mögliche Auswirkung auf die Projektentwicklung.)

## Ausblick
(Kurzer Ausblick auf die nächsten Schritte und Erwartungen.)

Schreibe sachlich, professionell und im Förderbericht-Stil. Keine Floskeln. Nutze konkrete Informationen aus den Reporting-Daten."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


# ── PDF Generation ───────────────────────────────────────────────────────────

ACCENT_COLOR = colors.HexColor("#1a1a2e")
SECONDARY_COLOR = colors.HexColor("#4f46e5")
LIGHT_GRAY = colors.HexColor("#f5f5f5")
MID_GRAY = colors.HexColor("#888888")


def build_pdf(startup_name, scope_label, report_text):
    """Build a professional PDF from the report text. Returns PDF bytes."""
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )

    styles = getSampleStyleSheet()

    style_cover_title = ParagraphStyle(
        "CoverTitle",
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=28,
        textColor=ACCENT_COLOR,
        spaceAfter=6,
    )
    style_cover_sub = ParagraphStyle(
        "CoverSub",
        fontName="Helvetica",
        fontSize=13,
        leading=18,
        textColor=SECONDARY_COLOR,
        spaceAfter=4,
    )
    style_cover_meta = ParagraphStyle(
        "CoverMeta",
        fontName="Helvetica",
        fontSize=9,
        leading=14,
        textColor=MID_GRAY,
        spaceAfter=2,
    )
    style_h2 = ParagraphStyle(
        "H2",
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=18,
        textColor=ACCENT_COLOR,
        spaceBefore=18,
        spaceAfter=6,
    )
    style_body = ParagraphStyle(
        "Body",
        fontName="Helvetica",
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#1a1a1a"),
        alignment=TA_JUSTIFY,
        spaceAfter=8,
    )
    style_caption = ParagraphStyle(
        "Caption",
        fontName="Helvetica-Oblique",
        fontSize=9,
        leading=12,
        textColor=MID_GRAY,
        spaceAfter=4,
    )

    story = []
    today = datetime.now().strftime("%d. %B %Y").replace(
        "January", "Januar").replace("February", "Februar").replace("March", "März"
        ).replace("April", "April").replace("May", "Mai").replace("June", "Juni"
        ).replace("July", "Juli").replace("August", "August").replace("September", "September"
        ).replace("October", "Oktober").replace("November", "November").replace("December", "Dezember")

    # ── Cover block ──
    story.append(Spacer(1, 1.5 * cm))
    story.append(Paragraph("Förderbericht", style_cover_title))
    story.append(Paragraph(startup_name, style_cover_sub))
    story.append(Paragraph(f"Berichtszeitraum: {scope_label}", style_cover_meta))
    story.append(Paragraph(f"Erstellt am: {today}", style_cover_meta))
    story.append(Paragraph("Fördermaßnahme: R42 Games Accelerator · Sächsische Aufbaubank (SAB)", style_cover_meta))
    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width="100%", thickness=2, color=SECONDARY_COLOR, spaceAfter=24))

    # ── Parse and render report sections ──
    current_para = []

    def flush_para():
        text = " ".join(current_para).strip()
        if text:
            story.append(Paragraph(text, style_body))
        current_para.clear()

    for line in report_text.split("\n"):
        stripped = line.strip()

        if stripped.startswith("## "):
            flush_para()
            heading = stripped[3:].strip()
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e0e0e0"), spaceBefore=4, spaceAfter=4))
            story.append(Paragraph(heading, style_h2))

        elif stripped.startswith("- ") or stripped.startswith("* "):
            flush_para()
            item_text = stripped[2:].strip()
            # Strip markdown bold
            item_text = item_text.replace("**", "")
            story.append(Paragraph(f"• {item_text}", style_body))

        elif stripped == "":
            flush_para()

        else:
            # Strip markdown bold markers for body text
            clean = stripped.replace("**", "<b>", 1).replace("**", "</b>", 1) if "**" in stripped else stripped
            current_para.append(clean)

    flush_para()

    # ── Footer caption ──
    story.append(Spacer(1, 1 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e0e0e0"), spaceAfter=6))
    story.append(Paragraph(
        f"Dieser Bericht wurde automatisch generiert · R42 Games Accelerator · {today}",
        style_caption
    ))

    doc.build(story)
    return buffer.getvalue()


# ── Main entry point ─────────────────────────────────────────────────────────

def generate_report(startup_id, monat_id=None):
    """
    Main function called by Flask route.
    monat_id=None means "full year".
    Returns (pdf_bytes, filename, airtable_record_id).
    """
    # Fetch startup
    startup = fetch_startup(startup_id)
    if not startup:
        raise ValueError(f"Start-up {startup_id} nicht gefunden.")
    startup_name = startup["fields"].get("Name", "Unbekannt")

    # Determine scope
    all_monate = fetch_monate_all()
    monat_map = {m["id"]: m["fields"].get("Name", "") for m in all_monate}

    if monat_id:
        monat_name = monat_map.get(monat_id, "Unbekannter Monat")
        scope_label = monat_name
        monat_ids = [monat_id]
    else:
        scope_label = "Gesamtes Jahr"
        monat_ids = None  # all months

    # Fetch data
    reportings = fetch_reportings_for_startup(startup_id, monat_ids)

    # Enrich reportings with month names
    for r in reportings:
        r_monat_ids = r["fields"].get("Monat", [])
        r["fields"]["Monat_Name"] = monat_map.get(r_monat_ids[0], "?") if r_monat_ids else "?"

    # Sort reportings by month order
    reportings.sort(key=lambda r: MONTH_ORDER.index(r["fields"].get("Monat_Name", "")) if r["fields"].get("Monat_Name", "") in MONTH_ORDER else 99)

    milestones = fetch_milestones_for_startup(startup_id)
    previous_reports = fetch_previous_reports(startup_id)

    # Generate content with Claude
    report_text = generate_report_with_claude(
        startup_name, scope_label, reportings, milestones, previous_reports
    )

    # Build PDF
    pdf_bytes = build_pdf(startup_name, scope_label, report_text)

    # Upload to Airtable
    report_name = f"{startup_name} – {scope_label}"
    record_id = upload_report_to_airtable(pdf_bytes, startup_id, monat_id, report_name)

    filename = f"Foerderbericht_{startup_name.replace(' ', '_')}_{scope_label.replace(' ', '_')}.pdf"
    return pdf_bytes, filename, record_id
