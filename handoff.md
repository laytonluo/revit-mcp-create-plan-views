# BEAM_MODELING 交接摘要

**日期：** 2026-06-11  
**SRS 版本：** v1.4  
**程式碼位置：** `BEAM_MODELING.extension/BEAM_MODELING.panel/CreateBeam.pushbutton/`

---

## 1. 已完成的項目

### SRS 文件
- [x] SRS v1.4 完成，新增 §4.4.1（手動選取橘色覆寫）和 §4.4.2（建立完成摘要彈窗）
- [x] 上傳至私有 GitHub Repo：`BEAM_CREATED_BY_DWG_PYREVIT`，已從原始 Repo 移除

### WPF XAML
- [x] `ui/MainWindow.xaml`：左右分割版型，包含 CAD 連結選單、3×3 圖層對應網格、尺寸來源 RadioButton、確認表工具列、**中心線顏色圖例（綠=已配對 / 紅=未配對）**、DataGrid（可下拉編輯族群類型）
- [x] `ui/AddTypeDialog.xaml`：5 欄位表單（複製自、建議名稱、名稱、寬度b、深度h）

### script.py — 各節段狀態

| 節段 | 說明 | 狀態 |
|------|------|------|
| §0 | `check_active_view()` — 視圖類型與 GenLevel 驗證 | ✅ 完成 |
| §1 | `get_cad_links / get_all_layers / get_structural_beam_types / get_string_instance_params / get_solid_fill_pattern_id` | ✅ 完成 |
| §2 | DXF 匯出與解析（`export_dxf / load_netdxf / parse_dxf_layers / parse_dxf_texts / parse_dxf_geometry / cleanup_dxf`） | ✅ 完成 |
| §3 | 座標轉換（`get_cad_transform / mm_to_feet / cm_to_feet / cad_mm_to_revit_xyz / revit_xyz_to_cm / distance_2d_cm`） | ✅ 完成 |
| §4 | 中心線配對演算法（`classify_lines_by_angle / find_parallel_pairs / calc_centerline / match_labels_to_centerlines / match_sizes_to_centerlines / run_analysis`） | ✅ 完成 |
| §5 | 族群類型自動配對（`normalize_size / parse_size_cm / auto_match_family_type / detect_width_depth_params / load_csv_size_map`） | ✅ 完成 |
| §6 | DirectShape 暫時顯示（綠/紅配色）（`show_centerlines_as_direct_shapes / clear_direct_shapes`） | ✅ 完成 |
| §7 | 建立結構樑（`create_beams`） | ✅ 完成 |
| §8 | 手動覆寫圖形（`apply_manual_override`，RGB 255,128,64） | ✅ 完成 |
| §9 | WPF 主視窗（`BeamRow` + `BeamModelingWindow`，含全部事件 handler） | ✅ 完成 |
| §10 | 新增梁類型彈窗（`AddTypeDialog`） | ⚠️ 骨架，`_init` 和 `BtnOk_Click` 均為 `pass` |
| §11 | `main()` 進入點 | ✅ 完成 |

---

## 2. 目前進行到哪裡

**§9 BeamModelingWindow 剛完成實作**，包含所有事件 handler：

- `_on_analyze`：組裝 layer_config → 呼叫 `run_analysis` → 自動配對 → 填充 DataGrid → 顯示 DirectShape
- `_on_confirm`：同步 DataGrid → 清除 DirectShape → 建立樑 → 橘色覆寫 → 摘要彈窗 → 關閉視窗
- `_on_add_type`：呼叫 `AddTypeDialog`（目前為空實作）→ 成功後重新整理清單
- `_on_write_param_changed`：勾選時讀取文字實例參數清單
- `_on_cad_link_changed`、`_on_size_source_changed`、`_on_browse_csv`、`_on_closed`

**尚未整合測試**，全段 script.py 未在真實 PyRevit 環境執行過。

---

## 3. 下一步待辦

### 優先項目

#### §10 AddTypeDialog 實作
需在 `script.py:1475` 和 `script.py:1479` 填入邏輯：

```python
def _init(self, size_str):
    # 1. 填充 CmbSourceType：所有族群類型名稱
    for name in self._all_family_types:
        self._cmb_source.Items.Add(name)
    if self._all_family_types:
        self._cmb_source.SelectedIndex = 0

    # 2. 解析 size_str → 帶入建議名稱與尺寸欄位
    # 例：'60x85' → suggested='B60X85cm'、width=60、depth=85
    norm = normalize_size(size_str)
    w, d = parse_size_cm(norm)
    suggested = u"B{}X{}cm".format(w, d) if w and d else u""
    self._txt_suggested.Text = suggested
    self._txt_name.Text      = suggested
    if w:
        self._txt_width.Text = str(w)
    if d:
        self._txt_depth.Text = str(d)

def BtnOk_Click(self, sender, e):
    # 1. 驗證輸入
    name    = self._txt_name.Text.strip()
    src_name = self._cmb_source.SelectedItem
    try:
        w = float(self._txt_width.Text)
        d = float(self._txt_depth.Text)
    except:
        MessageBox.Show(u"請輸入有效的數字", ...)
        return

    # 2. 找來源 FamilySymbol
    all_symbols = get_structural_beam_types()
    src_fs = next((fs for fs in all_symbols if fs.Name == src_name), None)
    if src_fs is None:
        return

    # 3. DuplicateType
    t = Transaction(doc, u"新增梁類型")
    t.Start()
    new_type_id = src_fs.Duplicate(name)
    new_fs = doc.GetElement(new_type_id)

    # 4. detect_width_depth_params → 寫入寬度/深度
    wp, dp = detect_width_depth_params(src_fs)
    if wp:
        new_fs.LookupParameter(wp).Set(cm_to_feet(w))
    if dp:
        new_fs.LookupParameter(dp).Set(cm_to_feet(d))
    t.Commit()

    self._result_type_name = name
    self._win.Close()
```

