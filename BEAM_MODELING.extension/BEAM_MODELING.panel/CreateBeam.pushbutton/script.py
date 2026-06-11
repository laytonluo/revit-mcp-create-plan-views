# -*- coding: utf-8 -*-
"""
BEAM_MODELING — 結構樑翻模 PyRevit 外掛
SRS: BEAM_MODELING v1.4
"""
import os
import sys
import re
import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    ImportInstance, CADLinkType, Level, ViewPlan,
    FamilySymbol, StructuralType,
    Line, PolyLine, Arc, XYZ,
    Transaction, DirectShape,
    OverrideGraphicSettings, Color,
    FillPatternElement, FillPatternTarget,
)
from Autodesk.Revit.DB.Structure import StructuralType as ST
from System.Windows import Window, MessageBox, MessageBoxButton, MessageBoxResult
from System.Windows.Controls import ComboBoxItem
import System.Windows.Forms as WinForms

# ── PyRevit ──────────────────────────────────────────────────────────────────
from pyrevit import revit, forms
doc   = revit.doc
uidoc = revit.uidoc

# ── DLL 路徑（netDxf 打包於 lib/） ────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(__file__)
_LIB_DIR    = os.path.join(_SCRIPT_DIR, "lib")
_XAML_DIR   = os.path.join(_SCRIPT_DIR, "ui")

if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)


# ══════════════════════════════════════════════════════════════════════════════
# § 0  啟動前置判斷  (SRS §4.1.2)
# ══════════════════════════════════════════════════════════════════════════════

ALLOWED_VIEW_TYPES = ("FloorPlan", "StructuralPlan", "CeilingPlan")

def check_active_view():
    """確認目前作用中視圖為平面視圖，回傳 (ViewPlan, Level) 或 (None, None)。"""
    view  = uidoc.ActiveView
    vtype = view.ViewType.ToString()
    if vtype not in ALLOWED_VIEW_TYPES:
        MessageBox.Show(
            u"請先切換至樓層平面視圖再執行此工具",
            u"BEAM_MODELING",
            MessageBoxButton.OK
        )
        return None, None
    level = view.GenLevel
    if level is None:
        MessageBox.Show(
            u"目前視圖無關聯樓層（GenLevel 為 None），請確認視圖設定。",
            u"BEAM_MODELING",
            MessageBoxButton.OK
        )
        return None, None
    return view, level


# ══════════════════════════════════════════════════════════════════════════════
# § 1  讀取 Revit 資料  (SRS §4.1.1)
# ══════════════════════════════════════════════════════════════════════════════

def get_cad_links(view):
    """
    回傳目前視圖中所有 ImportInstance 的清單。
    每筆為 dict: { 'instance': ImportInstance, 'name': str }
    """
    results = []
    collector = (
        FilteredElementCollector(doc, view.Id)
        .OfClass(ImportInstance)
        .ToElements()
    )
    for inst in collector:
        try:
            cad_link_type = doc.GetElement(inst.GetTypeId())
            name = cad_link_type.get_Parameter(
                BuiltInParameter.SYMBOL_NAME_PARAM
            ).AsString()
        except Exception:
            name = inst.UniqueId
        results.append({"instance": inst, "name": name})
    return results


def get_all_layers(import_instance):
    """
    從 CAD 連結的幾何取得所有圖層名稱清單（已排序的字串 list）。
    使用 GetInstanceGeometry() 遍歷所有幾何物件，收集 GraphicsStyleId
    對應的圖層名稱。
    """
    layer_names = set()
    options = import_instance.Document.Application.Create.NewGeometryOptions()
    geo_elem = import_instance.get_Geometry(options)
    if geo_elem is None:
        return []
    for geo_obj in geo_elem:
        style_id = geo_obj.GraphicsStyleId
        if style_id and style_id.IntegerValue > 0:
            style = doc.GetElement(style_id)
            if style is not None:
                layer_names.add(style.Name)
    return sorted(layer_names)


def get_structural_beam_types():
    """
    回傳專案中所有結構樑族群類型（FamilySymbol list）。
    篩選條件：BuiltInCategory.OST_StructuralFraming
    """
    symbols = (
        FilteredElementCollector(doc)
        .OfClass(FamilySymbol)
        .OfCategory(BuiltInCategory.OST_StructuralFraming)
        .ToElements()
    )
    return list(symbols)


def get_string_instance_params(family_symbol):
    """
    回傳指定族群類型的所有文字類型（StorageType.String）實例參數名稱清單。
    用於「梁編號寫入實例參數」的下拉選單。
    """
    from Autodesk.Revit.DB import StorageType
    param_names = []
    for param in family_symbol.Parameters:
        if (not param.IsReadOnly
                and param.StorageType == StorageType.String
                and not param.Definition.Name.startswith("_")):
            param_names.append(param.Definition.Name)
    return sorted(param_names)


def get_solid_fill_pattern_id(doc):
    """
    取得 Solid Fill FillPatternElement 的 ElementId。
    優先找名稱含「Solid」或「實心」的 Drafting 圖樣；找不到回傳 ElementId.InvalidElementId。
    """
    from Autodesk.Revit.DB import ElementId
    patterns = (
        FilteredElementCollector(doc)
        .OfClass(FillPatternElement)
        .ToElements()
    )
    for p in patterns:
        fp = p.GetFillPattern()
        if fp.IsSolidFill:
            return p.Id
    # IsSolidFill 找不到時，用名稱模糊搜尋
    for p in patterns:
        n = p.Name.lower()
        if u"solid" in n or u"實心" in n:
            return p.Id
    return ElementId.InvalidElementId


# ══════════════════════════════════════════════════════════════════════════════
# § 2  DXF 自動匯出與解析  (SRS §5.1, §5.2)
# ══════════════════════════════════════════════════════════════════════════════

def export_dxf(doc, view, import_instance):
    """
    將目前視圖匯出為暫存 DXF（ACADVersion.R2010）。
    回傳暫存 DXF 路徑，失敗回傳 None。
    DXFExportOptions 不含 MergedViews 屬性（Revit 2024 已移除）。
    (SRS §5.1)
    """
    try:
        from Autodesk.Revit.DB import DXFExportOptions, ACADVersion
        import tempfile, os
        link_type = doc.GetElement(import_instance.GetTypeId())
        dwg_name  = os.path.splitext(
            link_type.get_Parameter(
                BuiltInParameter.SYMBOL_NAME_PARAM).AsString())[0]
        temp_dir  = tempfile.gettempdir()
        dxf_name  = dwg_name + "_TEMP"
        dxf_path  = os.path.join(temp_dir, dxf_name + ".dxf")

        opts = DXFExportOptions()
        opts.FileVersion = ACADVersion.R2010
        view_ids = System.Collections.Generic.List[ElementId]()
        view_ids.Add(view.Id)
        doc.Export(temp_dir, dxf_name, view_ids, opts)
        return dxf_path if os.path.exists(dxf_path) else None
    except Exception as e:
        raise RuntimeError(u"DXF 匯出失敗：{}".format(str(e)))


_netdxf_asm = None

