// Revit API — 讀取 Levels、View Types (ViewFamilyType)、View Templates
// 用途：由 CREATE_PLAN_VIEWS STEP 1 送入 Revit MCP 執行
// 回傳：JSON 字串，包含 levels / viewTypes / templates
//
// MCP 技術注意事項：
//   - 文件變數名稱為 document（小寫）
//   - 不可使用 using 指令（程式碼插入於 method 內部）
//   - ElementId 取值使用 .Value（Revit 2024+）

var sb = new System.Text.StringBuilder();

// ---------- Levels（依 Elevation 升序）----------
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

// ---------- View Types / ViewFamilyType（所有，依 ViewFamily 分類）----------
// label 對應：FloorPlan=Floor Plan Views, StructuralPlan=Structural Plan Views, CeilingPlan=Reflected Ceiling Plan Views
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
sb.Append("],");

// ---------- View Templates（依 ViewType 分類）----------
var templateList = new System.Collections.Generic.List<View>();
foreach (Element e in new FilteredElementCollector(document).OfClass(typeof(View)))
{
    var v = (View)e;
    if (v.IsTemplate && (v.ViewType == ViewType.FloorPlan ||
        v.ViewType == ViewType.EngineeringPlan ||
        v.ViewType == ViewType.CeilingPlan))
        templateList.Add(v);
}

sb.Append("\"templates\":[");
for (int i = 0; i < templateList.Count; i++)
{
    var v = templateList[i];
    string label = v.ViewType == ViewType.FloorPlan ? "Floor Plan Views" :
                   v.ViewType == ViewType.EngineeringPlan ? "Structural Plan Views" :
                   "Reflected Ceiling Plan Views";
    sb.AppendFormat("{{\"name\":\"{0}\",\"id\":{1},\"label\":\"{2}\"}}",
        v.Name, v.Id.Value, label);
    if (i < templateList.Count - 1) sb.Append(",");
}
sb.Append("]}");

return sb.ToString();
