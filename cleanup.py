"""清除敏感檔案。

信用卡帳單處理完、資料已寫入 Google Sheet 之後，把下載的 PDF、
轉出的圖片、OCR 文字檔（可能含姓名、卡號、金額）全部刪除，
避免個資留在本機。

若某家銀行標記 need review，可用 keep_prefixes 保留該家的除錯檔
（例如 'ctbc' 會保留 ctbc_page_0.txt），方便事後檢查。

可單獨執行：
    venv\\Scripts\\python.exe cleanup.py
"""
import os

import config


def _is_kept(name, keep_prefixes):
    lowered = name.lower()
    return any(lowered.startswith(prefix.lower()) for prefix in keep_prefixes)


def cleanup_sensitive_files(keep_prefixes=(), verbose=True):
    """刪除 downloads 與 temp 底下所有敏感檔案，回傳已刪除的清單。

    keep_prefixes: 檔名開頭的保留清單，例如 ('ctbc', 'cathay')。
    """
    removed = []
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
                if _is_kept(name, keep_prefixes):
                    kept.append(path)
                    continue
                try:
                    os.remove(path)
                    removed.append(path)
                except OSError as e:
                    failed.append((path, e))

    if verbose:
        print(f"\n=== 清除敏感檔案 === 已刪除 {len(removed)} 個，保留 {len(kept)} 個")
        for path in removed:
            print(f"  已刪除 {os.path.relpath(path, config.BASE_DIR)}")
        for path in kept:
            print(f"  保留（待人工確認） {os.path.relpath(path, config.BASE_DIR)}")
        for path, error in failed:
            print(f"  刪除失敗 {path}: {error}")

    return removed


if __name__ == '__main__':
    cleanup_sensitive_files()