def load_netdxf():
    """
    載入 netDxf.netstandard.dll，回傳 assembly 物件。
    重複呼叫時直接回傳已載入的 assembly（避免重複載入）。
    """
    global _netdxf_asm
    if _netdxf_asm is not None:
        return _netdxf_asm
    import clr
    dll = os.path.join(_LIB_DIR, "netDxf.netstandard.dll")
    if not os.path.exists(dll):
        raise RuntimeError(u"找不到 netDxf.netstandard.dll，請確認放置於 lib/ 資料夾")
    import System.Reflection as Reflection
    _netdxf_asm = Reflection.Assembly.LoadFrom(dll)
    return _netdxf_asm


def _get_target_block(dxf_doc, dxf_doc_type, dwg_name):
    """
    從 DXF 取得含樑幾何與標籤的目標 Block。
    Block 命名格式：{dwgName}-{CADLinkTypeId}-{ViewName}
    以 '{dwgName}-' 為前綴搜尋，避免誤抓含底線的網格 Block。
    (SRS §5.2)
    """
    blocks_obj  = dxf_doc_type.GetProperty("Blocks").GetValue(dxf_doc)
    block_items = blocks_obj.GetType().GetProperty("Items").GetValue(blocks_obj)
    prefix = dwg_name.replace(".dwg", "") + "_dwg-"
    for blk in block_items:
        bn = blk.GetType().GetProperty("Name").GetValue(blk)
        if str(bn).startswith(prefix):
            return blk
    return None


def _get_dwg_name_from_instance(import_instance):
    """從 ImportInstance 取得 DWG 檔名（含副檔名）。"""
    link_type = doc.GetElement(import_instance.GetTypeId())
    return link_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()


def parse_dxf_layers(dxf_path):
    """
    解析 DXF，回傳所有圖層名稱清單（已排序）。
    用於 UI 圖層下拉選單。
    """
    asm          = load_netdxf()
    dxf_doc_type = asm.GetType("netDxf.DxfDocument")
    dxf_doc      = dxf_doc_type.GetMethod(
        "Load", [type(dxf_path)]).Invoke(None, [dxf_path])
    layers_obj   = dxf_doc_type.GetProperty("Layers").GetValue(dxf_doc)
    items        = layers_obj.GetType().GetProperty("Items").GetValue(layers_obj)
    names = []
    for item in items:
        names.append(str(item.GetType().GetProperty("Name").GetValue(item)))
    return sorted(names)


def parse_dxf_texts(dxf_path, layer_name, dwg_name):
    """
    從指定圖層讀取 MText，回傳 list of dict:
      { 'value': str, 'x': float, 'y': float, 'rotation': float }
    座標單位：mm（DXF 原始值）。
    rotation：0/360 → 水平；90 → 垂直。
    (SRS §5.2)
    """
    asm          = load_netdxf()
    dxf_doc_type = asm.GetType("netDxf.DxfDocument")
    mtext_type   = asm.GetType("netDxf.Entities.MText")
    dxf_doc      = dxf_doc_type.GetMethod(
        "Load", [type(dxf_path)]).Invoke(None, [dxf_path])

    block = _get_target_block(dxf_doc, dxf_doc_type, dwg_name)
    if block is None:
        return []

    entities = block.GetType().GetProperty("Entities").GetValue(block)
    results  = []
    for ent in entities:
        et = ent.GetType()
        if not mtext_type.IsAssignableFrom(et):
            continue
        layer_obj = et.GetProperty("Layer").GetValue(ent)
        lname     = str(layer_obj.GetType().GetProperty("Name").GetValue(layer_obj))
        if lname != layer_name:
            continue
        val    = str(et.GetProperty("Value").GetValue(ent))
        pos    = et.GetProperty("Position").GetValue(ent)
        px     = float(pos.GetType().GetProperty("X").GetValue(pos))
        py     = float(pos.GetType().GetProperty("Y").GetValue(pos))
        rot_p  = et.GetProperty("Rotation")
        rot    = float(rot_p.GetValue(ent)) if rot_p else 0.0
        rot    = rot % 360.0
        results.append({"value": val, "x": px, "y": py, "rotation": rot})
    return results


def parse_dxf_geometry(dxf_path, layer_name, dwg_name):
    """
    從指定圖層讀取線段幾何，回傳正規化後的 Line 清單。
    Line 格式：{ 'x1', 'y1', 'x2', 'y2' }，單位 mm。
    - Line       → 直接加入
    - LwPolyline（段數 ≤ 3）→ 拆解為多條 Line
    - LwPolyline（段數 > 3）→ 排除
    - Arc        → 排除
    (SRS §4.5.2；netDxf 中 PolyLine 對應類型為 LwPolyline，頂點屬性為 Vertexes)
    """
    asm          = load_netdxf()
    dxf_doc_type = asm.GetType("netDxf.DxfDocument")
    line_type    = asm.GetType("netDxf.Entities.Line")
    lw_type      = asm.GetType("netDxf.Entities.LwPolyline")
    dxf_doc      = dxf_doc_type.GetMethod(
        "Load", [type(dxf_path)]).Invoke(None, [dxf_path])

    block = _get_target_block(dxf_doc, dxf_doc_type, dwg_name)
    if block is None:
        return []

    entities = block.GetType().GetProperty("Entities").GetValue(block)
    lines    = []

    for ent in entities:
        et = ent.GetType()
        layer_obj = et.GetProperty("Layer").GetValue(ent)
        lname     = str(layer_obj.GetType().GetProperty("Name").GetValue(layer_obj))
        if lname != layer_name:
            continue

        if line_type.IsAssignableFrom(et):
            sp = et.GetProperty("StartPoint").GetValue(ent)
            ep = et.GetProperty("EndPoint").GetValue(ent)
            lines.append({
                "x1": float(sp.GetType().GetProperty("X").GetValue(sp)),
                "y1": float(sp.GetType().GetProperty("Y").GetValue(sp)),
                "x2": float(ep.GetType().GetProperty("X").GetValue(ep)),
                "y2": float(ep.GetType().GetProperty("Y").GetValue(ep)),
            })

        elif lw_type.IsAssignableFrom(et):
            verts_obj = et.GetProperty("Vertexes").GetValue(ent)
            verts = list(verts_obj)
            segs  = len(verts) - 1
            if segs < 1 or segs > 3:
                continue
            for i in range(segs):
                v1 = verts[i];   v2 = verts[i + 1]
                vt = v1.GetType()
                # LwPolylineVertex 座標在 Position (Vector2)
                pos1 = vt.GetProperty("Position").GetValue(v1)
                pos2 = vt.GetProperty("Position").GetValue(v2)
                pt   = pos1.GetType()
                lines.append({
                    "x1": float(pt.GetProperty("X").GetValue(pos1)),
                    "y1": float(pt.GetProperty("Y").GetValue(pos1)),
                    "x2": float(pt.GetProperty("X").GetValue(pos2)),
                    "y2": float(pt.GetProperty("Y").GetValue(pos2)),
                })
        # Arc → 排除（不處理）

    return lines


def cleanup_dxf(dxf_path):
    """刪除暫存 DXF 檔案。"""
    try:
        if dxf_path and os.path.exists(dxf_path):
            os.remove(dxf_path)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# § 3  座標轉換  (SRS §5.7)
