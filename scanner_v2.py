#!/usr/bin/env python3
"""GeoSentinel 2.0 Scanner — Multi-source disease surveillance with anomaly detection.
Sources: WHO DON, PAHO (WHO Americas), GDELT news, Mastodon hashtags, Reddit (OAuth).
Features: deduplication, traveler detection, anomaly scoring, city-level geocoding,
case/death count extraction."""

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
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from collections import defaultdict

VERSION = "2.0"

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

# ═══ Major international airport hubs by country ═══
FLIGHT_HUBS = {
    "BD": [{"city":"Dhaka","lat":23.81,"lng":90.41,"iata":"DAC","routes":["DEL","DXB","KUL","SIN","DOH"]}],
    "IN": [{"city":"Delhi","lat":28.61,"lng":77.21,"iata":"DEL","routes":["DXB","LHR","SIN","BKK","JFK"]},
           {"city":"Mumbai","lat":19.07,"lng":72.88,"iata":"BOM","routes":["DXB","LHR","SIN","DOH","JFK"]}],
    "ET": [{"city":"Addis Ababa","lat":9.02,"lng":38.75,"iata":"ADD","routes":["DXB","JNB","NBO","LHR","CDG"]}],
    "CD": [{"city":"Kinshasa","lat":-4.44,"lng":15.27,"iata":"FIH","routes":["ADD","NBO","JNB","BRU","CDG"]}],
    "KH": [{"city":"Phnom Penh","lat":11.56,"lng":104.92,"iata":"PNH","routes":["BKK","SIN","ICN","HKG","KUL"]}],
    "TH": [{"city":"Bangkok","lat":13.75,"lng":100.5,"iata":"BKK","routes":["SIN","HKG","NRT","ICN","LHR"]}],
    "SN": [{"city":"Dakar","lat":14.69,"lng":-17.44,"iata":"DSS","routes":["CDG","CMN","ADD","LIS","MAD"]}],
    "NG": [{"city":"Lagos","lat":6.52,"lng":3.38,"iata":"LOS","routes":["LHR","DXB","ADD","JNB","CDG"]}],
    "KE": [{"city":"Nairobi","lat":-1.29,"lng":36.82,"iata":"NBO","routes":["ADD","DXB","LHR","JNB","BKK"]}],
    "BR": [{"city":"São Paulo","lat":-23.55,"lng":-46.63,"iata":"GRU","routes":["MIA","JFK","LHR","CDG","EZE"]}],
    "MX": [{"city":"Mexico City","lat":19.43,"lng":-99.13,"iata":"MEX","routes":["LAX","MIA","JFK","MAD","BOG"]}],
    "CN": [{"city":"Beijing","lat":39.90,"lng":116.41,"iata":"PEK","routes":["ICN","NRT","SIN","LHR","JFK"]}],
    "ZA": [{"city":"Johannesburg","lat":-26.20,"lng":28.05,"iata":"JNB","routes":["LHR","DXB","ADD","NBO","CDG"]}],
}

IATA_COORDS = {
    "DEL":(28.61,77.21),"DXB":(25.25,55.36),"LHR":(51.47,-0.46),"SIN":(1.35,103.99),
    "BKK":(13.69,100.75),"JFK":(40.64,-73.78),"CDG":(49.01,2.55),"NRT":(35.76,140.39),
    "ICN":(37.46,126.44),"HKG":(22.31,113.92),"KUL":(2.74,101.70),"DOH":(25.26,51.57),
    "NBO":(-1.32,36.93),"JNB":(-26.14,28.25),"ADD":(8.98,38.80),"BRU":(50.90,4.48),
    "MIA":(25.79,-80.29),"LAX":(33.94,-118.41),"MAD":(40.47,-3.57),"LIS":(38.77,-9.13),
    "CMN":(33.37,-7.59),"GRU":(-23.43,-46.47),"EZE":(-34.82,-58.54),"BOG":(4.70,-74.15),
    "PNH":(11.55,104.84),"DAC":(23.84,90.40),"DSS":(14.74,-17.49),"LOS":(6.58,3.32),
    "BOM":(19.09,72.87),"FIH":(-4.39,15.44),"MEX":(19.44,-99.07),"PEK":(40.08,116.58),
}

