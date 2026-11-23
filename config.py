"""設定：路徑、銀行清單、帳單區間。

銀行清單與試算表名稱放在 banks.json（不進版控）。
第一次使用請複製 banks.example.json 為 banks.json，填入自己的銀行與試算表。

憑證一律放在 secrets\\（已列入 .gitignore）：
  credentials.json     Google OAuth 用戶端憑證
  token.json           授權後的 refresh token（第一次執行時自動產生）
  service_account.json 服務帳戶金鑰（寫入 Google Sheet 用）
"""
import datetime
import json
import os

# 路徑一律由本檔位置推算，整個資料夾搬移後仍可運作
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# Google API
# --------------------------------------------------------------------------
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/spreadsheets',
]

SECRETS_DIR = (os.environ.get('CREDIT_CARD_SECRETS_DIR')
               or os.path.join(BASE_DIR, 'secrets'))
CREDENTIALS_FILE = os.path.join(SECRETS_DIR, 'credentials.json')
TOKEN_FILE = os.path.join(SECRETS_DIR, 'token.json')
SERVICE_ACCOUNT_FILE = os.path.join(SECRETS_DIR, 'service_account.json')

# --------------------------------------------------------------------------
# 銀行清單
# --------------------------------------------------------------------------
BANKS_FILE = (os.environ.get('CREDIT_CARD_BANKS_FILE')
              or os.path.join(BASE_DIR, 'banks.json'))

# Windows 認證管理員的服務名稱（信用卡帳單 PDF 密碼存在這裡）
KEYRING_SERVICE = 'credit_card_auto'


def _load_banks(path):
    """讀 banks.json，回傳 (banks, spreadsheet_name)。"""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f'找不到銀行設定檔：{path}\n'
            f'請複製 banks.example.json 為 banks.json，並填入自己的銀行資料。')
    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    banks = data.get('banks') or {}
    if not banks:
        raise ValueError(f'{path} 內沒有 banks 設定。')
    return banks, data.get('spreadsheet', '')


BANK_CONFIG, SPREADSHEET_NAME = _load_banks(BANKS_FILE)

# --------------------------------------------------------------------------
# 帳單搜尋區間：每月 21 日執行，涵蓋前月 22 日至本月 21 日
# --------------------------------------------------------------------------
def _statement_window(day=None):
    """回傳 (前月22日, 指定日)；day 預設為今天。"""
    today = day or datetime.date.today()
    if today.month == 1:
        start = datetime.date(today.year - 1, 12, 22)
    else:
        start = datetime.date(today.year, today.month - 1, 22)
    return start.strftime('%Y/%m/%d'), today.strftime('%Y/%m/%d')


STATEMENT_START, STATEMENT_END = _statement_window()

# --------------------------------------------------------------------------
# 檔案儲存路徑
# --------------------------------------------------------------------------
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')
TEMP_DIR = os.path.join(BASE_DIR, 'temp')

# 執行完（資料已寫入 Google Sheet）後，是否刪除所有敏感檔案
CLEANUP_AFTER_RUN = True

# 若某家銀行標記 need review / no detect，保留該家的除錯檔（page_0.txt 等）
KEEP_DEBUG_ON_REVIEW = True

# 視為敏感、必須刪除的副檔名（帳單 PDF、轉出的圖片、OCR 文字檔）
SENSITIVE_EXTENSIONS = ('.pdf', '.png', '.jpg', '.jpeg', '.txt', '.pickle')

# --------------------------------------------------------------------------
# OCR 執行檔
# --------------------------------------------------------------------------
def _detect_tesseract():
    """找 tesseract；可用環境變數 TESSERACT_CMD 覆寫。"""
    env = os.environ.get('TESSERACT_CMD')
    if env:
        return env

    candidates = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        '/usr/bin/tesseract',
        '/usr/local/bin/tesseract',
        '/opt/homebrew/bin/tesseract',
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return 'tesseract'      # 交給 PATH


TESSERACT_CMD = _detect_tesseract()

# 確保目錄存在
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
