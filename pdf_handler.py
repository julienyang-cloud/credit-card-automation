"""PDF 解密與清理。

帳單 PDF 的密碼存在 Windows 認證管理員（或各平台的 keyring），
程式不落地、不寫進設定檔。
"""
import os

import fitz  # PyMuPDF
import keyring

import config


def decrypt_pdf_safe(input_path, output_path, bank_code):
    """用 keyring 內的密碼解密 PDF，成功回傳 True。"""
    try:
        password = keyring.get_password(config.KEYRING_SERVICE, bank_code)
        if not password:
            print(f"密碼未設定: {bank_code}")
            return False

        doc = fitz.open(input_path)
        if doc.is_encrypted:
            if not doc.authenticate(password):
                print(f"密碼錯誤: {bank_code}")
                doc.close()
                return False

        doc.save(output_path, garbage=4, deflate=True)
        doc.close()
        return True
    except Exception as e:
        print(f"解密過程中發生錯誤: {e}")
        return False


def secure_cleanup(file_path):
    """處理完後立即刪除檔案。"""
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError as e:
            print(f"清理檔案失敗: {e}")
