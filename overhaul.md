# Logion 2 — Overhaul / Review-Tracking

Stand: 2026-06-09. Konsolidierte Befunde aus vier parallelen Code-Reviews (Backend-Services/Router, RAG/AI, Document-Parsing/Workflows, Frontend). Verifizierte Punkte sind mit ✅ markiert.

**Arbeitsplan:**
- Phase 1 ✅ ABGESCHLOSSEN: Kritische Bugs #1–#10 + toter Code (inkl. Legacy-Translate-Cluster)
- Phase 2 ✅ ABGESCHLOSSEN: #11–#16 alle erledigt (#11: bewusst kein HNSW-Forcing, siehe Befund)
- Phase 3 (nächster Schritt): Detailbefunde (Anhang) — nach Bedarf priorisieren

Legende: `[ ]` offen · `[~]` in Arbeit · `[x]` erledigt

### 🔖 Hier weitermachen
Phase 3 — lohnendste Kandidaten aus dem Anhang:
1. `create_project` löscht Projekt bei Parsing-Fehler (Datenverlust-Risiko, project_service.py:146)
2. Workflow-Locking TOCTOU (segment_service.py:451) — atomares UPDATE/`with_for_update`
3. `metadata_json`-Mutationen ohne `flag_modified` (translate-Pfad ist weg, aber segment_service.py:54 bleibt)
4. Frontend: Load-Race in `useProjectData` (ignore-Flag), API-Client `VITE_API_BASE`
5. `parse_document`-Fallback: unbekannte Endungen klar ablehnen statt DOCX-Crash

**Hinweis:** DB-Migration ausgeführt (halfvec + Indizes, alembic@`f8970d1b1e8e`). `tmp/` ist gitignored (Scratch + Testskripte: `rerank_probe.py`, `test_rerank_e2e.py`, `test_hnsw_correctness.py`).

---

## Phase 1 — Kritische Bugs (#1–#10) + toter Code

### 🔴 Kritische Bugs

- [x] **#1 `Data` statt `data` → NameError** ✅verifiziert
  `backend/app/ai_service.py:562` — Fallback in `improve_narrative_text` crasht selbst (`Data` undefiniert). Fix: `data.get(...)`.

- [x] **#2 Doppelter `except` → `None`-Rückgabe** ✅verifiziert
  `backend/app/ai_service.py:374-378` — `generate_indicator_suggestion`: erster `except` loggt nur ohne return, zweiter unerreichbar. Funktion gibt bei Fehler `None` statt Fallback-Dict. Fix: zusammenführen, return ergänzen.

- [x] **#3 Server-Restart-Deadlock bei `ingesting`** ✅verifiziert
  `backend/app/main.py:23` — Recovery setzt nur `rag_status == "processing"` zurück, Reingest/Reinitialize nutzen `"ingesting"` → Projekt hängt dauerhaft. Fix: `rag_status.in_(["processing", "ingesting"])`.

- [x] **#4 `NameError` im Reingest-Recovery** ✅verifiziert
  `backend/app/workflows/reingest.py:231` — `to_model_class("Project")` existiert nicht; bare `except` (Z.235) verschluckt den NameError → Projekt bleibt in `ingesting`. Fix: `Project` direkt verwenden.

- [x] **#5 Kaputtes Comment-Done-Linking**
  `backend/app/document/parser/main.py:91-108` — markiert zufälligen Kommentar als „erledigt", sobald irgendeiner `done="1"` hat (kein `paraId`-Mapping). Produziert falsche Daten. Fix: korrektes paraId→commentId-Mapping ODER fehlerhaften Block entfernen.

- [x] **#6 Endnote-Übersetzung geht verloren**
  `backend/app/document/assembler/footnotes.py:241` — nutzt `if seg.target_content` statt `is not None` (Footnotes Z.166 korrekt). Leere Endnoten-Übersetzung → fällt auf Quelltext zurück. Fix: `is not None`.

- [x] **#7 Frontend: Prop-Mutationen**
  - `frontend/src/components/ProjectList.jsx:351,359` — `archiveDialog.folderName = …` mutiert Parent-State direkt; Ordnername kann verloren gehen. Fix: über Callback-Argument `onConfirm(folderName)`.
  - `frontend/src/components/segment/hooks/useSegmentMatches.js:18,37` — `.sort()` mutiert `segment.context_matches` in-place. Fix: `[...rawMatches].sort(...)`.

