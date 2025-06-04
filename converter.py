import os
import sys
import base64
import argparse
import datetime
import xml.etree.ElementTree as ET
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

def format_date(datum_str):
    """
    Erwartet ein Datum im Format YYYY-MM-DD und gibt 'D.M.YYYY' zurück.
    Falls format nicht passt oder None, wird der Originalstring zurückgegeben.
    """
    try:
        d = datetime.datetime.strptime(datum_str, "%Y-%m-%d")
        return f"{d.day}.{d.month}.{d.year}"
    except:
        return datum_str or ""

def format_period_monthyear(start_str, end_str):
    """
    Wandelt z.B. '2025-05-01'/'2025-05-31' in '05/2025'.
    Wenn nur der Monat relevant ist, wird aus dem Startdatum Monat/Jahr verwendet.
    """
    try:
        d = datetime.datetime.strptime(start_str, "%Y-%m-%d")
        return f"{d.month:02d}/{d.year}"
    except:
        return ""

def draw_header(c, width, height, supplier_name, invoice_id, issue_date, page_num, total_pages):
    """
    Zeichnet auf jeder Seite oben:
    - Links: 'E-Rechnung | {Lieferant}'
    - Rechts oben: 'Rechnungsnummer: … | Datum: …'
    - Unterhalb rechts: 'Seite X / Y'
    """
    left_margin = 30 * mm
    right_margin = 30 * mm
    top_y = height - 20 * mm

    # "E-Rechnung | Lieferant"
    c.setFont("Helvetica-Bold", 12)
    c.drawString(left_margin, top_y, f"E-Rechnung | {supplier_name or ''}")

    # "Rechnungsnummer: … | Datum: …"
    header_text = f"Rechnungsnummer: {invoice_id or ''} | Datum: {format_date(issue_date)}"
    c.setFont("Helvetica", 9)
    tw = c.stringWidth(header_text, "Helvetica", 9)
    c.drawString(width - right_margin - tw, top_y, header_text)

    # "Seite X / Y"
    page_text = f"Seite {page_num} / {total_pages}"
    c.setFont("Helvetica", 9)
    ptw = c.stringWidth(page_text, "Helvetica", 9)
    c.drawString(width - right_margin - ptw, top_y - 6, page_text)

def draw_footer(c, width):
    """
    Zeichnet am unteren Rand den Hinweistext (klein, kursiv).
    """
    left_margin = 30 * mm
    footer_y = 15 * mm
    footer_text = ("* Wichtig: Dieses Dokument ist eine automatisch generierte Zusammenfassung "
                   "der E-Rechnung, es ersetzt nicht die Originaldatei!")
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(left_margin, footer_y, footer_text)

def extract_attachments(xml_root, output_dir, base_name):
    """
    Alle <EmbeddedDocumentBinaryObject>-Elemente finden und als durchnummerierte PDF-Dateien
    "<Basisname>_Anhang1.pdf", "<Basisname>_Anhang2.pdf", … speichern.
    Rückgabe: Liste der erzeugten Pfade.
    """
    attachments = []
    elems = [e for e in xml_root.iter() if e.tag.endswith("EmbeddedDocumentBinaryObject")]
    for idx, elem in enumerate(elems, start=1):
        enc = elem.text
        if not enc:
            continue
        try:
            pdf_bytes = base64.b64decode(enc)
        except Exception as e:
            print(f"Fehler beim Dekodieren von Anhang #{idx}: {e}")
            continue
        fn = f"{base_name}_Anhang{idx}.pdf"
        outp = os.path.join(output_dir, fn)
        with open(outp, "wb") as f:
            f.write(pdf_bytes)
        print(f"Anhang #{idx} gespeichert als: {outp}")
        attachments.append(outp)
    if not attachments:
        print("Kein PDF-Anhang gefunden.")
    return attachments

