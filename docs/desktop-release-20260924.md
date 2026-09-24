# 影片桌面版：百分比、百筆寫入與 Gemini Key 保存

來源 commit：`3f77070`。舊版 `20260922-reviewed` 保留，這次建置 ID 為 `20260924-progress-key`。

## 使用變更

- 影片分析顯示百分比、已完成／總數、未完成數；掃描時進度列保持活動，顯示已入冊影片數。掃描前不知道總數，因此掃描階段不顯示猜測的百分比。
- 建立清冊時每 100 筆影片寫入一次 Excel，結尾寫入剩餘資料。分析時 SQLite 仍逐筆保存，Excel 每 100 筆更新，結束或安全停止時更新餘數。Excel 若被開啟鎖定，分析資料保留在 SQLite，UI 會顯示待同步狀態；請關閉 Excel 後繼續。
- 「設定／更換 Key」把 Key 存於目前 Windows 使用者的 Credential Manager，啟動自動讀取。更換前不會覆蓋；不會寫入 Excel、媒體成果或安裝包。這次沒有將既有對話中的 Key 自動寫入憑證庫。

## 驗證

- `.venv/Scripts/python.exe -m pytest -q -rs`：**300 passed, 2 skipped in 22.90s**。跳過項目為需明確啟用的付費 Gemini 實測、目前 Windows 沒有建立測試 symlink 的權限。
- Windows Credential Manager 以唯一測試目標實際儲存、讀取、更換與刪除，測試結束不留測試 Key。
- `packaging/audit_bundle.py ... --frozen-archive`：`passed: true, findings: []`。完整 manifest **1008 個檔案**大小與 SHA256 已核對。
- `packaging/smoke_desktop.py ... --qa-id progress-key --analyze --uninstall`：隔離安裝、合成影片本機分析、排除照片、Excel 超連結、原始檔雜湊不變、卸載保留成果，全部通過。收據：`build/desktop-acceptance/progress-key/acceptance.json`。
- 控制代理直接啟動本次 portable EXE，目視確認 1080×730 主視窗顯示 `0%　已完成 0 / 0`、Key 狀態和更換按鈕；Key 對話框可開啟並關閉，沒有輸入真實 Key。

| 產物 | 大小 | SHA256 |
| --- | ---: | --- |
| `dist/20260924-progress-key/MediaCatalogVideoDesktop-Setup.exe` | 15478461 bytes | `2CBF64A92DB415487B92BFAE210CAA97CE9FB4A625981380E59F93B711F14709` |
| `dist/20260924-progress-key/MediaCatalogVideoDesktop/MediaCatalogVideoDesktop.exe` | 3454858 bytes | `52F76400524EA37AB0F46E6F433F002E57E5BA92EEA047ED1022FB48E4F22AA6` |

安裝包尚未簽章；尚未在完全乾淨的 Windows 電腦測試首次環境下載，且沒有呼叫付費 Gemini API。
