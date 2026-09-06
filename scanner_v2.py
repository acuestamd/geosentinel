#!/usr/bin/env python3
"""GeoSentinel 3.0: source-aware public health document triage.
Automated extraction is unverified. No outbreak probability, clinical severity,
or international-spread forecast is inferred from these documents.
"""

import base64
import json
import os
import re
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import hashlib
import math
import html
import time
from html.parser import HTMLParser
from pathlib import Path
from collectors import Collector
from signal_store import (SCHEMA_VERSION, canonical_url, document_id, normalize_date, parse_date,
                          deduplicate_documents, merge_retained, load_document_cache, validate_output)
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from collections import defaultdict

VERSION = "3.0"

DIR = os.path.dirname(os.path.abspath(__file__))
SIGNALS_FILE = os.path.join(DIR, "signals.json")
HISTORY_FILE = os.path.join(DIR, "signal_history.json")

# Anomaly detection tuning (see detect_anomalies).
ANOMALY_MIN_COUNT = 3     # noise floor: never flag a surge below this many reports
ANOMALY_ALPHA = 0.3       # EWMA weight for the per-scan volume baseline

# ═══════════════════════════════════════════
# GEOCODING DATABASE — City + Country level
# ═══════════════════════════════════════════
GEO_DB = [
    # Cities first (more specific = higher priority)
    {"keys":["chiang mai"],"lat":18.79,"lng":98.98,"name":"Chiang Mai","country":"Thailand","iso":"TH","region":"SE Asia"},
    {"keys":["phuket"],"lat":7.88,"lng":98.39,"name":"Phuket","country":"Thailand","iso":"TH","region":"SE Asia"},
    {"keys":["bangkok"],"lat":13.75,"lng":100.5,"name":"Bangkok","country":"Thailand","iso":"TH","region":"SE Asia"},
    {"keys":["bali","denpasar"],"lat":-8.34,"lng":115.09,"name":"Bali","country":"Indonesia","iso":"ID","region":"SE Asia"},
    {"keys":["jakarta"],"lat":-6.21,"lng":106.85,"name":"Jakarta","country":"Indonesia","iso":"ID","region":"SE Asia"},
    {"keys":["hanoi"],"lat":21.03,"lng":105.85,"name":"Hanoi","country":"Vietnam","iso":"VN","region":"SE Asia"},
    {"keys":["ho chi minh","saigon"],"lat":10.82,"lng":106.63,"name":"Ho Chi Minh City","country":"Vietnam","iso":"VN","region":"SE Asia"},
    {"keys":["phnom penh"],"lat":11.56,"lng":104.92,"name":"Phnom Penh","country":"Cambodia","iso":"KH","region":"SE Asia"},
    {"keys":["siem reap"],"lat":13.36,"lng":103.86,"name":"Siem Reap","country":"Cambodia","iso":"KH","region":"SE Asia"},
    {"keys":["manila"],"lat":14.60,"lng":120.98,"name":"Manila","country":"Philippines","iso":"PH","region":"SE Asia"},
    {"keys":["kuala lumpur"],"lat":3.14,"lng":101.69,"name":"Kuala Lumpur","country":"Malaysia","iso":"MY","region":"SE Asia"},
    {"keys":["delhi","new delhi"],"lat":28.61,"lng":77.21,"name":"Delhi","country":"India","iso":"IN","region":"South Asia"},
    {"keys":["mumbai","bombay"],"lat":19.07,"lng":72.88,"name":"Mumbai","country":"India","iso":"IN","region":"South Asia"},
    {"keys":["goa"],"lat":15.30,"lng":74.12,"name":"Goa","country":"India","iso":"IN","region":"South Asia"},
    {"keys":["kolkata","calcutta"],"lat":22.57,"lng":88.36,"name":"Kolkata","country":"India","iso":"IN","region":"South Asia"},
    {"keys":["chennai","madras"],"lat":13.08,"lng":80.27,"name":"Chennai","country":"India","iso":"IN","region":"South Asia"},
    {"keys":["kathmandu"],"lat":27.72,"lng":85.32,"name":"Kathmandu","country":"Nepal","iso":"NP","region":"South Asia"},
    {"keys":["dhaka","dacca"],"lat":23.81,"lng":90.41,"name":"Dhaka","country":"Bangladesh","iso":"BD","region":"South Asia"},
    {"keys":["colombo"],"lat":6.93,"lng":79.84,"name":"Colombo","country":"Sri Lanka","iso":"LK","region":"South Asia"},
    {"keys":["cancun","cancún"],"lat":21.16,"lng":-86.85,"name":"Cancún","country":"Mexico","iso":"MX","region":"Latin America"},
    {"keys":["mexico city","ciudad de mexico"],"lat":19.43,"lng":-99.13,"name":"Mexico City","country":"Mexico","iso":"MX","region":"Latin America"},
    {"keys":["lima"],"lat":-12.05,"lng":-77.04,"name":"Lima","country":"Peru","iso":"PE","region":"Latin America"},
    {"keys":["cusco","cuzco"],"lat":-13.53,"lng":-71.97,"name":"Cusco","country":"Peru","iso":"PE","region":"Latin America"},
    {"keys":["bogota","bogotá"],"lat":4.71,"lng":-74.07,"name":"Bogotá","country":"Colombia","iso":"CO","region":"Latin America"},
    {"keys":["cartagena"],"lat":10.39,"lng":-75.51,"name":"Cartagena","country":"Colombia","iso":"CO","region":"Latin America"},
    {"keys":["rio de janeiro","rio"],"lat":-22.91,"lng":-43.17,"name":"Rio de Janeiro","country":"Brazil","iso":"BR","region":"Latin America"},
    {"keys":["sao paulo","são paulo"],"lat":-23.55,"lng":-46.63,"name":"São Paulo","country":"Brazil","iso":"BR","region":"Latin America"},
    {"keys":["buenos aires"],"lat":-34.60,"lng":-58.38,"name":"Buenos Aires","country":"Argentina","iso":"AR","region":"Latin America"},
    {"keys":["nairobi"],"lat":-1.29,"lng":36.82,"name":"Nairobi","country":"Kenya","iso":"KE","region":"East Africa"},
    {"keys":["mombasa"],"lat":-4.05,"lng":39.67,"name":"Mombasa","country":"Kenya","iso":"KE","region":"East Africa"},
    {"keys":["dar es salaam"],"lat":-6.79,"lng":39.28,"name":"Dar es Salaam","country":"Tanzania","iso":"TZ","region":"East Africa"},
    {"keys":["zanzibar"],"lat":-6.17,"lng":39.20,"name":"Zanzibar","country":"Tanzania","iso":"TZ","region":"East Africa"},
    {"keys":["kampala"],"lat":0.35,"lng":32.58,"name":"Kampala","country":"Uganda","iso":"UG","region":"East Africa"},
    {"keys":["addis ababa"],"lat":9.02,"lng":38.75,"name":"Addis Ababa","country":"Ethiopia","iso":"ET","region":"East Africa"},
    {"keys":["kigali"],"lat":-1.97,"lng":30.10,"name":"Kigali","country":"Rwanda","iso":"RW","region":"East Africa"},
    {"keys":["kinshasa"],"lat":-4.44,"lng":15.27,"name":"Kinshasa","country":"DR Congo","iso":"CD","region":"Central Africa"},
    {"keys":["lagos"],"lat":6.52,"lng":3.38,"name":"Lagos","country":"Nigeria","iso":"NG","region":"West Africa"},
    {"keys":["accra"],"lat":5.60,"lng":-0.19,"name":"Accra","country":"Ghana","iso":"GH","region":"West Africa"},
    {"keys":["dakar"],"lat":14.69,"lng":-17.44,"name":"Dakar","country":"Senegal","iso":"SN","region":"West Africa"},
    {"keys":["cairo"],"lat":30.04,"lng":31.24,"name":"Cairo","country":"Egypt","iso":"EG","region":"North Africa"},
    {"keys":["marrakech","marrakesh"],"lat":31.63,"lng":-8.01,"name":"Marrakech","country":"Morocco","iso":"MA","region":"North Africa"},
    {"keys":["cape town"],"lat":-33.93,"lng":18.42,"name":"Cape Town","country":"South Africa","iso":"ZA","region":"Southern Africa"},
    {"keys":["johannesburg"],"lat":-26.20,"lng":28.05,"name":"Johannesburg","country":"South Africa","iso":"ZA","region":"Southern Africa"},
    {"keys":["beijing","peking"],"lat":39.90,"lng":116.41,"name":"Beijing","country":"China","iso":"CN","region":"East Asia"},
    {"keys":["shanghai"],"lat":31.23,"lng":121.47,"name":"Shanghai","country":"China","iso":"CN","region":"East Asia"},
    {"keys":["hong kong"],"lat":22.32,"lng":114.17,"name":"Hong Kong","country":"China","iso":"CN","region":"East Asia"},
    {"keys":["tokyo"],"lat":35.68,"lng":139.69,"name":"Tokyo","country":"Japan","iso":"JP","region":"East Asia"},
    {"keys":["singapore"],"lat":1.35,"lng":103.82,"name":"Singapore","country":"Singapore","iso":"SG","region":"SE Asia"},
    {"keys":["sydney"],"lat":-33.87,"lng":151.21,"name":"Sydney","country":"Australia","iso":"AU","region":"Oceania"},
    {"keys":["istanbul"],"lat":41.01,"lng":28.98,"name":"Istanbul","country":"Turkey","iso":"TR","region":"Middle East"},
    {"keys":["dubai"],"lat":25.20,"lng":55.27,"name":"Dubai","country":"UAE","iso":"AE","region":"Middle East"},
    # Countries (fallback)
    {"keys":["thailand"],"lat":13.75,"lng":100.5,"name":"Thailand","country":"Thailand","iso":"TH","region":"SE Asia"},
    {"keys":["indonesia"],"lat":-2.5,"lng":118.0,"name":"Indonesia","country":"Indonesia","iso":"ID","region":"SE Asia"},
    {"keys":["vietnam"],"lat":14.06,"lng":108.28,"name":"Vietnam","country":"Vietnam","iso":"VN","region":"SE Asia"},
    {"keys":["cambodia"],"lat":12.57,"lng":104.99,"name":"Cambodia","country":"Cambodia","iso":"KH","region":"SE Asia"},
    {"keys":["philippines"],"lat":12.88,"lng":121.77,"name":"Philippines","country":"Philippines","iso":"PH","region":"SE Asia"},
    {"keys":["malaysia"],"lat":4.21,"lng":101.98,"name":"Malaysia","country":"Malaysia","iso":"MY","region":"SE Asia"},
    {"keys":["myanmar","burma"],"lat":21.91,"lng":95.96,"name":"Myanmar","country":"Myanmar","iso":"MM","region":"SE Asia"},
    {"keys":["laos"],"lat":19.86,"lng":102.50,"name":"Laos","country":"Laos","iso":"LA","region":"SE Asia"},
    {"keys":["india"],"lat":20.59,"lng":78.96,"name":"India","country":"India","iso":"IN","region":"South Asia"},
    {"keys":["nepal"],"lat":28.39,"lng":84.12,"name":"Nepal","country":"Nepal","iso":"NP","region":"South Asia"},
    {"keys":["bangladesh"],"lat":23.68,"lng":90.36,"name":"Bangladesh","country":"Bangladesh","iso":"BD","region":"South Asia"},
    {"keys":["sri lanka"],"lat":7.87,"lng":80.77,"name":"Sri Lanka","country":"Sri Lanka","iso":"LK","region":"South Asia"},
    {"keys":["pakistan"],"lat":30.38,"lng":69.35,"name":"Pakistan","country":"Pakistan","iso":"PK","region":"South Asia"},
    {"keys":["afghanistan"],"lat":33.94,"lng":67.71,"name":"Afghanistan","country":"Afghanistan","iso":"AF","region":"South Asia"},
    {"keys":["mexico"],"lat":23.63,"lng":-102.55,"name":"Mexico","country":"Mexico","iso":"MX","region":"Latin America"},
    {"keys":["brazil"],"lat":-14.24,"lng":-51.93,"name":"Brazil","country":"Brazil","iso":"BR","region":"Latin America"},
    {"keys":["peru"],"lat":-9.19,"lng":-75.02,"name":"Peru","country":"Peru","iso":"PE","region":"Latin America"},
    {"keys":["colombia"],"lat":4.57,"lng":-74.3,"name":"Colombia","country":"Colombia","iso":"CO","region":"Latin America"},
    {"keys":["ecuador"],"lat":-1.83,"lng":-78.18,"name":"Ecuador","country":"Ecuador","iso":"EC","region":"Latin America"},
    {"keys":["bolivia"],"lat":-16.29,"lng":-63.59,"name":"Bolivia","country":"Bolivia","iso":"BO","region":"Latin America"},
    {"keys":["argentina"],"lat":-38.42,"lng":-63.62,"name":"Argentina","country":"Argentina","iso":"AR","region":"Latin America"},
    {"keys":["chile"],"lat":-35.68,"lng":-71.54,"name":"Chile","country":"Chile","iso":"CL","region":"Latin America"},
    {"keys":["venezuela"],"lat":6.42,"lng":-66.59,"name":"Venezuela","country":"Venezuela","iso":"VE","region":"Latin America"},
    {"keys":["costa rica"],"lat":9.75,"lng":-83.75,"name":"Costa Rica","country":"Costa Rica","iso":"CR","region":"Latin America"},
    {"keys":["guatemala"],"lat":15.78,"lng":-90.23,"name":"Guatemala","country":"Guatemala","iso":"GT","region":"Latin America"},
    {"keys":["honduras"],"lat":15.20,"lng":-86.24,"name":"Honduras","country":"Honduras","iso":"HN","region":"Latin America"},
    {"keys":["panama"],"lat":8.54,"lng":-80.78,"name":"Panama","country":"Panama","iso":"PA","region":"Latin America"},
    {"keys":["dominican republic"],"lat":18.74,"lng":-70.16,"name":"Dominican Republic","country":"Dominican Republic","iso":"DO","region":"Caribbean"},
    {"keys":["haiti"],"lat":18.97,"lng":-72.29,"name":"Haiti","country":"Haiti","iso":"HT","region":"Caribbean"},
    {"keys":["cuba"],"lat":21.52,"lng":-77.78,"name":"Cuba","country":"Cuba","iso":"CU","region":"Caribbean"},
    {"keys":["jamaica"],"lat":18.11,"lng":-77.30,"name":"Jamaica","country":"Jamaica","iso":"JM","region":"Caribbean"},
    {"keys":["kenya"],"lat":-0.02,"lng":37.91,"name":"Kenya","country":"Kenya","iso":"KE","region":"East Africa"},
    {"keys":["tanzania"],"lat":-6.37,"lng":34.89,"name":"Tanzania","country":"Tanzania","iso":"TZ","region":"East Africa"},
    {"keys":["uganda"],"lat":1.37,"lng":32.29,"name":"Uganda","country":"Uganda","iso":"UG","region":"East Africa"},
    {"keys":["rwanda"],"lat":-1.94,"lng":29.87,"name":"Rwanda","country":"Rwanda","iso":"RW","region":"East Africa"},
    {"keys":["ethiopia"],"lat":9.15,"lng":40.49,"name":"Ethiopia","country":"Ethiopia","iso":"ET","region":"East Africa"},
    {"keys":["south africa"],"lat":-30.56,"lng":22.94,"name":"South Africa","country":"South Africa","iso":"ZA","region":"Southern Africa"},
    {"keys":["nigeria"],"lat":9.08,"lng":7.49,"name":"Nigeria","country":"Nigeria","iso":"NG","region":"West Africa"},
    {"keys":["ghana"],"lat":7.95,"lng":-1.02,"name":"Ghana","country":"Ghana","iso":"GH","region":"West Africa"},
    {"keys":["senegal"],"lat":14.50,"lng":-14.45,"name":"Senegal","country":"Senegal","iso":"SN","region":"West Africa"},
    {"keys":["cameroon"],"lat":7.37,"lng":12.35,"name":"Cameroon","country":"Cameroon","iso":"CM","region":"West Africa"},
    {"keys":["ivory coast","cote d'ivoire","côte d'ivoire"],"lat":7.54,"lng":-5.55,"name":"Ivory Coast","country":"Ivory Coast","iso":"CI","region":"West Africa"},
    {"keys":["guinea"],"lat":9.95,"lng":-9.70,"name":"Guinea","country":"Guinea","iso":"GN","region":"West Africa"},
    {"keys":["sierra leone"],"lat":8.46,"lng":-11.78,"name":"Sierra Leone","country":"Sierra Leone","iso":"SL","region":"West Africa"},
    {"keys":["liberia"],"lat":6.43,"lng":-9.43,"name":"Liberia","country":"Liberia","iso":"LR","region":"West Africa"},
    {"keys":["mali"],"lat":17.57,"lng":-4.00,"name":"Mali","country":"Mali","iso":"ML","region":"West Africa"},
    {"keys":["congo","drc","democratic republic"],"lat":-4.04,"lng":21.76,"name":"DRC","country":"DR Congo","iso":"CD","region":"Central Africa"},
    {"keys":["egypt"],"lat":26.82,"lng":30.80,"name":"Egypt","country":"Egypt","iso":"EG","region":"North Africa"},
    {"keys":["morocco"],"lat":31.79,"lng":-7.09,"name":"Morocco","country":"Morocco","iso":"MA","region":"North Africa"},
    {"keys":["sudan"],"lat":12.86,"lng":30.22,"name":"Sudan","country":"Sudan","iso":"SD","region":"East Africa"},
    {"keys":["south sudan"],"lat":6.88,"lng":31.31,"name":"South Sudan","country":"South Sudan","iso":"SS","region":"East Africa"},
    {"keys":["somalia"],"lat":5.15,"lng":46.20,"name":"Somalia","country":"Somalia","iso":"SO","region":"East Africa"},
    {"keys":["chad"],"lat":15.45,"lng":18.73,"name":"Chad","country":"Chad","iso":"TD","region":"Central Africa"},
    {"keys":["central african republic","car"],"lat":6.61,"lng":20.94,"name":"CAR","country":"Central African Republic","iso":"CF","region":"Central Africa"},
    {"keys":["angola"],"lat":-11.20,"lng":17.87,"name":"Angola","country":"Angola","iso":"AO","region":"Southern Africa"},
    {"keys":["mozambique"],"lat":-18.67,"lng":35.53,"name":"Mozambique","country":"Mozambique","iso":"MZ","region":"Southern Africa"},
    {"keys":["zambia"],"lat":-13.13,"lng":27.85,"name":"Zambia","country":"Zambia","iso":"ZM","region":"Southern Africa"},
    {"keys":["zimbabwe"],"lat":-19.02,"lng":29.15,"name":"Zimbabwe","country":"Zimbabwe","iso":"ZW","region":"Southern Africa"},
    {"keys":["malawi"],"lat":-13.25,"lng":34.30,"name":"Malawi","country":"Malawi","iso":"MW","region":"Southern Africa"},
    {"keys":["madagascar"],"lat":-18.77,"lng":46.87,"name":"Madagascar","country":"Madagascar","iso":"MG","region":"East Africa"},
    {"keys":["china"],"lat":35.86,"lng":104.20,"name":"China","country":"China","iso":"CN","region":"East Asia"},
    {"keys":["japan"],"lat":36.20,"lng":138.25,"name":"Japan","country":"Japan","iso":"JP","region":"East Asia"},
    {"keys":["south korea","korea"],"lat":35.91,"lng":127.77,"name":"South Korea","country":"South Korea","iso":"KR","region":"East Asia"},
    {"keys":["australia"],"lat":-25.27,"lng":133.78,"name":"Australia","country":"Australia","iso":"AU","region":"Oceania"},
    {"keys":["fiji"],"lat":-17.71,"lng":178.07,"name":"Fiji","country":"Fiji","iso":"FJ","region":"Oceania"},
    {"keys":["turkey"],"lat":38.96,"lng":35.24,"name":"Turkey","country":"Turkey","iso":"TR","region":"Middle East"},
    {"keys":["iraq"],"lat":33.22,"lng":43.68,"name":"Iraq","country":"Iraq","iso":"IQ","region":"Middle East"},
    {"keys":["yemen"],"lat":15.55,"lng":48.52,"name":"Yemen","country":"Yemen","iso":"YE","region":"Middle East"},
    {"keys":["saudi arabia"],"lat":23.89,"lng":45.08,"name":"Saudi Arabia","country":"Saudi Arabia","iso":"SA","region":"Middle East"},
    {"keys":["italy"],"lat":41.87,"lng":12.57,"name":"Italy","country":"Italy","iso":"IT","region":"Europe"},
    {"keys":["spain"],"lat":40.46,"lng":-3.75,"name":"Spain","country":"Spain","iso":"ES","region":"Europe"},
    {"keys":["france"],"lat":46.23,"lng":2.21,"name":"France","country":"France","iso":"FR","region":"Europe"},
    {"keys":["germany"],"lat":51.17,"lng":10.45,"name":"Germany","country":"Germany","iso":"DE","region":"Europe"},
    {"keys":["uk","united kingdom","britain","england"],"lat":55.38,"lng":-3.44,"name":"UK","country":"United Kingdom","iso":"GB","region":"Europe"},
    {"keys":["greece"],"lat":39.07,"lng":21.82,"name":"Greece","country":"Greece","iso":"GR","region":"Europe"},
    {"keys":["portugal"],"lat":39.40,"lng":-8.22,"name":"Portugal","country":"Portugal","iso":"PT","region":"Europe"},
    {"keys":["mauritania"],"lat":21.01,"lng":-10.94,"name":"Mauritania","country":"Mauritania","iso":"MR","region":"West Africa"},
]

