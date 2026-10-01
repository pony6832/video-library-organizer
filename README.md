# Video Library Organizer（影片資料庫整理）

為本機影片建立可搜尋的清冊與內容摘要的 Windows 桌面程式。掃描指定資料夾，以本機視覺模型（Qwen3.5 9B，透過 Ollama）
描述每支影片的內容、重點與關鍵字，可選擇用 Gemini 補強；結果寫入來源資料夾下的 `媒體整理成果`（SQLite ＋ Excel）。
原始影片不會被移動、改名或修改 metadata。

> 本倉庫是 [media-catalog-a-plus-stable](https://github.com/pony6832/media-catalog-a-plus-stable) 的後繼版本，保留完整開發歷史。
> 舊名稱「Media Catalog Video Desktop」0.2.0 的使用者可直接安裝本版升級。

## 下載

到 [Releases](https://github.com/pony6832/video-library-organizer/releases) 下載 `VideoLibraryOrganizer-<版本>-Setup.exe`，雙擊安裝，不需要 Python 或 Codex。

- 目前版本：**0.3.0 Beta 1**（預覽版，供測試回饋）
- 安裝在目前使用者帳號，不需系統管理員權限；**未數位簽章**，SmartScreen 出現時按「其他資訊」→「仍要執行」。
- 安裝包不含模型、使用者媒體或 API Key。第一次使用請按右上角「環境設定」→「檢查環境」，
  缺少的工具與約 6.6 GB 本機模型會在你按下「安裝缺少元件」後才下載。
- 操作說明與限制見 [繁體中文桌面版說明](packaging/README-zh-TW.md)。

## 0.3.0 Beta 1 的主要變更

- **新介面**：步驟列（選擇資料夾 → 建立清冊 → 分析 → 檢閱成果）、「下一步」提示、分析方式選項卡
  （本機分析／Gemini 雲端強化，付費選項以琥珀色標示）、有顏色區分的狀態標籤、支援高 DPI。
- **穩定性**：Excel 開著也能繼續分析並於關閉後補寫；單一影片失敗不再被當成當機重啟；
  逾時會一併結束 ffmpeg／node 子程序；UI 不會因資料庫忙碌而凍結。
- **大型資料夾**：重新掃描略過未變動的檔案；進度統計與 Excel 同步不再隨筆數平方成長；
  快剪影片片段數有上限；已刪除、搬走或被取代的影片標為「來源已移除」不再重試，搬移的檔案沿用既有分析。
- **雲端與安全**：Gemini 錯誤分類（額度、Key、內容封鎖、伺服器），永久錯誤不重試、429 依建議退避；
  API Key 不再傳給 npm／winget／ffmpeg 等外部工具。
- **開發**：GitHub Actions CI（ruff ＋ pytest）、版本號單一來源（`pyproject.toml`）。

## 開發與建置

```powershell
uv venv .venv --python 3.11
uv pip install --python .venv\Scripts\python.exe -e ".[test]" pyinstaller==6.22.3
.venv\Scripts\python.exe -m pytest -q --ignore=tests/integration
```

建置安裝包需要 Inno Setup 6（可攜模式放在 `.tools\build\inno`），然後執行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-desktop.ps1 -BuildId <新的ID>
.venv\Scripts\python.exe packaging/smoke_desktop.py dist\<新的ID> --qa-id <新的ID> --analyze --uninstall
```

每次建置使用新的 BuildId，不覆寫舊版本；產物包含 onedir 程式資料夾、安裝程式及 `SHA256.json`。
驗收腳本以 QA 模式安裝（不建立捷徑、不寫入解除安裝紀錄），實際建立清冊與本機分析後再解除安裝。

---

# 舊版：Media Catalog A+ Skill（Codex）

以下為隨倉庫保留的 Codex Skill 版本說明。

## 換電腦安裝

不要複製舊電腦中已安裝 Skill 的 `.runtime` 或 `.tools`。Python 虛擬環境和 Node 工具含有電腦專屬路徑，必須在每一台電腦重新安裝。

新電腦需先準備：

- Python 3.11 以上
- Node.js 18 以上與 `npm.cmd`
- FFmpeg（`ffmpeg -version` 可執行）
- Ollama 與本機模型 `Qwen3-vl:8b-instruct`
- Codex 的 Watch Skill；若 Watch 不可用，安裝器提供的 MCP Video Analyzer 0.8.0 會作為影片備援

在專案根目錄執行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-media-inventory-skill.ps1
```

安裝器會在目前 Windows 使用者的桌面建立或更新唯一一份 `Media Catalog A+ Stable` 捷徑。捷徑只包含已安裝 Skill 的啟動位置，不包含 Gemini Key、模型名稱或媒體路徑。

## 使用方式

### 在 Codex 貼上路徑

可直接在對話輸入：

```text
整理並分析這個資料夾：D:\你的媒體資料夾
```

指令會先建立或更新清冊，再開啟 Media Catalog A+ 狀態視窗。新清冊完成後會顯示「清冊就緒，請選擇分析模式」；普通辨識直接按「開始／繼續分析」，需要雲端加強時在「分析方式」選「Gemini 雲端強化」後按「開始 Gemini 強化」。右上角狀態標籤：綠色「執行中」代表 15 秒內有 worker 心跳；藍色為清冊就緒或已停止，琥珀色為建立清冊、等待 Excel 關閉等等待狀態，紅色為錯誤。視窗上方的步驟列會標示目前進行到「選擇資料夾 → 建立清冊 → 分析 → 檢閱成果」哪一步。詳細說明見 [`docs/media-catalog-a-plus-setup.md`](docs/media-catalog-a-plus-setup.md)。

### 不開 Codex，從桌面啟動

1. 雙擊桌面的 `Media Catalog A+ Stable`。
2. 狀態標籤顯示「尚未選擇資料夾」時，按亮起的「選擇資料夾…」。
3. 選定單一媒體根目錄；UI 會先顯示「正在建立／更新清冊」。
4. 顯示「清冊就緒，請選擇分析模式」後，普通辨識按「開始／繼續分析」；需要指定加強時在「分析方式」選「Gemini 雲端強化」後按「開始 Gemini 強化」（琥珀色代表可能計費）。
5. 強制模式會先列出未審核照片／影片數、正常請求上限與含重試上限；確認後才開始。

取消資料夾選擇不會建立 `媒體整理成果`。分析或清冊掃描進行中不能切換根目錄；先按「安全停止」，等程序退出後才能重新選擇。桌面啟動只顯示 A+ UI，不會顯示 PowerShell 或 Python 黑色終端視窗。

### 普通辨識與強制 Gemini 強化

- 「本機分析」維持本地優先，只在本地結果資訊不足時自動使用 Gemini。
- 「Gemini 雲端強化」會重新分析未審核項目；Excel 已標成「已審核」的列不會重跑。
- 照片每張只傳一張縮放預覽；影片每支最多選 12 個片段，每段只傳 1～3 張縮圖，不上傳完整影片或完整本機路徑。
- Gemini 每次失敗會重試一次；仍失敗時保留本地結果，Excel 顯示「Gemini 強化失敗」供人工確認，不中斷整批。
- API Key 只從私人環境變數讀取，不寫入 Git、Skill、捷徑、Excel、SQLite 或程序參數。

## 如何判讀執行結果

- `MEDIA_ANALYSIS_PROGRESS`：逐項進度，程序仍在執行。
- `MEDIA_ANALYSIS_READY ... remaining=0`：所有清冊項目都有分析結果。
- `MEDIA_ANALYSIS_INCOMPLETE`：仍有失敗或空白辨識列；查看 Excel 的「錯誤原因」，修正後重新執行即可自動重試。
- `MEDIA_ANALYSIS_ERROR`：環境預檢、來源完整性、Excel 鎖定或重複執行失敗。

所有會修改 SQLite／Excel 的命令都會鎖定單一清冊，避免兩個程序同時寫入。若上次異常中斷，重新執行會自動恢復 `processing`、`skipped`、重試 `failed`，並修復舊版狀態已完成但描述／重點／關鍵字不完整的項目。批次結束前會從 SQLite 原子式重建 Excel，因此前一次中止留下的半成品會在重跑時補齊。

## 影像圖書館（清冊檢視面板）

`media_library/` 是一個本機網頁面板，可匯入本程式產生的「媒體清冊」Excel，像影像圖書館的總目錄一樣瀏覽、搜尋、挑選和播放影片。清冊的每個欄位都能直接編輯，修改會即時寫回原始 Excel。啟動方式與功能說明見 [media_library/README.md](media_library/README.md)。

> 注意：本程式批次結束時會從 SQLite 重建 Excel。若用面板改過某份清冊後，又用本程式對同一份清冊重新執行分析，面板寫進 Excel 的修改可能會被覆蓋。面板第一次寫入前，會先把清冊備份到 `media_library/data/backups/`。
