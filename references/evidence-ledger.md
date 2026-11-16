# 進階操作：命令列與引用依據

這份文件供手動操作程式或維護工具時使用。一般使用流程見 [README](../README.md)。

## 手動執行命令

以下指令從 skill 資料夾執行，將 D:/我的論文 換成自己的論文路徑。需要 Python 3.10 以上與 scripts/requirements.txt 中的 PyMuPDF。

先掃描引用與來源 PDF 候選：

```sh
python scripts/highlight_citations.py scan --root "D:/我的論文" --entry thesis.tex --bib references.bib --pdf-dir "參考論文"
```

掃描會產生 citation_evidence.json。候選檔案仍需閱讀標題、作者與版本確認；再逐筆核對引用、填入真實原句及判定，才能畫線。

先驗證原句能否定位，再產生標註副本：

```sh
python scripts/highlight_citations.py highlight --root "D:/我的論文" --dry-run
python scripts/highlight_citations.py highlight --root "D:/我的論文"
```

若已要求直接更新專案內的來源 PDF：

```sh
python scripts/highlight_citations.py highlight --root "D:/我的論文" --in-place
```

dry-run 不會寫入 PDF 或報告。正式執行的報告位於專案內 annotated_papers/run-*；另存模式的標註副本也在該處。

## 引用依據記錄什麼？

citation_evidence.json 中，papers 依書目引用鍵記錄來源 PDF 路徑、標題及 DOI；citations 記錄各筆引用位置與原文依據。

| 欄位 | 內容 |
| --- | --- |
| id | 掃描產生的引用識別碼，請保留 |
| cite_key | 書目引用鍵 |
| source、line、context | 論文檔案、行號與引用上下文 |
| review.status、review.note | 支持關係判定及說明 |
| evidence | 一或多段原文，各自指定 page、quote 與 note |

page 是 PDF 檢視器由 1 起算的實體頁序，quote 必須是該頁實際出現的來源文字。跨頁段落拆開記錄，中文改寫應連到原始來源語言的段落。

下列是合成範例，示意單一引用紀錄的格式：

```json
{
  "id": "generated-by-scan",
  "cite_key": "example",
  "source": "sections/introduction.tex",
  "line": 12,
  "context": "The three groups were measured separately.",
  "review": {
    "status": "supported",
    "note": "The source describes three separately measured groups."
  },
  "evidence": [
    {
      "page": 2,
      "quote": "The sample includes three groups, measured separately.",
      "note": "Replace with the actual wording from the source PDF."
    }
  ]
}
```

沒有找到相關原文時，evidence 留空並列為待處理；設定 supported 不會讓程式判定語意正確。原文支持關係需要閱讀核對。

## 完整顏色對照

| 判定 | 顏色 | 意義 |
| --- | --- | --- |
| supported | 黃色 | 引用內容獲原文支持 |
| partial | 橘色 | 只有部分支持，需要釐清 |
| inferred | 紫色 | 作者推論，原文未直接提出該結論 |
| unsupported | 紅色 | 未獲支持；只有存在相關反證或限制段落時才標註該段 |
| unreviewed | 灰色 | 支持關係尚未判定 |

同頁同段原文共用一個標註，註解列出各筆引用的個別判定。共用顏色優先順序是紅、橘、紫、灰、黃，表示該段連結的引用中需要注意的狀態。一筆引用可有多段原文，因此標註數量與引用筆數可能不同。

## 如何判讀執行結果？

matched 表示原句已定位，highlighted 表示標註已儲存。這兩者都不代表學術上的支持關係已通過。

新增或改寫的引用、缺少 PDF、原句找不到、頁碼不正確、檔案被鎖定及空白依據都需要處理。非零結束碼表示仍有待處理事項，請閱讀執行報告。

直接標註模式中，每篇的所有已填原句均通過才寫入。存檔先經暫存 PDF 驗證，保留頁面文字與其他批註；重跑會替換本工具以 thesis-citation: 識別的批註。

不同書目鍵若指向同一 PDF，直接標註模式會拒絕寫入，以免其中一個鍵的標註覆蓋另一個。這與同一書目鍵在多個位置被引用不同；後者會正常合併。

重新掃描會保留上下文未變動的依據，把改變的紀錄移入封存。仍需重新閱讀受影響的完整主張；局部引用識別碼相同不代表周圍文字與來源版本均未變。刪除引用或失去有效依據後，也須檢查先前已寫入的標註是否仍適用。

## 測試

在 skill 資料夾執行：

```sh
python -m unittest discover -s scripts -p test_highlight_citations.py -v
```

測試使用臨時建立的合成 LaTeX、BibTeX 與 PDF，不需要真實論文或 pytest。這些測試驗證標註與錯誤處理的程式行為，無法證明真實引用的學術支持關係。

程式處理常見的單組引用命令；自訂巨集、多組 multicites、條件編譯、includeonly、BibTeX 字串巨集需要額外檢查。它也不會自行從翻譯推導原句、執行 OCR、定位圖片內容或監控檔案變動。

PDF 功能使用 [PyMuPDF](https://pymupdf.readthedocs.io/en/latest/about.html)，第三方授權資訊見官方文件。