def parse_invoice_data(xml_root):
    """
    Liest aus der UBL-XML alle relevanten Felder ein und packt sie in ein Dictionary:
    - Metadaten (ID, IssueDate, DueDate, InvoiceTypeCode, Note, DocumentCurrencyCode, BuyerReference, InvoicePeriod)
    - AccountingSupplierParty + AccountingCustomerParty
    - PaymentMeans
    - TaxTotal + TaxSubtotal
    - LegalMonetaryTotal
    - InvoiceLine (Positionen)
    - AdditionalDocumentReference (Dokumentverweise)
    """
    data = {
        "invoice_id": None,
        "issue_date": None,
        "due_date": None,
        "invoice_type_code": None,
        "note": None,
        "currency": None,
        "buyer_reference": None,
        "invoice_period": {"start": None, "end": None},
        "supplier": {
            "endpoint_id": None,
            "name": None,
            "street": None,
            "city": None,
            "postal_zone": None,
            "country": None,
            "company_id": None,
            "registration_name": None,
            "contact_name": None,
            "contact_telephone": None,
            "contact_email": None
        },
        "customer": {
            "endpoint_id": None,
            "name": None,
            "street": None,
            "city": None,
            "postal_zone": None,
            "country": None,
            "registration_name": None
        },
        "payment_means": {
            "payment_means_code": None,
            "payment_id": None,
            "account_id": None,
            "account_name": None,
            "bic": None
        },
        "tax_total": {
            "tax_amount": None,
            "tax_subtotal": {
                "taxable_amount": None,
                "tax_amount": None,
                "tax_category": {
                    "id": None,
                    "percent": None,
                    "scheme_id": None
                }
            }
        },
        "monetary_total": {
            "line_extension_amount": None,
            "tax_exclusive_amount": None,
            "tax_inclusive_amount": None,
            "allowance_total_amount": None,
            "charge_total_amount": None,
            "payable_amount": None
        },
        "items": [],
        "additional_documents": [],
        # Für Seite 3: „Informationen zum Vertrag“
        "profile_id": None,
        "customization_id": None
    }

    # Hilfsfunktion: find mit Wildcard-NS
    def f(path):
        return xml_root.find(path)

    # Metadaten
    elem = f(".//{*}ID")
    if elem is not None:
        data["invoice_id"] = elem.text
    elem = f(".//{*}IssueDate")
    if elem is not None:
        data["issue_date"] = elem.text
    elem = f(".//{*}DueDate")
    if elem is not None:
        data["due_date"] = elem.text
    elem = f(".//{*}InvoiceTypeCode")
    if elem is not None:
        data["invoice_type_code"] = elem.text
    elem = f(".//{*}Note")
    if elem is not None:
        data["note"] = elem.text.strip()
    elem = f(".//{*}DocumentCurrencyCode")
    if elem is not None:
        data["currency"] = elem.text
    elem = f(".//{*}BuyerReference")
    if elem is not None:
        data["buyer_reference"] = elem.text

    # InvoicePeriod
    elem = f(".//{*}InvoicePeriod//{*}StartDate")
    if elem is not None:
        data["invoice_period"]["start"] = elem.text
    elem = f(".//{*}InvoicePeriod//{*}EndDate")
    if elem is not None:
        data["invoice_period"]["end"] = elem.text

    # ProfileID / CustomizationID (Seite 3)
    elem = f(".//{*}ProfileID")
    if elem is not None:
        data["profile_id"] = elem.text
    elem = f(".//{*}CustomizationID")
    if elem is not None:
        data["customization_id"] = elem.text

    # AdditionalDocumentReference (Seite 3 / Anlagen)
    for docref in xml_root.findall(".//{*}AdditionalDocumentReference"):
        doc_id = docref.find(".//{*}ID")
        desc = docref.find(".//{*}DocumentDescription")
        if doc_id is not None or desc is not None:
            data["additional_documents"].append({
                "id": doc_id.text if doc_id is not None else "",
                "description": desc.text if desc is not None else ""
            })

    # Lieferant (AccountingSupplierParty)
    sup = xml_root.find(".//{*}AccountingSupplierParty//{*}Party")
    if sup is not None:
        e = sup.find(".//{*}EndpointID")
        if e is not None:
            data["supplier"]["endpoint_id"] = e.text
        e = sup.find(".//{*}PartyName//{*}Name")
        if e is not None:
            data["supplier"]["name"] = e.text
        addr = sup.find(".//{*}PostalAddress")
        if addr is not None:
            street = addr.find(".//{*}StreetName")
            city = addr.find(".//{*}CityName")
            pz = addr.find(".//{*}PostalZone")
            country = addr.find(".//{*}Country//{*}IdentificationCode")
            if street is not None:
                data["supplier"]["street"] = street.text
            if city is not None:
                data["supplier"]["city"] = city.text
            if pz is not None:
                data["supplier"]["postal_zone"] = pz.text
            if country is not None:
                data["supplier"]["country"] = country.text
        e = sup.find(".//{*}PartyTaxScheme//{*}CompanyID")
        if e is not None:
            data["supplier"]["company_id"] = e.text
        e = sup.find(".//{*}PartyLegalEntity//{*}RegistrationName")
        if e is not None:
            data["supplier"]["registration_name"] = e.text
        contact = sup.find(".//{*}Contact")
        if contact is not None:
            e = contact.find(".//{*}Name")
            if e is not None:
                data["supplier"]["contact_name"] = e.text
            e = contact.find(".//{*}Telephone")
            if e is not None:
                data["supplier"]["contact_telephone"] = e.text
            e = contact.find(".//{*}ElectronicMail")
            if e is not None:
                data["supplier"]["contact_email"] = e.text

    # Kunde (AccountingCustomerParty)
    cust = xml_root.find(".//{*}AccountingCustomerParty//{*}Party")
    if cust is not None:
        e = cust.find(".//{*}EndpointID")
        if e is not None:
            data["customer"]["endpoint_id"] = e.text
        e = cust.find(".//{*}PartyName//{*}Name")
        if e is not None:
            data["customer"]["name"] = e.text
        addr = cust.find(".//{*}PostalAddress")
        if addr is not None:
            street = addr.find(".//{*}StreetName")
            city = addr.find(".//{*}CityName")
            pz = addr.find(".//{*}PostalZone")
            country = addr.find(".//{*}Country//{*}IdentificationCode")
            if street is not None:
                data["customer"]["street"] = street.text
            if city is not None:
                data["customer"]["city"] = city.text
            if pz is not None:
                data["customer"]["postal_zone"] = pz.text
            if country is not None:
                data["customer"]["country"] = country.text
        e = cust.find(".//{*}PartyLegalEntity//{*}RegistrationName")
        if e is not None:
            data["customer"]["registration_name"] = e.text

    # Zahlungsinformationen (PaymentMeans)
    pay = xml_root.find(".//{*}PaymentMeans")
    if pay is not None:
        e = pay.find(".//{*}PaymentMeansCode")
        if e is not None:
            data["payment_means"]["payment_means_code"] = e.text
        e = pay.find(".//{*}PaymentID")
        if e is not None:
            data["payment_means"]["payment_id"] = e.text
        acc = pay.find(".//{*}PayeeFinancialAccount")
        if acc is not None:
            e = acc.find(".//{*}ID")
            if e is not None:
                data["payment_means"]["account_id"] = e.text
            e = acc.find(".//{*}Name")
            if e is not None:
                data["payment_means"]["account_name"] = e.text
            e = acc.find(".//{*}FinancialInstitutionBranch//{*}ID")
            if e is not None:
                data["payment_means"]["bic"] = e.text

    # Steuerdetails (TaxTotal)
    tax = xml_root.find(".//{*}TaxTotal")
    if tax is not None:
        e = tax.find(".//{*}TaxAmount")
        if e is not None:
            data["tax_total"]["tax_amount"] = e.text
        subt = tax.find(".//{*}TaxSubtotal")
        if subt is not None:
            e = subt.find(".//{*}TaxableAmount")
            if e is not None:
                data["tax_total"]["tax_subtotal"]["taxable_amount"] = e.text
            e = subt.find(".//{*}TaxAmount")
            if e is not None:
                data["tax_total"]["tax_subtotal"]["tax_amount"] = e.text
            cat = subt.find(".//{*}TaxCategory")
            if cat is not None:
                e = cat.find(".//{*}ID")
                if e is not None:
                    data["tax_total"]["tax_subtotal"]["tax_category"]["id"] = e.text
                e = cat.find(".//{*}Percent")
                if e is not None:
                    data["tax_total"]["tax_subtotal"]["tax_category"]["percent"] = e.text
                e = cat.find(".//{*}TaxScheme//{*}ID")
                if e is not None:
                    data["tax_total"]["tax_subtotal"]["tax_category"]["scheme_id"] = e.text

    # Monetäre Summen (LegalMonetaryTotal)
    mt = xml_root.find(".//{*}LegalMonetaryTotal")
    if mt is not None:
        e = mt.find(".//{*}LineExtensionAmount")
        if e is not None:
            data["monetary_total"]["line_extension_amount"] = e.text
        e = mt.find(".//{*}TaxExclusiveAmount")
        if e is not None:
            data["monetary_total"]["tax_exclusive_amount"] = e.text
        e = mt.find(".//{*}TaxInclusiveAmount")
        if e is not None:
            data["monetary_total"]["tax_inclusive_amount"] = e.text
        e = mt.find(".//{*}AllowanceTotalAmount")
        if e is not None:
            data["monetary_total"]["allowance_total_amount"] = e.text
        e = mt.find(".//{*}ChargeTotalAmount")
        if e is not None:
            data["monetary_total"]["charge_total_amount"] = e.text
        e = mt.find(".//{*}PayableAmount")
        if e is not None:
            data["monetary_total"]["payable_amount"] = e.text

    # Positionen (InvoiceLine)
    for line in xml_root.findall(".//{*}InvoiceLine"):
        itm = {
            "id": None,
            "quantity": None,
            "quantity_unit": None,
            "line_extension_amount": None,
            "item_name": None,
            "tax_category": {"id": None, "percent": None, "scheme_id": None},
            "price_amount": None,
            "price_currency": None,
            "base_quantity": None,
            "base_quantity_unit": None
        }
        e = line.find(".//{*}ID")
        if e is not None:
            itm["id"] = e.text
        e = line.find(".//{*}InvoicedQuantity")
        if e is not None:
            itm["quantity"] = e.text
            itm["quantity_unit"] = e.get("unitCode")
        e = line.find(".//{*}LineExtensionAmount")
        if e is not None:
            itm["line_extension_amount"] = e.text

        # Item → Name + ClassifiedTaxCategory
        root_item = line.find(".//{*}Item")
        if root_item is not None:
            e = root_item.find(".//{*}Name")
            if e is not None:
                itm["item_name"] = e.text
            cat = root_item.find(".//{*}ClassifiedTaxCategory")
            if cat is not None:
                e = cat.find(".//{*}ID")
                if e is not None:
                    itm["tax_category"]["id"] = e.text
                e = cat.find(".//{*}Percent")
                if e is not None:
                    itm["tax_category"]["percent"] = e.text
                e = cat.find(".//{*}TaxScheme//{*}ID")
                if e is not None:
                    itm["tax_category"]["scheme_id"] = e.text

        # Price
        pr = line.find(".//{*}Price")
        if pr is not None:
            e = pr.find(".//{*}PriceAmount")
            if e is not None:
                itm["price_amount"] = e.text
                itm["price_currency"] = e.get("currencyID")
            e = pr.find(".//{*}BaseQuantity")
            if e is not None:
                itm["base_quantity"] = e.text
                itm["base_quantity_unit"] = e.get("unitCode")

        data["items"].append(itm)

    return data