### 🟠 Sicherheit

- [x] **#8 Path Traversal / Filesystem-Enumeration** ✅verifiziert
  `backend/app/routers/settings.py:43-86` — `browse-dirs?path=/etc` listet jedes Server-Verzeichnis; kein Confinement, keine Auth. Fix: auf erlaubten Root (Home/STORAGE_ROOT) per `os.path.commonpath` beschränken, sonst 403.

- [x] **#9 XSS über `formatSourceContent`**
  `frontend/src/utils/editorTransforms.js:123,234` — Textinhalte nicht escaped vor `dangerouslySetInnerHTML`; `<img onerror=…>` aus DOCX/TM wird ausgeführt. `highlightGlossaryTerms` escaped nur `"`. Fix: Textknoten escapen (analog `diffUtils`) / DOMPurify.

- [x] **#10 Interne Fehler an Client geleakt**
  `backend/app/routers/settings.py:107-108,136-137` — `HTTPException(500, detail=str(e))` leakt Pfade/Stacktraces. Fix: generische Meldung + serverseitiges Logging.

### 🧹 Toter / doppelter Code

- [x] **Frontend-Duplikate löschen**
  - `frontend/src/components/SegmentRow.jsx` (310 Z., tot — aktiv ist `segment/SegmentRow.jsx`)
  - `frontend/src/components/AISettingsTab.jsx` (186 Z., tot — aktiv ist `settings/AISettingsTab.jsx`; enthält zweite hardcodierte API_BASE)
  - `frontend/src/components/UploadView.jsx` (tot; importiert nicht-existente `uploadProject`)

- [x] **Backend toter/Legacy-Code**
  - `backend/app/core/database.py` — von nichts importiert, totes Duplikat von `database.py`
  - `backend/app/rag/ingestion.py` — `ingest_project_files`/`embed_project_segments` nirgends aufgerufen; enthält latenten `embed_batch`-Tuple-Bug (Z.166,201,263 entpacken das Tuple nicht). Entfernen ODER reparieren+nutzen.
  - `backend/app/rag/retrieval.py:482-484` — `_rerank` ruft nicht-existente `_rerank_and_score` → garantierter AttributeError. Tot.
  - `backend/app/ai/memory.py`, `backend/app/ai/engine.py` — Legacy-TM (all-MiniLM 384-dim in Vector(2048)-Spalte), nur von `routers/translate.py` referenziert. Prüfen+entfernen.
  - `backend/app/scoring.py` (`ScoringEngine` nirgends importiert), `backend/app/aligner.py` (LaBSE, nicht im aktiven Pfad), `backend/app/parser_helper.py` (`_repair_tags` nirgends importiert) — tot.
  - `backend/app/rag/retrieval.py:41-54` — CrossEncoder (~470 MB) wird geladen, aber nie aufgerufen. Laden entfernen.
  - `backend/app/models.py:133 TranslationMemoryUnit` (`tm_vectors`) — vermutlich durch `TranslationUnit` ersetzt; prüfen.
  - `backend/app/workflows/preload_matches.py:27-51` — tote `pass`-Schleife + Stream-of-Consciousness-Kommentare; ungenutzter `manager`.
  - `backend/app/services/export_service.py:1-24` — doppelte + ungenutzte Imports.

- [x] **Hardcodierter Absolutpfad** `backend/app/main.py:135` — `/Users/beiti/prog/logion2/...` entfernen; ai_models-Lade-Logik auf `config.get_ai_models_config` konsolidieren.

---

## Phase 2 — Performance / Skalierung (#11–#16) — später besprechen

