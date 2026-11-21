#!/usr/bin/env python3
"""Controllo quotidiano: ogni app TK deve avere la stessa versione su main, Google Play e App Store.
Una versione in revisione conta come allineata. Avvisa su Telegram solo se qualcosa non va
(versione rimasta indietro, compilazione fallita, app respinta da Apple).

uso: controlla.py            stampa il resoconto e avvisa su Telegram se serve
     controlla.py --muto     solo resoconto
Gira sul box (attività pianificata «TK-controlla-app», ogni mattina): chiavi in ~/.tk-play e ~/.appstoreconnect,
Telegram da ~/.claude/tk-telegram.json, gh già collegato."""
import json
import os
import re
import subprocess
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")  # console di Windows (cp1252): la freccia «↳» la faceva fermare

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUI)
import ios_invia  # noqa: E402
import play_carica  # noqa: E402

# app: (repo, pacchetto Android, id Apple)
APP = {
    "tk-pdf": ("tk-pdf-app", "it.pietrodefilippis.tkpdf", "6829887886"),
    "tk-foto": ("tk-foto-app", "it.pietrodefilippis.tkfoto", "6829888740"),
    "tk-acconti": ("tk-acconti-app", "it.pietrodefilippis.tkacconti", "6829888434"),
    "tk-clienti": ("tk-clienti-app", "it.pietrodefilippis.tkclienti", "6829888913"),
    "tk-ftp": ("tk-ftp-app", "it.pietrodefilippis.tkftp", "6829888868"),
    "tk-iscrizioni": ("tk-iscrizioni-app", "it.pietrodefilippis.tkiscrizioni", "6829889179"),
    "tk-desk": ("tk-desk-app", "it.pietrodefilippis.tkdesk", "6829889038"),
    "tk-tv": ("tk-tv-app", "it.pietrodefilippis.tktv", "6829889330"),
    "tk-pietro": ("tk-pietro-app", "it.pietrodefilippis.tkpietro", "6829889095"),
    "triburba": ("triburba-app", "it.triburba.app", "6832613390"),
}
# su App Store non ancora uscite: la prima pubblicazione resta a mano (serve il video per i revisori)
PRIMA_VOLTA_APPLE = {"tk-foto": "prima pubblicazione su App Store ferma: serve il video su un iPhone con iOS 17"}
VALIDI_APPLE = ("READY_FOR_SALE", "WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_DEVELOPER_RELEASE",
                "PENDING_APPLE_RELEASE", "PROCESSING_FOR_APP_STORE", "READY_FOR_DISTRIBUTION")


def main_versione(repo):
    t = urllib.request.urlopen(f"https://raw.githubusercontent.com/tecnikgeek-repo/{repo}/main/pubspec.yaml", timeout=30).read().decode()
    v, b = re.search(r"(?m)^version:\s*([0-9.]+)\+(\d+)", t).groups()
    return v, int(b)


def play(pacchetto):
    play_carica.TOK = play_carica.TOK or play_carica.gettone()
    e = play_carica.chiama("POST", f"{play_carica.API}/{pacchetto}/edits", {})["id"]
    try:
        rel = play_carica.chiama("GET", f"{play_carica.API}/{pacchetto}/edits/{e}/tracks/production").get("releases", [])
    finally:
        play_carica.chiama("DELETE", f"{play_carica.API}/{pacchetto}/edits/{e}")
    codici = [int(c) for r in rel for c in r.get("versionCodes", [])]
    return max(codici) if codici else 0, ", ".join(r.get("name", "") for r in rel)


def apple(app_id):
    return [(v["attributes"]["versionString"], v["attributes"]["appStoreState"]) for v in ios_invia.versioni(app_id)]


def ultima_esecuzione(repo, workflow):
    r = subprocess.run(["gh", "run", "list", "-R", f"tecnikgeek-repo/{repo}", "-w", workflow, "-b", "main", "-L", "1",
                        "--json", "conclusion,status,url"], capture_output=True, text=True, encoding="utf-8")
    d = json.loads(r.stdout or "[]")
    return d[0] if d else None


def telegram(testo):
    c = json.load(open(os.path.expanduser("~/.claude/tk-telegram.json"), encoding="utf-8"))
    corpo = json.dumps({"chat_id": c["chat_id"], "text": testo, "disable_web_page_preview": True}).encode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{c['token']}/sendMessage", corpo,
                                                  headers={"Content-Type": "application/json"}), timeout=30)


def controlla():
    problemi, righe = [], []
    for nome, (repo, pacchetto, app_id) in APP.items():
        try:
            v, b = main_versione(repo)
            codice_play, nome_play = play(pacchetto)
            vers_apple = apple(app_id)
        except (Exception, SystemExit) as e:  # una app che non risponde non deve fermare le altre
            problemi.append(f"{nome}: controllo non riuscito ({str(e)[:150]})")
            continue
        stato_apple = next((s for vs, s in vers_apple if vs == v), None)
        righe.append(f"{nome}: main {v}+{b} · Play {nome_play or '-'} · Apple {', '.join(f'{x} {y}' for x, y in vers_apple[:2])}")
        if codice_play < b:
            problemi.append(f"{nome}: Google Play è indietro (codice {codice_play}, main {v}+{b})")
        elif codice_play > b:
            problemi.append(f"{nome}: Google Play ha un codice più alto di main ({codice_play} > {b}): main va alzato")
        if nome in PRIMA_VOLTA_APPLE and not any(s == "READY_FOR_SALE" for _, s in vers_apple):
            righe.append(f"   ↳ {PRIMA_VOLTA_APPLE[nome]}")
        elif stato_apple in ("REJECTED", "METADATA_REJECTED", "INVALID_BINARY"):
            problemi.append(f"{nome}: Apple ha respinto la {v} ({stato_apple}): leggere il Centro risoluzioni")
        elif stato_apple not in VALIDI_APPLE:
            problemi.append(f"{nome}: App Store è indietro (main {v}, Apple {vers_apple[0][0] if vers_apple else '-'} {vers_apple[0][1] if vers_apple else ''})")
        for wf in ("play.yml", "ios.yml"):
            u = ultima_esecuzione(repo, wf)
            if u and u.get("conclusion") == "failure":
                problemi.append(f"{nome}: ultima compilazione {wf} FALLITA {u['url']}")
    return problemi, righe


if __name__ == "__main__":
    problemi, righe = controlla()
    print("\n".join(righe))
    if problemi:
        print("\nDA SISTEMARE:\n" + "\n".join(problemi))
        if "--muto" not in sys.argv:
            telegram("📱 App TK non allineate\n\n" + "\n".join("• " + p for p in problemi) +
                     "\n\nCorreggere da una chat: «allinea le app».")
    else:
        print("\nTutto OK: stessa versione su main, Google Play e App Store.")
