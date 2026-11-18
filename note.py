#!/usr/bin/env python3
"""Note di rilascio dai commit della versione in corso (quelli fatti da quando pubspec.yaml ha il numero attuale).
Va lanciato dentro il repo dell'app, con la storia completa (checkout con fetch-depth: 0).
uso: note.py [massimo caratteri, predefinito 500]"""
import re
import subprocess
import sys


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8").stdout


def versione(rif):
    m = re.search(r"^version:\s*([0-9.]+)", git("show", f"{rif}:pubspec.yaml"), re.M)
    return m.group(1) if m else None


def pulisci(riga):
    riga = re.sub(r"^(iOS|Android|Play|CI)?\s*v?[0-9]+\.[0-9]+\.[0-9]+(\+[0-9]+)?\s*[:\-–]\s*", "", riga.strip())
    riga = riga.replace("[skip ci]", "").strip()
    return riga[:1].upper() + riga[1:] if riga else ""


def main():
    massimo = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    attuale = versione("HEAD")
    righe = []
    for riga in git("log", "-60", "--no-merges", "--format=%H\t%s").splitlines():
        sha, titolo = riga.split("\t", 1)
        if versione(sha) != attuale:
            break
        if re.match(r"^(iOS|CI|Play|Merge)\b", titolo) and not re.search(r"[0-9]+\.[0-9]+\.[0-9]+", titolo):
            continue  # lavori di compilazione, non interessano a chi usa l'app
        t = pulisci(titolo)
        if t and t not in righe:
            righe.append(t)
    righe.reverse()
    righe = righe or ["Miglioramenti e correzioni."]
    testo = "\n".join("• " + r for r in righe)
    if len(testo) > massimo:  # versione corta: senza parentesi, fino al primo «;»
        corte = [re.sub(r"\s*\([^)]*\)", "", r).split(";")[0].strip() for r in righe]
        testo = ""
        for r in corte:
            nuova = (testo + "\n" if testo else "") + "• " + r
            if len(nuova) > massimo:
                break
            testo = nuova
    print(testo or ("• " + righe[-1])[:massimo])


if __name__ == "__main__":
    main()