- [x] **#11 ANN-Indizes (halfvec HNSW) — FERTIG, bewusst KEIN Forcing** — Spalten `halfvec(2048)`, HNSW-Indizes gebaut (Migration ausgeführt). **Korrektheitstest gegen echte Daten** (`tmp/score_test/test_hnsw_correctness.py`, 12 Samples über alle Projekte): Die 102-ms-Messung von gestern war die *ungefilterte* Query — die echten App-Queries filtern nach `project_id` und laufen via Btree exakt in ~13 ms. Forciertes HNSW (`iterative_scan=strict_order`) wäre für context_chunks **6× langsamer** (79,6 vs. 12,9 ms — globaler Graph kämpft gegen Projektfilter) bei worst recall 0,95. Planner wählt beim größten Projekt (1.869 Seg.) bereits **von selbst** HNSW. → Planner-Default ist korrekt; Indizes liegen bereit und greifen automatisch mit wachsender Datenmenge. Keine Code-Änderung.
- [x] **#12 DB-Indizes + Alembic — FERTIG** — Alembic eingeführt (`backend/alembic/`, `env.py` an App-`Base`/`engine`, `requirements.in` ergänzt). Migration `f8970d1b1e8e` ausgeführt (alembic_version gestempelt). btree `ix_segments_project_id` + Composite `ix_segments_project_index` **verifiziert genutzt** (Bitmap Index Scan, 1,3 ms statt Seq Scan über 13k Zeilen). Modelle: `Segment.project_id index=True` + `__table_args__`-Composite. `create_all` bleibt für frische DBs; Migration idempotent (`IF NOT EXISTS`).
- [x] **#13 `SegmentRow`-Memoization — FERTIG** — `SplitView.jsx`: (1) `filteredSegments` + Progress-% in `useMemo` (stabilisiert auch den Scroll-Effekt), (2) Handler über Latest-Ref-Pattern (`rowHandlers`, stabile Identität, ruft immer die aktuelle Implementierung — kein Refactor der 3 Hooks nötig), (3) `registerEditor` in `useCallback`, (4) Skalar-Props `generating`/`isFlashing` statt ganzer Maps (durchgezogen bis `SourceColumn`; `ReviewView` angepasst). memo greift jetzt: Chat-Tippen/Logs rerendern keine Zeilen mehr. Build ✅.
- [x] **#14 Fuzzy/TM-Scores — UMGESETZT** (empirisch kalibriert via `tmp/score_test/`)
  - **Cross-lingual-Erkenntnis:** Fuzzy scheidet aus (perfektes DE-Äquivalent fuzzy 49 vs. unverwandtes EN 86). Voyage-Relevance trennt sauber relevant (0,85-0,95) von Müll (0,2-0,35).
  - **Umgesetzt in `retrieval.py`:** (1) Exakt-Hash-Matches markiert (`metadata.exact`) + im Dedup höchste Prio → behalten 100/99/98, werden nie vom Rerank überschrieben. (2) `_rescale_relevance`: Log-Kurve über Band [0,75-0,99]→0-100 (konfigurierbar via `rerank_band_lo/hi`). (3) Längenfaktor + `+2`-Boost + hartcodierter `>35`-Cutoff entfernt. (4) Per-Kategorie-Slider (`threshold_mandatory/optional/tm`) verkabelt — waren vorher **tot** (nur `threshold_internal_tm` kam an). (5) Kein Flat-Fallback 80 mehr — ohne Voyage nur Exakt-Matches.
  - **E2E-verifiziert (echte Voyage):** Exakt=99 geschützt, perfektes Äquiv=86, „anderer Satz, gleiche Orgs"=68 (bei Slider opt≥75 gecuttet), Müll raus.
  - Offen/optional: Band-Grenzen-Slider in der RAG-Settings-UI (aktuell nur via config); interne TM (`search_internal_tm`) bewusst unverändert gelassen (User: erst mal lassen).
  - **Hauptbug:** `retrieve_matches` (`retrieval.py:152`) schickt **alle** Kandidaten durch `_rerank_voyage`, inkl. der exakten Hash-TM-Matches aus `_lookup_tm` (Score 100/99/98). `_rerank_voyage` überschreibt `match.score` (Z.229) → **exakte 100%-Matches zeigen plötzlich den Voyage-Relevance-Score (gedeckelt 99)**, z.B. „78%".
  - **Skalen-Konflation:** Angezeigter Score = Voyage `relevance_score * 100` (semantische Relevanz), NICHT die im CAT-Tool erwartete Fuzzy/Edit-Distance-%. → Zahlen wirken willkürlich.
  - **search_internal_tm:** mischt `fuzz.ratio` (0-100 Edit-Distance) mit Voyage-Relevance im selben Merge+Sort (Z.393) — inkomparabel.
  - **Flat-Fallbacks:** ohne Voyage-Client alle Scores 80 (`:173`) bzw. 60 (`:442`).
  - **Vorschlag (Design, braucht Freigabe):** Voyage nur zum **Finden/Ordnen** der Kandidaten nutzen; **angezeigten Score** als echte Fuzzy-Ratio (`fuzz.WRatio`/`token_sort_ratio` auf tag-strippten Source) berechnen; exakte Matches behalten 100/99/98 (nie überschreiben). Einheitliche, übersetzer-verständliche Skala.
  - O(n²) in `_fuzzy_internal_tm` (Z.413) ist sekundär — User sagt Fuzzy „funktioniert eigentlich gut", Optimierung optional.
