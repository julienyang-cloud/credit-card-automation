"""清除敏感檔案與過期日誌。

1. 敏感檔案清理：
   信用卡帳單處理完、資料已寫入 Google Sheet 之後，把下載的 PDF、
   轉出的圖片、OCR 文字檔（可能含姓名、卡號、金額）全部刪除，
   避免個資留在本機。
   - 若某家銀行標記 need review / no detect，可用 keep_prefixes 保留該家的除錯檔
     （例如 'ctbc' 會保留 ctbc_page_0.txt、ctbc_page_0.png）。
   - 即使標記為保留，超過 DEBUG_RETENTION_DAYS（預設 60 天）的除錯檔一律強制清理。

2. 日誌清理：
   logs/ 底下的 run_YYYYMMDD_HHMMSS.log 若超過 LOG_RETENTION_DAYS（預設 120 天），
   自動清理，避免財務歷史日誌無限制累積。

可單獨執行：
    venv\\Scripts\\python.exe cleanup.py
"""
import datetime
import os
import re

import config

_LOG_FILENAME_RE = re.compile(r'^run_(\d{8})_(\d{6})\.log$')


def _is_kept(name, keep_prefixes):
    lowered = name.lower()
    return any(lowered.startswith(prefix.lower()) for prefix in keep_prefixes)


def _file_age_days(path):
    """計算檔案距離現在的天數（以修改時間 mtime 為準）。"""
    try:
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        return (datetime.datetime.now() - mtime).total_seconds() / 86400.0, mtime
    except OSError:
        return 0.0, datetime.datetime.now()


def cleanup_sensitive_files(keep_prefixes=(), max_debug_days=None, verbose=True):
    """刪除 downloads 與 temp 底下所有敏感檔案，回傳 (已刪除清單, 逾期強制刪除清單, 保留清單)。

    keep_prefixes: 檔名開頭的保留清單，例如 ('ctbc', 'cathay')。
    max_debug_days: 保留除錯檔的最長天數，預設讀取 config.DEBUG_RETENTION_DAYS（60 天）。
    """
    if max_debug_days is None:
        max_debug_days = getattr(config, 'DEBUG_RETENTION_DAYS', 60)

    removed = []
    expired = []
    kept = []
    failed = []

    for folder in (config.DOWNLOAD_DIR, config.TEMP_DIR):
        if not os.path.isdir(folder):
            continue
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if not name.lower().endswith(config.SENSITIVE_EXTENSIONS):
                    continue
                path = os.path.join(root, name)
                age_days, mtime = _file_age_days(path)

                if _is_kept(name, keep_prefixes):
                    # 即使標記為保留，若超過 max_debug_days 天仍強制清理
                    if max_debug_days is not None and age_days > max_debug_days:
                        try:
                            os.remove(path)
                            expired.append((path, mtime, age_days))
                        except OSError as e:
                            failed.append((path, e))
                    else:
                        kept.append((path, mtime, age_days))
                    continue

                try:
                    os.remove(path)
                    removed.append(path)
                except OSError as e:
                    failed.append((path, e))

    if verbose:
        total_deleted = len(removed) + len(expired)
        print(f"\n=== 清除敏感檔案 === 已刪除 {total_deleted} 個（含 {len(expired)} 個逾期除錯檔），保留 {len(kept)} 個")
        for path in removed:
            print(f"  已刪除 {os.path.relpath(path, config.BASE_DIR)}")
        for path, mtime, age in expired:
            print(f"  逾期強制清除（已保留 {age:.1f} 天 > {max_debug_days} 天）：{os.path.relpath(path, config.BASE_DIR)}")
        for path, mtime, age in kept:
            print(f"  保留（待人工確認，建立於 {mtime:%Y-%m-%d}，已保留 {age:.1f} 天）：{os.path.relpath(path, config.BASE_DIR)}")
        for path, error in failed:
            print(f"  刪除失敗 {path}: {error}")

    return removed, expired, kept


def cleanup_old_logs(log_dir=None, max_days=None, verbose=True):
    """刪除 logs 目錄下超過 max_days 天的 run_YYYYMMDD_HHMMSS.log 檔案。

    max_days: 最長保留天數，預設讀取 config.LOG_RETENTION_DAYS（120 天）。
    """
    if log_dir is None:
        log_dir = getattr(config, 'LOG_DIR', os.path.join(config.BASE_DIR, 'logs'))
    if max_days is None:
        max_days = getattr(config, 'LOG_RETENTION_DAYS', 120)

    if not os.path.isdir(log_dir):
        return []

    removed = []
    kept = []
    failed = []

    now = datetime.datetime.now()

    for name in os.listdir(log_dir):
        match = _LOG_FILENAME_RE.match(name)
        if not match:
            continue

        path = os.path.join(log_dir, name)
        # 優先從檔名解析時間，解析失敗則依檔案 mtime
        try:
            log_time = datetime.datetime.strptime(
                f"{match.group(1)}_{match.group(2)}", "%Y%m%d_%H%M%S")
        except ValueError:
            log_time = datetime.datetime.fromtimestamp(os.path.getmtime(path))

        age_days = (now - log_time).total_seconds() / 86400.0

        if age_days > max_days:
            try:
                os.remove(path)
                removed.append((path, log_time, age_days))
            except OSError as e:
                failed.append((path, e))
        else:
            kept.append((path, log_time, age_days))

    if verbose:
        print(f"\n=== 清理過期日誌 === 已刪除 {len(removed)} 個超過 {max_days} 天的日誌，保留 {len(kept)} 個")
        for path, log_time, age in removed:
            print(f"  已刪除過期日誌（{log_time:%Y-%m-%d}，已留存 {age:.1f} 天）：{os.path.relpath(path, config.BASE_DIR)}")
        for path, error in failed:
            print(f"  刪除日誌失敗 {path}: {error}")

    return removed


def cleanup_all(keep_prefixes=(), verbose=True):
    """一併清理敏感檔案與過期日誌。"""
    cleaned_sensitive = cleanup_sensitive_files(keep_prefixes=keep_prefixes, verbose=verbose)
    cleaned_logs = cleanup_old_logs(verbose=verbose)
    return cleaned_sensitive, cleaned_logs


if __name__ == '__main__':
    cleanup_all()
