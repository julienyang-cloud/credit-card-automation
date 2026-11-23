"""把各銀行帳單 PDF 的密碼寫進系統 keyring（Windows 認證管理員）。

密碼不會寫進任何檔案，也不會出現在 log。

用法：
    venv\\Scripts\\python.exe setup_passwords.py          逐一輸入
    venv\\Scripts\\python.exe setup_passwords.py --list   檢查哪些已設定
"""
import getpass
import sys

import keyring

import config


def _entries():
    """回傳 [(銀行代號, keyring 鍵)]。"""
    return [(code, info.get('keyring_code') or code)
            for code, info in config.BANK_CONFIG.items()]


def list_status():
    print(f'keyring 服務名稱：{config.KEYRING_SERVICE}\n')
    for code, key in _entries():
        value = keyring.get_password(config.KEYRING_SERVICE, key)
        print(f'  {code:22s} {key:22s} {"已設定" if value else "未設定"}')


def set_all():
    print(f'憑證會存進系統 keyring，服務名稱：{config.KEYRING_SERVICE}')
    print('（Windows：控制台 -> 認證管理員 -> Windows 認證）\n')
    for code, key in _entries():
        existing = keyring.get_password(config.KEYRING_SERVICE, key)
        hint = '（已有值，直接 Enter 保留）' if existing else ''
        password = getpass.getpass(f'{code} 的 PDF 密碼{hint}: ')
        if password:
            keyring.set_password(config.KEYRING_SERVICE, key, password)
            print('  -> 已儲存')
    print('\n完成。')


if __name__ == '__main__':
    if '--list' in sys.argv[1:]:
        list_status()
    else:
        set_all()