# ══════════════════════════════════════════════════════════════════════════════

def get_cad_transform(import_instance):
    """
    回傳 ImportInstance 的 Transform（包含偏移/旋轉/縮放）。
    用於將 DXF 文字座標（CAD 局部座標）轉為 Revit 世界座標。
    注意：Revit API 的 GetInstanceGeometry() 已為世界座標，不需再套此 Transform。
    """
    return import_instance.GetTransform()

def mm_to_feet(mm):
    """mm → Revit 內部單位 feet。"""
    return mm / 304.8

def cm_to_feet(cm):
    """cm → Revit 內部單位 feet。"""
    return cm / 30.48

def cad_mm_to_revit_xyz(x_mm, y_mm, transform, z_feet=0.0):
    """
    DXF 文字座標 (mm, CAD 局部) → Revit 世界座標 (feet)。
    幾何線段已透過 GetInstanceGeometry() 取得世界座標，不經此函式。
    (SRS §5.7)
    """
    pt = XYZ(x_mm / 304.8, y_mm / 304.8, z_feet)
    return transform.OfPoint(pt)

def revit_xyz_to_cm(xyz):
    """XYZ (feet) → (x_cm, y_cm)，用於顯示與距離計算。"""
    return xyz.X * 30.48, xyz.Y * 30.48

def distance_2d_cm(pt_a, pt_b):
    """兩個 (x_cm, y_cm) tuple 的 2D 歐式距離（cm）。(SRS §4.5.5)"""
    import math
    return math.sqrt((pt_a[0] - pt_b[0]) ** 2 + (pt_a[1] - pt_b[1]) ** 2)


# ══════════════════════════════════════════════════════════════════════════════
# § 4  中心線配對演算法  (SRS §4.5.3)
# ══════════════════════════════════════════════════════════════════════════════

ANGLE_TOL   = 1.0    # °
LENGTH_TOL  = 5.0    # mm
MIN_WIDTH   = 20.0   # cm  (= 200 mm)
MAX_WIDTH   = 120.0  # cm  (= 1200 mm)
MIN_OVERLAP = 0.80   # 80%

import math as _math

def _line_length(line):
    """回傳線段長度（mm）。"""
    dx = line["x2"] - line["x1"]
    dy = line["y2"] - line["y1"]
    return _math.sqrt(dx * dx + dy * dy)

def _line_angle_deg(line):
    """回傳線段角度（0~180°，消除方向性）。"""
    dx = line["x2"] - line["x1"]
    dy = line["y2"] - line["y1"]
    a  = _math.degrees(_math.atan2(dy, dx)) % 180.0
    return a

def _ensure_same_direction(l1, l2):
    """
    確保 l2 的方向與 l1 相同（起終點同向）。
    若反向則翻轉 l2，回傳修正後的 l2 dict（不改動原物件）。
    """
    dx1 = l1["x2"] - l1["x1"];  dy1 = l1["y2"] - l1["y1"]
    dx2 = l2["x2"] - l2["x1"];  dy2 = l2["y2"] - l2["y1"]
    if dx1 * dx2 + dy1 * dy2 < 0:
        return {"x1": l2["x2"], "y1": l2["y2"],
                "x2": l2["x1"], "y2": l2["y1"]}
    return l2

def _perpendicular_distance(l1, l2):
    """
    計算兩條平行線之間的垂直距離（mm）。
    取 l2 起點到 l1 所在直線的距離。
    """
    dx = l1["x2"] - l1["x1"];  dy = l1["y2"] - l1["y1"]
    length = _math.sqrt(dx * dx + dy * dy)
    if length < 1e-9:
        return 0.0
    # 法向量：(-dy, dx) / length
    nx = -dy / length;  ny = dx / length
    vx = l2["x1"] - l1["x1"];  vy = l2["y1"] - l1["y1"]
    return abs(vx * nx + vy * ny)

def _projection_overlap_ratio(l1, l2):
    """
    計算兩條平行線在主方向的投影重疊比例（相對於 l1 長度）。
    """
    dx = l1["x2"] - l1["x1"];  dy = l1["y2"] - l1["y1"]
    length = _math.sqrt(dx * dx + dy * dy)
    if length < 1e-9:
        return 0.0
    ux = dx / length;  uy = dy / length
    # l1 投影範圍
    p1s = 0.0;  p1e = length
    # l2 兩端在 l1 方向的投影
    def proj(x, y):
        return (x - l1["x1"]) * ux + (y - l1["y1"]) * uy
    p2s = proj(l2["x1"], l2["y1"])
    p2e = proj(l2["x2"], l2["y2"])
    if p2s > p2e:
        p2s, p2e = p2e, p2s
    overlap = max(0.0, min(p1e, p2e) - max(p1s, p2s))
    return overlap / length


def classify_lines_by_angle(lines):
    """
    依角度分組，回傳 { 'horizontal': [...], 'vertical': [...], 'diagonal': [...] }。
    水平：角度 ±ANGLE_TOL° 以內（含 180°±）
    垂直：角度 90°±ANGLE_TOL° 以內
    (SRS §4.5.3 Step A)
    """
    groups = {"horizontal": [], "vertical": [], "diagonal": []}
    for line in lines:
        a = _line_angle_deg(line)
        if a <= ANGLE_TOL or a >= (180.0 - ANGLE_TOL):
            groups["horizontal"].append(line)
        elif abs(a - 90.0) <= ANGLE_TOL:
            groups["vertical"].append(line)
        else:
            groups["diagonal"].append(line)
    return groups


def find_parallel_pairs(lines):
    """
    在同方向線段中尋找等長平行線對，每條線最多配對一次。
    條件：
      ① 長度誤差 ≤ LENGTH_TOL (mm)
      ② 垂直距離在 MIN_WIDTH*10 ～ MAX_WIDTH*10 mm
      ③ 投影重疊比例 ≥ MIN_OVERLAP
    回傳 list of (line1, line2_aligned)。
    (SRS §4.5.3 Step B)
    """
    used   = set()
    pairs  = []
    min_d  = MIN_WIDTH  * 10.0   # cm → mm
    max_d  = MAX_WIDTH  * 10.0

    for i, l1 in enumerate(lines):
        if i in used:
            continue
        len1 = _line_length(l1)
        best = None;  best_d = float("inf")
        for j, l2 in enumerate(lines):
            if j <= i or j in used:
                continue
            len2 = _line_length(l2)
            if abs(len1 - len2) > LENGTH_TOL:
                continue
            l2a = _ensure_same_direction(l1, l2)
            d   = _perpendicular_distance(l1, l2a)
            if d < min_d or d > max_d:
                continue
            if _projection_overlap_ratio(l1, l2a) < MIN_OVERLAP:
                continue
            if d < best_d:
                best = (j, l2a);  best_d = d
        if best is not None:
            used.add(i);  used.add(best[0])
            pairs.append((l1, best[1]))
    return pairs


