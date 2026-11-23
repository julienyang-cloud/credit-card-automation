"""帳單解析：依銀行別規則，從 PDF 文字層或 OCR 取得繳款截止日與應繳金額。

數位產生的 PDF 優先讀文字層（數字精準、不會有 OCR 誤判）；
文字層是圖形或編碼混亂的銀行才退回 OCR，並針對該行帳單區塊裁切以提高辨識率。

回傳狀態：
  ok          金額、最低應繳金額、繳款截止日都取得，且 OCR 信心足夠
  need_review 缺少最低應繳金額、缺少日期/金額，或 OCR 信心不足
"""
import os
import re

import fitz
import pytesseract
from PIL import Image, ImageOps

import config

pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

DATE_SLASH = re.compile(r'(\d{3,4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})')
DATE_CN = re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日')
NUMBER = re.compile(r'\d{1,3}(?:,\s?\d{3})+|\d+')

# OCR 平均信心值低於此門檻就標記 need review
CONFIDENCE_THRESHOLD = 60.0

# region: 相對於整頁的比例 (left, top, right, bottom)
BANK_RULES = {
    'CTBC': {
        'method': 'ocr', 'region': (0.0, 0.0, 0.5, 0.5), 'psm': 3, 'dpi': 200,
        'due_labels': ['繳款截止'],
        'amount_labels': ['本期應繳總金額'],
        'min_labels': ['最低應繳總金額'],
    },
    'SinoPac': {
        'method': 'ocr', 'region': (0.0, 0.0, 1.0, 1.0), 'psm': 3, 'dpi': 300,
        'due_labels': ['繳款截止日'],
        'amount_labels': ['本期應繳總金額', '本期金額合計'],
        'min_labels': ['最低應繳金額'],
    },
    'Taishin': {
        'method': 'text',
        'due_labels': ['繳款截止日'],
        'amount_labels': ['本期累計應繳金額'],
        'min_labels': ['本期最低應繳金額'],
    },
    'Union': {
        'method': 'ocr', 'region': (0.0, 0.0, 1.0, 0.5), 'psm': 3, 'dpi': 200,
        'due_labels': ['繳款截止日'],
        'amount_labels': ['本期應繳總金'],   # OCR 有時把「額」認成「客」
        'min_labels': ['最低應繳金'],
    },
    'Esun': {
        'method': 'ocr', 'region': (0.0, 0.0, 1.0, 0.5), 'psm': 3, 'dpi': 200,
        'due_labels': ['繳款截止日'],
        'amount_labels': ['本期應繳總金額', '臺幣應繳總金額'],
        'min_labels': ['最低應繳金額'],
    },
    'DBS': {
        'method': 'text',
        'positional': 'dbs',   # 帳務明細列為純數字列：第 4 個總額、第 5 個最低
    },
    'HSBC': {
        'method': 'ocr', 'region': (0.04, 0.36, 0.80, 0.53), 'psm': 6, 'dpi': 300,
        'due_labels': ['繳款截止日'],
        'amount_labels': ['本期應繳總額'],
        'min_labels': ['最低應繳金'],
    },
    'StandardChartered': {
        'method': 'ocr',
        'region': (0.40, 0.18, 1.00, 0.36),          # 信用卡帳款總額區塊
        'date_region': (0.03, 0.18, 0.45, 0.36),     # 繳款截止日區塊
        'min_region': (0.68, 0.18, 1.00, 0.36),      # 最低應繳金額（右欄）
        'psm': 6, 'dpi': 300,
        'due_labels': ['繳款截止日期'],
        'amount_labels': ['本期累積應繳金額', '本期累積應織金額'],
        'min_labels': ['本期最低應繳金額', '本期最低應織金額'],
        'date_cn': True,
    },
    # 元大：文字層乾淨，但標籤一整列、數值在下一列，需依欄位順序取用
    'Yuanda': {
        'method': 'text',
        'positional': 'yuanda',
    },
    # 遠東：文字層是自訂編碼（數字可讀、中文全亂），且廣告圖層壓在金額欄上，
    # 因此只 OCR 左欄的繳款截止日；金額欄讀不到就標 no detect，留給人工。
    'FarEast': {
        # 版面說明：
        # - 金額欄與繳款截止日在第一頁上 1/3 (y 0~0.33)；
        # - 應繳總金額下方常有灰底區塊，OCR 容易被廣告圖層干擾，
        #   故僅嘗試讀取上部區域，若信心不足則金額標「no detect」。
        'method': 'ocr',
        'region': (0.00, 0.05, 0.70, 0.33),       # 上 1/3 預留少許邊距
        'psm': 6, 'dpi': 400, 'preprocess': True,
        'due_labels': ['繳款截止日', '緻款截止日', '紋款截止日', '酸款截止日'],
        'amount_labels': ['本期應繳總額', '本期應繳金額'],
        'min_labels': ['最低應繳金額'],
    },
}

