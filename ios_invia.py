#!/usr/bin/env python3
"""Manda in revisione su App Store la build appena caricata su TestFlight, con l'API di App Store Connect.
Gira nelle GitHub Actions dopo il caricamento; si può lanciare anche a mano.

uso: ios_invia.py <id app Apple> <versione> <build> <novità>   aspetta la build, prepara la versione e invia
     ios_invia.py --serve <id app Apple> <build>                 esce con 0 se la build NON c'è ancora (va compilata)
     ios_invia.py --stato <id app Apple>                         versioni e stati (sola lettura)

Chiave: variabili ASC_KEY_P8 (contenuto), ASC_KEY_ID, ASC_ISSUER_ID; a mano usa ~/.appstoreconnect.
Regole:
- versione già in vendita con lo stesso numero → niente da fare;
- versione in attesa di revisione (WAITING_FOR_REVIEW) più vecchia → si ritira e si sostituisce con la nuova;
- versione IN_REVIEW → si ferma senza errore: ci pensa il prossimo giro (o il controllo quotidiano);
- i dati per i revisori (contatto, account demo, note) si copiano dalla versione precedente."""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import jwt

BASE = "https://api.appstoreconnect.apple.com"


def chiave():
    p8 = os.environ.get("ASC_KEY_P8")
    if p8:
        return p8, os.environ["ASC_KEY_ID"], os.environ["ASC_ISSUER_ID"]
    return (open(os.path.expanduser("~/.appstoreconnect/private_keys/AuthKey_UHQQW6T3UP.p8")).read(),
            "UHQQW6T3UP", "69a6de8f-9a66-47e3-e053-5b8c7c11a4d1")


def gettone():
    p8, kid, iss = chiave()
    ora = int(time.time())
    return jwt.encode({"iss": iss, "iat": ora, "exp": ora + 1100, "aud": "appstoreconnect-v1"}, p8,
                      algorithm="ES256", headers={"kid": kid, "typ": "JWT"})


def api(metodo, percorso, corpo=None):
    for prova in range(6):
        r = urllib.request.Request(BASE + percorso, method=metodo, data=json.dumps(corpo).encode() if corpo else None,
                                   headers={"Authorization": "Bearer " + gettone(), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=60) as risposta:
                testo = risposta.read()
                return risposta.status, (json.loads(testo) if testo.strip() else {})
        except urllib.error.HTTPError as e:
            testo = e.read()
            if e.code >= 500 and prova < 5:
                time.sleep(10)
                continue
            return e.code, (json.loads(testo) if testo.strip() else {})
        except urllib.error.URLError:
            time.sleep(10)
    return 0, {"errore": "rete"}


def chiama(metodo, percorso, corpo=None):
    s, d = api(metodo, percorso, corpo)
    if s not in (200, 201, 204):
        raise SystemExit(f"App Store Connect: {metodo} {percorso} -> {s}\n{json.dumps(d, ensure_ascii=False)[:1500]}")
    return d


def build(app, numero):
    d = chiama("GET", f"/v1/builds?filter[app]={app}&filter[version]={numero}&limit=5")["data"]
    return d[0] if d else None


def versioni(app):
    return chiama("GET", f"/v1/apps/{app}/appStoreVersions?limit=10&fields[appStoreVersions]=versionString,appStoreState")["data"]


def stato(app):
    for v in versioni(app):
        print(v["attributes"]["versionString"], v["attributes"]["appStoreState"])


def aspetta_build(app, numero):
    for _ in range(90):  # fino a 45 minuti: Apple elabora la build dopo il caricamento
        b = build(app, numero)
        stato_b = b["attributes"]["processingState"] if b else "non ancora visibile"
        if stato_b == "VALID":
            return b
        if stato_b in ("FAILED", "INVALID"):
            raise SystemExit(f"Apple ha scartato la build {numero}: {stato_b}")
        print("build", numero, stato_b, "…", flush=True)
        time.sleep(30)
    raise SystemExit(f"La build {numero} non è pronta dopo 45 minuti")


def ritira_invii(app):
    for s in chiama("GET", f"/v1/reviewSubmissions?filter[app]={app}&filter[state]=WAITING_FOR_REVIEW,READY_FOR_REVIEW,UNRESOLVED_ISSUES")["data"]:
        chiama("PATCH", f"/v1/reviewSubmissions/{s['id']}", {"data": {"type": "reviewSubmissions", "id": s["id"], "attributes": {"canceled": True}}})
        print("invio precedente ritirato", s["id"])
    for _ in range(40):
        if not chiama("GET", f"/v1/reviewSubmissions?filter[app]={app}&filter[state]=CANCELING,WAITING_FOR_REVIEW,READY_FOR_REVIEW")["data"]:
            return
        time.sleep(15)
    raise SystemExit("Apple non ha ancora chiuso l'invio precedente")


def dettagli_revisione(versione, precedente):
    s, d = api("GET", f"/v1/appStoreVersions/{versione}/appStoreReviewDetail")
    if s == 200 and d.get("data"):
        return
    if not precedente:
        raise SystemExit("Mancano i dati per i revisori e non c'è una versione precedente da cui copiarli")
    vecchi = chiama("GET", f"/v1/appStoreVersions/{precedente}/appStoreReviewDetail")["data"]["attributes"]
    campi = {k: vecchi.get(k) for k in ("contactFirstName", "contactLastName", "contactPhone", "contactEmail",
                                         "demoAccountName", "demoAccountPassword", "demoAccountRequired", "notes")
             if vecchi.get(k) is not None}
    chiama("POST", "/v1/appStoreReviewDetails", {"data": {"type": "appStoreReviewDetails", "attributes": campi,
           "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": versione}}}}})
    print("dati per i revisori copiati dalla versione precedente")


