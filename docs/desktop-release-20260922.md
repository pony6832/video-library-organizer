# Windows 影片桌面版 0.1.0 — 2026-09-22 封裝驗證

## 最新審查修正版：20260922-reviewed

目前預設下載／安裝產物為 reviewed，不是下方保留的歷史 final。
應用程式及封裝來源：`0a42c2528f4618f40e1113debbc8a80c5fa81520`；建置時 tracked tree 乾淨。
本次共用 MCP 就緒檢查核對 shim、package name、0.8.0 版本、JSON 及 dist/index.js；
不完整工具安裝會保留唯一備份後 fresh install，修復拒絕 reparse point。
AUTO 模型探索成功但生成失敗，現在保留本機結果，同時持久化 Gemini 警告與失敗／降級數。
無 Key、單純低信心或本機請求額度限制，不算供應商失敗。

| 產物（相對工作目錄） | bytes | SHA256 |
| --- | ---: | --- |
| `dist/20260922-reviewed/MediaCatalogVideoDesktop-Setup.exe` | 15471502 | `6F8759DF3B46C881797350CDE3F94D5A23553335E7C8D4F94070EF4F04BF5782` |
| `dist/20260922-reviewed/MediaCatalogVideoDesktop/MediaCatalogVideoDesktop.exe` | 3446450 | `C845AEAB64BD123A7C10841CBA3E6B40DF0D29E39F155FF3006A5EAF3AA2403A` |

onedir：1007 檔、46018771 bytes；完整檔案清單 `dist/20260922-reviewed/SHA256.json`。
兩個 EXE Authenticode 均為 `NotSigned`。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-desktop.ps1 -BuildId 20260922-reviewed
.venv/Scripts/python.exe packaging/audit_bundle.py dist/20260922-reviewed/MediaCatalogVideoDesktop --frozen-archive
.venv/Scripts/python.exe packaging/smoke_desktop.py dist/20260922-reviewed --qa-id reviewed --analyze --uninstall
.venv/Scripts/python.exe -m pytest -q -rs
```

建置內已執行 expanded frozen archive audit：`passed: true, findings: []`。
另獨立重跑相同 audit 亦通過。新版 portable 診斷為 `ready=true`，所有元件 true。
reviewed 真實隔離安裝、本機合成影片分析、解除安裝全部通過，收據：
`build/desktop-acceptance/reviewed/acceptance.json`。只有 1 支影片入冊、0 照片，
Excel 2 列 × 12 欄且 C2 超連結存在；影片／照片 SHA256 前後一致。
解除安裝僅移除隔離 QA 程式，原始檔、SQLite、Excel、既有使用者 MCP 保留。
子程序雲端 Key 已移除；無付費 API 呼叫。reviewed GUI 視覺驗收由控制代理獨立執行，
本段不以歷史 final GUI 截圖冒充新版檢查。
最終完整 pytest：**295 passed, 2 skipped in 20.83s**。
兩項跳過明確為 Gemini live explicit opt-in，以及 Windows 建立目錄 symlink 缺權限（WinError 1314）；
不是兩項外部整合 opt-in，也沒有跳過 native Tk。MCP 安全修復另用不需該權限的實際 junction 測試，2 項通過。

## 歷史產物與來源：20260922-final（保留，不覆寫）

控制代理最終獨立驗收：reviewed 原生 EXE 主視窗 1080×730，所有控制項清楚可讀、無裁切，閒置關閉成功。重新執行完整測試為 **295 passed, 2 skipped in 30.10s**；核對 manifest 全部 **1008** 個檔案大小與 SHA256 一致，expanded frozen audit 再次 `passed: true, findings: []`。最終 scoped re-review 確認兩项 Important 與報告 Minor 均已修復，fix diff 無新增重大問題。以下內容為歷史產物紀錄，不代表目前下載版本。

應用程式來源 commit：`fd5ebe63ca2ea6401c863cfbb883e184d24d6ddc`；
封裝腳本、授權與測試由包含本文件的 Task4 commit 提供。
工作目錄：`C:/Users/pony6832/Documents/ChatGPT/影片照片資料庫整理AGENT/.worktrees/fix-hidden-powershell`。

| 產物（相對上述工作目錄） | bytes | SHA256 |
| --- | ---: | --- |
| `dist/20260922-final/MediaCatalogVideoDesktop-Setup.exe` | 15466938 | `8F4CEFE9F1FBF511415099B4AFFB69E5ADB5D25875F5C5D74E5B4B5CBFDC70D3` |
| `dist/20260922-final/MediaCatalogVideoDesktop/MediaCatalogVideoDesktop.exe` | 3443777 | `6D7B5F5EBA68C8EA4E5E10BA8C86AA48C944B041B54660CF4A26329529094A9A` |

完整 onedir 為 1007 檔、46016098 bytes；搬移時必須保留 `_internal`。
全檔雜湊位於 `dist/20260922-final/SHA256.json`。
兩個 EXE 的 Authenticode 狀態均為 `NotSigned`，不能宣稱已簽章。

## 可重跑命令

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-desktop.ps1 -BuildId 20260922-final
.venv/Scripts/python.exe packaging/audit_bundle.py dist/20260922-final/MediaCatalogVideoDesktop --frozen-archive
.venv/Scripts/python.exe packaging/smoke_desktop.py dist/20260922-final --qa-id final --analyze --uninstall
.venv/Scripts/python.exe -m pytest -q
```

