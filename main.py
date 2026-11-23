"""信用卡帳單自動化：Gmail 收信 -> 解析 -> 寫入 Google Sheet。

國泰（Cathay）信件只有 HTML 內文、PDF 標籤是圖形，因此不下載 PDF，
直接解析郵件內文；其他銀行則下載 PDF、解密後解析（文字層優先，必要時 OCR）。

無法取得資料時，會在該列的金額欄寫入狀態標記：
  no mail      找不到帳單信件
  no pdf       有信件但沒有 PDF 附件
  no detect    有 PDF 但辨識不出應繳金額
  need review  有金額但缺少日期／最低應繳，或 OCR 信心不足
"""
import os
import re
from datetime import datetime

import config
import cleanup
import gmail_client
import pdf_handler
import sheets_client
import statement_parser

MARK_OK = 'ok'
MARK_NO_MAIL = 'no mail'
MARK_NO_PDF = 'no pdf'
MARK_NO_DETECT = 'no detect'
MARK_REVIEW = 'need review'
MARK_WRITE_FAILED = 'sheet error'

DATE_RE = re.compile(r'(\d{3}/\d{2}/\d{2})')
AMOUNT_RE = re.compile(r'([\d,]+)')

# 沒有 PDF 的銀行，仍可從郵件內文撈到繳款截止日（樂天只寫「10月26日」，沒有年份）
BODY_DUE_PATTERNS = {
    'Rakuten': re.compile(r'繳款(?:期限|截止日)[^0-9]{0,6}(\d{1,2})\s*月\s*(\d{1,2})\s*日'),
}


def _find_value(lines, label, value_re, lookahead=3):
    """先找標籤，再從同一行或後續幾行找出符合格式的值。"""
    for i, line in enumerate(lines):
        if label not in line:
            continue

        # 標籤與值在同一行，例如「繳款截止日 115/11/01」
        rest = line.split(label, 1)[1]
        match = value_re.search(rest)
        if match:
            return match.group(1)

        # 值在標籤下方，例如標籤一行、數字下一行
        for j in range(i + 1, min(i + 1 + lookahead, len(lines))):
            match = value_re.search(lines[j])
            if match:
                return match.group(1)
    return None


def parse_cathay_body(body):
    """從國泰郵件內文解析結帳日、繳款截止日、應繳總金額、最低應繳金額。"""
    lines = [line.strip() for line in body.splitlines() if line.strip()]

    closing_date = _find_value(lines, '帳單結帳日', DATE_RE)
    due_date = _find_value(lines, '繳款截止日', DATE_RE)
    total = _find_value(lines, '本期應繳總金額', AMOUNT_RE)
    minimum = _find_value(lines, '最低應繳總金額', AMOUNT_RE)

    return {
        'closing_date': closing_date,
        'due_date': due_date,
        'amount': total.replace(',', '') if total else None,
        'minimum': minimum.replace(',', '') if minimum else None,
    }


def process_cathay(body):
    """國泰：純郵件內文解析，不碰 PDF。"""
    if not body.strip():
        print("[Cathay] 有信件但內文為空，無法解析。")
        sheets_client.write_marker('Cathay', MARK_REVIEW)
        return MARK_REVIEW

    debug_path = os.path.join(config.TEMP_DIR, 'cathay_body.txt')
    with open(debug_path, 'w', encoding='utf-8') as f:
        f.write(body)
    print(f"[Cathay] 內文長度: {len(body)} 字，已存至 {debug_path}")

    info = parse_cathay_body(body)
    print(f"[Cathay] 結帳日: {info['closing_date']}, "
          f"繳款截止日: {info['due_date']}, "
          f"應繳總金額: {info['amount']}, "
          f"最低應繳: {info['minimum']}")

    if not info['amount']:
        print("[Cathay] 內文中找不到應繳總金額。")
        sheets_client.write_marker(
            'Cathay', MARK_NO_DETECT, due_date=info['due_date'])
        return MARK_NO_DETECT

    if not info['due_date'] or not info['minimum']:
        sheets_client.write_marker(
            'Cathay', MARK_REVIEW, due_date=info['due_date'])
        return MARK_REVIEW

    if not sheets_client.update_bill_to_sheet(
            info['due_date'], info['amount'], 'Cathay'):
        return MARK_WRITE_FAILED
    return MARK_OK


