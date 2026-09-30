# 影片桌面版：Excel 清冊加上資料夾名稱前綴

新建清冊檔名採「`檢測資料夾名稱_媒體清冊.xlsx`」，位於該資料夾的「媒體整理成果」內。例如選擇「完成片段」，輸出為「完成片段_媒體清冊.xlsx」。SQLite 與原始媒體的位置不變。

相容規則：若同一成果目錄已有舊版「媒體清冊.xlsx」，程式繼續使用舊檔，不自動更名或搬移，因此既有 Excel「已審核」狀態和續跑流程維持可用。舊檔不存在時才採用新名稱。

驗證：新目錄檔名、既有舊檔選取、CLI 輸出及舊檔損壞時拒絕覆寫測試通過；完整測試 **301 passed、2 skipped**。兩項略過為付費 Gemini live 測試未啟用，以及 Windows 測試環境沒有建立目錄 symlink 的權限。

安裝包：`dist/20260930-prefixed-catalog/MediaCatalogVideoDesktop-Setup.exe`，15,479,519 bytes，SHA256 `F53A11A8DC45BB1C89026D021580DF7351CF3896DDF180C7164244BC668CCFCB`。expanded frozen audit `passed: true, findings: []`；1008 個 manifest 項目大小與 SHA256 全部核對。

隔離安裝／本機分析／卸載測試：`build/desktop-acceptance/prefixed-catalog/acceptance.json`，成功分析 1 支合成影片、排除照片、Excel 2 列 × 12 欄及超連結有效，原始檔雜湊不變。QA 結果目錄中實際產生 `synthetic-media_媒體清冊.xlsx`。未進行付費 Gemini 呼叫。

本次變更尚未推送 GitHub。既有 2026-09-24 安裝包不含此檔名變更；需使用本次新建安裝包。