命令實際執行過；重跑需改成新的 BuildId、qa-id（既有目錄明確拒絕覆寫）。
建置工具 Python 3.11.15、PyInstaller 6.22.3、hooks 2026.7、Inno Setup 6.7.3。
腳本不清理、不刪舊 build/dist；拒絕輸出目錄 reparse point，不含自動下載編譯器。
runtime：openpyxl 3.1.5、Pillow 11.3.0、et_xmlfile；沒有開發測試框架、使用者媒體或模型權重。

## 已驗證

- 實際 frozen portable EXE `--help` 正常退出；診斷 JSON `ready=true`，全部外部元件已就緒。
- Inno 每使用者安裝，`/QAINSTALL=1 /NOICONS /TASKS= /VERYSILENT /NORESTART` 安裝至全新隔離 QA 路徑，不建立公用捷徑、不自動啟動、不登錄正式產品解除安裝項目。
- 已安裝 EXE 與 onedir 原檔 SHA256 相同，installed `--help` 成功。
- fresh FFmpeg 3 秒合成影片 + PNG：清冊只有 1 支影片、不新增照片。
- 真正 installed EXE 本機推論完成，狀態 analyzed 且描述非空；執行子程序環境移除雲端 Key，不呼叫付費 API。
- Excel 2 列 × 12 欄，C2 檔案超連結存在。影片與照片原始 SHA256 前後一致。
- final QA 解除安裝成功，僅 QA 程式移除；合成原始檔、SQLite、Excel 以及既有使用者本機 MCP package 保留，雜湊不變。
- 原 A+ Stable / Codex Skill 未被安裝或解除安裝操作指定。
- 控制代理對 rc3 installed EXE 做真實 GUI 檢視：1080×730 主視窗文字和控制項未裁切，Windows 資料夾選擇對話框可開啟，取消回到乾淨閒置狀態；未選取任何使用者媒體。
- final 與 rc3 應用程式碼相同；final 更新的僅第三方說明及打包驗證流程。
- 控制代理另獨立開啟最終 `dist/20260922-final` 的portable EXE直接視覺確認：原生視窗所有控制項清楚可讀，閒置關閉成功；非以rc3視覺結果代替final。
- 重用 BuildId 實際被拒絕（`Build ID already exists`），不覆寫既有產物。
- 封裝稽核 11 項 TDD regression 通過，檢查 runtime、非 lite 資料、假憑證、私有路徑、ZIP 壓縮內容；final EXE 的434個PYZ模組亦解壓掃描通過。

詳細實際 smoke receipts：`build/desktop-acceptance/rc3/acceptance.json`、
`build/desktop-acceptance/final/acceptance.json`（後者包含解除安裝），診斷和安裝log在相同目录。

## 邊界與限制

