"""研报正文抽取(两段式的"文字层")。

实测纪律(详见原型踩坑):
- 正文用 PyMuPDF(fitz),又快又准,中文研报基本能干净抽出。
- 别用 pdftotext(poppler):很多研报是 Aspose 生成、嵌双字体(无 ToUnicode 的那份会吐乱码)。
- 图表内的数字文字层抓不到 → 由 SKILL 层定点读图补全(标注"图内读数,可能±误差")。
"""


def pdf_to_text(path):
    """抽取整篇 PDF 文字层,按页拼接(带页码锚)。"""
    import fitz  # PyMuPDF,延迟导入

    doc = fitz.open(path)
    try:
        return "".join(f"\n===第{i + 1}页===\n" + doc[i].get_text("text") for i in range(doc.page_count))
    finally:
        doc.close()
