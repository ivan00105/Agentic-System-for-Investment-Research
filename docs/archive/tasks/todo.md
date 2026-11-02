# 開發可視化接入 V1–V5

規格：[plan.md](plan.md)。狀態：**全部尚未執行；沒有派工**。這是接入交付清單，不是第二個 C0–C10 tracker；正式 cutover 後未完成項移入同一任務來源。

## V1 — 隔離 pilot 與工具決定

**依賴：** 記錄當前 dirty baseline；只使用 allowlisted 副本，不改主 checkout、client 設定或 live store。

**預計資源：** `.tmp/visibility-pilot/` 的 source／tooling／測試任務；正式結果 `verification/development/visibility-pilot.json`。

- [ ] 釘選 Backlog／Groma／scanner 實際版本，記錄 Windows／Node 相容性及本機設定；不用 global install、autoCommit、remoteOperations、cross-branch aggregation 或自動 shell hook。
- [ ] Backlog：CLI／UI 共用任務；試自訂 status、owner、AC、dependency、archive gate、雙 editor 變更；證明無外部傳送／runtime 呼叫或意外 Git 操作。
- [ ] Groma：僅掃描允許來源；對照 atlas 檢查 Python／React、模組責任、task pin、dirty diff、draft；記錄未知關係、initial scan／edit 更新成本，分別作 go／no-go。

**證明：** 檢視副本前後檔案／Git diff、binding／network observations、可重現操作紀錄與 inspected captures。原始 C1 hashes 不變。不在計劃階段跑安裝；執行時才按完整計劃操作。若工具原生行為不合，記錄限制，不 fork 或當場改建自製系統。

## V2 — 任務狀態核對與單一來源切換

**依賴：** V1 Backlog go；C0 給文件編輯視窗，不需要重新實作 C1。

**預計檔案：** Backlog config／task files；`STATUS.md`、`docs/workstreams.md`、`docs/integration.md` 的當前狀態責任。保留所有原始需求／AC／歷史紀錄。

- [ ] 先核對 5–8 個代表性 task；既有 C lane／task ID 留在 title／label／brief，不因工具 ID 而重編產品計劃。
- [ ] C1 implemented、另一人 review pending、C0 gate pending、C3 blocked、C5 ready-unassigned、C6 partial、optional 未選用均表達正確。
- [ ] 通過才將保留範圍逐項 cut over；brief／AC 在對應 task 擁有唯一手填來源；舊表格連到 task／board 或日期明確的 export，不長期雙寫。

**證明：** 對照既有文件和 evidence，記錄 native task ID 對應；檢查連結、AC 無遺失、狀態無擅自提升。只在切換真的完成時勾選；import 不等於獨立 acceptance。

## V3 — Agent 開工／交接與範圍核對

**依賴：** V2；沿用 C0 ownership、shared-file 和實驗權限規則。

**預計檔案：** 短 `AGENTS.md`、原生 task template／notes；若 native 功能確有缺口，再新增 `tools/check_task_scope.py`、`tests/test_task_scope.py` 與一份可攜帶 receipt。

- [ ] 開工先讀一個 task／AC／gate／owner／dirty entry，記錄 plan 和 planned references；未知 chat 不當作 live agent。
- [ ] Handoff 提供實際 changed files、行為、focused checks、evidence、限制，不能由執行者文字宣稱自動 Accepted；人工來源 review 與 software checks 分開。
- [ ] entry／exit 範圍核對涵蓋 tracked／untracked／刪除／改名／既有 dirty；超出範圍或多作者歸屬不明有明確回報，不自動 reset／stash。

**證明：** 若新增 checker，執行 `.\.venv\Scripts\python.exe -m pytest -q tests/test_task_scope.py`，在 temporary root 測既有 dirty 未改／再改、外圍改動、新檔、刪除／改名、缺證據、修改 AC、舊版本 proof。優先用原生功能，不為演示而建立 task DB／web API。

## V4 — 架構與任務連結

**依賴：** V2；Groma 部分須 V1 Groma go，否則走 atlas fallback。

**預計檔案：** 若 go，新增工具管理的 `groma/` 與其 config，校正 records／flows；task references／modified files；若 no-go，只更新 task-to-atlas references，不建替代編輯器。

- [ ] 用現有 atlas 和 source 核對 UI／API／worker／retrieval／facts-calculation／store／screen／model 等責任；自動線、人工策劃、planned drafts 清楚分別。
- [ ] 選 task 可定位 planned／actual components，選元件可看相關工作／code；缺 owner、unresolved Python calls、舊 snapshot 都可辨識。
- [ ] 試新增／延後／停用設計，不把圖變動當成實作；原始 atlas／evidence bytes 保留，不匯出／公開 source。

**證明：** 人工沿 fresh source → typed facts → saved report → optional review 對照；再核對 replay 不打 provider、restart interruption、不存在的 correction loop 不顯示已完成。工具 UI 做鍵盤／窄畫面與 stale-reference 檢查。未通過 Groma 的項目保持 deferred，不偽造完成。

## V5 — 專案內固定入口與一個真實任務 trial

**依賴：** V2/V3；V4 完成其 go 或明確 fallback 決定。

**預計檔案：** 必要時 `tools/package.json`／lock（只放 dev-tool 釘選依賴）、`.gitignore` 的 tooling outputs、`start-project-board.ps1`、README 導覽、正式 trial record；不改 app runtime dependencies。

- [ ] 一個本機入口能開任務與可用架構視圖；package／scanner versions、啟停、offline 與更新方式記錄清楚；ports 與研究 app 分開。
- [ ] 下一個已授權 task 走一次 plan → implementation → handoff → review，並試一個 scope change；沒有自動派工、paid call、new worktree 或 source export。
- [ ] 核對維護負擔：不重填三份狀態；退回普通 Markdown／atlas 可行；將未完成接入 task 移到正式 tracker，這份清單只留下交付索引。

**證明：** 啟動／關閉、檔案／Git diff、state 一致、review evidence、rollback 演練紀錄；使用者試用未發生就不能由 agent 勾選。安裝／scan 是實作時的工作，本次計劃沒有執行。

## Checkpoint 與停止條件

- [ ] Backlog 與 Groma 分別有實測 go／no-go；未知事項如實保留。
- [ ] 規格第 10 節七個案例有相應證據；只宣稱實際可用的功能。
- [ ] 原有 research 行為、C1 evidence／acceptance gates、dirty checkout 和 live stores 保持安全。
- [ ] 無新 task DB／自製 writable web app／重複 tracker／預設背景 AI reviewer；接入解決需求後停止擴張。