def calc_centerline(line1, line2):
    """
    由兩條配對線計算中心線與梁寬。
    回傳 dict:
      { 'x1','y1','x2','y2': float（mm）,
        'cx','cy': float（中心點，mm）,
        'width_cm': float }
    (SRS §4.5.3 Step D)
    """
    mx1 = (line1["x1"] + line2["x1"]) / 2.0
    my1 = (line1["y1"] + line2["y1"]) / 2.0
    mx2 = (line1["x2"] + line2["x2"]) / 2.0
    my2 = (line1["y2"] + line2["y2"]) / 2.0
    cx  = (mx1 + mx2) / 2.0
    cy  = (my1 + my2) / 2.0
    width_mm  = _perpendicular_distance(line1, line2)
    return {
        "x1": mx1, "y1": my1,
        "x2": mx2, "y2": my2,
        "cx": cx,  "cy": cy,
        "width_cm": width_mm / 10.0,
    }


def match_labels_to_centerlines(labels, centerlines):
    """
    反向配對法：以標籤為主動方，找最近的中心線中心點配對。
    若多個標籤搶同一條中心線，保留距離最近者。
    回傳更新後的 centerlines list，每筆新增：
      'label_value'、'label_rot'、'is_unmatched'
    (SRS §4.5.5)
    """
    # 初始化
    for cl in centerlines:
        cl["label_value"]  = ""
        cl["label_rot"]    = 0.0
        cl["is_unmatched"] = True

    # 每個標籤找最近中心線
    assignments = {}  # centerline index → (dist, label)
    for lbl in labels:
        best_i = None;  best_d = float("inf")
        for i, cl in enumerate(centerlines):
            d = _math.sqrt((lbl["x"] - cl["cx"]) ** 2 +
                           (lbl["y"] - cl["cy"]) ** 2)
            if d < best_d:
                best_d = d;  best_i = i
        if best_i is None:
            continue
        if best_i not in assignments or best_d < assignments[best_i][0]:
            assignments[best_i] = (best_d, lbl)

    for i, (_, lbl) in assignments.items():
        centerlines[i]["label_value"]  = lbl["value"]
        centerlines[i]["label_rot"]    = lbl["rotation"]
        centerlines[i]["is_unmatched"] = False

    return centerlines


def match_sizes_to_centerlines(size_labels, centerlines):
    """
    將尺寸標籤（A5-G / A5-B / A5）反向配對至中心線。
    每條中心線新增 'detected_size' 欄位（空字串表示未配對）。
    (SRS §4.5.5 Step 3)
    """
    for cl in centerlines:
        cl["detected_size"] = ""

    assignments = {}
    for lbl in size_labels:
        best_i = None;  best_d = float("inf")
        for i, cl in enumerate(centerlines):
            d = _math.sqrt((lbl["x"] - cl["cx"]) ** 2 +
                           (lbl["y"] - cl["cy"]) ** 2)
            if d < best_d:
                best_d = d;  best_i = i
        if best_i is None:
            continue
        if best_i not in assignments or best_d < assignments[best_i][0]:
            assignments[best_i] = (best_d, lbl)

    for i, (_, lbl) in assignments.items():
        centerlines[i]["detected_size"] = lbl["value"]

    return centerlines


def _direction_label(is_vertical, is_small_beam, label_rot):
    """
    依大梁/小梁與角度回傳方向文字。
    大梁：垂直大梁 / 水平大梁
    小梁：依標籤 rotation 判斷（SRS §4.2.4）
          rot ≈ 90° → 小梁(垂直)；rot ≈ 0°/360° → 小梁(水平)
    """
    if not is_small_beam:
        return u"垂直大梁" if is_vertical else u"水平大梁"
    rot = label_rot % 180.0
    return u"小梁(垂直)" if abs(rot - 90.0) < 10.0 else u"小梁(水平)"


def run_analysis(view, import_instance, layer_config, size_source,
                 csv_path=None, transform=None):
    """
    主分析流程：匯出 DXF → 解析幾何與文字 → 配對 → 回傳 beam_rows。

    layer_config = {
        'girder_v_line':  str,  'girder_v_label': str, 'girder_v_size': str,
        'girder_h_line':  str,  'girder_h_label': str, 'girder_h_size': str,
        'beam_line':      str,  'beam_label':     str, 'beam_size':     str,
    }
    size_source: 'layer' | 'csv' | 'manual'

    回傳 beam_rows list，每筆：
      { 'beam_id', 'direction', 'detected_size',
        'family_type', 'is_manual',
        'center_start_mm', 'center_end_mm' }   # mm，供後續轉 Revit XYZ
    (SRS §4.5)
    """
    dxf_path = export_dxf(doc, view, import_instance)
    if dxf_path is None:
        raise RuntimeError(u"DXF 匯出失敗")

    dwg_name = _get_dwg_name_from_instance(import_instance)
    csv_map  = {}
    if size_source == "csv" and csv_path:
        csv_map = load_csv_size_map(csv_path)

    beam_rows = []

    # ── 三組（垂直大梁、水平大梁、小梁）────────────────────────────────────
    configs = [
        ("girder_v", True,  False),
        ("girder_h", False, False),
        ("beam",     None,  True),
    ]

    for prefix, is_vertical, is_small in configs:
        line_layer  = layer_config.get(prefix + "_line",  "")
        label_layer = layer_config.get(prefix + "_label", "")
        size_layer  = layer_config.get(prefix + "_size",  "")

        if not line_layer:
            continue

        # 幾何：配對中心線
        raw_lines = parse_dxf_geometry(dxf_path, line_layer, dwg_name)
        groups    = classify_lines_by_angle(raw_lines)

        if is_small:
            target_groups = [("horizontal", False), ("vertical", True)]
        elif is_vertical:
            target_groups = [("vertical", True)]
        else:
            target_groups = [("horizontal", False)]

        centerlines = []
        for grp_key, vert in target_groups:
            pairs = find_parallel_pairs(groups[grp_key])
            for l1, l2 in pairs:
                cl = calc_centerline(l1, l2)
                cl["is_vertical_geom"] = vert
                centerlines.append(cl)

        # 標籤配對
        labels = parse_dxf_texts(dxf_path, label_layer, dwg_name) if label_layer else []
        centerlines = match_labels_to_centerlines(labels, centerlines)

        # 尺寸配對
        if size_source == "layer" and size_layer:
            size_lbls   = parse_dxf_texts(dxf_path, size_layer, dwg_name)
            centerlines = match_sizes_to_centerlines(size_lbls, centerlines)
        elif size_source == "manual":
            for cl in centerlines:
                cl["detected_size"] = "{:.1f}".format(cl["width_cm"])

        # 組裝 beam_rows
        for cl in centerlines:
            beam_id = cl.get("label_value", "")
            size_str = cl.get("detected_size", "")

            # CSV 來源：用梁編號查對照表
            if size_source == "csv" and beam_id in csv_map:
                size_str = csv_map[beam_id]

            direction = _direction_label(
                cl.get("is_vertical_geom", False), is_small, cl.get("label_rot", 0.0))

            beam_rows.append({
                "beam_id":        beam_id,
                "direction":      direction,
                "detected_size":  size_str,
                "family_type":    "",
                "is_manual":      cl.get("is_unmatched", True),
                "center_start_mm": (cl["x1"], cl["y1"]),
                "center_end_mm":   (cl["x2"], cl["y2"]),
            })

    return beam_rows