# ═══ Traveler signal patterns ═══
TRAVELER_PATTERNS = [
    r"(?:came|got|returned?|back|arrived)\s+(?:from|back from)\s+\w+.*(?:sick|ill|fever|diarr|vomit|infected|hospital)",
    r"(?:sick|ill|fever|diarr|vomit|infected)\s+(?:after|since|from)\s+(?:my |our |a )?(?:trip|travel|vacation|holiday|visit)",
    r"(?:travel|trip|vacation|holiday)\s+(?:to|in)\s+\w+.*(?:sick|ill|fever|diarr|outbreak|warning|alert)",
    r"(?:don'?t |do not )?(?:travel|go|visit)\s+(?:to )?\w+.*(?:outbreak|disease|infection|epidemic|cases)",
    r"(?:outbreak|epidemic|cases|deaths?|infections?)\s+(?:in|reported in|confirmed in|spreading in)",
    r"(?:WHO|CDC|health authority|ministry of health).*(?:warn|alert|declare|confirm|report)",
    r"(?:traveler|tourist|visitor|passenger)s?\s+(?:sick|ill|infected|diagnosed|hospitalized|quarantine)",
    r"(?:airport|border|flight|cruise)\s+(?:screen|check|quarantine|ban|restrict)",
]

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
    """Resolve a signal to a single location.

    Picks the location named EARLIEST in the text. The subject of an outbreak
    headline is almost always stated before any country mentioned in passing,
    so 'cholera in DR Congo, spreading toward Uganda' resolves to DR Congo —
    not Uganda, which an earlier first-match-wins scan would have returned.
    Within the chosen country, prefers the most specific match (city over
    country, since cities precede countries in GEO_DB), so 'dengue in Bangkok,
    Thailand' resolves to Bangkok rather than Thailand."""
    t = text.lower()
    matches = []  # (text_position, db_index, entry)
    for idx, entry in enumerate(GEO_DB):
        pos = None
        for key in entry["keys"]:
            p = _match_pos(key, t)
            if p is not None and (pos is None or p < pos):
                pos = p
        if pos is not None:
            matches.append((pos, idx, entry))
    if not matches:
        return None
    # Primary country = the one named earliest in the text.
    primary_iso = min(matches, key=lambda m: m[0])[2]["iso"]
    # Within it, the most specific entry wins (lowest db_index = city).
    entry = min((m for m in matches if m[2]["iso"] == primary_iso),
                key=lambda m: m[1])[2]
    return {
        "lat": entry["lat"], "lng": entry["lng"],
        "name": entry["name"], "country": entry["country"],
        "iso": entry["iso"], "region": entry.get("region", "")
    }

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
    """Check if text describes a traveler-specific health signal."""
    t = text.lower()
    for pat in TRAVELER_PATTERNS:
        if re.search(pat, t):
            return True
    return False

def compute_confidence(signal):
    """Multi-factor confidence scoring."""
    base = {"who": 0.95, "paho": 0.85, "news": 0.70, "mastodon": 0.45, "reddit": 0.40}
    conf = base.get(signal.get("source", ""), 0.5)
    if signal.get("is_traveler"): conf += 0.1
    if signal.get("type") == "official_alert": conf += 0.1
    if "outbreak" in signal.get("summary", "").lower(): conf += 0.05
    if "death" in signal.get("summary", "").lower(): conf += 0.05
    return min(1.0, round(conf, 2))

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

# ═══ Search functions ═══

