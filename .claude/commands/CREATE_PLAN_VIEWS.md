# CREATE_PLAN_VIEWS

執行以下完整流程，透過 Revit MCP 批次創建平面視圖。
全程共呼叫 Revit MCP **最多 2 次**（STEP 1 讀取資料、STEP 6 創建視圖），中間步驟均為勾選互動。

## MCP 技術注意事項
- MCP 文件變數名稱為 `document`（小寫）
- 程式碼插入於 method 內，**不可加 `using` 指令**
- ElementId 取值使用 `.Value`（Revit 2024+，`IntegerValue` 已棄用）
- STEP 0、2、3、6 使用 `AskUserQuestion` 勾選介面
- **Dismiss 規則**：任何 `AskUserQuestion` 若回傳包含 `dismissed` 的字串，立即終止整個流程並顯示「已取消，未對 Revit 進行任何操作。」，不再詢問任何問題
- **OTHER 規則**：任何 `AskUserQuestion` 若回傳 `[No preference]` 或非預期值，視為使用者未選取，重新顯示同一個問題一次；若第二次仍未選取，終止流程

---

## STEP 0 — 檢查對話快取

**在執行 STEP 1 之前**，先檢查本次對話記憶體中是否已存在 `levels` 與 `viewTypes` 資料（即本對話曾執行過 STEP 1）。

### 情況 A：對話中已有資料

顯示快取摘要並使用 `AskUserQuestion`（單選）詢問：
- header：`資料來源`
- question：`偵測到本次對話已載入 Revit 資料（X 個 Level，Y 個 View Type），是否沿用？`
- options：
  - label：`沿用`，description：`跳過讀取，直接從 STEP 2 開始（Revit 專案無異動時使用）`
  - label：`重新讀取`，description：`重新從 Revit 讀取最新資料（專案有新增樓層或視圖類型時使用）`

若回傳 `沿用`：**跳過 STEP 1，直接進入 STEP 2**，沿用對話中已有的 `levels`、`viewTypes`。
若回傳 `重新讀取`：繼續執行 STEP 1。

### 情況 B：對話中無資料

直接執行 STEP 1。

---

## STEP 1 — 讀取 Revit 資料（MCP Call #1）

使用 `mcp__revit-mcp__send_code_to_revit` 執行：

```csharp
var sb = new System.Text.StringBuilder();

var levelList = new System.Collections.Generic.List<Level>();
foreach (Element e in new FilteredElementCollector(document).OfClass(typeof(Level)))
    levelList.Add((Level)e);
levelList.Sort((a, b) => a.Elevation.CompareTo(b.Elevation));

sb.Append("{\"levels\":[");
for (int i = 0; i < levelList.Count; i++)
{
    sb.AppendFormat("{{\"name\":\"{0}\",\"id\":{1}}}", levelList[i].Name, levelList[i].Id.Value);
    if (i < levelList.Count - 1) sb.Append(",");
}
sb.Append("],");

var viewTypeList = new System.Collections.Generic.List<ViewFamilyType>();
foreach (Element e in new FilteredElementCollector(document).OfClass(typeof(ViewFamilyType)))
{
    var vft = (ViewFamilyType)e;
    if (vft.ViewFamily == ViewFamily.FloorPlan ||
        vft.ViewFamily == ViewFamily.StructuralPlan ||
        vft.ViewFamily == ViewFamily.CeilingPlan)
        viewTypeList.Add(vft);
}

sb.Append("\"viewTypes\":[");
for (int i = 0; i < viewTypeList.Count; i++)
{
    var vft = viewTypeList[i];
    string label = vft.ViewFamily == ViewFamily.FloorPlan ? "Floor Plan Views" :
                   vft.ViewFamily == ViewFamily.StructuralPlan ? "Structural Plan Views" :
                   "Reflected Ceiling Plan Views";
    sb.AppendFormat("{{\"name\":\"{0}\",\"id\":{1},\"label\":\"{2}\"}}",
        vft.Name, vft.Id.Value, label);
    if (i < viewTypeList.Count - 1) sb.Append(",");
}
sb.Append("]}");

return sb.ToString();
```

解析結果，保存 `levels`、`viewTypes` 供後續步驟使用。

---

## STEP 2 — 選擇視圖類別

使用 `AskUserQuestion`（單選）：
- header：`視圖類別`
- question：`請選擇要創建的視圖類別：`
- options：
  - `Floor Plan Views` / 描述：樓板平面圖
  - `Structural Plan Views` / 描述：結構平面圖
  - `Reflected Ceiling Plan Views` / 描述：天花板反射平面圖

記錄回傳值為 `selectedCategory`。

---

## STEP 3 — 選擇視圖類型 VIEW TYPE

從 `viewTypes` 中篩選 `label == selectedCategory` 的項目。

若只有一個，自動選取並告知使用者：「✅ 已自動選取唯一 VIEW TYPE：[名稱]」，跳過此步驟。

若有多個，使用 `AskUserQuestion`（單選）：
- header：`VIEW TYPE`
- question：`請選擇 VIEW TYPE（視圖類型）：`
- options：依篩選結果取前 4 項列出，每項 label 為 ViewFamilyType 名稱，description 留空
- 若篩選結果超過 4 項，於 question 末加註：`（第 5 項以上請點選 Other 輸入名稱）`