def pulisci(testo):
    # Apple rifiuta simboli ed emoji nelle «Novità» (409 INVALID_CHARACTERS, es. «✕»): croci → «X», altri simboli via
    import unicodedata
    testo = re.sub("[✕✖✗✘×]", "X", testo)
    testo = "".join(ch for ch in testo if unicodedata.category(ch) != "So" and ord(ch) <= 0xFFFF)
    # Guideline 2.3.10 (tk-pdf 1.7.10 respinta il 18/11/2026): niente Google Play, Android, APK nelle «Novità».
    # Si toglie il pezzo di frase (fra «;») che li nomina; se la riga resta vuota sparisce.
    terzi = re.compile(r"google\s*play|play\s*store|android|\bapk\b", re.I)
    righe = []
    for riga in testo.splitlines():
        punto = "• " if riga.lstrip().startswith("•") else ""
        pezzi = [p.strip() for p in riga.lstrip("• ").split(";") if p.strip() and not terzi.search(p)]
        if pezzi:
            frase = "; ".join(pezzi)
            righe.append(punto + frase[:1].upper() + frase[1:])
    return "\n".join(righe) or "• Miglioramenti e correzioni."


def novita(versione, testo):
    testo = pulisci(testo)
    for loc in chiama("GET", f"/v1/appStoreVersions/{versione}/appStoreVersionLocalizations")["data"]:
        chiama("PATCH", f"/v1/appStoreVersionLocalizations/{loc['id']}", {"data": {
            "type": "appStoreVersionLocalizations", "id": loc["id"], "attributes": {"whatsNew": testo[:4000]}}})


def invia(app, numero, n_build, testo):
    tutte = versioni(app)
    in_vendita = next((v for v in tutte if v["attributes"]["appStoreState"] == "READY_FOR_SALE"), None)
    gia = next((v for v in tutte if v["attributes"]["versionString"] == numero and v["attributes"]["appStoreState"] in (
        "READY_FOR_SALE", "WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_DEVELOPER_RELEASE", "PENDING_APPLE_RELEASE",
        "PROCESSING_FOR_APP_STORE", "READY_FOR_DISTRIBUTION")), None)
    if gia:
        print(f"App Store: {numero} è già {gia['attributes']['appStoreState']}: niente da fare")
        return
    if any(v["attributes"]["appStoreState"] == "IN_REVIEW" for v in tutte):
        print("::warning::App Store: c'è una versione IN REVISIONE in questo momento; la", numero, "si manda al prossimo giro")
        return
    b = aspetta_build(app, n_build)
    aperta = next((v for v in tutte if v["attributes"]["appStoreState"] in (
        "PREPARE_FOR_SUBMISSION", "WAITING_FOR_REVIEW", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED", "INVALID_BINARY")), None)
    if aperta and aperta["attributes"]["appStoreState"] == "WAITING_FOR_REVIEW":
        ritira_invii(app)
    if aperta:
        ver = aperta["id"]
        if aperta["attributes"]["versionString"] != numero:
            chiama("PATCH", f"/v1/appStoreVersions/{ver}", {"data": {"type": "appStoreVersions", "id": ver, "attributes": {"versionString": numero}}})
    else:
        ver = chiama("POST", "/v1/appStoreVersions", {"data": {"type": "appStoreVersions",
              "attributes": {"platform": "IOS", "versionString": numero, "releaseType": "AFTER_APPROVAL"},
              "relationships": {"app": {"data": {"type": "apps", "id": app}}}}})["data"]["id"]
        print("versione", numero, "creata")
    chiama("PATCH", f"/v1/appStoreVersions/{ver}/relationships/build", {"data": {"type": "builds", "id": b["id"]}})
    dettagli_revisione(ver, in_vendita["id"] if in_vendita else None)
    if not in_vendita:
        # prima pubblicazione: Apple vuole il video dell'app sul telefono (Guideline 2.1), l'invio resta a mano
        print(f"::warning::App Store: {numero} pronta con la build {n_build}, ma è la PRIMA pubblicazione: "
              "serve il video per i revisori, invio a mano (dev/app-store/strumenti/ripresenta.py invia)")
        return
    novita(ver, testo)
    ritira_invii(app)  # un invio in bozza rimasto aperto impedisce di crearne uno nuovo
    sub = chiama("POST", "/v1/reviewSubmissions", {"data": {"type": "reviewSubmissions", "attributes": {"platform": "IOS"},
          "relationships": {"app": {"data": {"type": "apps", "id": app}}}}})["data"]["id"]
    chiama("POST", "/v1/reviewSubmissionItems", {"data": {"type": "reviewSubmissionItems", "relationships": {
        "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": sub}},
        "appStoreVersion": {"data": {"type": "appStoreVersions", "id": ver}}}}})
    for prova in range(10):  # subito dopo aver legato la build Apple risponde 409 per qualche minuto
        s, r = api("PATCH", f"/v1/reviewSubmissions/{sub}", {"data": {"type": "reviewSubmissions", "id": sub, "attributes": {"submitted": True}}})
        if s in (200, 201):
            print(f"App Store: {numero} (build {n_build}) inviata in revisione")
            return
        if s != 409 or prova == 9:
            raise SystemExit(f"App Store: invio -> {s}\n{json.dumps(r, ensure_ascii=False)[:1500]}")
        time.sleep(60)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--serve"]:
        sys.exit(1 if build(a[1], a[2]) else 0)
    elif a[:1] == ["--stato"]:
        stato(a[1])
    elif len(a) == 4:
        invia(*a)
    else:
        raise SystemExit(__doc__)
