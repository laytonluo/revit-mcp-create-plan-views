# 專案說明 — CREATE_PLAN_VIEWS

## 觸發指令

使用者輸入 `CREATE_PLAN_VIEWS` 時，立即讀取 `.claude/commands/CREATE_PLAN_VIEWS.md` 並依照其中的流程逐步執行，無需任何額外說明。

## 注意事項

- 此專案透過 Revit MCP（`mcp__revit-mcp__send_code_to_revit`）控制 Revit
- 所有送入 Revit 的程式碼均為 **C#**
- 執行前請確認 Revit 已開啟且 MCP Server 連線正常
- 詳細需求規格請參閱 `SRS_CREATE_PLAN_VIEWS.md`
