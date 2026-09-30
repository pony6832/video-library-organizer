---
name: media-inventory
description: Use when the user 貼上單一本機資料夾路徑，或要求整理本機照片、影片、建立媒體清冊、媒體整理成果、預覽描述、亮點或關鍵字。
---

# 媒體資料夾整理

## 核心原則

只處理使用者明確指定的單一根目錄。來源媒體保持原位且不可修改；所有清冊與暫存結果只寫入根目錄下的 `媒體整理成果`。

## 只建立或更新清冊

收到「整理這個資料夾：<path>」或只要求媒體清冊時：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill-root>\scripts\run_media_catalog.ps1" -RootPath '<path>'
```

`<path>` 放在 PowerShell 單引號字串內：路徑中的每個 `'` 必須改寫成兩個 `''`（例如 `D:\Tom's Videos` → `'D:\Tom''s Videos'`），不可改用雙引號，也不可加入其他命令或字元。

將 `MEDIA_CATALOG_READY` 視為完成，並回傳 `catalog=` 指向的 Excel 清冊。若出現 `MEDIA_CATALOG_ERROR`，回報錯誤且不要改用其他根目錄。

## 建立清冊並分析全部待處理媒體

收到「整理並分析這個資料夾：<path>」、要求預覽描述、亮點或關鍵字時：

1. 先執行上方清冊命令，確認 `MEDIA_CATALOG_READY`。
2. 執行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "<skill-root>\scripts\run_media_analysis.ps1" -RootPath '<path>'
   ```

3. launcher 會自動開啟 Media Catalog A+ 單視窗並開始分析，不需要再選資料夾或按開始。
4. 右上角狀態標籤為綠色「執行中」代表 worker 在 15 秒內有心跳；藍色為就緒或已停止，琥珀色為等待（建立清冊、恢復、等待 Excel 關閉），紅色為錯誤或心跳逾時。
5. UI 顯示影片數、影像數、總容量、完成／總數、未完成、目前媒體／片段與該影片 Gemini 強化使用量。
6. `安全停止` 只寫入 SQLite stop request；worker 完成目前片段與 checkpoint 後才退出。關閉視窗時也要使用「安全停止後關閉」，不強制終止正在寫入的 worker。
7. 分析器取得單一批次鎖後執行 Ollama、FFmpeg、Watch／MCP 預檢，並從 SQLite 已完成片段繼續。每支影片最多以 Gemini 3.7 Flash 強化 12 片段／36 張影格，只會傳送縮放預覽與最小分析證據。
8. 只有 `MEDIA_ANALYSIS_READY ... remaining=0 excel_sync_pending=false` 才代表完成。`MEDIA_ANALYSIS_INCOMPLETE` 表示仍有失敗、空白辨識列或 Excel 尚未同步，修正後重新執行同一 launcher 即可繼續。

停在 SQLite 與 Excel 預覽清冊。不要繼續寫入媒體 metadata、Markdown、備份或搜尋索引。

## 桌面獨立使用

使用者不在 Codex 中操作時，可雙擊 Windows 桌面的 `Media Catalog A+ Stable`：

1. 無預設路徑時，UI 狀態為「尚未選擇資料夾」，不啟動 worker。
2. 按「選擇資料夾…」並指定單一根目錄；取消時不建立任何成果。
3. 有效路徑會在背景建立或更新清冊，完成後顯示「清冊就緒，請選擇分析模式」。「分析方式」維持「本機分析」並按「開始／繼續分析」進行一般分析，或依下方流程使用 Gemini 雲端強化。這個等待狀態不是故障。
4. 執行中不可切換路徑；先按「安全停止」，等待 worker 退出後再選擇。

桌面入口不取代 Codex 流程。當 Codex 已提供 `RootPath` 時，launcher 仍直接顯示該路徑並自動開始，不要再次要求使用者選擇。捷徑不得包含 Gemini Key、模型名稱或上次媒體路徑。

## 常見錯誤

- 路徑不存在或指向磁碟根目錄：回報固定錯誤，不建立替代資料夾。
- `MEDIA_ANALYSIS_ERROR`：回報環境、來源驗證、Excel 鎖定或重複批次錯誤；不要繞過 Ollama、FFmpeg、Watch 或版本檢查。
- 同一根目錄不可同時執行兩個分析程序。一般模式中斷後可重新執行分析 launcher；強制 Gemini 中斷則使用下方同模式續跑流程。
- Excel 損壞或缺少必要欄位時停止更新，保留原檔，不可刪除清冊繞過人工審核保護。先請使用者修復或由備份還原 Excel，再續跑。
- Excel 正開啟時分析會繼續寫入 SQLite，UI 顯示「等待 Excel 關閉」；關閉 Excel 後，一般模式按「開始／繼續分析」，強制模式依下方同模式續跑流程。
- Gemini 只從私人環境變數 `GEMINI_API_KEY` 讀取。更換或撤銷金鑰後重新啟動 UI；不要把金鑰寫入指令、Skill、Excel 或專案檔案。

## 換電腦使用

不要直接複製已安裝 Skill 裡的 `.runtime` 或 `.tools`。Python 虛擬環境與 Node 工具包含電腦專屬路徑；每台新電腦都必須從專案原始碼重新執行安裝器。分析前需有 Python 3.11+、Node.js 18+、FFmpeg、Ollama 與 `Qwen3-vl:8b-instruct` 模型。

安裝器使用專案內附驗證器，不需要另裝 Codex 的技能開發工具。Python 必須包含 Tkinter 與 venv，npm 必須可執行；下載 Python／Node 套件仍需要網路。若安裝失敗，回報安裝器列出的備份路徑，不刪除備份。

## 強制 Gemini 強化與續跑

1. 在 UI 選定指定根目錄，等到清冊就緒且沒有 worker 執行，在「分析方式」選「Gemini 雲端強化」後按「開始 Gemini 強化」。此模式會傳送預覽到外部 Gemini API 並可能產生費用；不可把一般整理要求自行升級為強制模式。
2. Key 只從私人 `GEMINI_API_KEY` 讀取；若設定 `GEMINI_MODEL`，目前須為 `gemini-3.7-flash`。不要將 Key 寫入任何檔案或回覆。
3. 確認視窗列出未審核照片／影片、略過的已審核數，以及一般與含重試請求上限。讓使用者確認才啟動；取消不執行。Excel「已審核」的媒體會略過。
4. 中斷後選擇同一根目錄，再在「分析方式」選「Gemini 雲端強化」後按「開始 Gemini 強化」，沿用未完成的強制批次與已鎖定片段。不要改選「本機分析」或使用一般 launcher，那會使用 AUTO 模式。
5. 安全停止會等待目前片段 checkpoint；不要因暫時沒有進度而另開第二個程序。

UI 視窗出現、`UI_STARTED` 或綠色「執行中」均不等於分析完成。桌面模式請確認最終完成狀態、未完成數為 0、Excel 同步完成，並檢查失敗／警告；不可只因啟動命令返回就宣稱完成。強制批次的完成不保證每次雲端辨識成功，失敗與額度警告必須如實回報。