DISEASES = {
    "nipah": {"cat": "viral", "sev": 9, "emoji": "🦇"},
    "ebola": {"cat": "hemorrhagic", "sev": 10, "emoji": "🩸"},
    "marburg": {"cat": "hemorrhagic", "sev": 10, "emoji": "🩸"},
    "dengue": {"cat": "vector-borne", "sev": 6, "emoji": "🦟"},
    "malaria": {"cat": "vector-borne", "sev": 7, "emoji": "🦟"},
    "cholera": {"cat": "waterborne", "sev": 8, "emoji": "💧"},
    "typhoid": {"cat": "waterborne", "sev": 6, "emoji": "💧"},
    "zika": {"cat": "vector-borne", "sev": 5, "emoji": "🦟"},
    "chikungunya": {"cat": "vector-borne", "sev": 5, "emoji": "🦟"},
    "yellow fever": {"cat": "vector-borne", "sev": 8, "emoji": "🦟"},
    "avian flu": {"cat": "respiratory", "sev": 8, "emoji": "🐦"},
    "h5n1": {"cat": "respiratory", "sev": 8, "emoji": "🐦"},
    "bird flu": {"cat": "respiratory", "sev": 8, "emoji": "🐦"},
    "h5n6": {"cat": "respiratory", "sev": 8, "emoji": "🐦"},
    "mpox": {"cat": "viral", "sev": 5, "emoji": "🦠"},
    "monkeypox": {"cat": "viral", "sev": 5, "emoji": "🦠"},
    "measles": {"cat": "vaccine-preventable", "sev": 6, "emoji": "💉"},
    "diphtheria": {"cat": "vaccine-preventable", "sev": 7, "emoji": "💉"},
    "polio": {"cat": "vaccine-preventable", "sev": 9, "emoji": "💉"},
    "tuberculosis": {"cat": "respiratory", "sev": 7, "emoji": "🫁"},
    "tb": {"cat": "respiratory", "sev": 7, "emoji": "🫁"},
    "plague": {"cat": "bacterial", "sev": 9, "emoji": "☠️"},
    "anthrax": {"cat": "bacterial", "sev": 8, "emoji": "☠️"},
    "meningitis": {"cat": "bacterial", "sev": 7, "emoji": "🧠"},
    "rift valley fever": {"cat": "vector-borne", "sev": 7, "emoji": "🦟"},
    "lassa fever": {"cat": "hemorrhagic", "sev": 8, "emoji": "🩸"},
    "lassa": {"cat": "hemorrhagic", "sev": 8, "emoji": "🩸"},
    "rabies": {"cat": "viral", "sev": 9, "emoji": "🐕"},
    "hepatitis a": {"cat": "waterborne", "sev": 5, "emoji": "💧"},
    "hepatitis e": {"cat": "waterborne", "sev": 5, "emoji": "💧"},
    "norovirus": {"cat": "waterborne", "sev": 4, "emoji": "💧"},
    "leptospirosis": {"cat": "waterborne", "sev": 5, "emoji": "💧"},
    "schistosomiasis": {"cat": "parasitic", "sev": 4, "emoji": "🪱"},
    "leishmaniasis": {"cat": "parasitic", "sev": 5, "emoji": "🪱"},
    "chagas": {"cat": "parasitic", "sev": 6, "emoji": "🪱"},
    "covid": {"cat": "respiratory", "sev": 5, "emoji": "🦠"},
    "sars": {"cat": "respiratory", "sev": 8, "emoji": "🦠"},
    "mers": {"cat": "respiratory", "sev": 8, "emoji": "🦠"},
    "gastroenteritis": {"cat": "waterborne", "sev": 3, "emoji": "💧"},
    "food poisoning": {"cat": "waterborne", "sev": 3, "emoji": "💧"},
    "diarrhea": {"cat": "waterborne", "sev": 3, "emoji": "💧"},
    "diarrhoea": {"cat": "waterborne", "sev": 3, "emoji": "💧"},
    "fever": {"cat": "unknown", "sev": 4, "emoji": "🌡️"},
    "hiv": {"cat": "viral", "sev": 7, "emoji": "🔴"},
    "hantavirus": {"cat": "viral", "sev": 8, "emoji": "🐭"},
    "hanta": {"cat": "viral", "sev": 8, "emoji": "🐭"},
    "oropouche": {"cat": "vector-borne", "sev": 6, "emoji": "🦟"},
    "crimean-congo": {"cat": "hemorrhagic", "sev": 9, "emoji": "🩸"},
    "cchf": {"cat": "hemorrhagic", "sev": 9, "emoji": "🩸"},
    "west nile": {"cat": "vector-borne", "sev": 5, "emoji": "🦟"},
    "japanese encephalitis": {"cat": "vector-borne", "sev": 7, "emoji": "🦟"},
    # Emerging avian-influenza subtypes under WHO/FAO watch
    "h7n9": {"cat": "respiratory", "sev": 8, "emoji": "🐦"},
    "h9n2": {"cat": "respiratory", "sev": 7, "emoji": "🐦"},
    "h5n2": {"cat": "respiratory", "sev": 7, "emoji": "🐦"},
    "h5n5": {"cat": "respiratory", "sev": 7, "emoji": "🐦"},
    "h3n8": {"cat": "respiratory", "sev": 7, "emoji": "🐦"},
    "h10n3": {"cat": "respiratory", "sev": 7, "emoji": "🐦"},
    "h10n8": {"cat": "respiratory", "sev": 7, "emoji": "🐦"},
    # Pertussis (resurgent, vaccine-preventable)
    "pertussis": {"cat": "vaccine-preventable", "sev": 6, "emoji": "💉"},
    "whooping cough": {"cat": "vaccine-preventable", "sev": 6, "emoji": "💉"},
    # Polio-adjacent surveillance terms
    "acute flaccid paralysis": {"cat": "vaccine-preventable", "sev": 8, "emoji": "💉"},
    "cvdpv": {"cat": "vaccine-preventable", "sev": 8, "emoji": "💉"},
    # Sudan ebolavirus (no licensed vaccine — distinct from Zaire ebolavirus)
    "sudan virus": {"cat": "hemorrhagic", "sev": 10, "emoji": "🩸"},
    # WHO "Disease X" / unexplained-cluster terminology
    "disease x": {"cat": "unknown", "sev": 6, "emoji": "🦠"},
    "mystery illness": {"cat": "unknown", "sev": 6, "emoji": "🦠"},
    "unexplained illness": {"cat": "unknown", "sev": 6, "emoji": "🦠"},
}

