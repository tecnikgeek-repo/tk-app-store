#!/usr/bin/env python3
"""Carica un .aab su Google Play (canale di produzione) e lo manda in revisione, con l'API di Google Play.
Gira nelle GitHub Actions dopo la compilazione; si può lanciare anche a mano.

uso: play_carica.py <pacchetto> <file.aab> <note>     carica e invia
     play_carica.py <pacchetto> --stato                versione in produzione e in revisione (sola lettura)

Chiave dell'account di servizio tk-play-pubblica: variabile PLAY_JSON (contenuto) o file ~/.tk-play/tk-play-pubblica.json.
Se il codice di versione è già su Play non fa niente (un push senza versione nuova non crea release).
Moduli: pyjwt, cryptography (requests non serve)."""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt

API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
CARICA = "https://androidpublisher.googleapis.com/upload/androidpublisher/v3/applications"


def chiave():
    testo = os.environ.get("PLAY_JSON") or open(os.path.expanduser("~/.tk-play/tk-play-pubblica.json"), encoding="utf-8").read()
    return json.loads(testo)


def gettone():
    k = chiave()
    ora = int(time.time())
    asserzione = jwt.encode({"iss": k["client_email"], "scope": "https://www.googleapis.com/auth/androidpublisher",
                             "aud": k["token_uri"], "iat": ora, "exp": ora + 3600}, k["private_key"], algorithm="RS256")
    corpo = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": asserzione}).encode()
    return json.load(urllib.request.urlopen(k["token_uri"], corpo, timeout=30))["access_token"]


TOK = None


def chiama(metodo, url, corpo=None, dati=None, tipo="application/json"):
    global TOK
    TOK = TOK or gettone()
    if corpo is not None:
        dati = json.dumps(corpo).encode()
    r = urllib.request.Request(url, data=dati, method=metodo, headers={"Authorization": "Bearer " + TOK, "Content-Type": tipo})
    try:
        with urllib.request.urlopen(r, timeout=600) as risposta:
            testo = risposta.read()
            return json.loads(testo) if testo.strip() else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Google Play: {metodo} {url.split('/applications/')[-1]} -> {e.code}\n{e.read().decode()[:1500]}")


def stato(pacchetto):
    e = chiama("POST", f"{API}/{pacchetto}/edits", {})["id"]
    try:
        for t in chiama("GET", f"{API}/{pacchetto}/edits/{e}/tracks/production").get("releases", []):
            print(t.get("status"), t.get("name"), t.get("versionCodes"))
    finally:
        chiama("DELETE", f"{API}/{pacchetto}/edits/{e}")


def carica(pacchetto, aab, note):
    e = chiama("POST", f"{API}/{pacchetto}/edits", {})["id"]
    try:
        b = chiama("POST", f"{CARICA}/{pacchetto}/edits/{e}/bundles?uploadType=media", dati=open(aab, "rb").read(),
                   tipo="application/octet-stream")
    except SystemExit as errore:
        chiama("DELETE", f"{API}/{pacchetto}/edits/{e}")
        if "already" in str(errore).lower():  # «Version code N has already been used»
            print("versione già su Google Play: niente da caricare")
            return
        raise
    codice = int(b["versionCode"])
    # nome come quelli fatti a mano nella Console: «39 (1.0.38)»; TK_VERSIONE = numero di pubspec senza +build
    nome = f"{codice} ({os.environ['TK_VERSIONE']})" if os.environ.get("TK_VERSIONE") else str(codice)
    chiama("PUT", f"{API}/{pacchetto}/edits/{e}/tracks/production", {"track": "production", "releases": [{
        "name": nome, "versionCodes": [str(codice)], "status": "completed",
        "releaseNotes": [{"language": "it-IT", "text": note[:500]}]}]})
    # changesNotSentForReview=false: le modifiche partono subito per la revisione di Google
    chiama("POST", f"{API}/{pacchetto}/edits/{e}:commit?changesNotSentForReview=false")
    print(f"Google Play: {nome} (codice {codice}) caricata e inviata in revisione")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[2] == "--stato":
        stato(sys.argv[1])
    elif len(sys.argv) == 4:
        carica(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(__doc__)
