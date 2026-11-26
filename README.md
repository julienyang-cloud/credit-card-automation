# 信用卡帳單自動化

每月自動從 Gmail 找出各銀行的信用卡電子帳單，解密 PDF、解析「本期應繳金額」與「繳款截止日」，寫入 Google Sheet。

全程在本機執行；帳單 PDF 在資料寫入後立即刪除，密碼存在系統 keyring（Windows 認證管理員），不寫進任何設定檔。

---

## 功能

- **多銀行、可自行擴充**：銀行清單放在 `banks.json`，新增銀行只要加一筆設定（必要時再加解析規則）。
- **文字層優先**：數位產生的 PDF 直接讀文字層，數字精準；文字層是圖片的銀行才退回 OCR。
- **處理沒有附件的帳單信**：有些銀行（例如樂天、富邦）只寄「請登入查看」的通知信，會標記 `no pdf`。
- **處理只有 HTML 內文的帳單**：國泰世華的 PDF 是圖形，改為直接解析郵件內文。
- **不中斷**：任何一家失敗都只寫入狀態標記，不影響其他銀行。
- **自動清除敏感檔**：執行完刪除 PDF、轉出的圖片、OCR 文字檔。
- **補跑機制**：電腦關機錯過時間，開機後會自動補執行，且不會重複寫入同一期。

## 運作流程

```
run_monthly.py            決定「本期結算日」（最近一個 21 日）
   │                      設定帳單區間：前月 22 日 ~ 本期 21 日
   ▼
main.py                   逐一處理 banks.json 內的銀行
   │
   ├─ gmail_client        用 from: + 主旨關鍵字 + 日期區間找信
   │                      → 下載 PDF 附件（或只取內文）
   ├─ pdf_handler         用 keyring 內的密碼解密
   ├─ statement_parser    文字層 → 失敗則 OCR（可裁切特定區域）
   └─ sheets_client       寫入 B 欄（繳款截止日）與本期金額欄
   ▼
cleanup.py                刪除 downloads\ 與 temp\ 內的敏感檔案
```

## 需求

- Python 3.10 以上
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)（只有需要 OCR 的銀行才用得到，需含繁體中文語系）
- 一個 Google Cloud 專案（啟用 Gmail API 與 Google Sheets API）

## 安裝

```bash
git clone https://github.com/julienyang-cloud/credit-card-automation.git
cd credit-card-automation

python -m venv venv
venv\Scripts\activate          # macOS / Linux: source venv/bin/activate
pip install -r requirements.txt
```

Tesseract 安裝：

