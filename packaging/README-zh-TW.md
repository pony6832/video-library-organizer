# 影片資料庫整理 — Windows 輕量桌面版 0.1.0

此版本僅整理與分析影片，不新增或分析照片；原始媒體不搬移、不更名。
不需要 Codex 或另外安裝 Python。支援 Windows 10/11 x64。

## 安裝與使用

1. 執行 MediaCatalogVideoDesktop-Setup.exe，安裝到目前使用者帳號。
2. 從桌面或開始功能表「Media Catalog Video Desktop」啟動。
3. 先按「環境檢查／首次設定」檢查；檢查本身不會下載或分析。
4. 缺少元件時，經你按下安裝才會下載 FFmpeg、Node.js、Ollama、
   MCP Video Analyzer 及 qwen3-vl:8b-instruct 模型（約 6 GB）。
   需要網路與足夠空間，外部元件安裝可能需要 Windows 權限確認。
5. 選擇可讀寫的影片資料夾，等清冊建立後按「開始／繼續分析」。
6. 進度列顯示完成百分比、已完成及未完成數；建立清冊時顯示活動指示與已寫入影片數。
7. 使用「開啟 Excel 清冊」或「開啟成果資料夾」檢閱。分析品質仍需人工確認。

SQLite、Excel 與分析暫存位於所選資料夾內的「媒體整理成果」。
自動分析採本機優先；若不提供 Gemini Key，也沒有環境中的雲端 Key，
不會使用 Gemini。若提供 Key，低信心縮圖可能送至 Gemini 並產生費用。
Gemini 強化會先要求確認；實際模型依 API 當下可用穩定 Flash 清單選擇。
按「設定／更換 Key」輸入一次後，Key 儲存在目前 Windows 使用者的 Credential Manager，
下次啟動自動讀取；需要更換時再按相同按鈕。介面不顯示完整 Key，安裝包、捷徑、
媒體成果及命令列均不含 Key。若 Gemini 回報 Key 無效，請更換後重新執行。

建立清冊或分析時每 100 筆同步一次 Excel；完成或安全停止時同步剩餘筆數。
SQLite 每筆即時保存。Excel 開啟期間 Windows 可能鎖定檔案，請關閉後繼續。

本機模型需 GPU/記憶體資源；速度及可用性取決於設備。
完成之前不要拔除媒體磁碟；可先按「安全停止」等待目前步驟保存。
Excel 若正在開啟可能暫時無法更新；請關閉 Excel 後重試。

## 安全與移除

此安裝包與主程式「未數位簽章」，Windows SmartScreen 可能警告。
請核對來源與 SHA256 後自行決定是否執行；不要關閉防毒防護。
輕量包不含模型、FFmpeg、Node.js、Ollama、API Key 或使用者媒體。
不影響既有 Media Catalog A+ Stable / Codex Skill 安裝。
解除安裝只移除本產品檔案與捷徑，不刪原始影片、整理成果、使用者
憑證、外部工具或 %LOCALAPPDATA%\MediaCatalogVideoDesktop 中的執行資料。

尚未在完全乾淨的 Windows 電腦測試所有首次下載流程；付費雲端呼叫未納入離線驗證。
第三方授權見 THIRD-PARTY-NOTICES.txt 及 _internal/licenses。

## 診斷

可執行主程式加 `--diagnostics C:\任意可寫資料夾\diagnostics.json`。
回傳 0 代表元件就緒；1 代表仍有待設定元件，JSON 提供檢查結果。
GUI EXE 沒有終端輸出，請使用 JSON 檔案查看診斷。
