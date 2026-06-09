// Revit API — 批次創建平面視圖（含重複視圖跳過邏輯）
// 用途：由 /CREATE_PLAN_VIEWS slash command STEP 7 送入 Revit MCP 執行
// 注意：Claude 執行時需將 Add(...) 逐筆填入實際資料
//
// 注意事項（從實際執行確認）：
//   - MCP 文件變數名稱為 document（小寫）
//   - 不可使用 using 指令（程式碼插入於 method 內部）
//   - ElementId 取值使用 .Value（Revit 2024+，IntegerValue 已棄用）
//   - 不可自行建立 Transaction（MCP send_code_to_revit 已內含 Transaction）
//   - ElementId 建構子使用 int 型別（long 需 cast）

// 由 Claude 依 STEP 1~5 收集的資料填入實際數值
var viewNames = new System.Collections.Generic.List<string>();
var levelIds  = new System.Collections.Generic.List<long>();
var vftIds    = new System.Collections.Generic.List<long>();
// viewNames.Add("1FL-建築平面"); levelIds.Add(311); vftIds.Add(49552);
// viewNames.Add("2FL-建築平面"); levelIds.Add(694); vftIds.Add(49552);

// 取得已存在視圖名稱
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