UNKNOWN = "未識別"
STATUS_OK = 'ok'
STATUS_REVIEW = 'need_review'


def _to_int(raw):
    """'130, 704' / '8, 347 元' / '$0' -> '130704' / '8347' / '0'"""
    if raw is None:
        return None
    digits = re.sub(r'[^\d]', '', str(raw))
    return digits or None


def _value_after_label(lines, labels, pattern, lookahead=2):
    """在標籤右側或下方幾行找出符合 pattern 的值。"""
    for i, line in enumerate(lines):
        for label in labels:
            if label not in line:
                continue
            rest = line.split(label, 1)[1]
            match = pattern.search(rest)
            if match:
                return match.group(0)
            for j in range(i + 1, min(i + 1 + lookahead, len(lines))):
                match = pattern.search(lines[j])
                if match:
                    return match.group(0)
    return None


def _format_date(match):
    year, month, day = (int(g) for g in match.groups())
    if year < 200:      # 民國年
        year += 1911
    return f'{year}/{month:02d}/{day:02d}'


def _parse_date(lines, rule):
    date_pattern = DATE_CN if rule.get('date_cn') else DATE_SLASH
    raw = _value_after_label(lines, rule['due_labels'], date_pattern)
    if not raw:
        return UNKNOWN
    return _format_date(date_pattern.search(raw))


def _parse_amount(lines, rule):
    raw = _value_after_label(lines, rule['amount_labels'], NUMBER)
    return _to_int(raw)


def _parse_minimum(lines, rule):
    labels = rule.get('min_labels')
    if not labels:
        return None
    raw = _value_after_label(lines, labels, NUMBER)
    return _to_int(raw)


def _text_layer_lines(pdf_path):
    """把文字層的 word 依 y 座標組成行。"""
    doc = fitz.open(pdf_path)
    words = doc[0].get_text("words")
    doc.close()

    rows = {}
    for x0, y0, _x1, _y1, word, *_ in words:
        rows.setdefault(round(y0 / 4) * 4, []).append((x0, word))

    lines = []
    for y in sorted(rows):
        parts = [w for _, w in sorted(rows[y])]
        lines.append(' '.join(parts))
    return lines


def _parse_dbs(lines):
    due_date = UNKNOWN
    for line in lines:
        first = DATE_SLASH.search(line)
        if first and DATE_SLASH.search(line, first.end()):
            due_date = _format_date(DATE_SLASH.search(line, first.end()))
            break

    amount = minimum = None
    for line in lines:
        tokens = line.split()
        numbers = [t for t in tokens if NUMBER.fullmatch(t)]
        if len(numbers) == 5 and len(tokens) == 5:
            amount = _to_int(numbers[3])     # 本期全部應繳金額
            minimum = _to_int(numbers[4])    # 本期最低應繳金額
            break

    return due_date, amount, minimum


def _render_page1(pdf_path, dpi):
    doc = fitz.open(pdf_path)
    pix = doc[0].get_pixmap(dpi=dpi)
    doc.close()
    return Image.frombytes('RGB', (pix.width, pix.height), pix.samples)