未在完全乾淨的 Windows 電腦驗證首次下載全部工具；此主機已具備FFmpeg、Node、Ollama、MCP及模型。
未做 Gemini 付費呼叫、SmartScreen/防毒白名單測試、數位簽章或 Windows 10 實機測試。
描述品質需人工審查，合成測試只證明管線與來源保護，不能代表真實題材準確率。
不包含影像原始檔、模型、雲端Key或本機開發路徑。上游 Python/SSL/ffi DLL 含官方
python-build-standalone 編譯時 `Administrator/ADMINI~1` 暫存原始碼路徑；保留供應商DLL不修改，
稽核只對這些精準vendor編譯前綴豁免，並非使用者本機路徑。

PyInstaller 提示的缺少模組主要是平台條件或可選相依（posix、lxml、numpy、olefile等）；
真實 Tk、Excel、影片清冊、擷取與本機推論已驗證。可選影像格式並非此影片專用入口範圍。

Inno compiler 顯示未註冊／Non-commercial use only，未購買商用授權；其附帶license.txt保留。
商業散布前請核對 [Inno 官方授權說明](https://jrsoftware.org/isinfo.php)，此處不代作法律判斷。

完整pytest驗證曾遭同一測試process反覆建立Tk interpreter的間歇錯誤：第一輪251pass/2skip
只有封裝測試假Key字串觸發安全測試（已修正）；第二輪250pass/2skip、2個Tk建立失敗。
兩項失敗各用新process單獨跑通過，實際Tcl檔案存在。主代理另證明12次純Tk及8次
DesktopApplication create/destroy都成功，但pytest仍偶發初始化失敗。
測試專用gc.collect曾使單檔兩輪20/20通過，但完整suite仍失敗；其後關閉自動GC也未解決。
因此移除無效GC方案，**不宣稱GC為已確認根因**。目前4個真實Tk測試各在fresh child
process執行原始assertions，60秒逾時、子程序錯誤完整回傳、無retry/skip，符合產品
每process一個Tk interpreter的使用模式；應用程式runtime完全未變。

歷史 Task4 驗證：`.venv/Scripts/python.exe -m pytest -q` → **252 passed, 2 skipped in 21.67s**；不是最新套件總數。
隨後桌面測試再跑一次 → **20 passed in 4.82s**。最新 skip 原因已更正並記錄於上方 reviewed 節；未用 skip 略過 native Tk。

## Review fix 1：憑證稽核擴充

原稽核只有 Gemini 字串形狀，已擴充代表性 OpenAI `sk-`／`sk-proj-`、Anthropic
`sk-ant-` 形狀，以及 JSON、明確credential欄位的Python字串賦值、dotenv的非空
literal值；支援CRLF與Windows UTF-16的ASCII憑證語法，拒絕`.env.*`設定檔。
正常getenv/environ查詢、空值、只提環境變數名稱不被當作Key。
同樣掃描ZIP/PYZ解壓後內容；報告只輸出檔名，不顯示疑似秘密。

初版擴充規則在供應商binary中誤抓`mask-`後綴和SQLite一般`token='x'`語法；
現以完整token邊界、代表性長度上限及明確credential欄位語境修正，補反例回歸。
不對整個供應商套件或檔案加入憑證豁免。一般小寫parser變數`token`不是必然憑證，
裸`TOKEN`限uppercase dotenv整行或JSON字段；精確getenv語法保留通過。

RED：新增測試先18fail/16pass；邊界反例2fail/34pass；CRLF與quoted dotenv
回歸6fail/38pass。GREEN命令：
`.venv/Scripts/python.exe -m pytest tests/test_desktop_packaging.py tests/test_a_plus_security.py -q`
→ **46 passed in 0.58s**（44封裝＋2原有安全測試）。
再跑上述`audit_bundle.py ... --frozen-archive` → `passed: true, findings: []`。
最終installer/EXE未重建、hash與本文件一致；runtime與封裝內容完全未改。

這是**有範圍的啟發式檢查，不是完整secret scanner**：未知token格式、被混淆或分割的
值、非ASCII憑證、加密／額外巢狀封裝仍可能漏判；不能用通過結果保證任何秘密都不存在。