def fetch_gdelt(query, max_records=25):
    """Keyless global news via GDELT 2.0 doc API."""
    params = urllib.parse.urlencode({
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(max_records),
        "sort": "DateDesc",
        "timespan": "7d",
    })
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + params
    req = urllib.request.Request(url, headers={"User-Agent": f"geosentinel/{VERSION}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []  # GDELT occasionally returns non-JSON for malformed queries
        out = []
        for a in data.get("articles", []):
            seen = a.get("seendate", "")
            published = ""
            if len(seen) >= 15:
                published = f"{seen[0:4]}-{seen[4:6]}-{seen[6:8]}T{seen[9:11]}:{seen[11:13]}:{seen[13:15]}Z"
            country = a.get("sourcecountry", "")
            out.append({
                "title": a.get("title") or "",
                "description": country,
                "url": a.get("url") or "",
                "published": published,
            })
        return out
    except Exception as e:
        print(f"  [!] GDELT error: {e}", file=sys.stderr)
        return []

def fetch_who():
    url = "https://www.who.int/api/hubs/diseaseoutbreaknews?$orderby=PublicationDate%20desc&$top=30"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get("value", [])
    except Exception as e:
        print(f"  [!] WHO error: {e}", file=sys.stderr)
        return []

def fetch_paho(limit=40):
    """PAHO (WHO Americas region) news RSS. Items are general PAHO news;
    detect_diseases() filters to outbreak-relevant entries downstream."""
    url = "https://www.paho.org/en/rss.xml"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"geosentinel/{VERSION}", "Accept": "application/rss+xml,application/xml"})
        with urllib.request.urlopen(req, timeout=20) as r:
            tree = ET.fromstring(r.read())
    except Exception as e:
        print(f"  [!] PAHO error: {e}", file=sys.stderr)
        return []
    out = []
    for item in tree.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        desc = _HTML_TAG.sub(" ", (item.findtext("description") or "")).strip()
        link = (item.findtext("link") or "").strip()
        pub = _to_iso(item.findtext("pubDate"))
        out.append({"title": title, "description": desc[:500], "url": link, "published": pub})
    return out

REDDIT_UA = f"geosentinel/{VERSION} (+https://github.com/acuestamd/project-geosentinel)"

def get_reddit_token():
    """Reddit application-only OAuth (client_credentials).
    Requires REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET env vars. Returns None if either
    is missing so the rest of the pipeline keeps running without Reddit."""
    cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        return None
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=data,
        headers={"Authorization": f"Basic {auth}", "User-Agent": REDDIT_UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get("access_token")
    except Exception as e:
        print(f"  [!] Reddit auth error: {e}", file=sys.stderr)
        return None

def fetch_reddit(query, token, limit=20):
    """Authenticated Reddit search via OAuth Bearer token."""
    if not token:
        return []
    params = urllib.parse.urlencode({"q": query, "limit": str(limit), "sort": "new", "t": "month"})
    url = "https://oauth.reddit.com/search?" + params
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": REDDIT_UA,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        out = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            permalink = d.get("permalink", "")
            out.append({
                "title": d.get("title") or "",
                "description": (d.get("selftext") or "")[:500],
                "url": "https://www.reddit.com" + permalink if permalink else (d.get("url") or ""),
                "published": datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc).isoformat() if d.get("created_utc") else "",
            })
        return out
    except Exception as e:
        print(f"  [!] Reddit error: {e}", file=sys.stderr)
        return []

MASTODON_INSTANCES = ["mastodon.social", "mstdn.social", "mas.to"]