# ══════════════════════════════════════════════════════════════════════════════
# § 5  族群類型自動配對  (SRS §4.2.2)
# ══════════════════════════════════════════════════════════════════════════════

def normalize_size(raw):
    """
    尺寸字串正規化：去括號、轉小寫、統一分隔符為 x。
    '(60X85)' → '60x85'  /  '60*75' → '60x75'
    (SRS §5.3)
    """
    s = raw.strip().lower()
    s = s.replace("(", "").replace(")", "")
    s = re.sub(r"[xX\*×]", "x", s)
    return s

def parse_size_cm(normalized):
    """回傳 (width_cm, depth_cm)，解析失敗回傳 (None, None)。"""
    try:
        parts = normalized.split("x")
        return int(parts[0]), int(parts[1])
    except Exception:
        return None, None

def _extract_numbers(s):
    """從字串擷取所有數字，回傳 tuple，用於尺寸比對。"""
    return tuple(int(n) for n in re.findall(r"\d+", s))

def auto_match_family_type(size_str, all_family_types):
    """
    依尺寸字串自動配對族群類型，回傳第一個符合的 FamilySymbol 名稱（str）或 None。
    比對邏輯：
      1. 將 size_str 正規化後擷取數字 tuple，如 (60, 85)
      2. 對每個族群類型名稱同樣正規化擷取數字
      3. 數字 tuple 完全相符 → 配對成功
    忽略前綴（B/RC）、後綴（cm）、大小寫。
    (SRS §4.2.2)
    """
    norm = normalize_size(size_str)
    target_nums = _extract_numbers(norm)
    if not target_nums:
        return None
    for fs in all_family_types:
        type_norm = normalize_size(fs.Name)
        if _extract_numbers(type_norm) == target_nums:
            return fs.Name
    return None

def auto_match_family_type_name(size_str, type_name_list):
    """
    同 auto_match_family_type，但輸入為名稱清單（字串 list），
    供 DataGrid 下拉使用。
    """
    norm        = normalize_size(size_str)
    target_nums = _extract_numbers(norm)
    if not target_nums:
        return ""
    for name in type_name_list:
        if _extract_numbers(normalize_size(name)) == target_nums:
            return name
    return ""

# 寬度/深度參數別名（SRS §4.3）
_WIDTH_ALIASES = [u"梁寬", u"寬度", u"b", u"width"]
_DEPTH_ALIASES = [u"梁深", u"深度", u"h", u"depth"]

# 快取：避免同族群重複跳出選擇 UI
_param_cache = {}   # family_name → (width_param, depth_param)

def detect_width_depth_params(family_symbol):
    """
    偵測族群的寬度/深度參數名稱。
    回傳 (width_param_name, depth_param_name)，找不到回傳 (None, None)。
    若同時偵測到多個符合參數，跳出 AskUserQuestion 讓使用者選擇一次後快取。
    (SRS §4.3)
    """
    from Autodesk.Revit.DB import StorageType
    fname = family_symbol.Family.Name
    if fname in _param_cache:
        return _param_cache[fname]

    def find_params(aliases):
        matched = []
        for p in family_symbol.Parameters:
            if p.IsReadOnly or p.StorageType != StorageType.Double:
                continue
            pname_lower = p.Definition.Name.lower()
            for alias in aliases:
                if alias.lower() in pname_lower:
                    matched.append(p.Definition.Name)
                    break
        return matched

    w_params = find_params(_WIDTH_ALIASES)
    d_params = find_params(_DEPTH_ALIASES)

    # 若有多個符合，讓使用者選（PyRevit forms）
    def pick_one(candidates, role):
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) == 0:
            return None
        return forms.ask_for_one_item(
            candidates,
            default=candidates[0],
            prompt=u"族群「{}」偵測到多個{}參數，請選擇：".format(fname, role),
            title=u"BEAM_MODELING — 參數選擇"
        )

    w = pick_one(w_params, u"寬度")
    d = pick_one(d_params, u"深度")
    _param_cache[fname] = (w, d)
    return w, d


def load_csv_size_map(csv_path):
    """
    解析 CSV 對照表，回傳 { 梁編號（原始大小寫）: 正規化尺寸字串 }。
    編碼 UTF-8（支援 BOM），第一行為標題略過。
    支援尺寸格式：(60X85)、60X85、60x85、60*75 等。
    (SRS §5.4, §6)
    """
    result = {}
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
        for row in lines[1:]:   # 略過標題
            row = row.strip()
            if not row:
                continue
            parts = row.split(",")
            if len(parts) < 2:
                continue
            beam_id  = parts[0].strip()
            size_raw = parts[1].strip()
            result[beam_id] = normalize_size(size_raw)
    except Exception as e:
        raise RuntimeError(u"CSV 解析失敗：{}".format(str(e)))
    return result


# ══════════════════════════════════════════════════════════════════════════════
# § 6  DirectShape 暫時顯示  (SRS §4.2.5)
# ══════════════════════════════════════════════════════════════════════════════

_temp_direct_shapes = []   # ElementId list

def show_centerlines_as_direct_shapes(beam_rows, view, import_instance):
    """
    以 DirectShape 在模型中顯示偵測到的梁中心線（暫時顯示）。
    配色規則（在兩種背景均清晰）：
      ● 亮綠 RGB(0,220,0)   — 已配對標籤
      ● 亮紅 RGB(255,60,60) — 無對應標籤
    ElementId 存入 _temp_direct_shapes，供後續清除。
    (SRS §4.2.5)
    """
    global _temp_direct_shapes

    tf     = get_cad_transform(import_instance)
    cat_id = ElementId(int(BuiltInCategory.OST_GenericModel))

    # 預建兩套 OverrideGraphicSettings
    solid_id = get_solid_fill_pattern_id(doc)

    def make_ogs(r, g, b):
        ogs = OverrideGraphicSettings()
        c   = Color(r, g, b)
        ogs.SetProjectionLineColor(c)
        ogs.SetSurfaceForegroundPatternColor(c)
        ogs.SetSurfaceForegroundPatternVisible(True)
        if solid_id and solid_id.Value > 0:
            ogs.SetSurfaceForegroundPatternId(solid_id)
        return ogs

    ogs_matched   = make_ogs(0, 220, 0)    # 亮綠：已配對
    ogs_unmatched = make_ogs(255, 60, 60)  # 亮紅：未配對

    t = Transaction(doc, u"BEAM_MODELING — 顯示中心線")
    t.Start()
    for row in beam_rows:
        try:
            sx, sy = row["center_start_mm"]
            ex, ey = row["center_end_mm"]
            pt_s = cad_mm_to_revit_xyz(sx, sy, tf, 0.0)
            pt_e = cad_mm_to_revit_xyz(ex, ey, tf, 0.0)

            if pt_s.DistanceTo(pt_e) < 1e-6:
                continue

            curve = Line.CreateBound(pt_s, pt_e)
            ds    = DirectShape.CreateElement(doc, cat_id)
            ds.SetShape([curve])

            # 依配對狀態套用顏色覆寫
            ogs = ogs_unmatched if row.get("is_unmatched", True) else ogs_matched
            view.SetElementOverrides(ds.Id, ogs)

            _temp_direct_shapes.append(ds.Id)
        except Exception:
            continue
    t.Commit()