def make_id(text):
    return hashlib.md5(text.encode()).hexdigest()[:12]

def _to_iso(raw):
    """Normalize an RFC-822 date (RSS pubDate, e.g. 'Wed, 11 Jun 2026 14:03:00 GMT')
    to a UTC ISO-8601 string the dashboard's time filter can parse. Returns the
    raw string unchanged if it can't be parsed, and '' for empty input."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return raw

def _match_pos(key, text_lower):
    """Return the start index of `key` in `text_lower`, or None if absent.
    Short keys (≤4 chars) use word-boundary matching so ambiguous abbreviations
    like 'car', 'uk', 'rio', 'tb' don't false-positive inside longer words
    ('cargo', 'puke', 'trio', 'subtle')."""
    if len(key) <= 4:
        m = re.search(r"\b" + re.escape(key) + r"\b", text_lower)
        return m.start() if m else None
    i = text_lower.find(key)
    return i if i >= 0 else None

def _matches(key, text_lower):
    return _match_pos(key, text_lower) is not None

def geocode(text):
    """Resolve explicit geography conservatively; abstain on ambiguity."""
    from signal_quality import geocode_text
    return geocode_text(text)

def detect_diseases(text):
    """Detect disease mentions, sorted by severity (most severe first).
    Only diseases[0] is consumed downstream; the rest is kept for context.
    Longer names are tested first so the most specific label wins a severity tie."""
    t = text.lower()
    found = []
    for name, info in sorted(DISEASES.items(), key=lambda x: -len(x[0])):
        if _matches(name, t):
            found.append({"name": name.strip(), "cat": info["cat"], "sev": info["sev"], "emoji": info["emoji"]})
    return sorted(found, key=lambda d: -d["sev"])

def is_traveler_signal(text):
    from signal_quality import analyze_text
    return analyze_text(text, "community")["is_traveler"]

# Extract crude case/death counts from outbreak text.
# Conservative: matches "N cases" / "N deaths" with an optional qualifier, plus
# the spelled-out "N million/thousand cases" form; rejects results > 10M to
# filter out years, population sizes, etc.
_QUAL = r"(?:confirmed |suspected |new |reported |probable |additional )?"
# Integer grouped in strict 3-digit blocks, or plain digits. Only unambiguous
# typographic groupers are allowed \u2014 a plain ASCII space would glue an ordinal
# to a count ("COVID-19 200 cases" -> 19200, "day 3 200 cases" -> 3200).
_GROUP_SEP = ",\u00a0\u202f"  # comma, nbsp, thin space
_INT = r"\d{1,3}(?:[" + _GROUP_SEP + r"]\d{3})+|\d+"
_SEP = re.compile("[" + _GROUP_SEP + "]")
_MULT = {"thousand": 1_000, "million": 1_000_000}
_PATS = {
    "cases": (
        re.compile(r"\b(\d+(?:\.\d+)?)\s+(million|thousand)\s+" + _QUAL + r"cases?\b", re.IGNORECASE),
        re.compile(r"\b(" + _INT + r")\s+" + _QUAL + r"cases?\b", re.IGNORECASE),
    ),
    "deaths": (
        re.compile(r"\b(\d+(?:\.\d+)?)\s+(million|thousand)\s+" + _QUAL + r"deaths?\b", re.IGNORECASE),
        re.compile(r"\b(" + _INT + r")\s+" + _QUAL + r"deaths?\b", re.IGNORECASE),
    ),
}

def extract_counts(text):
    """Pull case/death counts from outbreak text. Returns {} if none found or implausible."""
    out = {}
    for key, (mult_pat, int_pat) in _PATS.items():
        n = None
        m = mult_pat.search(text)
        if m:
            n = int(float(m.group(1)) * _MULT[m.group(2).lower()])
        else:
            m = int_pat.search(text)
            if m:
                digits = _SEP.sub("", m.group(1))
                if digits.isdigit():
                    n = int(digits)
        if n is not None and 0 < n < 10_000_000:  # reject implausibly large matches
            out[key] = n
    return out

# Feed processing: one normalization/triage path for every source.
_HTML_TAG = re.compile(r"<[^>]+>")
DOCUMENTS_FILE = os.path.join(DIR, "signal_documents.json")
CONTEXT_FILE = os.path.join(DIR, "environment_context.json")


class _FeedText(HTMLParser):
    """Keep inline text contiguous (Mastodon splits URLs over nested spans)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("p", "div", "li", "h1", "h2", "h3"):
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Text field must be a string")
    parser = _FeedText()
    parser.feed(value)
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def _warn_skips(source, skipped, total):
    if total and skipped > total // 2:
        print(f"[!] {source}: skipped {skipped}/{total} items — possible upstream format change", file=sys.stderr)