- [x] **#15 LLM-Batch-Chunking — FERTIG** — `generate_structured_batch` chunkt jetzt intern (MAX_BATCH_CHUNK=15, deckt alle 3 Call-Sites ab; gefährlichster Pfad war `tasks.py`: ALLE Projektsegmente in einem Prompt). Fehlende/gecrashte Segmente werden per **Bisection-Retry** (bis Tiefe 5, runter bis Solo-Calls) wiederholt — ein „vergiftetes" Segment kann nur noch sich selbst kosten, nicht den Batch. Endgültig fehlende IDs werden explizit geloggt und vom Caller als `error` markiert (sichtbar, nicht still verloren). Mit Mock-LLM verifiziert: Drop-Erkennung, Crash-Isolation, Usage-Summierung.
- [x] **#16 Voyage-Retry/Backoff** — `retrieval.py`. `_voyage_with_retry` mit exponentiellem Backoff um `embed`, `_rerank_voyage`, `_rerank_internal_tm`; transiente Fehler (429/5xx/timeout/connection) bis 3× retry, sonst Re-raise an bestehende Fallbacks. ✅ Import OK.

---

## Phase 3 — Detailbefunde (Anhang)

### Backend Services / Router
- `project_service.py:146-151` — `create_project` löscht gesamtes Projekt bei Parsing-Fehler eines beliebigen Files; verwaiste physische Dateien. → `status="error"` + pro-File try/except.
- `main.py:97-108` — CORS `allow_credentials=True` + Wildcard methods/headers; hardcodierte localhost-Ports. → Origins in Config.
- `routers/translate.py:68-125` — `translate_project`: synchroner Endpoint mit hunderten LLM-Calls, commit alle 10 Segmente, kein Wiederaufsetzpunkt; wirkt redundant zur Workflow-Variante.
- `routers/project.py:81-95` — `get_project` zählt Wordcount bei jedem GET über alle source_contents. → beim Parsen cachen.
- `segment_service.py:54-61` — `get_segments` mutiert `metadata_json` (repetition_count) in read-Pfad ohne `flag_modified`. → nur ins Response-Dict.
- `routers/translate.py:55-58,111-113` — `metadata_json` in-place mutiert ohne `flag_modified` → `ai_reasoning`/`ai_alternatives` evtl. nicht gespeichert.
- `backup_service.py:268-270` — `json.loads(raw + '}}]}]}]}]}')`-Hack, Ergebnis ungenutzt (toter Code).
- `backup_service.py:367-423` — Restore in einer Riesen-Transaktion; Glossar/UsageLog referenzieren ungeflushte Segmente. → `flush()` nach Segment-Insert.
- `models.py:208` — `AiUsageLog.segment_id` FK ohne `ondelete` → manuelles Vorab-Löschen überall nötig. → `ondelete="SET NULL"`.
- `routers/segment.py:77-80` — `update_segment` gibt `segment.__dict__.copy()` zurück, umgeht Pydantic-Schema; kein `response_model`.
- Diverse `bare except:` (`config.py:25`, `glossary_service.py:21`, `scoring.py:68`, `rag/ingestion.py:32`, `rag/retrieval.py:310`, `reingest.py:235,406`, `document/utils.py:14`).
- `schemas.py:55-67 ProjectListResponse` — `filename`/`status` doppelt definiert.
- `project_service.py:20-21` — `os.makedirs(UPLOAD_DIR)` als Import-Seiteneffekt, CWD-abhängig; `uploads/` vs `projectdata/` inkonsistent.
- `backup_scheduler.py:11-46` — `while True` ohne Task-Handle/Cancel; `interval_minutes` nicht gegen >0 validiert.