def clear_direct_shapes():
    """
    刪除所有暫存 DirectShape，並清空清單。
    於「確認建立」或視窗關閉時呼叫。
    (SRS §4.2.5)
    """
    global _temp_direct_shapes
    if not _temp_direct_shapes:
        return
    t = Transaction(doc, u"BEAM_MODELING — 清除暫存中心線")
    t.Start()
    for eid in _temp_direct_shapes:
        try:
            if doc.GetElement(eid) is not None:
                doc.Delete(eid)
        except Exception:
            pass
    t.Commit()
    _temp_direct_shapes = []


# ══════════════════════════════════════════════════════════════════════════════
# § 7  建立結構樑  (SRS §5.6)
# ══════════════════════════════════════════════════════════════════════════════

def create_beams(beam_rows, view, level, import_instance, write_param_name=None):
    """
    依確認表建立結構樑。
    - 族群類型名稱為空者略過（SRS §4.2.7）
    - write_param_name 不為 None 時，將梁編號寫入該實例參數（SRS §4.2.6）
    回傳 (created_elements, manual_element_ids, skipped_count)
      created_elements:   成功建立的 Element list
      manual_element_ids: 其中 is_manual=True 的 ElementId list
      skipped_count:      略過數量（族群類型為空）
    (SRS §5.6)
    """
    from Autodesk.Revit.DB.Structure import StructuralType

    # 建立族群類型名稱 → FamilySymbol 的查找表
    all_symbols = get_structural_beam_types()
    symbol_map  = {fs.Name: fs for fs in all_symbols}

    # 取得 CAD Transform（DXF 文字座標轉 Revit 世界座標）
    tf = get_cad_transform(import_instance)

    # 樓層 Z 高度（feet）
    z_feet = level.Elevation

    created_elements   = []
    manual_element_ids = []
    skipped_count      = 0

    # Transaction 由 PyRevit 環境自行管理（非 MCP 環境）
    t = Transaction(doc, u"BEAM_MODELING — 建立結構樑")
    t.Start()
    for row in beam_rows:
            type_name = row.get("family_type", "")
            if not type_name:
                skipped_count += 1
                continue

            fs = symbol_map.get(type_name)
            if fs is None:
                skipped_count += 1
                continue

            # 確保族群類型已啟用
            if not fs.IsActive:
                fs.Activate()
                doc.Regenerate()

            # 中心線起終點：DXF mm 座標 → Revit XYZ (feet)
            sx, sy = row["center_start_mm"]
            ex, ey = row["center_end_mm"]
            pt_start = cad_mm_to_revit_xyz(sx, sy, tf, z_feet)
            pt_end   = cad_mm_to_revit_xyz(ex, ey, tf, z_feet)

            # 起終點相同時略過（零長度線）
            if pt_start.DistanceTo(pt_end) < 1e-6:
                skipped_count += 1
                continue

            try:
                curve = Line.CreateBound(pt_start, pt_end)
                beam  = doc.Create.NewFamilyInstance(
                    curve, fs, level, StructuralType.Beam)

                # 寫入梁編號至實例參數
                if write_param_name and row.get("beam_id"):
                    param = beam.LookupParameter(write_param_name)
                    if param and not param.IsReadOnly:
                        param.Set(row["beam_id"])

                created_elements.append(beam)
                if row.get("is_manual", False):
                    manual_element_ids.append(beam.Id)

            except Exception:
                skipped_count += 1

    t.Commit()

    return created_elements, manual_element_ids, skipped_count


# ══════════════════════════════════════════════════════════════════════════════
# § 8  圖形覆寫  (SRS §4.4.1)
# ══════════════════════════════════════════════════════════════════════════════

def apply_manual_override(view, element_ids):
    """
    對 is_manual=True 的樑套用 OverrideGraphicSettings：
    實心填滿，顏色 RGB(255, 128, 64)。
    (SRS §4.4.1)
    """
    if not element_ids:
        return

    solid_id = get_solid_fill_pattern_id(doc)
    fill_color = Color(255, 128, 64)

    ogs = OverrideGraphicSettings()
    ogs.SetSurfaceForegroundPatternColor(fill_color)
    ogs.SetSurfaceForegroundPatternVisible(True)
    if solid_id and solid_id.Value > 0:
        ogs.SetSurfaceForegroundPatternId(solid_id)

    t = Transaction(doc, u"BEAM_MODELING — 圖形覆寫")
    t.Start()
    for eid in element_ids:
        view.SetElementOverrides(eid, ogs)
    t.Commit()


# ══════════════════════════════════════════════════════════════════════════════
# § 9  WPF 主視窗
# ══════════════════════════════════════════════════════════════════════════════

import System.Collections.ObjectModel as ObsCol
from System.ComponentModel import INotifyPropertyChanged
from System.Windows import Visibility

class BeamRow(object):
    """DataGrid 一列的資料模型。"""
    def __init__(self, beam_id, direction, detected_size,
                 family_type, is_manual,
                 center_start_mm, center_end_mm):
        self.BeamId          = beam_id
        self.Direction       = direction
        self.DetectedSize    = detected_size
        self.FamilyTypeName  = family_type
        self.IsManual        = is_manual
        self.StatusText      = u"⚠️ 未配對" if is_manual else u"✅ 已配對"
        self.center_start_mm = center_start_mm
        self.center_end_mm   = center_end_mm


