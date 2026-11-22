"""Generate the TEST-ONLY fixtures (fictional organisations, documented file layouts).

These files exist so the pipeline logic can be tested offline. They are NOT demo data and are never
loaded by the application; the real pipeline reads the files configured in config/sources.yaml.
Run: python tests/fixtures/make_fixtures.py
"""
from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from suppliergraph.ingest.common import make_lei

HERE = Path(__file__).parent
rng = random.Random(7)

# (key, legal name, country, parent key or None) -- all fictional
ENTITIES = [
    ("RW", "Rheinwerk Systemhaus GmbH", "DE", "RWH"),
    ("RWH", "Rheinwerk Holding AG", "DE", "RWG"),
    ("RWG", "Rheinwerk Group SE", "DE", None),
    ("AL", "Alster Logistik AG", "DE", None),
    ("EB", "Elbe Bauservice GmbH & Co. KG", "DE", "EBH"),
    ("EBH", "Elbe Beteiligungs GmbH", "DE", None),
    ("NH", "Nordlicht Handels GmbH", "DE", "NHI"),
    ("NHI", "Nordlicht International Holding Ltd", "GB", None),
    ("ID", "Isar Digital SE", "DE", None),
    ("SR", "Spree Reinigung GmbH", "DE", None),
    ("WE", "Weser Energie AG", "DE", None),
    ("MM", "Main Medizintechnik GmbH", "DE", None),
    ("DC", "Donau Consulting GmbH", "AT", None),
    ("HB", "Harz Bueromoebel GmbH", "DE", None),
]
LEI = {k: make_lei(f"TEST{i:02d}{k:<2}".replace(" ", "X").ljust(18, "0")[:18]) for i, (k, *_r) in enumerate(ENTITIES)}

CPV = [
    ("72000000-5", "IT services: consulting, software development, Internet and support", "IT-Dienste: Beratung, Softwareentwicklung, Internet und Support"),
    ("72200000-7", "Software programming and consultancy services", "Softwareprogrammierung und -beratung"),
    ("72300000-8", "Data services", "Datendienste"),
    ("60000000-8", "Transport services (excl. waste transport)", "Verkehrsleistungen (ohne Abfalltransport)"),
    ("60100000-9", "Road transport services", "Strassentransportleistungen"),
    ("45000000-7", "Construction work", "Bauarbeiten"),
    ("45200000-9", "Works for complete or part construction and civil engineering work", "Bauarbeiten fuer Gebaeude und Tiefbau"),
    ("90900000-6", "Cleaning and sanitation services", "Reinigungs- und Hygienedienste"),
    ("90910000-9", "Cleaning services", "Reinigungsdienste"),
    ("33000000-0", "Medical equipments, pharmaceuticals and personal care products", "Medizinische Geraete, Arzneimittel und Koerperpflegemittel"),
    ("33100000-1", "Medical equipments", "Medizinische Geraete"),
    ("39000000-2", "Furniture (incl. office furniture), furnishings and appliances", "Moebel (einschl. Bueromoebel), Einrichtungen und Geraete"),
    ("39100000-3", "Furniture", "Moebel"),
]
TOPIC = {
    "72200000": ("Softwareentwicklung fuer Fachverfahren", "Entwicklung und Betrieb einer Fachanwendung, Anforderung: Zertifizierung nach ISO 27001."),
    "72300000": ("Datenmigration und Datenhaltung", "Migration von Altdaten, Datendienste und Archivierung. ISO 9001 erforderlich."),
    "60100000": ("Fahrdienste und Kurierleistungen", "Strassentransport von Aktenmaterial zwischen Standorten."),
    "45200000": ("Sanierung Verwaltungsgebaeude", "Bauarbeiten und Tiefbau, Nachweis ISO 14001 erwuenscht."),
    "90910000": ("Unterhaltsreinigung", "Reinigungsdienste fuer Verwaltungsgebaeude, Gebaeudereinigung."),
    "33100000": ("Medizinische Geraete fuer die Klinik", "Lieferung medizinischer Geraete einschliesslich Wartung."),
    "39100000": ("Bueromoebel", "Lieferung von Moebeln und Bueromoebeln fuer Verwaltung."),
}
# supplier key -> (name variants used in tenders, categories it serves)
SUPPLIERS = {
    "RW": (["Rheinwerk Systemhaus GmbH", "RHEINWERK SYSTEMHAUS GMBH", "Rheinwerk Systemhaus"], ["72200000", "72300000"]),
    "ID": (["Isar Digital SE", "Isar Digital"], ["72200000", "72300000"]),
    "AL": (["Alster Logistik AG", "Alster Logistik Aktiengesellschaft"], ["60100000"]),
    "EB": (["Elbe Bauservice GmbH & Co. KG", "Elbe Bauservice GmbH u. Co. KG"], ["45200000"]),
    "SR": (["Spree Reinigung GmbH", "Spree Reinigung"], ["90910000"]),
    "MM": (["Main Medizintechnik GmbH", "Main Medizintechnik"], ["33100000"]),
    "HB": (["Harz Bueromoebel GmbH", "Harz Büromöbel GmbH"], ["39100000"]),
    "NH": (["Nordlicht Handels GmbH", "Nordlicht Handels"], ["39100000", "33100000"]),
}
BUYERS = ["Stadt Beispielburg", "Landesamt fuer Verwaltungs-IT Musterland", "Universitaet Musterstadt", "Bundesanstalt fuer Testwesen"]
LEI_PUBLISHED = {"RW", "ID", "AL", "EB"}   # suppliers whose OCDS identifier is an LEI (used for ER evaluation)


