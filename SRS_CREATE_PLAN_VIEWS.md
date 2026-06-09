# SRS — CREATE_PLAN_VIEWS

**版本：** 1.7  
**日期：** 2026-05-18  
**狀態：** 定案

---

## 1. 系統概述

| 項目 | 說明 |
|------|------|
| 系統名稱 | CREATE_PLAN_VIEWS |
| 目的 | 透過 MCP 控制 Revit，批次創建指定樓層的平面視圖 |
| 觸發方式 | 使用者輸入指令 `CREATE_PLAN_VIEWS` |
| 執行環境 | Claude Code 桌面 App + Revit MCP Server |
| MCP 呼叫次數 | 最多 2 次（首次執行 2 次；同一對話重複執行且沿用資料時僅 1 次） |
| AskUserQuestion 呼叫次數 | 最多 4 次（STEP 0、2、3、6） |

---

## 2. 前置條件

- Revit 專案已開啟且 MCP Server 連線正常
- 專案中已定義 Levels 與 ViewFamilyTypes

---

## 3. 使用者互動流程

### Step 0 — 觸發與快取檢查

使用者輸入 `CREATE_PLAN_VIEWS`。

系統檢查本次對話記憶體中是否已存在 `levels` 與 `viewTypes` 資料：

**情況 A：對話中已有資料（曾執行過 Step 1）**

以勾選介面詢問（僅兩個選項）：

| 選項 | 說明 |
|------|------|
| 沿用 | 跳過 Step 1，直接從 Step 2 開始（Revit 專案無異動時使用） |
| 重新讀取 | 重新從 Revit 讀取最新資料（專案有新增樓層或視圖類型時使用） |

選擇「沿用」→ 跳至 Step 2，**不呼叫 MCP**。  
選擇「重新讀取」→ 繼續執行 Step 1。

**情況 B：對話中無資料（首次執行）**

直接執行 Step 1。

---

### Step 1 — 讀取 Revit 資料（MCP Call #1）

透過 Revit MCP 讀取並保存至對話記憶體：
- 所有 Levels（名稱 + ElementId，依 Elevation 升序）
- 所有 View Types（ViewFamilyType，名稱 + ElementId + 所屬類別）

> **不讀取 View Templates**（已從本版本移除）

---

### Step 2 — 選擇視圖類別（勾選單選）

| 選項 | Revit ViewFamily |
|------|-----------------|
| Floor Plan Views | ViewFamily.FloorPlan |
| Structural Plan Views | ViewFamily.StructuralPlan |
| Reflected Ceiling Plan Views | ViewFamily.CeilingPlan |

記錄為 `selectedCategory`。

---

### Step 3 — 選擇視圖類型 VIEW TYPE（勾選單選）

依 `selectedCategory` 篩選對應的 ViewFamilyType 清單。

> **說明：** VIEW TYPE（視圖類型）即 Revit 中的 ViewFamilyType，決定新建視圖的類型。例如 Floor Plan 類別下可能有「0B-建築底圖」、「0C-室裝底圖」等不同 View Type。

若該類別僅有一個 VIEW TYPE，自動選取並告知使用者，跳過此步驟。  
若有多個，以勾選介面列出前 4 項供選擇；超過 4 項時於題目末加註提示使用者透過 Other 輸入名稱。

記錄 `selectedViewTypeName`、`selectedViewTypeId`。

---

### Step 4 — 自動選取樓層範圍（無使用者互動）

**不詢問使用者**，依命名規則自動篩選：

| 群組 | 判斷規則 | 範例 | 處理 |
|------|----------|------|------|
| 地上層 | 名稱第一字元為數字（0-9） | 1FL, 2FL, 10FL | ✅ 納入 |
| 屋突層 | 名稱開頭為大寫 `R` | RF, R1FL, RFL | ✅ 納入 |
| 地下層 | 名稱開頭為大寫 `B` | B1F, B2F, BSF | ✅ 納入 |
| 獨立樓層 | 以上三類以外 | GL, TEMP | ❌ 自動排除 |