class BeamModelingWindow(object):
    """主視窗：載入 MainWindow.xaml，綁定所有事件 handler。"""

    def __init__(self, view, level):
        self._view           = view
        self._level          = level
        self._import_inst    = None    # 選定的 ImportInstance
        self._dxf_path       = None
        self._csv_path       = None
        self._cad_link_list  = []      # list of {'instance':..., 'name':...}
        self._all_type_names = []      # 所有結構樑族群類型名稱
        self._beam_rows_obs  = ObsCol.ObservableCollection[object]()

        # 載入 XAML
        import System.Windows.Markup as markup
        xaml_path = os.path.join(_XAML_DIR, "MainWindow.xaml")
        with open(xaml_path, "r", encoding="utf-8") as f:
            self._win = markup.XamlReader.Parse(f.read())

        # 控件參照
        w = self._win
        self._cmb_cad_link   = w.FindName("CmbCadLink")
        self._txt_level      = w.FindName("TxtCurrentLevel")
        self._cmb_layers = {
            "girder_v_line":  w.FindName("CmbLayerGirderVLine"),
            "girder_v_label": w.FindName("CmbLayerGirderVLabel"),
            "girder_v_size":  w.FindName("CmbLayerGirderVSize"),
            "girder_h_line":  w.FindName("CmbLayerGirderHLine"),
            "girder_h_label": w.FindName("CmbLayerGirderHLabel"),
            "girder_h_size":  w.FindName("CmbLayerGirderHSize"),
            "beam_line":      w.FindName("CmbLayerBeamLine"),
            "beam_label":     w.FindName("CmbLayerBeamLabel"),
            "beam_size":      w.FindName("CmbLayerBeamSize"),
        }
        self._rb_from_layer = w.FindName("RbSizeFromLayer")
        self._rb_from_csv   = w.FindName("RbSizeFromCsv")
        self._rb_manual     = w.FindName("RbSizeManual")
        self._panel_csv     = w.FindName("PanelCsv")
        self._txt_csv_path  = w.FindName("TxtCsvPath")
        self._dg_beams      = w.FindName("DgBeams")
        self._btn_analyze   = w.FindName("BtnAnalyze")
        self._btn_confirm   = w.FindName("BtnConfirm")
        self._btn_add_type  = w.FindName("BtnAddType")
        self._chk_write     = w.FindName("ChkWriteParam")
        self._cmb_param     = w.FindName("CmbTargetParam")
        self._txt_status    = w.FindName("TxtStatus")

        # DataGrid 資料來源
        self._dg_beams.ItemsSource = self._beam_rows_obs

        # 族群類型清單
        self._all_type_names = [fs.Name for fs in get_structural_beam_types()]

        # 初始化
        self._init_cad_links()
        self._txt_level.Text = u"目前樓層：{}".format(level.Name if level else u"—")

        # 事件綁定
        self._cmb_cad_link.SelectionChanged  += self._on_cad_link_changed
        w.FindName("BtnAnalyze").Click        += self._on_analyze
        w.FindName("BtnConfirm").Click        += self._on_confirm
        w.FindName("BtnAddType").Click        += self._on_add_type
        w.FindName("BtnBrowseCsv").Click      += self._on_browse_csv
        self._rb_from_layer.Checked           += self._on_size_source_changed
        self._rb_from_csv.Checked             += self._on_size_source_changed
        self._rb_manual.Checked               += self._on_size_source_changed
        self._chk_write.Checked               += self._on_write_param_changed
        self._chk_write.Unchecked             += self._on_write_param_changed
        self._win.Closed                      += self._on_closed

    # ── 初始化 ────────────────────────────────────────────────────────────────

    def _init_cad_links(self):
        """填充 CAD 連結下拉選單，預設選第一個。"""
        self._cad_link_list = get_cad_links(self._view)
        self._cmb_cad_link.Items.Clear()
        for item in self._cad_link_list:
            self._cmb_cad_link.Items.Add(item["name"])
        if self._cad_link_list:
            self._cmb_cad_link.SelectedIndex = 0
            self._import_inst = self._cad_link_list[0]["instance"]
            self._populate_layer_combos(self._import_inst)

    def _populate_layer_combos(self, import_instance):
        """取得圖層清單，填充九個下拉選單並自動預填。"""
        try:
            layer_names = get_all_layers(import_instance)
        except Exception:
            layer_names = []

        for cmb in self._cmb_layers.values():
            cmb.Items.Clear()
            cmb.Items.Add(u"")          # 空白選項（不選）
            for n in layer_names:
                cmb.Items.Add(n)

        self._autofill_layers(layer_names)

    def _autofill_layers(self, layer_names):
        """
        依 SRS §4.1.3 關鍵字規則自動預填圖層下拉選單。
        規則：
          梁線  A2（不含_SB）→ 大梁垂直/水平；A2_SB → 小梁
          編號  AN-G → 垂直；AN-B → 水平；AN（不含-G/-B）→ 小梁
          尺寸  A5-G → 垂直；A5-B → 水平；A5（不含-G/-B/-COL/-SL）→ 小梁
        """
        def pick(keywords, exclude=None):
            for n in layer_names:
                nu = n.upper()
                if exclude and any(e.upper() in nu for e in exclude):
                    continue
                if any(k.upper() in nu for k in keywords):
                    return n
            return u""

        mapping = {
            "girder_v_line":  pick(["A2"],    exclude=["_SB"]),
            "girder_h_line":  pick(["A2"],    exclude=["_SB"]),
            "beam_line":      pick(["A2_SB"]),
            "girder_v_label": pick(["AN-G"]),
            "girder_h_label": pick(["AN-B"]),
            "beam_label":     pick(["AN"],    exclude=["AN-G", "AN-B", "AN-COL", "AN-SL"]),
            "girder_v_size":  pick(["A5-G"]),
            "girder_h_size":  pick(["A5-B"]),
            "beam_size":      pick(["A5"],    exclude=["A5-G", "A5-B", "A5-COL", "A5-SL"]),
        }
        for key, val in mapping.items():
            cmb = self._cmb_layers.get(key)
            if cmb and val:
                idx = cmb.Items.IndexOf(val)
                if idx >= 0:
                    cmb.SelectedIndex = idx

    # ── 事件 Handler ─────────────────────────────────────────────────────────

    def _on_cad_link_changed(self, sender, e):
        """切換 CAD 連結 → 重新讀取圖層。"""
        idx = self._cmb_cad_link.SelectedIndex
        if idx < 0 or idx >= len(self._cad_link_list):
            return
        self._import_inst = self._cad_link_list[idx]["instance"]
        self._populate_layer_combos(self._import_inst)

    def _on_size_source_changed(self, sender, e):
        """切換尺寸來源：控制 CSV 瀏覽列與尺寸下拉啟用狀態。"""
        is_layer = self._rb_from_layer.IsChecked
        is_csv   = self._rb_from_csv.IsChecked
        # CSV 瀏覽列顯示/隱藏
        self._panel_csv.Visibility = (
            Visibility.Visible if is_csv else Visibility.Collapsed)
        # 尺寸圖層下拉：只有「從圖層讀取」時啟用
        for key in ("girder_v_size", "girder_h_size", "beam_size"):
            self._cmb_layers[key].IsEnabled = bool(is_layer)

    def _on_browse_csv(self, sender, e):
        """開啟 .csv 檔案選擇對話框。"""
        dlg = WinForms.OpenFileDialog()
        dlg.Filter = u"CSV 檔案 (*.csv)|*.csv"
        dlg.Title  = u"選擇梁尺寸對照表"
        if dlg.ShowDialog() == WinForms.DialogResult.OK:
            self._csv_path = dlg.FileName
            self._txt_csv_path.Text = self._csv_path

    def _on_analyze(self, sender, e):
        """
        執行分析：
        1. 組裝 layer_config
        2. 呼叫 run_analysis() → 取得 beam_rows
        3. 自動配對族群類型
        4. 填充 DataGrid
        5. 顯示 DirectShape 中心線
        6. 啟用「確認建立」與「新增梁類型」
        """
        if self._import_inst is None:
            MessageBox.Show(u"請先選擇 CAD 連結", u"BEAM_MODELING", MessageBoxButton.OK)
            return

        self._txt_status.Text = u"分析中..."
        self._btn_analyze.IsEnabled = False

        try:
            layer_config = {k: (cmb.SelectedItem or u"")
                            for k, cmb in self._cmb_layers.items()}

            size_source = "layer"
            if self._rb_from_csv.IsChecked:
                size_source = "csv"
            elif self._rb_manual.IsChecked:
                size_source = "manual"

            rows = run_analysis(
                self._view, self._import_inst,
                layer_config, size_source, self._csv_path)

            # 自動配對族群類型
            for row in rows:
                matched = auto_match_family_type_name(
                    row["detected_size"], self._all_type_names)
                row["family_type"] = matched
                if matched:
                    row["is_manual"] = False   # 有配對到 → 非手動

            # 填充 DataGrid
            self._beam_rows_obs.Clear()
            for row in rows:
                self._beam_rows_obs.Add(BeamRow(
                    beam_id          = row.get("beam_id", ""),
                    direction        = row.get("direction", ""),
                    detected_size    = row.get("detected_size", ""),
                    family_type      = row.get("family_type", ""),
                    is_manual        = row.get("is_manual", True),
                    center_start_mm  = row["center_start_mm"],
                    center_end_mm    = row["center_end_mm"],
                ))

            # 暫存 beam_rows 供確認建立使用
            self._beam_rows = rows

            # DirectShape 中心線顯示
            clear_direct_shapes()
            show_centerlines_as_direct_shapes(rows, self._view, self._import_inst)

            # 啟用按鈕
            self._btn_confirm.IsEnabled  = True
            self._btn_add_type.IsEnabled = True
            self._chk_write.IsEnabled    = True

            matched_n   = sum(1 for r in rows if not r.get("is_manual", True))
            unmatched_n = len(rows) - matched_n
            self._txt_status.Text = u"分析完成：共 {} 條中心線（✅{} ⚠️{}）".format(
                len(rows), matched_n, unmatched_n)

        except Exception as ex:
            MessageBox.Show(
                u"分析失敗：{}".format(str(ex)),
                u"BEAM_MODELING", MessageBoxButton.OK)
            self._txt_status.Text = u"分析失敗"
        finally:
            self._btn_analyze.IsEnabled = True

    def _on_confirm(self, sender, e):
        """
        確認建立：
        1. 從 DataGrid 讀回使用者修改後的族群類型
        2. 清除 DirectShape
        3. 建立結構樑
        4. 套用橘色覆寫（手動選取者）
        5. 顯示結果摘要
        6. 關閉視窗
        """
        # 將 DataGrid 目前值同步回 beam_rows
        for i, br in enumerate(self._beam_rows_obs):
            if i < len(self._beam_rows):
                self._beam_rows[i]["family_type"] = br.FamilyTypeName
                self._beam_rows[i]["is_manual"]   = br.IsManual

        # 清除中心線
        clear_direct_shapes()

        # 寫入參數名稱
        write_param = None
        if self._chk_write.IsChecked and self._cmb_param.SelectedItem:
            write_param = str(self._cmb_param.SelectedItem)

        try:
            created, manual_ids, skipped = create_beams(
                self._beam_rows, self._view, self._level,
                self._import_inst, write_param)

            # 圖形覆寫
            if manual_ids:
                apply_manual_override(self._view, manual_ids)

            # 結果摘要（SRS §4.4.2）
            param_msg = u""
            if write_param:
                param_msg = u"\n  已將梁編號寫入參數「{}」".format(write_param)

            msg = (u"建立完成\n\n"
                   u"  ✅ 成功建立：{} 隻\n"
                   u"      其中手動選取：{} 隻（已標示橘色）\n\n"
                   u"  ⚠️ 略過（未找到族群類型）：{} 根{}"
                   ).format(len(created), len(manual_ids), skipped, param_msg)

            MessageBox.Show(msg, u"BEAM_MODELING — 建立完成", MessageBoxButton.OK)
            self._win.Close()

        except Exception as ex:
            MessageBox.Show(
                u"建立失敗：{}".format(str(ex)),
                u"BEAM_MODELING", MessageBoxButton.OK)

    def _on_add_type(self, sender, e):
        """開啟 AddTypeDialog，建立後重新整理族群類型清單與 DataGrid 下拉。"""
        # 取選取列的尺寸字串作為建議值
        selected = self._dg_beams.SelectedItem
        suggested = selected.DetectedSize if selected else u""

        dlg = AddTypeDialog(self._win, suggested, self._all_type_names)
        dlg.ShowDialog()

        if dlg.result_type_name:
            # 重新讀取族群類型清單
            self._all_type_names = [fs.Name for fs in get_structural_beam_types()]
            # 若選取列的尺寸可以配對新類型，自動選中
            if selected and dlg.result_type_name:
                selected.FamilyTypeName = dlg.result_type_name
                selected.IsManual       = False
                selected.StatusText     = u"✅ 已配對"
            self._txt_status.Text = u"已新增族群類型：{}".format(dlg.result_type_name)

    def _on_write_param_changed(self, sender, e):
        """勾選寫入參數時，讀取並填充可用的文字實例參數清單。"""
        is_checked = bool(self._chk_write.IsChecked)
        self._cmb_param.IsEnabled = is_checked
        if not is_checked:
            return
        # 取所有族群的字串參數聯集
        all_params = set()
        for fs in get_structural_beam_types():
            for pn in get_string_instance_params(fs):
                all_params.add(pn)
        self._cmb_param.Items.Clear()
        for pn in sorted(all_params):
            self._cmb_param.Items.Add(pn)
        if self._cmb_param.Items.Count > 0:
            self._cmb_param.SelectedIndex = 0

    def _on_closed(self, sender, e):
        """視窗關閉：清除 DirectShape 與暫存 DXF。"""
        clear_direct_shapes()
        cleanup_dxf(self._dxf_path)

    def Show(self):
        self._win.ShowDialog()


