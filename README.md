# revit-mcp-create-plan-views

透過 **Claude Code + Revit MCP** 批次創建 Revit 平面視圖的 AI 輔助工具。

---

## 功能說明

在 Revit 專案中，依照樓層批次建立指定類型的平面視圖（Floor Plan、Structural Plan、Reflected Ceiling Plan），並自動依命名規則套用視圖名稱。

### 主要特色

- **互動式選取**：透過 Claude Code 對話式介面選擇視圖類別與類型
- **自動命名解析**：從 ViewFamilyType 名稱自動解析前綴與後綴
- **智慧樓層分組**：自動將樓層分為地上層、屋突層、地下層、獨立樓層
- **防重複保護**：已存在的視圖自動略過，不會覆蓋

---

## 執行環境

| 項目 | 需求 |
|------|------|
| Revit | 2024 以上（`ElementId.Value` API） |
| Claude Code | 桌面 App（含 Revit MCP 連線） |
| Revit MCP | [revit-mcp](https://github.com/revit-mcp) 伺服器需已啟動 |

---

## 使用方式

1. 開啟 Revit 並啟動 Revit MCP Server
2. 在 Claude Code 輸入：

```
CREATE_PLAN_VIEWS
```

3. 依照互動步驟完成：
   - 選擇視圖類別（Floor Plan / Structural Plan / Ceiling Plan）
   - 選擇 View Type
   - 確認樓層清單與視圖命名預覽
   - 執行批次創建

---

## 視圖命名規則

ViewFamilyType 名稱自動解析為前綴與後綴：

| ViewFamilyType 名稱 | 命名格式 | 範例 |
|--------------------|---------|------|
| `結構平面` | `{樓層}-結構平面` | `1FL-結構平面` |
| `0A-結構平面底圖` | `{樓層}-結構平面底圖` | `1FL-結構平面底圖` |
| `0A-領標版-結構平面` | `領標版-{樓層}-結構平面` | `領標版-1FL-結構平面` |

---

## 樓層自動分組

| 群組 | 判斷規則 | 預設 |
|------|---------|------|
| 地上層 | 名稱首字元為數字（0–9） | ✅ 納入 |
| 屋突層 | 名稱開頭為大寫 `R` | ✅ 納入 |
| 地下層 | 名稱開頭為大寫 `B` | ✅ 納入 |
| 獨立樓層 | 以上三類以外（如 `GL`） | ❌ 排除 |

---

## 檔案結構

```
.
├── .claude/
│   ├── commands/
│   │   └── CREATE_PLAN_VIEWS.md   # Skill 主流程定義
│   └── settings.json              # MCP 工具權限設定
├── revit_code/
│   ├── get_data.cs                # STEP 1：讀取 Levels + ViewFamilyTypes
│   └── create_views.cs            # STEP 7：批次創建視圖
├── CLAUDE.md                      # 專案說明與觸發設定
├── SRS_CREATE_PLAN_VIEWS.md       # 需求規格文件
└── README.md
```

---

## 相關專案

- **PyRevit 版本**：同功能的 PyRevit 按鈕版本（WPF 對話框，無需 Claude Code）
  → [`CreatePlanViews.extension`](../CreatePlanViews.extension)

---

## License

MIT