def write_gleif():
    d = HERE / "gleif"
    d.mkdir(exist_ok=True)
    with open(d / "level1.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["LEI", "Entity.LegalName", "Entity.LegalAddress.Country", "Entity.LegalJurisdiction", "Entity.EntityStatus", "Entity.EntityCategory"])
        for k, name, c, _p in ENTITIES:
            w.writerow([LEI[k], name, c, c, "ACTIVE", "GENERAL"])
    with open(d / "level2.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Relationship.StartNode.NodeID", "Relationship.EndNode.NodeID", "Relationship.RelationshipType", "Relationship.RelationshipStatus"])
        for k, _n, _c, p in ENTITIES:
            if p:
                w.writerow([LEI[k], LEI[p], "IS_DIRECTLY_CONSOLIDATED_BY", "ACTIVE"])
        # published ultimate parents (note: RW -> RWG, RWH -> RWG)
        w.writerow([LEI["RW"], LEI["RWG"], "IS_ULTIMATELY_CONSOLIDATED_BY", "ACTIVE"])
        w.writerow([LEI["RWH"], LEI["RWG"], "IS_ULTIMATELY_CONSOLIDATED_BY", "ACTIVE"])
        w.writerow([LEI["EB"], LEI["EBH"], "IS_ULTIMATELY_CONSOLIDATED_BY", "ACTIVE"])
        w.writerow([LEI["NH"], LEI["NHI"], "IS_ULTIMATELY_CONSOLIDATED_BY", "ACTIVE"])


def write_cpv():
    d = HERE / "cpv"
    d.mkdir(exist_ok=True)
    with open(d / "cpv.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["CODE", "EN", "DE"])
        for code, en, de in CPV:
            w.writerow([code, en, de])


def write_sanctions():
    d = HERE / "sanctions"
    d.mkdir(exist_ok=True)
    with open(d / "targets.simple.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "schema", "name", "aliases", "countries", "datasets"])
        # fictional entries; the first is a deliberate near-duplicate of a fictional supplier's parent
        w.writerow(["TEST-001", "Company", "Nordlicht International Holding Limited", "Nordlicht Intl Holding", "gb", "test_list"])
        w.writerow(["TEST-002", "Company", "Kestrel Shipping Company", "", "ru", "test_list"])
        w.writerow(["TEST-003", "Person", "Jane Q. Example", "", "us", "test_list"])
        w.writerow(["TEST-004", "Organization", "Rheinbau Maschinen", "", "de", "test_list"])


def write_ocds():
    d = HERE / "ocds"
    d.mkdir(exist_ok=True)
    releases = []
    n = 0
    for year in range(2020, 2025):
        for _ in range(8):
            n += 1
            sup_key = rng.choice(list(SUPPLIERS))
            names, cats = SUPPLIERS[sup_key]
            cat = rng.choice(cats)
            title, desc = TOPIC[cat]
            buyer = rng.choice(BUYERS)
            bid = f"B{BUYERS.index(buyer)}"
            sup_name = rng.choice(names)
            amount = round(rng.uniform(20_000, 900_000), 2)
            month, day = rng.randint(1, 12), rng.randint(1, 28)
            supplier_party = {"id": f"S-{sup_key}-{names.index(sup_name)}", "name": sup_name,
                              "roles": ["supplier"], "address": {"countryName": "Deutschland"}}
            if sup_key in LEI_PUBLISHED:
                supplier_party["identifier"] = {"scheme": "XI-LEI", "id": LEI[sup_key], "legalName": sup_name}
            releases.append({
                "ocid": f"ocds-test-{n:04d}", "id": f"{n:04d}-1", "date": f"{year}-{month:02d}-{day:02d}T10:00:00Z",
                "tag": ["award"],
                "buyer": {"id": bid, "name": buyer},
                "parties": [
                    {"id": bid, "name": buyer, "roles": ["buyer"], "address": {"countryName": "Deutschland"}},
                    supplier_party,
                ],
                "tender": {
                    "id": f"{n:04d}", "title": title, "description": desc,
                    "items": [{"id": "1", "classification": {"scheme": "CPV", "id": cat}}] if rng.random() < 0.75 else [],
                },
                "awards": [{
                    "id": f"{n:04d}-A", "date": f"{year}-{month:02d}-{day:02d}T12:00:00Z",
                    "suppliers": [{"id": supplier_party["id"], "name": sup_name}],
                    "value": {"amount": amount, "currency": "EUR"},
                }],
            })
    with open(d / "releases.json", "w", encoding="utf-8") as fh:
        json.dump({"uri": "test://fixture", "publisher": {"name": "TEST FIXTURE"}, "releases": releases}, fh, indent=1)


def write_regulation():
    d = HERE / "regulation"
    d.mkdir(exist_ok=True)
    (d / "test_regulation.txt").write_text(
        "TEST REGULATION (fictional text for unit tests)\n\n"
        "Article 1. Contracting authorities shall publish every award notice within thirty days of the award decision. "
        "The notice shall name the winning supplier and the contract value.\n\n"
        "Article 2. Suppliers must identify and assess adverse human rights impacts in their own operations and supply chains. "
        "Suppliers shall document the results of each assessment and make them available on request.\n\n"
        "Article 3. This Regulation enters into force on the day following its publication.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_gleif(); write_cpv(); write_sanctions(); write_ocds(); write_regulation()
    print("fixtures written to", HERE)
