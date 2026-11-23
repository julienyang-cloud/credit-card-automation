import base64
import os
import re
import sys
from html.parser import HTMLParser
from datetime import datetime, timedelta

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config


def _is_interactive():
    """排程執行（pythonw）時不開瀏覽器等使用者授權，避免卡住。

    也可用環境變數 CREDIT_CARD_UNATTENDED=1 強制非互動。
    """
    if os.environ.get('CREDIT_CARD_UNATTENDED') == '1':
        return False
    return sys.stdout is not None


def _save_credentials(creds):
    """以 JSON 儲存授權（不用 pickle，避免反序列化風險）。"""
    os.makedirs(os.path.dirname(config.TOKEN_FILE), exist_ok=True)
    with open(config.TOKEN_FILE, 'w', encoding='utf-8') as f:
        f.write(creds.to_json())
    try:
        os.chmod(config.TOKEN_FILE, 0o600)
    except OSError:
        pass


def get_gmail_service():
    creds = None
    if os.path.exists(config.TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(
                config.TOKEN_FILE, config.SCOPES)
        except (ValueError, OSError) as e:
            print(f'token 檔無法讀取（{e}），將重新授權。')

    if creds and creds.valid:
        return build('gmail', 'v1', credentials=creds)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise RuntimeError(
                'Gmail 授權已失效（refresh token 過期或被撤銷）。\n'
                '請開一個有主控台的視窗，手動執行一次：\n'
                '    venv\\Scripts\\python.exe run_monthly.py --force\n'
                f'原始錯誤：{e}') from e
        _save_credentials(creds)
        return build('gmail', 'v1', credentials=creds)

    if not _is_interactive():
        raise RuntimeError(
            '找不到可用的 Gmail 授權，且目前是非互動執行（排程）。\n'
            '請先手動執行一次 run_now.bat，在瀏覽器完成授權後再讓排程接手。')

    flow = InstalledAppFlow.from_client_secrets_file(
        config.CREDENTIALS_FILE, config.SCOPES)
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    return build('gmail', 'v1', credentials=creds)

def get_all_attachments(parts, attachments):
    """遞迴收集 PDF 附件（副檔名不分大小寫，例如 .PDF）。"""
    for part in parts:
        if 'parts' in part:
            get_all_attachments(part['parts'], attachments)
        elif part.get('filename') and part['filename'].lower().endswith('.pdf'):
            attachments.append(part)


# 非帳單的附件關鍵字（例如台新同時寄「繳款單」）
NON_STATEMENT_HINTS = ('slip', 'payment', '繳款', 'terms', '注意事項')


def choose_statement(attachments):
    """在多個 PDF 中挑出帳單本體：先排除繳款單等，再取檔案最小的。"""
    if not attachments:
        return None
    candidates = [a for a in attachments
                  if not any(h in a['filename'].lower()
                             for h in NON_STATEMENT_HINTS)]
    pool = candidates or attachments
    return min(pool, key=lambda a: int(a.get('body', {}).get('size', 0)))

class _HTMLToText(HTMLParser):
    """將 HTML 轉為純文字（僅用標準庫，不需要額外套件）。"""

    # 這些標籤結束後應該換行
    BLOCK_TAGS = {
        'p', 'div', 'br', 'tr', 'table', 'ul', 'ol', 'li', 'h1', 'h2',
        'h3', 'h4', 'h5', 'h6', 'section', 'article', 'header', 'footer',
        'blockquote', 'pre', 'hr',
    }
    SKIP_TAGS = {'script', 'style', 'head', 'title'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self.BLOCK_TAGS:
            self.chunks.append('\n')
        elif tag in ('td', 'th'):
            self.chunks.append(' ')

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
        elif tag in self.BLOCK_TAGS:
            self.chunks.append('\n')

    def handle_data(self, data):
        if self._skip_depth == 0 and data:
            self.chunks.append(data)

    def get_text(self):
        raw = ''.join(self.chunks)
        # 壓縮空白但保留換行結構
        lines = []
        for line in raw.splitlines():
            line = re.sub(r'[ \t\u00a0\u3000]+', ' ', line).strip()
            if line:
                lines.append(line)
        return '\n'.join(lines)


def html_to_text(html):
    """HTML -> 純文字。"""
    parser = _HTMLToText()
    parser.feed(html)
    parser.close()
    return parser.get_text()


def _get_part_data(service, message_id, part):
    """取得 part 的內容；大型內文只有 attachmentId，需要另外下載。"""
    body = part.get('body', {})
    data = body.get('data')
    if data:
        return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')

    att_id = body.get('attachmentId')
    if att_id and service and message_id:
        fetched = service.users().messages().attachments().get(
            userId='me', messageId=message_id, id=att_id).execute()
        return base64.urlsafe_b64decode(fetched['data']).decode('utf-8', errors='replace')
    return ''


def _collect_parts(payload, mime_type, found):
    """遞迴收集指定 mimeType 的所有 part。"""
    if payload.get('mimeType') == mime_type:
        found.append(payload)
    for child in payload.get('parts', []) or []:
        _collect_parts(child, mime_type, found)
    return found


def get_email_body(payload, service=None, message_id=None):
    """取得郵件內文。

    優先使用 text/plain；若不存在（例如國泰只有 HTML），
    則改用 text/html 並轉為純文字。
    """
    plain_parts = _collect_parts(payload, 'text/plain', [])
    if plain_parts:
        text = ''.join(_get_part_data(service, message_id, p) for p in plain_parts)
        if text.strip():
            return text

    html_parts = _collect_parts(payload, 'text/html', [])
    html = ''.join(_get_part_data(service, message_id, p) for p in html_parts)
    if html.strip():
        return html_to_text(html)

    return ''

def _shift(date_str, days):
    """日期加減天數，格式 YYYY/MM/DD。"""
    day = datetime.strptime(date_str, '%Y/%m/%d') + timedelta(days=days)
    return day.strftime('%Y/%m/%d')


# 附件檔名來自信件內容，不可直接當路徑用
_UNSAFE_FILENAME = re.compile(r'[^\w.\- ()]+')


def _safe_filename(filename, fallback='statement.pdf'):
    """只取檔名本身，濾掉路徑與特殊字元，避免寫到 downloads 之外。"""
    name = os.path.basename(str(filename).replace('\\', '/'))
    name = _UNSAFE_FILENAME.sub('_', name).strip(' .')
    if not name.lower().endswith('.pdf'):
        return fallback
    return name[:120] or fallback


def download_latest_statement(service, bank_name):
    """回傳 dict：found（有無信件）、pdf_path（無附件時為 None）、body（郵件內文）。"""
    start_date = config.STATEMENT_START
    end_date = config.STATEMENT_END
    bank_config = config.BANK_CONFIG[bank_name]
    sender = bank_config['sender']
    keyword = bank_config.get('subject', '信用卡').replace(' ', '')

    # 樂天、富邦的帳單信沒有附件，加了 has:attachment 反而找不到信。
    # Gmail 的 after:/before: 都不含當日，所以各放寬一天，
    # 讓區間真正涵蓋「前月 22 日 ~ 本月 21 日」。
    query = f"from:{sender} {keyword}"
    if bank_config.get('has_attachment', True):
        query += " has:attachment"
    query += (f" after:{_shift(start_date, -1)}"
              f" before:{_shift(end_date, 1)}")
    print(f"[{bank_name}] 搜尋區間 {start_date} ~ {end_date}")
    print(f"[{bank_name}] 搜尋指令: {query}")
    
    results = service.users().messages().list(userId='me', q=query).execute()
    messages = results.get('messages', [])
    if not messages:
        return {'found': False, 'pdf_path': None, 'body': ''}

    msg = service.users().messages().get(userId='me', id=messages[0]['id'], format='full').execute()
    
    # 獲取郵件內文（沒有 text/plain 時會自動改用 HTML）
    body = get_email_body(msg['payload'], service=service, message_id=messages[0]['id'])
    
    attachments = []
    if 'parts' in msg['payload']:
        get_all_attachments(msg['payload']['parts'], attachments)
    
    best_attachment = choose_statement(attachments)
    if best_attachment is None:
        return {'found': True, 'pdf_path': None, 'body': body}

    att_id = best_attachment['body']['attachmentId']
    file_data = service.users().messages().attachments().get(userId='me', messageId=messages[0]['id'], id=att_id).execute()
    data = base64.urlsafe_b64decode(file_data['data'])

    safe_name = _safe_filename(best_attachment['filename'])
    file_path = os.path.join(config.DOWNLOAD_DIR, safe_name)
    with open(file_path, 'wb') as f:
        f.write(data)
    print(f"[{bank_name}] 已成功下載: {safe_name}")
    return {'found': True, 'pdf_path': file_path, 'body': body}