#### 整合測試
1. 在 PyRevit 環境載入外掛，確認 MainWindow 正常開啟
2. 選擇 CAD 連結，確認圖層自動填充
3. 執行分析，確認 DirectShape 綠/紅中心線顯示於平面圖中
4. 確認建立，確認結構樑位置正確
5. 手動選取流程：測試 AddTypeDialog（§10 完成後）

#### lib/ 資料夾補齊
確認 `lib/netDxf.netstandard.dll`（v2.4.0）已複製至：
```
BEAM_MODELING.extension/BEAM_MODELING.panel/CreateBeam.pushbutton/lib/
```

---

## 4. 重要設計決策與參數

### 演算法參數（script.py §4）

| 常數 | 值 | 說明 |
|------|----|------|
| `ANGLE_TOL` | 1.0° | 角度分組容差（水平/垂直） |
| `LENGTH_TOL` | 5.0 mm | 配對線段等長容差 |
| `MIN_WIDTH` | 20 cm | 最小梁寬（= 200 mm） |
| `MAX_WIDTH` | 120 cm | 最大梁寬（= 1200 mm） |
| `MIN_OVERLAP` | 80% | 平行線段投影重疊比例下限 |

### 顏色規範（SRS §4.4.1 / §4.2.5）

| 用途 | RGB |
|------|-----|
| DirectShape 已配對中心線 | (0, 220, 0)「亮綠」|
| DirectShape 未配對中心線 | (255, 60, 60)「亮紅」|
| 手動選取結構樑覆寫 | (255, 128, 64)「橘色」|

### DXF Block 搜尋前綴（§2）
Block 名稱格式：`{dwgName}_dwg-{typeId}-{viewName}`  
搜尋前綴：`{dwgName}_dwg-`（含 hyphen，避免誤抓網格 block 如 `BEAM_CREATED_BY_CAD_dwg_GRID`）

### LwPolyline 頂點座標（§2 已修正）
netDxf v2.4.0 的 `LwPolylineVertex` 的 X/Y 座標在 `vertex.Position.X / vertex.Position.Y`（`Vector2` 型別），**不是**直接 `vertex.X / vertex.Y`。

### Revit API 注意事項
- **MCP 環境**：已有 Transaction 包裹，測試碼不可再加 `Transaction`
- **PyRevit 環境（script.py）**：需自行建立 `Transaction`
- `ElementId.Value`（Revit 2024+），舊版用 `.IntegerValue`
- `DXFExportOptions.MergedViews`：Revit 2024 已移除，不可使用

### 資料流向
```
ImportInstance (Revit)
    ↓ export_dxf()
暫存 .dxf (temp/)
    ↓ parse_dxf_geometry() / parse_dxf_texts()
lines[], labels[], size_labels[]   # 單位：mm，CAD 局部座標
    ↓ classify → find_parallel_pairs → calc_centerline → match_labels
centerlines[]                      # 含 cx,cy（mm），label_value，is_unmatched
    ↓ cad_mm_to_revit_xyz(transform)
Revit XYZ (feet)
    ↓ NewFamilyInstance(curve, fs, level, Beam)
結構樑 Element
```

### WPF 事件綁定方式
IronPython 3 不支援 code-behind，所有事件以 Python 方法直接 `+=` 綁定：
```python
w.FindName("BtnAnalyze").Click += self._on_analyze
```

### 族群類型名稱配對邏輯（§5）
只比對數字 tuple，忽略前綴（B/RC）、後綴（cm）、大小寫：
- `"B60X85cm"` → `(60, 85)`
- `"(60X85)"` → `(60, 85)`
→ 兩者配對成功

---

## 5. 檔案結構

```
BEAM_MODELING.extension/
└── BEAM_MODELING.panel/
    └── CreateBeam.pushbutton/
        ├── script.py          # 主程式（§0–§11）
        ├── ui/
        │   ├── MainWindow.xaml
        │   └── AddTypeDialog.xaml
        └── lib/
            └── netDxf.netstandard.dll  ← 需手動補齊（v2.4.0）
```

---

*由 Claude Sonnet 4.6 產生，2026-06-11*