篩選完成後顯示提示文字（例：`📐 自動選取 27 個樓層（地上 21 + 屋突 2 + 地下 4），已排除獨立樓層`），直接進入 Step 5。

`selectedLevels` 包含所有納入樓層的 name 與 id，依 Elevation 升序排列。

---

### Step 5 — 自動解析視圖名稱（無使用者互動）

**不詢問使用者**，直接從 `selectedViewTypeName` 自動解析前綴與後綴。

#### 解析規則

1. 以 `-` 切割名稱
2. 若第一段為**純數字英文**（僅含 `[0-9A-Za-z]`，無中文字元）→ 丟棄
3. 計算剩餘段數：
   - 1 段 → 無前綴，後綴 = 該段
   - 2 段以上 → 前綴 = 第一段，後綴 = 最後一段

#### 範例

| VIEW TYPE 名稱 | 前綴 | 後綴 | 視圖名稱格式 |
|--------------|------|------|------------|
| `結構平面` | （無） | 結構平面 | `1FL-結構平面` |
| `0A-結構平面` | （無） | 結構平面 | `1FL-結構平面` |
| `0A-領標版-結構平面` | 領標版 | 結構平面 | `領標版-1FL-結構平面` |

#### 名稱組合規則

- 有前綴：`{prefix}-{levelName}-{suffix}`
- 無前綴：`{levelName}-{suffix}`

---

### Step 6 — 確認清單預覽（勾選確認）

列出即將創建的完整清單（依 Elevation 排序）：

```
┌──────────┬──────────────────────────┬──────────────────┐
│ Level    │ View Name                │ View Type        │
├──────────┼──────────────────────────┼──────────────────┤
│ B2F      │ B2F-結構平面             │ 0A-結構平面      │
│ B1F      │ B1F-結構平面             │ 0A-結構平面      │
│ 1FL      │ 1FL-結構平面             │ 0A-結構平面      │
└──────────┴──────────────────────────┴──────────────────┘
共 X 個視圖將被送入 Revit（已存在者執行時自動略過）
```

以勾選介面詢問：執行 或 取消。

---

### Step 7 — 執行創建（MCP Call #2）

- **取消**：中止流程，不對 Revit 進行任何操作。
- **執行**：透過 Revit MCP 批次創建視圖，略過已存在視圖，回報結果。

```
✅ 成功創建 3 個視圖：
  - B2F-結構平面
  - B1F-結構平面
  - 1FL-結構平面
⚠ 略過 1 個已存在視圖：
  - 2FL-結構平面
```

---

## 4. 技術實作說明

### 4.1 Revit MCP 使用方式

| 操作 | 方式 |
|------|------|
| MCP 文件變數名稱 | `document`（小寫） |
| 程式碼限制 | 不可使用 `using` 指令（namespace 宣告，插入於 method 內部） |
| Transaction | **不可自行建立**（`send_code_to_revit` 已內含 Transaction；自行嵌套會導致執行期例外） |
| ElementId 取值 | `.Value`（Revit 2024+，`IntegerValue` 已棄用） |
| ElementId 建構子 | 傳入 `int`（若資料為 `long` 需先 cast：`new ElementId((int)id)`） |
| 讀取 Levels | `FilteredElementCollector` 查詢 `Level` 類別 |
| 讀取 View Types | `FilteredElementCollector` 查詢 `ViewFamilyType`，依 `ViewFamily` 分類 |
| 創建 Plan View | `ViewPlan.Create(document, viewFamilyTypeId, levelId)` |

### 4.2 ViewFamily 對應關係

| 類別選項 | Revit ViewFamily | ViewType |
|----------|-----------------|----------|
| Floor Plan Views | `ViewFamily.FloorPlan` | `ViewType.FloorPlan` |
| Structural Plan Views | `ViewFamily.StructuralPlan` | `ViewType.EngineeringPlan` |
| Reflected Ceiling Plan Views | `ViewFamily.CeilingPlan` | `ViewType.CeilingPlan` |