# ══════════════════════════════════════════════════════════════════════════════
# § 10  新增梁類型彈窗  (SRS §4.3)
# ══════════════════════════════════════════════════════════════════════════════

class AddTypeDialog(Window):
    """
    新增梁類型彈窗：複製現有族群類型並修改尺寸參數。
    """

    def __init__(self, owner, suggested_size_str, all_family_types):
        self._result_type_name = None   # 建立成功後回傳新類型名稱
        self._all_family_types = all_family_types
        self._suggested_size   = suggested_size_str

        xaml_path = os.path.join(_XAML_DIR, "AddTypeDialog.xaml")
        with open(xaml_path, "r", encoding="utf-8") as f:
            import System.Windows.Markup as markup
            win = markup.XamlReader.Parse(f.read())

        self._win              = win
        self._cmb_source       = win.FindName("CmbSourceType")
        self._txt_suggested    = win.FindName("TxtSuggestedName")
        self._txt_name         = win.FindName("TxtTypeName")
        self._txt_width        = win.FindName("TxtWidthCm")
        self._txt_depth        = win.FindName("TxtDepthCm")

        win.Owner = owner
        win.FindName("BtnOk").Click += self.BtnOk_Click

        self._init(suggested_size_str)

    def _init(self, size_str):
        """填充複製來源下拉，自動帶入建議名稱與尺寸。"""
        pass

    def BtnOk_Click(self, sender, e):
        """
        1. 驗證輸入
        2. 複製族群類型（DuplicateType）
        3. 寫入寬度/深度參數
        4. 回傳新類型名稱
        """
        pass

    @property
    def result_type_name(self):
        return self._result_type_name

    def ShowDialog(self):
        self._win.ShowDialog()


# ══════════════════════════════════════════════════════════════════════════════
# § 11  進入點
# ══════════════════════════════════════════════════════════════════════════════

def main():
    view, level = check_active_view()
    if view is None:
        return
    win = BeamModelingWindow(view, level)
    win.Show()

main()