def create_invoice_pdf(invoice_data, output_path):
    """
    Erzeugt eine dreiseitige PDF-Datei mit Layout ähnlich dem Beispiel (ohne Farben).
    """
    width, height = A4
    c = canvas.Canvas(output_path, pagesize=A4)

    # Gesamtseitenzahl (wir wissen durch Layout, dass es genau 3 sein sollen)
    total_pages = 3

    # Seite 1: Übersicht
    draw_header(
        c, width, height,
        supplier_name=invoice_data["supplier"]["name"],
        invoice_id=invoice_data["invoice_id"],
        issue_date=invoice_data["issue_date"],
        page_num=1, total_pages=total_pages
    )
    y = height - 30 * mm  # Startpunkt unter Header

    # Überschrift "Übersicht"
    c.setFont("Helvetica-Bold", 12)
    c.drawString(30 * mm, y, "Übersicht")
    y -= 10 * mm

    # --- Informationen zum Käufer ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Informationen zum Käufer")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    # Käuferreferenz
    c.drawString(35 * mm, y, f"Käuferreferenz: {invoice_data['buyer_reference'] or '–'}")
    y -= 5 * mm
    # Name (falls registration_name vorhanden, nehmen wir die; sonst 'name')
    kn = invoice_data["customer"]["registration_name"] or invoice_data["customer"]["name"] or ""
    c.drawString(35 * mm, y, f"Name: {kn}")
    y -= 5 * mm
    # Adresse: Straße, PLZ, Ort, Land
    street = invoice_data["customer"]["street"] or ""
    pz = invoice_data["customer"]["postal_zone"] or ""
    city = invoice_data["customer"]["city"] or ""
    country = invoice_data["customer"]["country"] or ""
    # Adresszeile1
    c.drawString(35 * mm, y, f"Adresszeile 1: {street}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"PLZ: {pz}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Ort: {city}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Ländercode: {country}")
    y -= 8 * mm

    # --- Informationen zum Verkäufer ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Informationen zum Verkäufer")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    # Firmenname
    supn = invoice_data["supplier"]["name"] or ""
    c.drawString(35 * mm, y, f"Firmenname: {supn}")
    y -= 5 * mm
    # Straße / PLZ / Ort / Land
    street = invoice_data["supplier"]["street"] or ""
    pz = invoice_data["supplier"]["postal_zone"] or ""
    city = invoice_data["supplier"]["city"] or ""
    country = invoice_data["supplier"]["country"] or ""
    c.drawString(35 * mm, y, f"Adresszeile 1: {street}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"PLZ: {pz}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Ort: {city}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Ländercode: {country}")
    y -= 5 * mm
    # Kontaktperson
    c.drawString(35 * mm, y, f"Name: {invoice_data['supplier']['contact_name'] or ''}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Telefon: {invoice_data['supplier']['contact_telephone'] or ''}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"E-Mail-Adresse: {invoice_data['supplier']['contact_email'] or ''}")
    y -= 8 * mm

    # --- Rechnungsdaten ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Rechnungsdaten")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawString(35 * mm, y, f"Rechnungsnummer: {invoice_data['invoice_id'] or ''}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Rechnungsdatum: {format_date(invoice_data['issue_date'])}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Rechnungsart: {invoice_data['invoice_type_code'] or ''}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Währung: {invoice_data['currency'] or ''}")
    y -= 8 * mm

    # --- Abrechnungszeitraum ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Abrechnungszeitraum")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    start = invoice_data["invoice_period"]["start"]
    end = invoice_data["invoice_period"]["end"]
    c.drawString(35 * mm, y, f"Von: {format_date(start)}  Bis: {format_date(end)}")
    y -= 8 * mm

    # --- Gesamtbeträge der Rechnung ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Gesamtbeträge der Rechnung")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    mt = invoice_data["monetary_total"]
    tt = invoice_data["tax_total"]
    # Summe aller Positionen
    c.drawString(35 * mm, y, f"Summe aller Positionen                    {mt['line_extension_amount'] or '0.00'}")
    y -= 5 * mm
    # Summe Nachlässe
    c.drawString(35 * mm, y, f"Summe Nachlässe                       {mt['allowance_total_amount'] or '0.00'}")
    y -= 5 * mm
    # Summe Zuschläge
    c.drawString(35 * mm, y, f"Summe Zuschläge                        {mt['charge_total_amount'] or '0.00'}")
    y -= 5 * mm
    # Gesamtsumme (netto)
    # Hier nehmen wir tax_exclusive_amount, das entspricht Netto-Summe
    c.drawString(35 * mm, y, f"Gesamtsumme                     {mt['tax_exclusive_amount'] or '0.00'}")
    y -= 5 * mm
    # Summe Umsatzsteuer
    c.drawString(35 * mm, y, f"Summe Umsatzsteuer           {tt['tax_amount'] or '0.00'}")
    y -= 5 * mm
    # Gesamtsumme (brutto)
    c.drawString(35 * mm, y, f"Gesamtsumme                     {mt['tax_inclusive_amount'] or '0.00'}")
    y -= 5 * mm
    # Summe Fremdforderungen (in der Regel 0)
    c.drawString(35 * mm, y, f"Summe Fremdforderungen          { '0.00' }")
    y -= 5 * mm
    # Fälliger Betrag
    c.drawString(35 * mm, y, f"Fälliger Betrag               {mt['payable_amount'] or '0.00'}")
    y -= 8 * mm

    # --- Aufschlüsselung der Umsatzsteuer auf Ebene der Rechnung ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Aufschlüsselung der Umsatzsteuer auf Ebene der Rechnung")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    cat = invoice_data["tax_total"]["tax_subtotal"]["tax_category"]
    taxable = invoice_data["tax_total"]["tax_subtotal"]["taxable_amount"] or ""
    taxamt = invoice_data["tax_total"]["tax_subtotal"]["tax_amount"] or ""
    c.drawString(35 * mm, y, f"Umsatzsteuerkategorie: {cat['id'] or ''}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Gesamtsumme                  {taxable}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Umsatzsteuersatz          {cat['percent'] + '%' if cat['percent'] else ''}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Umsatzsteuerbetrag         {taxamt}")
    y -= 8 * mm

    # --- Zahlungsdaten (nur Überschrift auf Seite 1) ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Zahlungsdaten")
    y -= 12 * mm

    # Footer
    draw_footer(c, width)
    c.showPage()

    # Seite 2: Zahlungsdetails + Bemerkungen + Details Positionen
    draw_header(
        c, width, height,
        supplier_name=invoice_data["supplier"]["name"],
        invoice_id=invoice_data["invoice_id"],
        issue_date=invoice_data["issue_date"],
        page_num=2, total_pages=total_pages
    )
    y = height - 30 * mm

    # Fälligkeitsdatum
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, f"Fälligkeitsdatum: {format_date(invoice_data['due_date'])}")
    y -= 8 * mm

    # Code für das Zahlungsmittel
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Code für das Zahlungsmittel:")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawString(35 * mm, y, f"{invoice_data['payment_means']['payment_means_code'] or ''}")
    y -= 8 * mm

    # Verwendungszweck
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Verwendungszweck:")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawString(35 * mm, y, f"{invoice_data['invoice_id'] or ''}")
    y -= 8 * mm

    # Überweisung
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Überweisung")
    y -= 8 * mm

    # Kontoinhaber / IBAN / BIC
    c.setFont("Helvetica", 9)
    c.drawString(35 * mm, y, f"Kontoinhaber: {invoice_data['payment_means']['account_name'] or ''}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"IBAN: {invoice_data['payment_means']['account_id'] or ''}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"BIC: {invoice_data['payment_means']['bic'] or ''}")
    y -= 8 * mm

    # Bemerkungen zur Rechnung
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Bemerkungen zur Rechnung")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    # Note kann mehrzeilig sein, wir umbrechen bei ~80 Zeichen pro Zeile
    note = invoice_data["note"] or ""
    lines = note.split("|")
    for ln in lines:
        text = ln.strip()
        if not text:
            continue
        # Bei Bedarf in mehrere Zeilen umbrechen
        while len(text) > 80:
            part = text[:80]
            c.drawString(35 * mm, y, part)
            text = text[80:]
            y -= 5 * mm
        c.drawString(35 * mm, y, text)
        y -= 5 * mm

    # Leistungszeitraum (aus InvoicePeriod)
    period = format_period_monthyear(
        invoice_data["invoice_period"]["start"],
        invoice_data["invoice_period"]["end"]
    )
    if period:
        c.drawString(35 * mm, y, f"Leistungszeitraum: {period}")
        y -= 8 * mm
    else:
        y -= 5 * mm

    # Signaturtext, falls direkt in Note enthalten / sonst überspringen
    # Beispiel-PDF hat: "Wir bedanken uns … verbleiben …"
    # Wir gehen davon aus, dass solche Zeilen bereits in invoice_data["note"] stehen.

    y -= 5 * mm

    # --- Details (Positionen) ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Details")
    y -= 8 * mm

    # Für jede Position einzeln darstellen
    idx = 1
    for itm in invoice_data["items"]:
        # "Position: X"
        c.setFont("Helvetica-Bold", 9)
        c.drawString(30 * mm, y, f"Position: {idx}")
        y -= 6 * mm
        idx += 1

        # "Preiseinzelheiten"
        c.setFont("Helvetica-Bold", 9)
        c.drawString(35 * mm, y, "Preiseinzelheiten")
        y -= 6 * mm

        c.setFont("Helvetica", 9)
        c.drawString(40 * mm, y, f"Menge                      {itm['quantity'] or ''}")
        y -= 5 * mm
        c.drawString(40 * mm, y, f"Einheit                     {itm['quantity_unit'] or ''}")
        y -= 5 * mm
        c.drawString(40 * mm, y, f"Preis pro Einheit (netto)  {itm['price_amount'] or ''}")
        y -= 5 * mm
        c.drawString(40 * mm, y, f"Gesamtpreis (netto)       {itm['line_extension_amount'] or ''}")
        y -= 5 * mm
        c.drawString(40 * mm, y, f"Basismenge zum Artikelpreis: {itm['base_quantity'] or ''}")
        y -= 5 * mm
        c.drawString(40 * mm, y, f"Code der Maßeinheit: {itm['base_quantity_unit'] or ''}")
        y -= 5 * mm
        c.drawString(40 * mm, y, f"Umsatzsteuer: {itm['tax_category']['id'] or ''}")
        y -= 5 * mm
        c.drawString(40 * mm, y, f"Umsatzsteuersatz: {itm['tax_category']['percent'] + '%' if itm['tax_category']['percent'] else ''}")
        y -= 8 * mm

        # "Artikelinformationen"
        c.setFont("Helvetica-Bold", 9)
        c.drawString(35 * mm, y, "Artikelinformationen")
        y -= 6 * mm
        c.setFont("Helvetica", 9)
        c.drawString(40 * mm, y, f"Bezeichnung: {itm['item_name'] or ''}")
        y -= 8 * mm

        # Leere Zeile zur Abgrenzung
        y -= 5 * mm

        # Falls zu knapper Platz, neue Seite (danach Header neu zeichnen)
        if y < 60 * mm:
            draw_footer(c, width)
            c.showPage()
            draw_header(
                c, width, height,
                supplier_name=invoice_data["supplier"]["name"],
                invoice_id=invoice_data["invoice_id"],
                issue_date=invoice_data["issue_date"],
                page_num=2, total_pages=total_pages
            )
            y = height - 30 * mm

    # Nach den Positionen: Zusatzinfos Verkäufer/Käufer (wie Beispiel-PDF)
    # Informationen zum Verkäufer
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Informationen zum Verkäufer")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    # Abweichender Handelsname (= registration_name)
    c.drawString(35 * mm, y, f"Abweichender Handelsname: {invoice_data['supplier']['registration_name'] or ''}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Elektronische Adresse: {invoice_data['supplier']['contact_email'] or ''}")
    y -= 5 * mm
    # Schema der elektronischen Adresse: (hier leer, da im XML nicht erfasst)
    c.drawString(35 * mm, y, "Schema der elektronischen Adresse:")
    y -= 5 * mm
    # USt-ID
    c.drawString(35 * mm, y, f"Umsatzsteuer-ID: {invoice_data['supplier']['company_id'] or ''}")
    y -= 8 * mm

    # Informationen zum Käufer
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Informationen zum Käufer")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawString(35 * mm, y, f"Abweichender Handelsname: {invoice_data['customer']['registration_name'] or ''}")
    y -= 5 * mm
    # E-Mail-Adresse des Käufers (falls im XML vorhanden, hier leer)
    c.drawString(35 * mm, y, "Elektronische Adresse: ")
    y -= 8 * mm

    # Footer
    draw_footer(c, width)
    c.showPage()

    # Seite 3: Informationen zum Vertrag + Anlagen
    draw_header(
        c, width, height,
        supplier_name=invoice_data["supplier"]["name"],
        invoice_id=invoice_data["invoice_id"],
        issue_date=invoice_data["issue_date"],
        page_num=3, total_pages=total_pages
    )
    y = height - 30 * mm

    # Schema der elektronischen Adresse (leer, außerhalb der XML-Daten)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Schema der elektronischen Adresse:")
    y -= 8 * mm

    # Informationen zum Vertrag
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Informationen zum Vertrag")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawString(35 * mm, y, f"Spezifikationskennung: {invoice_data['profile_id'] or ''}")
    y -= 5 * mm
    c.drawString(35 * mm, y, f"Prozesskennung: {invoice_data['customization_id'] or ''}")
    y -= 10 * mm

    # Anlagen
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Anlagen")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawString(35 * mm, y, "Rechnungsbegründende Unterlagen")
    y -= 6 * mm
    idx = 1
    base_dir = os.path.dirname(output_path)
    base_fn = os.path.splitext(os.path.basename(output_path))[0]
    for doc in invoice_data["additional_documents"]:
        # Kennung
        c.drawString(40 * mm, y, f"Kennung: {doc['id'] or idx}")
        y -= 5 * mm
        # Beschreibung
        c.drawString(40 * mm, y, f"Beschreibung: {doc['description'] or ''}")
        y -= 5 * mm
        # Anhangsdokument (Dateiname)
        fn = f"{base_fn}_Anhang{idx}.pdf"
        c.drawString(40 * mm, y, f"Anhangsdokument: {fn}")
        y -= 5 * mm
        c.drawString(40 * mm, y, "Format des Anhangdokuments: application/pdf")
        y -= 5 * mm
        c.drawString(40 * mm, y, f"Name des Anhangdokuments: {fn}")
        y -= 10 * mm
        idx += 1

        if y < 50 * mm:
            draw_footer(c, width)
            c.showPage()
            draw_header(
                c, width, height,
                supplier_name=invoice_data["supplier"]["name"],
                invoice_id=invoice_data["invoice_id"],
                issue_date=invoice_data["issue_date"],
                page_num=3, total_pages=total_pages
            )
            y = height - 30 * mm

    # Footer
    draw_footer(c, width)
    c.showPage()

    c.save()
    print(f"PDF-Rechnung gespeichert als: {output_path}")

def main():
    parser = argparse.ArgumentParser(
        description="Konvertiert eine E-Rechnung (UBL/XML) in ein dreiseitiges PDF (layoutähnlich ohne Farben)."
    )
    parser.add_argument("xml_file", help="Pfad zur E-Rechnung im XML-Format")
    parser.add_argument("-o", "--output", help="Ausgabe-Verzeichnis für generierte PDFs", default="output")
    args = parser.parse_args()

    xml_path = args.xml_file
    out_dir = args.output
    os.makedirs(out_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(xml_path))[0]

    # XML einlesen
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f"Fehler beim Einlesen der XML-Datei: {e}")
        sys.exit(1)

    # Anhänge extrahieren (_Anhang1.pdf, _Anhang2.pdf …)
    extract_attachments(root, out_dir, base_name)

    # Rechnungsdaten extrahieren
    data = parse_invoice_data(root)

    # Primäre PDF: "<Basisname>.pdf"
    invoice_pdf_path = os.path.join(out_dir, f"{base_name}.pdf")
    create_invoice_pdf(data, invoice_pdf_path)

if __name__ == "__main__":
    main()
