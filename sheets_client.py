"""Google Sheets 寫入。

金額欄位依「表頭第 1 列的日期」對應：
  C1=2026/10/21 -> C 欄、D1=2026/11/21 -> D 欄、E1=2026/12/21 -> E 欄
對不到時才退回月份對照表（10/11/12 月）。
"""
import re
from datetime import datetime

import gspread
from gspread.utils import rowcol_to_a1

import config

# 備援：表頭找不到日期時，用月份對應欄位
COLUMN_BY_MONTH = {10: 3, 11: 4, 12: 5}


def _open_sheet():
    """開啟試算表的第一個工作表。"""
    if not config.SPREADSHEET_NAME:
        raise RuntimeError('banks.json 內沒有設定 spreadsheet 名稱。')
    gc = gspread.service_account(filename=config.SERVICE_ACCOUNT_FILE)
    return gc.open(config.SPREADSHEET_NAME).sheet1


def _month_of(date_str):
    """從 115/10/15 或 2026/11/02 取得月份，失敗回傳 None。"""
    if not date_str:
        return None
    match = re.search(r'(\d+)[/-](\d{1,2})[/-](\d{1,2})', str(date_str))
    return int(match.group(2)) if match else None


def _year_of(date_str):
    """取得西元年；民國年自動轉換。失敗回傳 None。"""
    if not date_str:
        return None
    match = re.search(r'(\d+)[/-](\d{1,2})[/-](\d{1,2})', str(date_str))
    if not match:
        return None
    year = int(match.group(1))
    return year + 1911 if year < 200 else year


def _normalize_date(date_str):
    """民國年轉西元年（115/11/01 -> 2026/11/01）。

    Google Sheets 會把「115/11/01」當成西元 115 年的日期，
    存成負數的日期序號，因此寫入前先轉換。
    """
    if not date_str:
        return date_str
    match = re.search(r'(\d+)[/-](\d{1,2})[/-](\d{1,2})', str(date_str))
    if not match:
        return date_str

    year, month, day = (int(g) for g in match.groups())
    if year < 200:          # 民國年
        year += 1911
    return f'{year}/{month:02d}/{day:02d}'


def _target_column(sheet=None):
    """回傳 (月份, 欄號)。

    先看表頭第 1 列有沒有與本期年月相同的日期；沒有才退回月份對照表。
    兩者都對不到時回傳 None（避免寫到錯的欄）。
    """
    month = _month_of(config.STATEMENT_END) or datetime.now().month
    year = _year_of(config.STATEMENT_END)

    if sheet is not None and year is not None:
        try:
            header = sheet.row_values(1)
        except Exception:
            header = []
        for index, value in enumerate(header, start=1):
            match = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', str(value))
            if match and int(match.group(1)) == year and int(match.group(2)) == month:
                return month, index

    return month, COLUMN_BY_MONTH.get(month)


def _find_row(sheet, bank_code):
    """用 A 欄的銀行名稱找列；找不到回傳 None。

    A 欄不可修改，但名稱可能被改成中文或英文（例如 星展 <-> DBS），
    因此依序嘗試 row_label 與 alt_names，只比對 A 欄、且必須完全相同。
    """
    info = config.BANK_CONFIG.get(bank_code, {})
    names = [info.get('row_label') or info.get('sheet_name') or bank_code]
    names += list(info.get('alt_names', []))

    wanted = {name.strip().casefold() for name in names if name}
    for index, value in enumerate(sheet.col_values(1), start=1):
        if value.strip().casefold() in wanted:
            return index

    print(f"[{bank_code}] 在試算表 A 欄找不到 {sorted(wanted)}，跳過。")
    return None


def write_marker(bank_code, marker, due_date=None):
    """在該銀行的金額欄寫入狀態標記（no mail / no pdf / no detect / need review）。

    若已解析到繳款截止日，仍會寫入 B 欄，避免既有資訊遺失。
    """
    try:
        sheet = _open_sheet()

        row = _find_row(sheet, bank_code)
        if row is None:
            return False

        month, col = _target_column(sheet)
        if col is None:
            print(f"[{bank_code}] 無法對應金額欄（月份 {month}），未寫入。")
            return False

        if due_date and due_date != '未識別':
            sheet.update_cell(row, 2, _normalize_date(due_date))

        sheet.update_cell(row, col, marker)

        print(f"[{bank_code}] 已標記「{marker}」於 {rowcol_to_a1(row, col)}")
        return True
    except Exception as e:
        print(f"[{bank_code}] 標記失敗: {e}")
        return False


def update_bill_to_sheet(due_date, amount, bank_code):
    """將帳單資訊寫入 Google Sheets。

    B 欄一律寫入繳款截止日（民國年自動轉西元年）。
    金額欄位依本期結算日對應表頭：
      STATEMENT_END = 2026/10/21 -> C 欄、11/21 -> D 欄、12/21 -> E 欄
    """
    try:
        sheet = _open_sheet()

        row = _find_row(sheet, bank_code)
        if row is None:
            return False

        month, col = _target_column(sheet)
        if col is None:
            print(f"[{bank_code}] 無法對應金額欄（月份 {month}），未寫入。")
            return False

        due_date_text = _normalize_date(due_date)

        sheet.update_cell(row, 2, due_date_text)
        sheet.update_cell(row, col, amount)

        print(f"[{bank_code}] 帳單月份 {month} 月 -> "
              f"{rowcol_to_a1(row, col)}，金額 {amount}，"
              f"繳款截止日 {due_date_text}")
        return True
    except Exception as e:
        print(f"[{bank_code}] 寫入失敗: {e}")
        return False