### 4.3 勾選介面行為規則

| 情況 | 處理方式 |
|------|---------|
| 使用者點選 Dismiss（右上角 ✕） | 立即終止整個流程，顯示「已取消，未對 Revit 進行任何操作。」 |
| 使用者選取 OTHER 或回傳非預期值 | 重新顯示同一問題一次；第二次仍無效則終止流程 |
| AskUserQuestion 選項上限 | 每個 question 最多 4 個選項；超過時取前 4，其餘提示透過 Other 輸入 |

### 4.4 對話快取機制

| 情境 | MCP 呼叫次數 | 說明 |
|------|-------------|------|
| 首次執行 | 2 次 | Step 1 讀取 + Step 7 創建 |
| 同對話重複執行（沿用資料） | 1 次 | 跳過 Step 1，僅 Step 7 創建 |
| 同對話重複執行（重新讀取） | 2 次 | 同首次執行 |
| 跨對話執行 | 2 次 | 新對話無快取，同首次執行 |

### 4.5 視圖名稱自動解析規則

VIEW TYPE 名稱以 `-` 為分隔符，規則如下：

| 條件 | 前綴 | 後綴 |
|------|------|------|
| 第一段純數字英文，共 2 段 | 無 | 第 2 段 |
| 第一段純數字英文，共 3 段以上 | 第 2 段 | 最後段 |
| 第一段含中文（無需丟棄），共 1 段 | 無 | 整個名稱 |
| 第一段含中文，共 2 段以上 | 第 1 段 | 最後段 |

---

## 5. 限制與範圍外事項

- 單次操作所有選定樓層套用同一個 View Type
- 視圖建立後不自動套用 View Template（可於 Revit 中手動套用）
- 不支援批次修改已存在視圖的設定
- 不支援 Scope Box、裁切範圍等進階設定
- 不支援使用者自訂視圖名稱前後綴（名稱完全由 VIEW TYPE 名稱解析決定）
- 樓層排序依 Revit 專案中的 Elevation 順序
- 對話快取僅在同一 Claude Code 對話內有效，跨對話需重新讀取

---

## 6. 變更紀錄

| 版本 | 日期 | 說明 |
|------|------|------|
| 1.0 | 2026-05-18 | 初版定案 |
| 1.1 | 2026-05-18 | Step 3 修正為選擇 VIEW TYPE；新增 Step 4 View Template；共 8 步 |
| 1.2 | 2026-05-18 | 移除 View Template 選擇步驟，步驟從 8 → 7；尾綴改由 VIEW TYPE 名稱解析 |
| 1.3 | 2026-05-18 | 新增 Step 0 對話快取機制；選擇步驟全面改為勾選介面（AskUserQuestion）；更新 MCP 呼叫次數說明 |
| 1.4 | 2026-05-18 | 新增勾選介面行為規則：Dismiss 立即終止流程；OTHER 重問一次後終止 |
| 1.5 | 2026-05-18 | Step 5 前綴改為 AskUserQuestion 介面（留空選項 + OTHER 輸入框） |
| 1.6 | 2026-05-18 | 4.1 技術說明新增：不可自行建立 Transaction；ElementId 建構子需傳入 int |
| 1.7 | 2026-05-18 | Step 1 移除 templates 讀取；Step 3 超過 4 項改提示 Other 輸入；Step 5 移除使用者自訂命名，改為自動從 VIEW TYPE 名稱解析前後綴；AskUserQuestion 呼叫從 7~8 次降至最多 5 次 |
| 1.8 | 2026-05-18 | Step 4 改為自動選取（地上層 + 屋突層 + 地下層），獨立樓層自動排除，無需使用者勾選；AskUserQuestion 呼叫降至最多 4 次 |