def fetch_mastodon(tag, limit=40):
    """Fetch Mastodon hashtag timeline (public, no auth) across fallback instances."""
    params = urllib.parse.urlencode({"limit": str(limit)})
    safe_tag = urllib.parse.quote(tag.lstrip("#"))
    for host in MASTODON_INSTANCES:
        url = f"https://{host}/api/v1/timelines/tag/{safe_tag}?" + params
        req = urllib.request.Request(url, headers={"User-Agent": REDDIT_UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            if isinstance(data, list):
                return data
            # An instance may return an error object ({"error": ...}) instead of
            # a timeline list — treat it as a miss and fall through to the next.
            print(f"  [!] Mastodon {host}/{safe_tag} non-list response", file=sys.stderr)
        except Exception as e:
            print(f"  [!] Mastodon {host}/{safe_tag} error: {e}", file=sys.stderr)
            continue
    return []

_HTML_TAG = re.compile(r"<[^>]+>")

def process_mastodon(statuses):
    signals = []
    skipped = 0
    if not isinstance(statuses, list):
        return signals
    for s in statuses:
        if not isinstance(s, dict):
            skipped += 1
            continue
        try:
            text = _HTML_TAG.sub(" ", (s.get("content") or "")).strip()
            if not text:
                continue
            loc = geocode(text)
            diseases = detect_diseases(text)
            if not (loc and (diseases or is_traveler_signal(text))):
                continue
            d = diseases[0] if diseases else {"name":"unknown illness","cat":"unknown","sev":4,"emoji":"🌡️"}
            traveler = is_traveler_signal(text)
            counts = extract_counts(text)
            signals.append({
                "id": make_id(text),
                "source": "mastodon",
                "type": "traveler_report" if traveler else "symptom_report",
                "disease": d["name"],
                "category": d["cat"],
                "emoji": d["emoji"],
                "location": loc,
                "severity": min(10, d["sev"] + (1 if traveler else 0)),
                "confidence": 0.55 if traveler else 0.45,
                "summary": text[:280],
                "url": s.get("url", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "published": s.get("created_at", ""),
                "is_traveler": traveler,
                "case_count": counts.get("cases"),
                "death_count": counts.get("deaths"),
            })
        except Exception as e:
            skipped += 1
            print(f"  [!] skip mastodon item: {e}", file=sys.stderr)
            continue
    _warn_skips("mastodon", skipped, len(statuses))
    return signals

# ═══ Processing ═══

def _warn_skips(source, skipped, total):
    """Surface a SYSTEMATIC upstream change: if most items in a source failed to
    process, that source is likely silently yielding nothing (a feed reshape),
    which matters more for a cron biosurveillance tool than a single bad item."""
    if total and skipped > total // 2:
        print(f"  [!!] {source}: skipped {skipped}/{total} items — possible upstream format change", file=sys.stderr)

def process_who(items):
    signals = []
    skipped = 0
    for item in items:
        try:
            title = (item.get("Name") or item.get("Title") or "")
            desc = (item.get("Description") or "")[:500]
            text = (title + " " + desc).strip()
            loc = geocode(text)
            if not loc:
                continue
            diseases = detect_diseases(text)
            d = diseases[0] if diseases else {"name":"unknown","cat":"unknown","sev":5,"emoji":"🦠"}
            sev = min(10, d["sev"] + (1 if "death" in text.lower() else 0))
            counts = extract_counts(text)
            pub = (item.get("PublicationDate") or "")
            signals.append({
                "id": make_id(title),
                "source": "who",
                "type": "official_alert",
                "disease": d["name"],
                "category": d["cat"],
                "emoji": d["emoji"],
                "location": loc,
                "severity": sev,
                "confidence": 0.95,
                "summary": title[:300],
                "url": "https://www.who.int/emergencies/disease-outbreak-news/item/" + (item.get("UrlName") or ""),
                "timestamp": pub or datetime.now(timezone.utc).isoformat(),
                "published": pub[:10],
                "is_traveler": False,
                "case_count": counts.get("cases"),
                "death_count": counts.get("deaths"),
            })
        except Exception as e:
            skipped += 1
            print(f"  [!] skip who item: {e}", file=sys.stderr)
            continue
    _warn_skips("who", skipped, len(items))
    return signals

def process_paho(items):
    signals = []
    skipped = 0
    for r in items:
        try:
            text = ((r.get("title") or "") + " " + (r.get("description") or "")).strip()
            loc = geocode(text)
            diseases = detect_diseases(text)
            if not (loc and diseases):
                continue
            d = diseases[0]
            sev = min(10, d["sev"] + (1 if "outbreak" in text.lower() else 0) + (1 if "death" in text.lower() else 0))
            counts = extract_counts(text)
            signals.append({
                "id": make_id(text),
                "source": "paho",
                "type": "official_alert",
                "disease": d["name"],
                "category": d["cat"],
                "emoji": d["emoji"],
                "location": loc,
                "severity": sev,
                "confidence": 0.85,
                "summary": text[:300],
                "url": r.get("url", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "published": r.get("published", ""),
                "is_traveler": False,
                "case_count": counts.get("cases"),
                "death_count": counts.get("deaths"),
            })
        except Exception as e:
            skipped += 1
            print(f"  [!] skip paho item: {e}", file=sys.stderr)
            continue
    _warn_skips("paho", skipped, len(items))
    return signals

def process_news(results, query=""):
    signals = []
    skipped = 0
    for r in results:
        try:
            # GDELT's 'description' carries the source's country, not the event's
            # location — geocoding it would mislocate signals, so use the headline.
            text = (r.get("title") or "").strip()
            loc = geocode(text)
            diseases = detect_diseases(text)
            if not (loc and diseases):
                continue
            d = diseases[0]
            sev = min(10, d["sev"] + (1 if "outbreak" in text.lower() else 0) + (1 if "death" in text.lower() else 0))
            traveler = is_traveler_signal(text)
            counts = extract_counts(text)
            signals.append({
                "id": make_id(text),
                "source": "news",
                "type": "traveler_report" if traveler else "outbreak_report",
                "disease": d["name"],
                "category": d["cat"],
                "emoji": d["emoji"],
                "location": loc,
                "severity": sev,
                "confidence": 0.75 if traveler else 0.70,
                "summary": text[:300],
                "url": r.get("url", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "published": r.get("published", ""),
                "is_traveler": traveler,
                "case_count": counts.get("cases"),
                "death_count": counts.get("deaths"),
            })
        except Exception as e:
            skipped += 1
            print(f"  [!] skip news item: {e}", file=sys.stderr)
            continue
    _warn_skips("news", skipped, len(results))
    return signals

def process_reddit(results):
    signals = []
    skipped = 0
    for r in results:
        try:
            text = ((r.get("title") or "") + " " + (r.get("description") or "")).strip()
            loc = geocode(text)
            diseases = detect_diseases(text)
            if not (loc and (diseases or is_traveler_signal(text))):
                continue
            d = diseases[0] if diseases else {"name":"unknown illness","cat":"unknown","sev":4,"emoji":"🌡️"}
            traveler = is_traveler_signal(text)
            counts = extract_counts(text)
            signals.append({
                "id": make_id(text),
                "source": "reddit",
                "type": "traveler_report" if traveler else "community_report",
                "disease": d["name"],
                "category": d["cat"],
                "emoji": d["emoji"],
                "location": loc,
                "severity": min(10, d["sev"] + (1 if traveler else 0)),
                "confidence": 0.50 if traveler else 0.40,
                "summary": text[:300],
                "url": r.get("url", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "published": r.get("published", ""),
                "is_traveler": traveler,
                "case_count": counts.get("cases"),
                "death_count": counts.get("deaths"),
            })
        except Exception as e:
            skipped += 1
            print(f"  [!] skip reddit item: {e}", file=sys.stderr)
            continue
    _warn_skips("reddit", skipped, len(results))
    return signals

# ═══ Deduplication ═══
def deduplicate(signals):
    """Remove near-duplicate signals using location+disease clustering."""
    seen = {}
    unique = []
    for s in signals:
        key = (s["location"]["iso"], s["disease"], s["source"])
        if key in seen:
            existing = seen[key]
            if s["severity"] > existing["severity"] or s["confidence"] > existing["confidence"]:
                unique.remove(existing)
                unique.append(s)
                seen[key] = s
        else:
            seen[key] = s
            unique.append(s)
    return unique

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

# ═══ Flight risk computation ═══
def compute_flight_risk(hotspots):
    """Compute potential spread routes from hotspot countries."""
    routes = []
    for h in hotspots:
        iso = h["iso"]
        if iso in FLIGHT_HUBS:
            for hub in FLIGHT_HUBS[iso]:
                for dest_iata in hub["routes"]:
                    if dest_iata in IATA_COORDS:
                        dest = IATA_COORDS[dest_iata]
                        routes.append({
                            "from": {"lat": hub["lat"], "lng": hub["lng"], "city": hub["city"], "iata": hub["iata"]},
                            "to": {"lat": dest[0], "lng": dest[1], "iata": dest_iata},
                            "threat_level": h["threat_level"],
                            "diseases": h["diseases"],
                            "severity": h["max_severity"],
                        })
    return routes

# ═══ Compute hotspots ═══
def compute_hotspots(signals):
    countries = {}
    for s in signals:
        iso = s["location"]["iso"]
        if iso not in countries:
            countries[iso] = {
                "iso": iso, "name": s["location"]["country"],
                "lat": s["location"]["lat"], "lng": s["location"]["lng"],
                "region": s["location"].get("region", ""),
                "signals": 0, "max_severity": 0,
                "diseases": set(), "sources": set(),
                "has_traveler_signals": False, "has_anomaly": False,
            }
        c = countries[iso]
        c["signals"] += 1
        c["max_severity"] = max(c["max_severity"], s["severity"])
        c["diseases"].add(s["disease"])
        c["sources"].add(s["source"])
        if s.get("is_traveler"): c["has_traveler_signals"] = True
        if s.get("anomaly"): c["has_anomaly"] = True

    hotspots = []
    for c in sorted(countries.values(), key=lambda x: -x["max_severity"]):
        threat = "CRITICAL" if c["max_severity"] >= 8 else "HIGH" if c["max_severity"] >= 6 else "MODERATE" if c["max_severity"] >= 4 else "LOW"
        hotspots.append({
            "iso": c["iso"], "name": c["name"],
            "lat": c["lat"], "lng": c["lng"],
            "region": c["region"],
            "signals": c["signals"], "max_severity": c["max_severity"],
            "threat_level": threat,
            "diseases": sorted(c["diseases"]),
            "sources": sorted(c["sources"]),
            "has_traveler_signals": c["has_traveler_signals"],
            "has_anomaly": c["has_anomaly"],
        })
    return hotspots

# ═══ Main scan ═══
def run_scan():
    import time
    t0 = time.time()

    print("=" * 60)
    print(f"🛰️  GeoSentinel {VERSION} Scanner — Full Spectrum Scan")
    print("=" * 60)

    all_signals = []

    # 1. WHO Disease Outbreak News
    print("\n📡 [1/5] WHO Disease Outbreak News...")
    who = fetch_who()
    print(f"   → {len(who)} items")
    all_signals.extend(process_who(who))

    # 2. PAHO (WHO regional office for the Americas)
    print("\n🌎 [2/5] PAHO news (WHO Americas)...")
    paho = fetch_paho()
    paho_sigs = process_paho(paho)
    print(f"   → {len(paho)} items, {len(paho_sigs)} disease-relevant signals")
    all_signals.extend(paho_sigs)

    # 3. News (GDELT — keyless global news API; ~1 req per 8s for unauth)
    news_queries = [
        '"dengue outbreak"',
        '"cholera outbreak"',
        '("H5N1" OR "H5N2" OR "H9N2" OR "avian flu" OR "bird flu") outbreak',
        '("ebola" OR "marburg" OR "sudan virus") outbreak',
        '"mpox" outbreak',
        '("nipah" OR "lassa fever") outbreak',
        '"yellow fever" outbreak',
        '"measles outbreak"',
        '("pertussis" OR "whooping cough") outbreak',
        '("mystery illness" OR "unexplained illness" OR "disease x")',
    ]
    print(f"\n🔍 [3/5] News search ({len(news_queries)} queries via GDELT)...")
    for i, q in enumerate(news_queries):
        results = fetch_gdelt(q, max_records=25)
        sigs = process_news(results, q)
        if sigs:
            print(f"   [{i+1}/{len(news_queries)}] {q} → {len(sigs)} signals")
        all_signals.extend(sigs)
        time.sleep(8.0)  # GDELT 429s aggressively under ~5s spacing

    # 4. Reddit (OAuth app-only; skipped silently if creds missing)
    reddit_token = get_reddit_token()
    if reddit_token:
        reddit_queries = [
            "travel sick illness trip",
            "got dengue traveling",
            "malaria travel experience",
            "food poisoning travel country",
            "travel health warning outbreak",
            "sick after vacation tropical",
        ]
        print(f"\n💬 [4/5] Reddit ({len(reddit_queries)} queries, OAuth)...")
        for q in reddit_queries:
            results = fetch_reddit(q, reddit_token, limit=20)
            sigs = process_reddit(results)
            if sigs:
                print(f"   '{q}' → {len(sigs)} signals")
            all_signals.extend(sigs)
            time.sleep(1.0)  # OAuth quota is ~100 req/min, polite spacing
    else:
        print("\n💬 [4/5] Reddit — skipped (no REDDIT_CLIENT_ID/SECRET set)")

    # 5. Mastodon (public hashtag timelines, no auth required)
    mastodon_tags = [
        "dengue", "malaria", "cholera", "ebola", "mpox", "measles",
        "outbreak", "h5n1", "avianflu", "nipah", "marburg", "yellowfever",
        "pertussis", "diseasex", "publichealth", "travelhealth",
    ]
    print(f"\n🐘 [5/5] Mastodon ({len(mastodon_tags)} hashtags)...")
    for tag in mastodon_tags:
        statuses = fetch_mastodon(tag, limit=40)
        sigs = process_mastodon(statuses)
        if sigs:
            print(f"   #{tag} → {len(sigs)} signals")
        all_signals.extend(sigs)
        time.sleep(1.0)

    # Post-processing
    print("\n⚙️  Processing...")

    for s in all_signals:
        s["confidence"] = compute_confidence(s)

    # Raw report volume per (country, disease) BEFORE dedup — this is what the
    # anomaly detector compares against its baseline (dedup would flatten it).
    raw_counts = defaultdict(int)
    for s in all_signals:
        raw_counts[s["location"]["iso"] + ":" + s["disease"]] += 1

    before = len(all_signals)
    all_signals = deduplicate(all_signals)
    print(f"   Dedup: {before} → {len(all_signals)}")

    history = load_history()
    all_signals = detect_anomalies(all_signals, history, raw_counts)
    anomalies = sum(1 for s in all_signals if s.get("anomaly"))
    # Distinct (country, disease) pairs seen for the first time — the dashboard
    # labels this "New (country, disease) Pairs", so count pairs, not signals
    # (one pair can survive dedup as several rows when multiple sources report it).
    new_signals = len({s["location"]["iso"] + ":" + s["disease"] for s in all_signals if s.get("is_new")})
    print(f"   Surge anomalies: {anomalies} | new pairs: {new_signals}")

    # Sort after anomaly detection so the canonical order reflects final state.
    all_signals.sort(key=lambda x: -(x["severity"] * x["confidence"]))

    hotspots = compute_hotspots(all_signals)
    flight_routes = compute_flight_risk(hotspots)
    print(f"   Flight risk routes: {len(flight_routes)}")

    traveler_count = sum(1 for s in all_signals if s.get("is_traveler"))
    stats = {
        "total_signals": len(all_signals),
        "by_source": {},
        "by_category": {},
        "by_severity": {"critical": 0, "high": 0, "moderate": 0, "low": 0},
        "by_region": {},
        "by_type": {},
        "countries_affected": len(hotspots),
        "traveler_signals": traveler_count,
        "anomalies_detected": anomalies,
        "new_signals": new_signals,
        "scan_duration_sec": round(time.time() - t0, 1),
    }
    for s in all_signals:
        stats["by_source"][s["source"]] = stats["by_source"].get(s["source"], 0) + 1
        stats["by_category"][s["category"]] = stats["by_category"].get(s["category"], 0) + 1
        stats["by_type"][s["type"]] = stats["by_type"].get(s["type"], 0) + 1
        r = s["location"].get("region", "Unknown")
        stats["by_region"][r] = stats["by_region"].get(r, 0) + 1
        if s["severity"] >= 8: stats["by_severity"]["critical"] += 1
        elif s["severity"] >= 6: stats["by_severity"]["high"] += 1
        elif s["severity"] >= 4: stats["by_severity"]["moderate"] += 1
        else: stats["by_severity"]["low"] += 1

    output = {
        "version": VERSION,
        "lastScan": datetime.now(timezone.utc).isoformat(),
        "scanDuration": stats["scan_duration_sec"],
        "signals": all_signals,
        "hotspots": hotspots,
        "flightRoutes": flight_routes,
        "stats": stats,
    }

    os.makedirs(os.path.dirname(SIGNALS_FILE), exist_ok=True)
    _atomic_write_json(SIGNALS_FILE, output, separators=(",", ":"))  # minified for the served file

    history["scans"].append({"time": output["lastScan"], "signals": len(all_signals), "hotspots": len(hotspots)})
    history["scans"] = history["scans"][-30:]
    save_history(history)

    elapsed = round(time.time() - t0, 1)
    print(f"\n{'=' * 60}")
    print(f"✅ Scan complete in {elapsed}s")
    print(f"   📊 {len(all_signals)} signals | {len(hotspots)} hotspots | {len(flight_routes)} flight routes")
    print(f"   🔴 Critical: {stats['by_severity']['critical']} | 🟠 High: {stats['by_severity']['high']} | 🟡 Moderate: {stats['by_severity']['moderate']} | 🟢 Low: {stats['by_severity']['low']}")
    print(f"   ✈️  Traveler signals: {traveler_count} | ⚠️  Anomalies: {anomalies}")
    print(f"   Sources: {', '.join(stats['by_source'].keys())}")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    run_scan()