### RAG / AI
- `ai_service.py`, `inference.py`, `auto_glossary.py` — `genai.configure()` global/prozessweit, fragil.
- Inkonsistente Retry-Counts (chat=2 vs gen=3), hardcodiert.
- `AiUsageLog` speichert keine berechneten Kosten (`cost`-Spalte auskommentiert); Voyage-Preise fehlen in `ai_models.json`.
- `inference.py:164-186,399-430` — untrusted TM/Glossar/Nachbar-Inhalte roh in Prompt interpoliert (Prompt-Injection); `_build_prompt_content` hat toten Code (`history` berechnet, nie genutzt; `out = system_instruction = …`).
- `assembly.py:103-127` — `context` zurückgegeben während `matches` noch mutiert wird (Aliasing); `gloss_matches` berechnet, nie hinzugefügt.
- `assembly.py:61-62,129-145` — Nachbarn global per `Segment.index` statt pro `file_id` → Kontext über Dateigrenzen.
- Magic Numbers in `retrieval.py`, `scoring.py`, `inference.py`, `assembly.py` → zentrale Config.
- `tmx.py:66-67` — Sprachpaar hardcoded en→de trotz konfigurierbarer Felder.
- `tmx.py:117-156` — blinde Inserts ohne `ON CONFLICT` → Duplikate akkumulieren.

### Document-Parsing / Workflows
- `assembler/main.py` / `parser/main.py` — kein Streaming/Größenlimit, ganzes DOCX + alle Segmente in Memory.
- `assembler/insert.py:79-102` — `inject_into_container` gruppiert alle Segmente pro Container neu, O(N×M). → einmal in `reassemble_docx` berechnen.
- `parser/traverse.py:411-419` — `_cluster_revisions` verwirft Revisionen ohne parsbares Datum → TC-Stages verschwinden still.
- `workflows/base.py:59-62` — `is_cancelled()` ohne None-Check für `self.project` → AttributeError bei gelöschtem Projekt.
- `segment_service.py:451-462` — Workflow-Locking nicht atomar (TOCTOU); zwei parallele Workflows möglich. → `with_for_update()` / conditional UPDATE.
- `assembler/insert.py:87-105` — Hyperlink-Pass-2-Fallback verlinkt evtl. alle Runs.
- `assembler/insert.py:43-46` — fehlende Note-Tags per 50%-Heuristik positioniert (unzuverlässig).
- `assembler/excel.py:49` — Zellen immer mit Space gejoint, verliert Newlines/Struktur.
- `parser/excel.py:64,70,88-89` — Rich-Text/Tags nicht extrahiert (`tags={}`); `quote_prefix`-Check immer False; Imports in Hot-Loop.
- `parser/main.py:23-26` — unbekannte Endungen (.pdf/.rtf/.tmx) blind als DOCX geparst → PackageNotFoundError crasht Workflow. (Kein RTF/PDF-Parser vorhanden, README irreführend.)
- `parser/footnotes.py:50,91` u.a. — `print()` statt Logger, verschluckt alle Footnote-Fehler.
- `parser/traverse.py` — 824 Z., Mehrfachverantwortung → Track-Changes & Tag-Cleanup auslagern.
- `parser/traverse.py:764-822` + `insert.py:117-140` — Tabellen-Iteration 3× dupliziert → `_iter_table_cells`-Helper.
- Magic Numbers (GAP_SECONDS=300, coverage≥0.95, diverse BATCH_SIZE) → zentrale Config.
- `assembler/tags.py:457-461` — `_handle_highlight` immer YELLOW, ignoriert echten Farbwert.
- `workflows/batch_translate.py:183` — falsche Batch-Nummer im Log (äußeres `i`).
- `assembler/main.py:90-93` — `_inject_comments_stub` schreibt Tags als rohen Plaintext.
- `parsing_service.py:40` — Temp-Pfad nur per `project_id` → Kollision bei Parallelität. → `tempfile`/UUID.
- `workflows/export.py:115` — `open("export_error.log","w")` im CWD, Race.

