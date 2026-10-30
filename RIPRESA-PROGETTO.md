# Ripresa del progetto: PDF Translate (fork italiano)

Ultimo aggiornamento: 30/10/2026. Questo file riassume dove si è arrivati, come
riprendere il lavoro e cosa resta da fare. Va aggiornato a ogni sessione.

## In breve

- **Cos'è:** fork di [breslee1707/VI-Translate](https://github.com/breslee1707/VI-Translate)
  (traduttore di PDF che conserva l'impaginazione, licenza AGPL-3.0).
- **Il fork:** [ganzo-ok/VI-Translate](https://github.com/ganzo-ok/VI-Translate), ramo `main`.
- **Obiettivo del proprietario:** interfaccia in italiano e traduzione affidabile di
  documenti tecnici lunghi (es. guida ISPE HVAC, 288 pagine) verso l'italiano.
- **Il proprietario** è poco pratico di programmazione: spiegazioni in italiano,
  passo per passo, niente gergo. Vuole una conferma prima di ogni pubblicazione.

## Dove si trova tutto (su questo PC)

| Cosa | Percorso |
|---|---|
| Codice del fork | `D:\Traduttore\VI-Translate` |
| Eseguibile pronto | `D:\Traduttore\VI-Translate\dist\PDFTranslate\PDFTranslate.exe` |
| Zip da distribuire | `D:\Traduttore\VI-Translate\dist\PDFTranslate-windows.zip` (322 MB) |
| Glossario in uso | `D:\Traduzioni\glossario.csv` (copia nel repo: `glossari/hvac-camere-bianche-en-it.csv`) |
| Documenti di prova | `D:\Traduzioni\` (risultati in `D:\Traduzioni\translated\`) |
| Impostazioni dell'app | `%LOCALAPPDATA%\PDFTranslate\settings.json` (contiene la chiave DeepL in chiaro) |
| Memoria traduzioni e blocchi Google | `%USERPROFILE%\.cache\pdf2zh\` (`cache.v1.db`, `google-api-block.json`) |
| Vecchia versione installata (0.2.3) | `C:\Program Files\PDFTranslate-windows` — non usarla insieme alla nuova |

Strumenti: git in `C:\Program Files\Git\cmd\git.exe` (installato con winget, accesso
GitHub salvato da Git Credential Manager); Python 3.12 di sistema per i test;
`.venv` nel repo per la build; Ollama in `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`
con i modelli `gemma3:12b`, `aya-expanse:8b`, `gemma3:4b`.
Remote: `origin` = fork, `upstream` = progetto originale.

## Cosa è stato fatto (commit sul fork, dal più vecchio)

1. `d25157e` — Interfaccia in **italiano**; all'avvio segue la **lingua del sistema**
   (lingue senza traduzione → inglese).
2. `6aac175` — Google tramite **translate.googleapis.com** (`client=gtx`) invece della
   pagina `/m`, che rifiutava questa rete; attesa 1 s tra le richieste; un rifiuto viene
   riprovato dopo 30 s e 90 s prima di fermarsi. **DeepL di scorta**: con una chiave,
   ciò che Google rifiuta va a DeepL. Opzione "Google tramite browser" spenta di default.
3. `960b646` — **Nessun aggiornamento automatico** (`AUTO_UPDATE = False` in
   `app/update.py`); il repository di riferimento è il fork; versione **0.4.1**.
4. `a43281b` — Se tutte le richieste a Google falliscono per motivi inattesi, il documento
   si **ferma dopo 3 errori** (o passa a DeepL) invece di finire tutto in inglese; il file
   `translation-service.log` registra risposte HTTP e tipi di errore (mai il testo).
5. `51d6d7b` — **Traduttore locale** con Ollama (servizio "Su questo PC") e **glossario**
   da file (`termine;traduzione`), usato dal traduttore locale e caricato su DeepL come
   glossario ufficiale. Le tabulazioni dei paragrafi giustificati ora diventano spazi
   (prima le parole tradotte uscivano attaccate).

Dettagli tecnici e motivazioni: `agent-knowledge/pdf-engine.md`, sezione
"Translation Service" (la parte iniziale descrive le scelte di questo fork, che vanno
contro alcune regole dell'autore originale **per decisione esplicita del proprietario**).

## Stato attuale

- **Test:** 537, tutti superati (`python -m unittest discover -s tests -t .`).
  Ruff: restano solo 2 avvisi già presenti nel codice originale.
- **Eseguibile:** costruito con `build.ps1`, smoke test superato, contiene tutte le novità
  ma riporta ancora la versione **0.4.1**.
- **Google:** dal 29/10/2026 rifiuta (HTTP 429) anche `translate.googleapis.com` da questa
  rete, dopo una traduzione di ~950 richieste. Non si sa quando si sblocca.
- **DeepL:** chiave inserita dal proprietario nell'app (non conoscerla, non chiederla in
  chat). Il documento HVAC (~697.000 caratteri) supera i 500.000 caratteri/mese del piano
  gratuito: probabilmente la quota del mese è esaurita o quasi.
- **Locale (Ollama):** funziona. Prova sulle pagine 13, 15, 41 dell'HVAC: buona qualità,
  glossario rispettato. Velocità su RTX 4070 Laptop 8 GB: gemma3:12b ~13 token/s (39% su
  CPU, documento intero stimato ~5 ore), aya-expanse:8b ~43 token/s, gemma3:4b ~74.
  **aya-expanse è solo per uso non commerciale**; Gemma consente l'uso commerciale.
- **In sospeso:** il proprietario deve scegliere il modello locale per tradurre l'intero
  documento HVAC (ultima domanda aperta).

## Cosa resta da fare (in ordine di utilità)

1. Tradurre l'HVAC completo con il modello scelto e controllarne la qualità.
2. **Quadratino prima dei punti elenco**: il PDF usa un simbolo (probabilmente un carattere
   privato del font Symbol) che il font di uscita non sa disegnare.
3. **Testi dentro le figure** (es. "Fresh Air", "Area served by the system") restano in
   inglese: fanno parte del disegno. Valutare l'OCR solo per le figure.
4. Indice e alcune tabelle complesse restano in parte in inglese (scelta dell'app
   originale per non rovinarle): valutare se allentarla.
5. Portare la versione a **0.4.2** (`APP_VERSION` in `app/update.py`) prima di distribuire
   nuove copie.
6. Arricchire il glossario con gli errori trovati nelle traduzioni.
7. Versione Android: **da non toccare** (richiesta esplicita del proprietario).

## Come riprendere il lavoro

```bash
# aggiornare il codice locale
"C:\Program Files\Git\cmd\git.exe" -C D:\Traduttore\VI-Translate pull origin main
# test (Python di sistema)
python -m unittest discover -s tests -t .
# eseguibile Windows (usa .venv; scarica modelli e font la prima volta)
powershell -ExecutionPolicy Bypass -File D:\Traduttore\VI-Translate\build.ps1
# prova da riga di comando con il traduttore locale e il glossario
python -m scripts.translate_pdf "D:\Traduzioni\file.pdf" --output-dir D:\Traduzioni\translated --target-language it --engine local --glossary D:\Traduzioni\glossario.csv --ollama-model gemma3:12b --pages 1-3
```

Prima di una build chiudere l'eseguibile in `dist` (lo script lo chiude da solo) e non
confondere le finestre: la versione nuova mostra "v0.4.1" in alto.

## Controllare le novità dell'autore originale

Il proprietario ha chiesto di farlo **periodicamente, a mano** (niente aggiornamenti
automatici):

```bash
"C:\Program Files\Git\cmd\git.exe" -C D:\Traduttore\VI-Translate fetch upstream
"C:\Program Files\Git\cmd\git.exe" -C D:\Traduttore\VI-Translate log --oneline main..upstream/main
```

Ultimo controllo: 28/10/2026, nessuna novità (ultima versione dell'autore: 0.4.0 del
21/10/2026, già inclusa). Se ci sono novità: riassumerle in italiano, chiedere quali
integrare, fonderle mantenendo le modifiche del fork, rieseguire i test e la build.

## Regole da rispettare

- Ogni push, pubblicazione o rilascio solo con l'assenso del proprietario.
- Non pubblicare versioni con tag `v*` senza richiesta: il fork non ha rilasci.
- Mai scrivere chiavi, password o la chiave DeepL in chat, nei log o nei commit.
- Il PDF di origine non va mai modificato; le traduzioni vanno in `translated\`.
- Fine dei messaggi di commit: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
