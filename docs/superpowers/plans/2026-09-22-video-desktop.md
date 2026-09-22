# Video Desktop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修復四項可靠性問題，交付易懂、僅分析影片、使用最新正式 Flash 模型的 Windows 輕量安裝版。
**Architecture:** 保留 Python/SQLite/Excel 分析核心與 Tkinter UI；獨立桌面入口支援 frozen worker。安裝包包含 Python runtime，首次啟動導引安裝外部工具與下載本地模型。
**Tech Stack:** Python 3.11+, Tkinter/ttk, SQLite, openpyxl, PyInstaller, Windows installer.

## Global Constraints

- 來源媒體不可修改、搬移或刪除；只分析影片，保留既有圖片成果。
- Gemini 僅使用 API 可用的最新正式 Flash 通用視覺模型；排除 Preview、Experimental、Live、TTS、影像生成與 Flash-Lite；不可靜默退回舊模型。
- 不呼叫付費 API 進行測試；Key 不得放入原始碼、安裝包、日誌或指令列。
- 保留舊版；新產品名稱 Media Catalog Video Desktop；Windows x64；主介面繁體中文。
- 不推送 GitHub；各步驟本機提交。測試先紅後綠，最後完整測試及真實 EXE 啟動驗證。

### Task 1: 四項修復

**Files:** batch_analysis.py, run_state.py, excel_catalog.py, scripts/install-media-inventory-skill.ps1; corresponding tests.
**Interfaces:** Preserve existing APIs. Worker supplied run_id must preserve stop; standalone newly begun run may clear old stop only at explicit resume boundary.
- [ ] Add failing regression tests: supplied stopped force run executes no image calls; resumed force inventory1→2 refreshes totals; malformed XLSX ZIP raises ReviewedPathsError; installer late failure restores existing installation without deleting backup/user data.
```python
assert store.begin_run(root_path=root, video_count=2, image_count=0,
                       total_bytes=20, mode=AnalysisMode.FORCE_GEMINI)[0].total_media == 2
```
- [ ] Run focused pytest; observe failures.
- [ ] Remove unconditional worker clear_stop; update resumed counts transactionally; normalize workbook-load KeyError/ValueError; transactional installer rollback using validated exact paths and rename of failed install, no recursive delete.
- [ ] Run focused and full pytest, commit and report red/green evidence.

### Task 2: Video-only and current stable Gemini

**Files:** scanner.py, bootstrap.py, batch_analysis.py, supervisor.py, force_gemini.py, gemini_client.py, new model_catalog.py, corresponding tests.
**Interfaces:** Optional video_only flag at core APIs preserves legacy generic tests; desktop uses video_only=True end-to-end. model_catalog.select_latest_stable_flash(models) returns explicit model ID or raises GeminiError; discovery uses API models list with pagination and header auth.
- [ ] Add red tests with image+video fixtures: desktop counts, pending/completion/force estimates exclude images but never delete old image records; model candidates gemini-3.7-flash, gemini-3.8-flash, gemini-4.0-flash-preview select gemini-3.8-flash; no stable candidate fails closed; list pagination handled.
```python
assert select_latest_stable_flash([
    {'name':'models/gemini-3.8-flash','supportedGenerationMethods':['generateContent']},
    {'name':'models/gemini-4.0-flash-preview','supportedGenerationMethods':['generateContent']}
]) == 'gemini-3.8-flash'
```
- [ ] Implement numeric version selection limited to general stable Flash IDs, live discovery before each cloud batch, bind explicit ID for batch and persist actual ID without key. Remove force fixed3.7 restriction. Provider error may retain local result but must show cloud failure, never use old-model fallback.
- [ ] Run focused and full tests, commit and report.

### Task 3: Friendly desktop UI and executable entry

**Files:** status_ui.py, supervisor.py, new desktop.py and setup_environment.py; tests.
**Interfaces:** desktop main routes --worker and --catalog commands when frozen, else starts UI; supervisor chooses sys.executable routing accordingly. First-run setup runs outside UI thread with progress and actionable errors.
- [ ] Add red tests for frozen worker arguments, video-only default, setup missing dependencies, status translation.
```python
assert '--worker' in build_worker_command(frozen=True, executable='app.exe', root=root)
```
- [ ] Implement step-oriented UI: folder selection; video count/size; progress/completed/pending; current filename; readable waiting/stopping/error; auto vs Gemini enhance; actual model field; open Excel/results; diagnostics/setup. Never show technical traceback as sole feedback. Disable conflicting actions while busy. Preserve existing stop/resume and confirmation.
- [ ] First-run environment setup checks FFmpeg, Node/npm, Ollama model; explicit user setup button launches downloads/install helpers, no automatic media upload. Bundle core Python dependencies, use user-local app data for tools/settings, no Codex dependency. Key input session-only or Windows secure storage, never plaintext persistence.
- [ ] Run tests and visible UI verification; commit with report.

### Task 4: Build installer and verification

**Files:** packaging/, scripts/build-desktop.ps1, README desktop instructions; packaging smoke tests.
**Interfaces:** MediaCatalogVideoDesktop.exe and MediaCatalogVideoDesktop-Setup.exe under dist; per-user installation, desktop/start-menu shortcuts, uninstaller that preserves media and credentials.
- [ ] Add smoke checks for frozen --help/diagnostics, application package completeness and no keys/private paths.
- [ ] Build with PyInstaller and available reputable Windows installer compiler; download tools only from official distribution. Do not claim signed if unsigned. Do not embed model weights in lite installer.
- [ ] Test real EXE launch plus setup/install into isolated temporary destination, verify installed EXE launches; preserve existing production installation. Run full tests and record SHA256/artifact sizes.
- [ ] Final independent whole-branch review and fix verified blockers. Deliver local installer links, plain-language usage, limitations (unsigned signing/specific clean-machine or paid API checks not performed).