記錄 `selectedViewTypeName`、`selectedViewTypeId`。

---

## STEP 4 — 自動選取樓層範圍

**不詢問使用者**，依以下規則自動篩選 `selectedLevels`：

| 群組 | 判斷規則 | 處理 |
|------|----------|------|
| 地上層 | 名稱第一字元為數字（0-9） | ✅ 納入 |
| 屋突層 | 名稱開頭為大寫 R | ✅ 納入 |
| 地下層 | 名稱開頭為大寫 B | ✅ 納入 |
| 獨立樓層 | 以上三類以外（如 GL） | ❌ 自動排除 |

篩選完成後顯示簡短提示，例如：
`📐 自動選取 27 個樓層（地上 21 + 屋突 2 + 地下 4），已排除獨立樓層（GL 等）`

直接進入 STEP 5，無需使用者確認。

---

## STEP 5 — 自動解析視圖名稱

**不詢問使用者**，直接從 `selectedViewTypeName` 解析前綴與後綴：

### 解析規則

1. 以 `-` 切割名稱
2. 若第一段為**純數字英文**（僅含 `[0-9A-Za-z]`，無中文）→ 丟棄
3. 計算剩餘段數：
   - 1 段 → 無前綴，後綴 = 該段
   - 2 段以上 → 前綴 = 第一段，後綴 = 最後一段

### 範例

| VIEW TYPE 名稱 | 解析結果 | 視圖名稱格式 |
|--------------|---------|------------|
| `結構平面` | 後綴：結構平面 | `1FL-結構平面` |
| `0A-結構平面` | 後綴：結構平面 | `1FL-結構平面` |
| `0A-領標版-結構平面` | 前綴：領標版，後綴：結構平面 | `領標版-1FL-結構平面` |

### 名稱組合

- 有前綴：`{prefix}-{levelName}-{suffix}`
- 無前綴：`{levelName}-{suffix}`

解析完成後直接進入 STEP 6，無需使用者確認命名格式。

---

## STEP 6 — 確認清單預覽

建立完整創建清單，以表格顯示（依 Elevation 排序）：

```
┌──────────┬──────────────────────────┬──────────────────┐
│ Level    │ View Name                │ View Type        │
├──────────┼──────────────────────────┼──────────────────┤
│ 1FL      │ 1FL-結構平面             │ 0A-結構平面      │
│ 2FL      │ 2FL-結構平面             │ 0A-結構平面      │
└──────────┴──────────────────────────┴──────────────────┘
共 X 個視圖將被送入 Revit（已存在者執行時自動略過）
```

使用 `AskUserQuestion`（單選）詢問確認：
- header：`確認執行`
- question：`確認要執行以上視圖創建嗎？`
- options：
  - label：`執行`，description：`送入 Revit 批次創建視圖`
  - label：`取消`，description：`中止流程，不對 Revit 進行任何操作`

---

## STEP 7 — 執行創建（MCP Call #2）

若回傳 `取消`：顯示「已取消，未對 Revit 進行任何操作。」並結束。

若回傳 `執行`：使用平行陣列逐筆填入實際數值後執行（**不可加 Transaction**，MCP 已包含）：

```csharp
// 由 Claude 依 STEP 1~5 收集的資料逐筆填入
var viewNames = new System.Collections.Generic.List<string>();
var levelIds  = new System.Collections.Generic.List<long>();
var vftIds    = new System.Collections.Generic.List<long>();
// viewNames.Add("1FL-結構平面"); levelIds.Add(311); vftIds.Add(254067);
// viewNames.Add("2FL-結構平面"); levelIds.Add(694); vftIds.Add(254067);

var existingNames = new System.Collections.Generic.HashSet<string>();
foreach (Element e in new FilteredElementCollector(document).OfClass(typeof(View)))
{
    var v = (View)e;
    if (!v.IsTemplate) existingNames.Add(v.Name);
}

var created = new System.Collections.Generic.List<string>();
var skipped  = new System.Collections.Generic.List<string>();

for (int i = 0; i < viewNames.Count; i++)
{
    string vn = viewNames[i];
    if (existingNames.Contains(vn)) { skipped.Add(vn); continue; }
    var view = ViewPlan.Create(document, new ElementId((int)vftIds[i]), new ElementId((int)levelIds[i]));
    view.Name = vn;
    created.Add(vn);
}

var sb = new System.Text.StringBuilder();
sb.Append("{\"created\":[");
for (int i = 0; i < created.Count; i++)
{
    sb.AppendFormat("\"{0}\"", created[i]);
    if (i < created.Count - 1) sb.Append(",");
}
sb.Append("],\"skipped\":[");
for (int i = 0; i < skipped.Count; i++)
{
    sb.AppendFormat("\"{0}\"", skipped[i]);
    if (i < skipped.Count - 1) sb.Append(",");
}
sb.Append("]}");

return sb.ToString();
```

回報結果：

```
✅ 成功創建 X 個視圖：
  - 1FL-結構平面
  ...

⚠ 略過 Y 個已存在視圖：
  - 2FL-結構平面
```