### Frontend
- `useProjectData.js:23-66` — kein Cleanup/Abort in `loadData`; Race beim Projektwechsel/StrictMode. → `ignore`-Flag/AbortController.
- `useProjectData.js` — inkonsistente `getSegments`-Antwortform (`setSegments(s)` vs `segs.segments || segs`).
- `useBlockingTask.js:110` vs `useAIQueue.js:76` — `res.segment` vs `...updated`; eine Stelle merged `undefined`.
- `useProjectWorkspace.js:56-95` — leerer Effekt + konkurrierende Pre-Translate-Mechanismen (Refactoring-Müll).
- Ungenutzte Exports: `handleEditorUpdate`, `savingId`, `setLogs`, `glossaryTerms`.
- `SplitView.jsx:173-186` — Scroll-Effekt mit instabiler `filteredSegments`/`rowVirtualizer`-Dependency.
- `useUIState.js:29` — `log` nicht `useCallback`-stabil; `logs` wächst unbegrenzt (kein Cap).
- Index-Keys: `SourceColumn.jsx:271`, `TargetColumn.jsx:240`, `ChatPanel.jsx:93` → stabile IDs.
- `ReviewView.jsx:42-47,193,231` — Refs per Index gekeyt, Liste änderbar → falsche DOM-Knoten.
- `client.js:1` — hardcodierte `API_BASE`, keine `import.meta.env.VITE_API_BASE`.
- API-Client — keine Request-Cancellation (`AbortSignal`), uneinheitliches Error-Handling, `alert()/confirm()` statt Modals.
- `useProjectData.js:279` — `window.location.href = "/"` statt React-State.
- `SplitView.jsx:275,280` — Progress-Division kann `NaN` ergeben.
- `ReviewView.jsx:10-16` — `decodeEntities` erzeugt `<textarea>` pro Segment pro Render. → memoisieren.

---

## Erledigt-Log

**2026-06-09 — Phase 1 abgeschlossen** (Backend `py_compile` ✅, Frontend `vite build` ✅)
- #1 `ai_service.py` — `Data` → `data` (verifiziert: `data` ist Param)
- #2 `ai_service.py` — doppelten `except` zusammengeführt, `return` ergänzt
- #3 `main.py` — Restart-Recovery auf `rag_status.in_(["processing","ingesting"])`
- #4 `reingest.py` — `to_model_class("Project")` → `Project`; bare `except` → `except Exception`
- #5 `parser/main.py` — echtes `paraId → commentId`-Mapping via `w14:paraId`; fehlerhafte Heuristik entfernt
- #6 `assembler/footnotes.py` — Endnote `is not None` (konsistent mit Footnote)
- #7 `ProjectList.jsx` — `onConfirm(folderName)` statt Prop-Mutation; `useSegmentMatches.js` — `[...rawMatches].sort()`
- #8 `settings.py` — `browse-dirs` auf Home-Root beschränkt (`_is_within_root`/`commonpath`), `parent` geklemmt
- #9 `editorTransforms.js` — `escapeHtmlPreservingTags` in beiden Render-Pfaden, `escapeAttr` für Glossar-Attribute
- #10 `settings.py` — generische 500-Meldungen + `logger.exception`
- Toter Code gelöscht: `components/SegmentRow.jsx`, `components/AISettingsTab.jsx`, `components/UploadView.jsx`, `core/database.py`, `parser_helper.py`
- #Absolutpfad: `main.py` `/config/models` nutzt jetzt `config.get_ai_models_config`; bare `except` in `config.py` gefixt

**2026-06-09 — Legacy-Cluster entfernt** (freigegeben; `app.main` importiert ✅, `compileall` ✅)
- Verifiziert: Frontend ruft nur `/project/segment/{id}/generate-draft`, **kein** Aufruf an `/translate/*` → Router tot.
- Gelöscht: `routers/translate.py` (+ `include_router`-Zeile), `ai/engine.py`, `ai/memory.py`, `ai/__init__.py` (ganzes `ai/`), `scoring.py`, `aligner.py`, `rag/ingestion.py`.
- `models.py` — `TranslationMemoryUnit` entfernt (`tm_vectors`-Tabelle bleibt in bestehenden DBs, harmlos).
- `rag/__init__.py` — toten `generate_segment_draft`-Adapter + `ingest_project_files`-Re-Export entfernt; `.dict()` → `.model_dump()`. `generate_segment_draft_v2` bleibt (Live-Pfad via `segment_service`).
- `rag/retrieval.py` — CrossEncoder-Laden (~470 MB, ungenutzt) + `numpy`-Import + tote `_rerank`-Methode entfernt.
- `preload_matches.py` — tote `pass`-Schleife + ungenutzter `manager` entfernt; **Bugfix**: `retrieve_matches` gibt `(matches, usage)` zurück → jetzt korrekt entpackt (vorher AttributeError → Preload war kaputt); `.dict()` → `.model_dump()`.
- `export_service.py` — duplizierte + ungenutzte Imports bereinigt.