def process_pdf_bank(bank_code, bank_info, pdf_path):
    """其他銀行：解密 PDF -> 解析（文字層優先，必要時 OCR）。"""
    decrypted_pdf = os.path.join(config.TEMP_DIR, f"{bank_code}_decrypted.pdf")

    try:
        if not pdf_handler.decrypt_pdf_safe(
                pdf_path, decrypted_pdf, bank_info['keyring_code']):
            print(f"[{bank_code}] PDF 解密失敗。")
            sheets_client.write_marker(bank_code, MARK_REVIEW)
            return MARK_REVIEW
        print(f"[{bank_code}] PDF 解密成功。")

        result = statement_parser.extract(decrypted_pdf, bank_code)

        # 有 PDF 但抓不到金額 -> no detect；抓到金額但其他欄位不齊 -> need review
        if result['amount'] is None:
            print(f"[{bank_code}] 無法辨識應繳金額（信心 {result['confidence']:.1f}）。")
            sheets_client.write_marker(
                bank_code, MARK_NO_DETECT, due_date=result['due_date'])
            return MARK_NO_DETECT

        if result['status'] != statement_parser.STATUS_OK:
            debug_file = os.path.join(config.TEMP_DIR, f'{bank_code}_page_0.txt')
            print(f"[{bank_code}] 需人工確認（信心 {result['confidence']:.1f}），"
                  f"請檢查 {debug_file}")
            sheets_client.write_marker(
                bank_code, MARK_REVIEW, due_date=result['due_date'])
            return MARK_REVIEW

        if not sheets_client.update_bill_to_sheet(
                result['due_date'], result['amount'], bank_code):
            return MARK_WRITE_FAILED
        return MARK_OK
    finally:
        # 解密後的 PDF 一律刪除；PNG 與文字檔保留供除錯
        pdf_handler.secure_cleanup(decrypted_pdf)


def _body_due_date(bank_code, body):
    """從郵件內文找繳款截止日，並補上年份。

    樂天只寫「繳款期限為 10月26日」，沒有年份，因此以本期結算日
    為基準，取最接近且落在前後 45 天內的年份；不合理就回傳 None。
    """
    pattern = BODY_DUE_PATTERNS.get(bank_code)
    if not pattern or not body:
        return None

    match = pattern.search(body)
    if not match:
        return None

    month, day = int(match.group(1)), int(match.group(2))
    end = datetime.strptime(config.STATEMENT_END, '%Y/%m/%d').date()
    for year in (end.year - 1, end.year, end.year + 1):
        try:
            candidate = datetime(year, month, day).date()
        except ValueError:
            return None
        if abs((candidate - end).days) <= 45:
            return candidate.strftime('%Y/%m/%d')
    return None


def process_bank(service, bank_code, bank_info):
    print(f"\n[{datetime.now()}] === 正在處理銀行: {bank_code} ===")

    result = gmail_client.download_latest_statement(service, bank_code)

    if not result['found']:
        print(f"[{bank_code}] 找不到帳單信件。")
        sheets_client.write_marker(bank_code, MARK_NO_MAIL)
        return MARK_NO_MAIL

    if bank_code == 'Cathay':
        return process_cathay(result['body'])

    if not result['pdf_path']:
        print(f"[{bank_code}] 有信件但沒有 PDF 附件。")
        due_date = _body_due_date(bank_code, result['body'])
        if due_date:
            print(f"[{bank_code}] 由內文取得繳款截止日: {due_date}")
        sheets_client.write_marker(bank_code, MARK_NO_PDF, due_date=due_date)
        return MARK_NO_PDF

    return process_pdf_bank(bank_code, bank_info, result['pdf_path'])


def main():
    service = gmail_client.get_gmail_service()
    summary = {}

    for bank_code, bank_info in config.BANK_CONFIG.items():
        try:
            summary[bank_code] = process_bank(service, bank_code, bank_info)
        except Exception as e:
            print(f"[{bank_code}] 處理時發生錯誤: {e}")
            sheets_client.write_marker(bank_code, MARK_REVIEW)
            summary[bank_code] = MARK_REVIEW

    print("\n=== 執行結果 ===")
    for bank_code, status in summary.items():
        print(f"  {bank_code:20s} {status}")

    # 資料已寫入 Google Sheet，接著刪除所有敏感檔案（PDF、圖片、文字檔）
    if config.CLEANUP_AFTER_RUN:
        # 只有「有檔案可檢查」的狀態才保留除錯檔；
        # no mail / no pdf 本來就沒有下載任何檔案，留著名單只會造成誤解。
        keep = ()
        if config.KEEP_DEBUG_ON_REVIEW:
            keep = tuple(code.lower() for code, status in summary.items()
                         if status in (MARK_REVIEW, MARK_NO_DETECT,
                                       MARK_WRITE_FAILED))
            if keep:
                print(f"\n以下銀行未成功，保留除錯檔：{', '.join(keep)}")
        cleanup.cleanup_sensitive_files(keep_prefixes=keep)
    else:
        print("\n（CLEANUP_AFTER_RUN=False，保留除錯檔案）")


if __name__ == "__main__":
    main()
