# 影片資料庫整理桌面版 0.2.0

發布標籤：`video-desktop-v0.2.0`。安裝程式名稱仍為 `MediaCatalogVideoDesktop-Setup.exe`，產品 AppId 保持一致，可更新既有桌面版。舊版 A+ Skill 的安裝位置與捷徑不變。

## 模型選擇

預設本機模型為 `qwen3.5:9b`（Q4_K_M，約 6.6 GB），辨識時關閉 thinking。環境設定與 CLI 使用同一個預設模型常數。指定 `--model Qwen3-vl:8b-instruct` 仍能使用舊模型。

本機實測使用 RTX 5070 12 GB、Ollama 0.34.1，三張相同合成畫面分別包含繁體中文、促銷文字、彩色幾何物件。兩模型均通過 3/3 JSON schema；Qwen3-VL 8B 首張／後兩張耗時 7.11／3.11／3.01 秒，Qwen3.5 9B 關閉 thinking 為 7.25／1.98／1.81 秒。後者在其中一張較少加入預約等畫面外推測。兩者均把棕色圖形描述為紅色，故本測試只支持作為輕量批次預設的選擇，不代表所有題材的準確率排名。

比較腳本：`scripts/benchmark-local-vision.py`；可重跑並保存圖像雜湊、原始分析與時間。此次收據位於本機 `build/model-comparison-20260930/results.json`。

Gemini 每次執行雲端分析前，查詢模型清單並選擇可用的最新正式一般用途 Flash；2026-09-30 查詢結果為 `gemini-3.8-flash`。本次未執行付費生成。

## 操作改善

- 總影片完成百分比及本片片段進度分開顯示；片段條表示目前段落以前的完成比例，不表示當段推論內部的百分比。
- Excel 每 100 筆同步，完成或安全停止時同步餘數；採串流重建以降低記憶體使用，保留超連結、人工已審核狀態、下拉選單與原子替換。
- 新建清冊採 `資料夾名稱_媒體清冊.xlsx`；已有舊版 `媒體清冊.xlsx` 時沿用。
- Key 一次儲存在 Windows Credential Manager。檢查 Key 按鈕只查模型清單，不送出媒體，亦不保證生成額度或計費可用。

## 驗證與邊界

完整測試：**306 passed, 2 skipped**。略過項目為未啟用付費 Gemini live 測試，以及 Windows 建立目錄 symlink 權限不足。

建置與驗證命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-desktop.ps1 -BuildId 20260930-v020
.venv/Scripts/python.exe packaging/smoke_desktop.py dist/20260930-v020 --qa-id v020-20260930 --analyze --uninstall
```

安裝包為輕量版，不含模型、媒體或使用者 Key。首次環境下載仍需網路；尚未在另一台完全乾淨的 Windows 實機驗證全部下載流程，EXE 未數位簽章。

## 最終安裝包與驗收

建置來源 commit：`dc78326`。輸出：`dist/20260930-v020/MediaCatalogVideoDesktop-Setup.exe`，15,482,115 bytes。

SHA256：`41091B0FAB9E7F6AE42136FD8357E9298774C950F9B57A29B5DB07AC0B207003`。

Expanded frozen archive audit 通過，findings 為空；1008 個 manifest 項目的大小與 SHA256 均核對一致。

真實隔離安裝、本機影片分析、QA 解除安裝全部通過。Excel 包含 1 支影片、12 欄與有效來源超連結，未收錄照片；原始影片／照片雜湊前後一致，解除安裝保留來源、整理成果及既有本機工具。收據位於 `build/desktop-acceptance/v020-20260930/acceptance.json`。

實際分析後 Ollama 回報 `qwen3.5:9b`、100% GPU、4096 context、載入大小約 5.5 GB。此數字僅代表本次小型驗收的運行配置；較多縮圖或長上下文的顯存需求可能較高。

原生 Tk 版面所需高度已驗證可容納於最小視窗高度，避免新增進度列擠壓底部按鈕。306 項測試通過，2 項略過。