def _process_records(items, source, query="", diagnostics=None):
    from signal_quality import analyze_text
    if not isinstance(items, list):
        return []
    signals, skipped = [], 0
    now = datetime.now(timezone.utc).isoformat()
    for item in items:
        try:
            if not isinstance(item, dict):
                raise ValueError("Expected feed object")
            if source == "who":
                title = plain_text(item.get("Name") or item.get("Title"))
                description = plain_text(item.get("Description"))
                raw_date = item.get("PublicationDate")
                slug = item.get("UrlName") or ""
                if not isinstance(slug, str):
                    raise ValueError("Expected WHO URL slug")
                url = "https://www.who.int/emergencies/disease-outbreak-news/item/" + urllib.parse.quote(slug, safe="-") if slug else ""
            elif source == "mastodon":
                title = ""
                description = plain_text(item.get("content"))
                raw_date = item.get("created_at")
                url = item.get("url") or item.get("uri") or ""
            else:
                title = plain_text(item.get("title"))
                # GDELT description is publisher country, not event geography.
                description = "" if source == "news" else plain_text(item.get("description"))
                raw_date = item.get("published")
                url = item.get("url") or ""
            text = (title + " " + description).strip()[:12000]
            if not text:
                raise ValueError("Required text is empty or missing")
            published = normalize_date(raw_date)
            analysis = analyze_text(text, source, published, title=title)
            disease = analysis.get("disease")
            if not disease and not analysis.get("is_traveler"):
                continue
            disease = disease or {"name": "unknown illness", "cat": "unknown", "sev": 4, "emoji": ""}
            loc = analysis.get("location")
            url = canonical_url(url)
            identity = document_id(url, text, published, source)
            reasons = list(analysis.get("reasons", []))
            if not published:
                reasons.append("Publication date unavailable; retrieval time is not event time.")
            if published and parse_date(published) > datetime.now(timezone.utc) + timedelta(minutes=5):
                reasons.append("Future publication date; held for context review.")
                analysis["triage"], analysis["event_status"] = "context", "uncertain"
            if not loc:
                reasons.append("Location unresolved; no map marker is created.")
            evidence = analysis.get("evidence", {})
            event_text = evidence.get("event_text", "")
            counts = extract_counts(event_text) if isinstance(event_text, str) and analysis.get("event_status") == "active" else {}
            level = "official" if source in ("who", "paho") else "media" if source == "news" else "community"
            event_key = (loc.get("iso", "") + ":" + loc.get("name", "")) if loc else "unresolved"
            signals.append({
                "id": identity, "document_id": identity,
                "event_id": make_id(event_key + ":" + disease["name"]),
                "source": source, "type": "traveler_report" if analysis.get("is_traveler") else "source_report",
                "disease": disease["name"], "category": disease["cat"], "emoji": disease.get("emoji", ""),
                "location": loc, "location_candidates": analysis.get("location_candidates", []),
                "evidence_level": level,
                "event_status": analysis["event_status"], "triage": analysis["triage"],
                "verification_status": "unverified", "rationale": reasons,
                "evidence": evidence, "summary": text[:1200], "original_title": title or text[:180],
                "url": url, "published": published, "retrieved_at": now, "timestamp": now,
                "date_basis": item.get("date_basis", "source_publication") if published else "unknown",
                "first_seen": now, "last_seen": now, "is_traveler": bool(analysis.get("is_traveler")),
                "case_count": counts.get("cases"), "death_count": counts.get("deaths"),
                "count_scope": "Mentioned in selected source passage; not independently verified" if counts else None,
                "provenance": {"url": url, "publisher": urllib.parse.urlsplit(url).hostname or "unknown",
                               "source": source, "retrieved_at": now, "query": item.get("query") or query},
                "queries": [item.get("query") or query] if item.get("query") or query else [],
                "observed_via": [source], "anomaly": False, "is_new": False,
            })
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
            skipped += 1
            print(f"[!] skip {source} item: {type(exc).__name__}", file=sys.stderr)
    _warn_skips(source, skipped, len(items))
    if diagnostics is not None:
        diagnostics["rejected_items"] = diagnostics.get("rejected_items", 0) + skipped
    return signals