| 平台 | 指令 |
|---|---|
| Windows | 安裝 [UB Mannheim 版](https://github.com/UB-Mannheim/tesseract/wiki)，勾選 Chinese (Traditional) |
| macOS | `brew install tesseract tesseract-lang` |
| Ubuntu | `sudo apt install tesseract-ocr tesseract-ocr-chi-tra` |

程式會自動尋找常見安裝路徑；找不到時可用環境變數指定：

```bash
set TESSERACT_CMD=C:\path\to\tesseract.exe
```

## 設定

### 1. 建立憑證資料夾

所有憑證都放在 `secrets\`（已列入 `.gitignore`）：

```
secrets\
  credentials.json       Google OAuth 用戶端憑證（讀 Gmail）
  token.json             授權後自動產生，不要手動編輯
  service_account.json   服務帳戶金鑰（寫 Google Sheet）
```

### 2. OAuth 用戶端（讀 Gmail）

1. 到 [Google Cloud Console](https://console.cloud.google.com/) 建立專案。
2. 「API 和服務」→ 啟用 **Gmail API**。
3. 「OAuth 同意畫面」→ 使用者類型選 **External**，填入應用程式名稱，並把自己的 Gmail 加入測試使用者。
4. 「憑證」→ 建立憑證 → **OAuth 用戶端 ID** → 應用程式類型選 **桌面應用程式**。
5. 下載 JSON，改名為 `secrets\credentials.json`。

> **重要**：OAuth 同意畫面若停在「Testing」狀態，refresh token **每 7 天就會過期**，排程會突然失敗。設定完成後請把「發布狀態」改為 **In production**（個人自用不需要通過 Google 驗證，只是會顯示「未驗證應用程式」警告）。

### 3. 服務帳戶（寫 Google Sheet）

1. 同一個專案 → 啟用 **Google Sheets API**。
2. 「憑證」→ 建立憑證 → **服務帳戶** → 建立完成後進入該帳戶 → 「金鑰」→ 新增金鑰 → JSON。
3. 下載的檔案改名為 `secrets\service_account.json`。
4. 複製服務帳戶的 email（`xxx@xxx.iam.gserviceaccount.com`），到你的 Google Sheet 按「共用」，把它加入為 **編輯者**。

### 4. 銀行清單 `banks.json`

```bash
copy banks.example.json banks.json     # macOS / Linux: cp
```

```json
{
  "spreadsheet": "我的信用卡帳單",
  "banks": {
    "CTBC": {
      "sender": "ebill@estats.ctbcbank.com",
      "subject": "信用卡",
      "keyring_code": "CTBC",
      "row_label": "CTBC"
    },
    "Rakuten": {
      "sender": "info@card.rakuten.com.tw",
      "subject": "電子帳單",
      "keyring_code": "Rakuten",
      "row_label": "Rakuten",
      "has_attachment": false
    }
  }
}
```

| 欄位 | 說明 |
|---|---|
| `spreadsheet` | Google Sheet 的檔名 |
| `sender` | 帳單寄件者，會組成 `from:` 查詢 |
| `subject` | 主旨關鍵字，留空則不篩選 |
| `keyring_code` | 到 keyring 取 PDF 密碼時用的鍵，預設同銀行代號 |
| `row_label` | 試算表 A 欄要對到的名稱 |
| `alt_names` | A 欄的備用名稱（例如同時存在「星展」與「DBS」） |
| `has_attachment` | 設 `false` 時查詢不加 `has:attachment`（信件本身不帶附件的銀行） |

`banks.json` 已列入 `.gitignore`，不會被提交。

### 5. 帳單 PDF 密碼

```bash
python setup_passwords.py          # 逐一輸入，密碼不會顯示在螢幕上
python setup_passwords.py --list   # 檢查哪些已設定
```

密碼存進系統 keyring，服務名稱為 `credit_card_auto`。銀行帳單若沒加密，可以跳過。

### 6. 試算表格式

```
     A            B              C            D            E
1               繳款截止日      2026/10/21   2026/11/21   2026/12/21
2   CTBC        2026/11/25      33625        33532
3   Rakuten     26                            no mail
4   Fubon       24                            no pdf
...
15  Total                                     45096
```

- **A 欄**：銀行名稱，程式只讀不寫。
- **B 欄**：繳款截止日，每次執行更新。
- **第 1 列 C 欄以後**：各期的執行日。程式會用「本期結算日」的年月去對應欄位，例如 11/21 執行就寫入 `D1=2026/11/21` 那一欄。
- **Total 列**：程式**不會**碰你的 `SUM` 公式；文字標記（`no mail` 等）會被 `SUM` 忽略。

## 執行

```bash
python run_monthly.py                    # 正常執行，同一期只跑一次
python run_monthly.py --force            # 忽略「本期已跑過」，強制重跑
python run_monthly.py --date 2026/11/21  # 模擬某一天（不會寫完成標記）
```

Windows 也可以直接雙擊 `run_now.bat`。

執行紀錄寫在 `logs\run_YYYYMMDD_HHMMSS.log`；跑完會在 `logs\` 留下 `.done_YYYY-MM` 標記，同一期再次觸發會直接跳過。

### 狀態標記

資料寫不進去時，會在該期的金額欄寫入標記，不會留空白：

| 標記 | 意義 |
|---|---|
| `no mail` | 找不到帳單信件（可能沒消費、沒寄送，或寄件者設定要調整） |
| `no pdf` | 有帳單信，但沒有 PDF 附件（銀行只寄登入連結） |
| `no detect` | 有 PDF，但辨識不出應繳金額 |
| `need review` | 有金額，但缺繳款截止日／最低應繳金額，或 OCR 信心不足 |
| `sheet error` | 寫入 Google Sheet 失敗 |

`need review` / `no detect` 會保留該銀行的除錯檔（`temp\<銀行>_page_0.txt`）方便檢查。

## 排程（Windows）

先用 `schtasks` 建立「每月 21 日 09:00」的任務：

```powershell
schtasks /create /tn "CreditCard_Monthly" ^
  /tr "\"C:\path\to\credit_card_auto\venv\Scripts\pythonw.exe\" \"C:\path\to\credit_card_auto\run_monthly.py\"" ^
  /sc monthly /d 21 /st 09:00 /f
```

再到「工作排程器」開啟這個任務，確認三件事：

- **一般** → 勾選「只在使用者登入時執行」（`InteractiveToken`）。這是必要的，因為 PDF 密碼存在使用者的 keyring。
- **設定** → 勾選「如果錯過排定的開始時間，請儘快執行」（`StartWhenAvailable`），電腦關機時才不會漏掉。
- **條件** → 取消「只有在電腦使用 AC 電源時才執行」。

或用 PowerShell 一次設定好：

```powershell
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
                                         -AllowStartIfOnBatteries `
                                         -DontStopIfGoingOnBatteries `
                                         -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Set-ScheduledTask -TaskName "CreditCard_Monthly" -Settings $settings
```

排程若在 22 號才補跑，帳單區間仍以「21 日」計算，不會多抓資料，也不會寫錯欄位。

## 安全性設計

- `secrets\`、`banks.json`、`logs\`、`downloads\`、`temp\` 全部列入 `.gitignore`。
- PDF 密碼存在系統 keyring，不寫入檔案、不寫入 log。
- 附件檔名會過濾路徑字元，避免寫到 `downloads\` 之外。
- 授權 token 以 JSON 儲存，不使用 `pickle`（避免反序列化風險）。
- 執行完自動刪除 PDF、圖片、OCR 文字檔；保留的除錯檔（如 `page_0.txt`、`page_0.png`）超過 60 天自動強制清理。
- 歷史執行日誌（`logs\run_*.log`）加入輪替機制，僅保留最近 120 天，避免財務紀錄無限期留存。

已知限制：

- `os.remove()` 只是移除檔案，不是安全抹除。SSD 上實際復原難度高，但請不要當成「銷毀」。
- `gmail.readonly` 是整個信箱的讀取權限（Google 沒有更細的 Gmail scope）。授權前請理解這一點。
- `token.json` 等同信箱的長期鑰匙，外流後請立即到 Google 帳號的「第三方應用程式」撤銷授權。
- 銀行帳單格式會變動，解析失敗時會標記狀態，但**不保證金額正確**，重要帳款請自行核對。

## 專案結構

```
credit_card_auto\
  config.py             路徑、banks.json 載入、帳單區間
  gmail_client.py       Gmail 查詢、附件下載、內文取出
  pdf_handler.py        PDF 解密、檔案清理
  statement_parser.py   各銀行解析規則（文字層 / OCR）
  sheets_client.py      Google Sheets 寫入與欄位定位
  main.py               單一銀行的處理流程
  run_monthly.py        排程進入點、補跑與去重
  cleanup.py            敏感檔案刪除
  setup_passwords.py    設定 keyring 密碼
  banks.example.json    銀行設定範例
  requirements.txt
```

## 免責聲明

本專案只會讀取你自己的信箱與你授權的試算表，不會上傳任何資料到第三方。銀行帳單格式與欄位可能隨時調整，解析結果僅供參考，繳款前請以銀行官方資訊為準。使用本專案造成的任何損失，作者不負任何責任。

## License

[MIT](LICENSE)
