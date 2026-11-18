# tk-app-store

Script comuni con cui le app TK (tk-pdf, tk-foto, tk-acconti, tk-clienti, tk-ftp, tk-iscrizioni, tk-desk, tk-tv, l'app del blog, triburba) si pubblicano da sole su **Google Play** e **App Store** a ogni versione nuova.

Un push su `main` con un numero di versione nuovo in `pubspec.yaml` fa partire tre compilazioni:

| Workflow | Cosa fa |
|---|---|
| `android.yml` | APK per l'aggiornamento interno |
| `play.yml` | .aab firmato → `play_carica.py` → canale di produzione di Google Play, inviato in revisione |
| `ios.yml` | `ios_invia.py --serve` (salta tutto se la build c'è già) → archivio firmato → TestFlight → `ios_invia.py` → revisione App Store |

Se il numero di versione non cambia, nessuno store riceve niente.

- `play_carica.py`: API di Google Play con l'account di servizio (segreto `PLAY_JSON`).
- `ios_invia.py`: API di App Store Connect (segreti `ASC_KEY_P8`, `ASC_KEY_ID`, `ASC_ISSUER_ID`).
- `note.py`: note di rilascio ricavate dai commit della versione in corso.
- `controlla.py`: controllo quotidiano che `main`, Google Play e App Store abbiano la stessa versione.

Licenza GNU AGPL-3.0 (file `COPYING`), come le app.