def process_who(items):
    return _process_records(items, "who")


def process_paho(items):
    return _process_records(items, "paho")


def process_news(items, query=""):
    return _process_records(items, "news", query)


def process_mastodon(items):
    return _process_records(items, "mastodon")


def process_reddit(items):
    return _process_records(items, "reddit")


# ═══ Deduplication ═══
def deduplicate(signals):
    """Compatibility API: keep distinct documents, cities and dates."""
    return deduplicate_documents(signals)

# ═══ Anomaly detection ═══
def _atomic_write_json(path, obj, **dump_kwargs):
    """Write JSON to a temp file then os.replace() it into place, so a crash
    mid-write can never leave a half-written (later un-parseable) file."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, **dump_kwargs)
    os.replace(tmp, path)

def load_history():
    """Load the cached baseline history, self-healing to an empty default when
    the file is missing, truncated, or the wrong shape. A corrupt cache must
    never crash the scan — otherwise the run would re-cache the corruption and
    brick every subsequent scan."""
    try:
        with open(HISTORY_FILE) as f:
            h = json.load(f)
        if isinstance(h, dict) and isinstance(h.get("baselines"), dict) and isinstance(h.get("scans"), list):
            return h
    except (ValueError, OSError):
        pass  # JSONDecodeError / UnicodeDecodeError are ValueError subclasses
    return {"scans": [], "baselines": {}}

def save_history(history):
    _atomic_write_json(HISTORY_FILE, history, indent=2)

def score_anomaly(curr, mean):
    """Decide whether `curr` reports this scan is a surge over the per-scan
    baseline `mean`. Requires a prior baseline, clears a noise floor, and
    exceeds a Poisson ~2σ band (mean + 2·√mean). Pure and unit-testable."""
    if mean <= 0 or curr < ANOMALY_MIN_COUNT:
        return False
    return curr > mean + 2 * math.sqrt(mean)

def detect_anomalies(signals, history, raw_counts):
    """Flag report-volume surges against a per-scan EWMA baseline.

    `raw_counts` maps 'iso:disease' -> number of RAW (pre-deduplication) reports
    this scan, so we measure report/chatter volume — not how many sources
    happened to survive dedup (which is at most ~5 and made the old detector
    fire on novelty, not surges). Two distinct, honest fields are emitted:
      anomaly  — a genuine surge vs the rolling baseline
      is_new   — first time this (country, disease) pair is seen (novelty, NOT
                 a surge; this is what made a cold cache flag everything)."""
    baselines = history.get("baselines", {})
    for s in signals:
        key = s["location"]["iso"] + ":" + s["disease"]
        # Only the new per-scan baseline is comparable. A legacy 'avg_weekly'
        # entry was computed on POST-dedup counts (≤5), so reusing it against
        # raw volume would fire a false surge — treat such pairs as unseen.
        mean = baselines.get(key, {}).get("avg_signals_per_scan", 0)
        curr = raw_counts.get(key, 1)
        if score_anomaly(curr, mean):
            s["anomaly"] = True
            s["anomaly_factor"] = round(curr / max(mean, 0.1), 1)
            s["is_new"] = False
        else:
            s["anomaly"] = False
            s["anomaly_factor"] = None
            s["is_new"] = mean == 0

    # Update the per-scan EWMA baseline from raw report volume. Legacy entries
    # (avg_weekly only) and brand-new pairs are seeded fresh, not blended onto
    # the wrong scale.
    for key, count in raw_counts.items():
        b = baselines.get(key)
        prev_mean = b.get("avg_signals_per_scan") if b else None
        if prev_mean is None:
            baselines[key] = {"avg_signals_per_scan": float(count), "samples": 1}
        else:
            b["avg_signals_per_scan"] = (1 - ANOMALY_ALPHA) * prev_mean + ANOMALY_ALPHA * count
            b["samples"] = b.get("samples", 1) + 1

    history["baselines"] = baselines
    return signals

# Location summaries are document counts, not estimates of outbreak risk.
def compute_hotspots(signals):
    locations = {}
    for signal in signals:
        loc = signal.get("location")
        if not loc or signal.get("triage", "review") != "review":
            continue
        key = (loc["iso"], loc["name"], loc["lat"], loc["lng"])
        if key not in locations:
            locations[key] = {**loc, "signals": 0, "diseases": set(), "sources": set()}
        row = locations[key]
        row["signals"] += 1
        row["diseases"].add(signal["disease"])
        row["sources"].add(signal["source"])
    return [{**row, "diseases": sorted(row["diseases"]), "sources": sorted(row["sources"])}
            for row in sorted(locations.values(), key=lambda row: (-row["signals"], row["name"]))]


# Main scan. Publication is gated on successful collection and schema validation.
def build_snapshot(fresh, cached, collector, now=None):
    now = now or datetime.now(timezone.utc)
    scan_time = now.isoformat()
    fresh = deduplicate_documents(fresh)
    signals = merge_retained(cached.get("signals", []), fresh, now)
    rows = list(collector.health.values())
    for row in rows:
        row["signals"] = sum(s["source"] == row["id"] for s in fresh)
        if row.get("rejected_items"):
            collector.error(row["id"], "Malformed input items were rejected")
            if row["rejected_items"] >= row["items"]:
                row["status"] = "error"
    working = [r for r in rows if r["successful_requests"] and r["items"] > r.get("rejected_items", 0)]
    configured = [r for r in rows if r["status"] != "disabled"]
    status = "unavailable" if not working else "healthy" if all(r["status"] == "ok" for r in configured) else "degraded"
    review = [s for s in signals if s["triage"] == "review"]
    known = [s for s in review if s.get("location")]
    official = any(r["id"] in ("who", "paho") for r in working)
    output = {
        "schema_version": SCHEMA_VERSION, "version": VERSION, "lastScan": scan_time,
        "lastSuccessfulScan": scan_time if working else cached.get("lastSuccessfulScan"),
        "health": {"status": status, "sources": rows, "official_source_available": official,
                   "retention_days": 30, "stale_after_minutes": 120,
                   "anomaly_model_status": "disabled_pending_validation",
                   "message": "Signals require human verification. Source health is not event truth."},
        "signals": signals, "hotspots": compute_hotspots(known),
        "stats": {"total_signals": len(signals), "review_signals": len(review),
                  "context_signals": len(signals) - len(review),
                  "countries_affected": len({s["location"]["iso"] for s in known}),
                  "unlocated_signals": sum(not s.get("location") for s in review),
                  "by_source": {key: sum(s["source"] == key for s in signals) for key in collector.health},
                  "traveler_signals": sum(s["is_traveler"] for s in review)},
        "methodology": {"version": "3.0", "verification": "All automated records remain unverified",
                        "event_grouping": "Candidate location/disease groups are not confirmed outbreaks",
                        "source": "https://github.com/acuestamd/project-geosentinel/blob/main/docs/METHODOLOGY.md"},
    }
    validate_output(output)
    return output


def run_scan():
    started = time.monotonic()
    cached = load_document_cache(DOCUMENTS_FILE)
    pipeline_signature = hashlib.sha256(b"".join(
        Path(DIR, name).read_bytes()
        for name in ("scanner_v2.py", "signal_quality.py", "signal_store.py"))).hexdigest()
    if cached.get("pipeline_signature") != pipeline_signature:
        # Cached classifications must never survive a change in their rules.
        cached["signals"] = []
    collector = Collector(cached.get("source_health"))
    collected = collector.collect()
    fresh = []
    for source, items in collected.items():
        fresh.extend(_process_records(items, source, diagnostics=collector.health[source]))
    output = build_snapshot(fresh, cached, collector)
    if output["health"]["status"] == "unavailable":
        raise RuntimeError("All sources unavailable: preserving the last published snapshot")
    from context_signals import enrich_context
    try:
        context_cache = json.loads(Path(CONTEXT_FILE).read_text())
    except (OSError, ValueError):
        context_cache = {}
    output["signals"], context_cache = enrich_context(output["signals"], context_cache)
    output["scanDuration"] = round(time.monotonic() - started, 1)
    validate_output(output)
    _atomic_write_json(SIGNALS_FILE, output, ensure_ascii=False, separators=(",", ":"))
    _atomic_write_json(DOCUMENTS_FILE, {
        "schema_version": SCHEMA_VERSION, "signals": output["signals"],
        "pipeline_signature": pipeline_signature,
        "lastSuccessfulScan": output["lastSuccessfulScan"],
        "source_health": {r["id"]: r for r in output["health"]["sources"]},
    }, ensure_ascii=False)
    _atomic_write_json(CONTEXT_FILE, context_cache, ensure_ascii=False)
    print(f"Built snapshot: {len(output['signals'])} documents, {output['stats']['review_signals']} for review; health={output['health']['status']}")
    return output


if __name__ == "__main__":
    run_scan()
