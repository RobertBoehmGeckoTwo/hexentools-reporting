"""
Start-up Reporting Form
Flask web app that serves an HTML form and submits data to Airtable.
"""

import os
import sys
import requests
from datetime import date
from flask import Flask, render_template, request, jsonify, send_file
from io import BytesIO
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "execution"))

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB (Vercel limit)


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "Datei zu groß — maximal 4 MB pro Anhang (Vercel-Limit)."}), 413

TOKEN = os.getenv("AIRTABLE_TOKEN")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

TABLES = {
    "startup": "tbljVyJ1i44R7maW4",
    "monate": "tblMrv2mRwamnlwlm",
    "reporting": "tblvpG23ye8TTGsLA",
}

ATTACHMENT_FIELDS = [
    "fldp8MM4aGDjSAjNn",  # Anhang 01
    "flddegQHaWK7KQlxs",  # Anhang 02
    "fldBXLzOOpQP6lfkZ",  # Anhang 03
]

MONTH_ORDER = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember"
]


def airtable_get(table_id, params=None):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{table_id}"
    records = []
    offset = None
    while True:
        p = params or {}
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


def upload_attachment(record_id, field_id, file_bytes, filename, content_type):
    """Upload a file attachment to an existing Airtable record field (base64 JSON)."""
    import base64
    url = f"https://content.airtable.com/v0/{BASE_ID}/{record_id}/{field_id}/uploadAttachment"
    upload_headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "contentType": content_type,
        "file": base64.b64encode(file_bytes).decode("utf-8"),
        "filename": filename,
    }
    resp = requests.post(url, headers=upload_headers, json=payload)
    resp.raise_for_status()
    return resp.json()


@app.route("/")
def index():
    startups = airtable_get(TABLES["startup"], {"sort[0][field]": "Name", "sort[0][direction]": "asc"})
    monate = airtable_get(TABLES["monate"])
    monate.sort(key=lambda r: MONTH_ORDER.index(r["fields"].get("Name", "")) if r["fields"].get("Name", "") in MONTH_ORDER else 99)
    return render_template("form.html", startups=startups, monate=monate)


@app.route("/submit", methods=["POST"])
def submit():
    try:
        startup_id = request.form.get("startup_id")
        monat_id = request.form.get("monat_id")

        app.logger.info(f"SUBMIT: startup_id={repr(startup_id)} monat_id={repr(monat_id)}")
        app.logger.info(f"FORM DATA: {dict(request.form)}")

        if not startup_id or not monat_id:
            return jsonify({"error": "Start-up und Monat sind Pflichtfelder."}), 400

        fields = {
            "Start-up": [startup_id],
            "Monat": [monat_id],
            "Allgemein": request.form.get("allgemein", ""),
            "Progress Product": request.form.get("progress_product", ""),
            "Progress Company": request.form.get("progress_company", ""),
            "Progress Community": request.form.get("progress_community", ""),
            "Releases": request.form.get("releases", ""),
            "Herausforderungen": request.form.get("herausforderungen", ""),
            "Datum Reporting": date.today().isoformat(),
        }

        # Remove empty text fields but always keep linked records
        fields = {k: v for k, v in fields.items() if v not in ("", [], None)}
        fields["Start-up"] = [startup_id]
        fields["Monat"] = [monat_id]

        # Create the record
        payload = {"fields": fields}
        app.logger.info(f"PAYLOAD: {payload}")
        create_resp = requests.post(
            f"https://api.airtable.com/v0/{BASE_ID}/{TABLES['reporting']}",
            headers=HEADERS,
            json=payload,
        )
        if not create_resp.ok:
            return jsonify({"error": f"Airtable-Fehler: {create_resp.text}", "debug_payload": payload}), 500
        record_id = create_resp.json()["id"]

        # Upload attachments
        file_keys = ["anhang_01", "anhang_02", "anhang_03"]
        for i, key in enumerate(file_keys):
            file = request.files.get(key)
            if file and file.filename:
                upload_attachment(
                    record_id,
                    ATTACHMENT_FIELDS[i],
                    file.read(),
                    file.filename,
                    file.content_type or "application/octet-stream",
                )

        return jsonify({"success": True, "record_id": record_id})

    except requests.HTTPError as e:
        return jsonify({"error": f"Airtable-Fehler: {e.response.text}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/foerderberichte")
def foerderberichte():
    startups = airtable_get(TABLES["startup"], {"sort[0][field]": "Name", "sort[0][direction]": "asc"})
    monate = airtable_get(TABLES["monate"])
    monate.sort(key=lambda r: MONTH_ORDER.index(r["fields"].get("Name", "")) if r["fields"].get("Name", "") in MONTH_ORDER else 99)
    return render_template("bericht_form.html", startups=startups, monate=monate)


@app.route("/foerderberichte/generieren", methods=["POST"])
def foerderberichte_generieren():
    try:
        from generate_report import generate_report

        startup_id = request.form.get("startup_id")
        monat_id = request.form.get("monat_id") or None  # empty string → None = full year

        if not startup_id:
            return jsonify({"error": "Bitte ein Start-up auswählen."}), 400

        pdf_bytes, filename, record_id = generate_report(startup_id, monat_id)

        return send_file(
            BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )

    except Exception as e:
        app.logger.error(f"Bericht-Fehler: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