def _mean_confidence(crop, rule):
    """Tesseract 的平均信心值（0-100）。"""
    data = pytesseract.image_to_data(
        crop, lang='chi_tra+eng',
        config=f"--psm {rule.get('psm', 3)}",
        output_type=pytesseract.Output.DICT)

    values = []
    for conf, text in zip(data['conf'], data['text']):
        if not text.strip():
            continue
        try:
            value = float(conf)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            values.append(value)
    return sum(values) / len(values) if values else 0.0


def _ocr_region(pdf_path, bank_code, rule, region, tag):
    """裁切指定區域並 OCR，回傳 (文字, 信心值)；同時保留 PNG 供除錯。"""
    img = _render_page1(pdf_path, rule.get('dpi', 200))

    if tag == 'amount':
        img.save(os.path.join(config.TEMP_DIR, f'{bank_code}_page_0.png'), 'PNG')

    left, top, right, bottom = region
    w, h = img.size
    crop = img.crop((int(left * w), int(top * h),
                     int(right * w), int(bottom * h)))

    text = pytesseract.image_to_string(
        crop, lang='chi_tra+eng', config=f"--psm {rule.get('psm', 3)}")
    return text, _mean_confidence(crop, rule)


def _non_empty_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def extract(pdf_path, bank_code):
    """解析帳單，回傳 dict(due_date, amount, minimum, confidence, status)。"""
    rule = BANK_RULES.get(bank_code)
    if not rule:
        return {'due_date': UNKNOWN, 'amount': None, 'minimum': None,
                'confidence': 0.0, 'status': STATUS_REVIEW}

    if rule['method'] == 'text':
        lines = _text_layer_lines(pdf_path)

        # 保留文字層內容供除錯（與 OCR 銀行一致的檔名）
        with open(os.path.join(config.TEMP_DIR, f'{bank_code}_page_0.txt'),
                  'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        if rule.get('positional') == 'dbs':
            due_date, amount, minimum = _parse_dbs(lines)
        else:
            due_date = _parse_date(lines, rule)
            amount = _parse_amount(lines, rule)
            minimum = _parse_minimum(lines, rule)

        # 文字層是精確值，不需要信心值
        confidence = 100.0
    else:
        amount_text, amount_conf = _ocr_region(
            pdf_path, bank_code, rule, rule['region'], 'amount')

        if rule.get('date_region'):
            date_text, date_conf = _ocr_region(
                pdf_path, bank_code, rule, rule['date_region'], 'date')
            confidence = min(amount_conf, date_conf)
        else:
            date_text = amount_text
            confidence = amount_conf

        amount_lines = _non_empty_lines(amount_text)
        date_lines = _non_empty_lines(date_text)

        due_date = _parse_date(date_lines, rule)
        amount = _parse_amount(amount_lines, rule)

        if rule.get('min_region'):
            min_text, min_conf = _ocr_region(
                pdf_path, bank_code, rule, rule['min_region'], 'min')
            confidence = min(confidence, min_conf)
            minimum = _parse_minimum(_non_empty_lines(min_text), rule)
        else:
            min_text = None
            minimum = _parse_minimum(amount_lines, rule)

        with open(os.path.join(config.TEMP_DIR, f'{bank_code}_page_0.txt'),
                  'w', encoding='utf-8') as f:
            f.write(date_text)
            if date_text is not amount_text:
                f.write('\n--- 金額區塊 ---\n')
                f.write(amount_text)
            if min_text is not None:
                f.write('\n--- 最低應繳區塊 ---\n')
                f.write(min_text)

    # 應繳金額為 0 時，最低應繳必為 0；OCR 常把單獨的「0」漏掉
    if amount == '0' and minimum is None:
        minimum = '0'

    status = STATUS_OK
    if due_date == UNKNOWN or amount is None or minimum is None:
        status = STATUS_REVIEW
    elif confidence < CONFIDENCE_THRESHOLD:
        status = STATUS_REVIEW

    print(f"[{bank_code}] 解析結果 - 日期: {due_date}, 金額: {amount}, "
          f"最低: {minimum}, 信心: {confidence:.1f}, 狀態: {status}")

    return {'due_date': due_date, 'amount': amount, 'minimum': minimum,
            'confidence': confidence, 'status': status}
