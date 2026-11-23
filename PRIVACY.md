# 隱私權政策 / Privacy Policy

最後更新：2026-11-24

## 中文

本工具（以下稱「本程式」）是一個**在使用者自己的電腦上執行**的個人自動化腳本，不是網路服務，也沒有任何伺服器。

### 存取的資料

| 資料 | 用途 | 儲存位置 |
|---|---|---|
| Gmail 信件（`gmail.readonly`） | 搜尋各銀行寄來的信用卡電子帳單，取出 PDF 附件或信件內文 | 只在使用者電腦的記憶體與暫存資料夾 |
| Google Sheets（`spreadsheets`） | 把解析出的「應繳金額」與「繳款截止日」寫入使用者指定的試算表 | 使用者自己的 Google 試算表 |
| 帳單 PDF 密碼 | 解密銀行寄來的加密 PDF | 使用者作業系統的 keyring（Windows 認證管理員），不寫入檔案 |

### 資料流向

- 所有資料**只在該使用者的電腦與其自己的 Google 帳號之間流動**。
- 本程式**不包含任何伺服器端元件**，開發者不會收到、也無法存取任何使用者的信件、金額或試算表內容。
- 不收集分析數據、不埋追蹤碼、不傳送遙測資料。

### 資料保留

- 帳單 PDF、轉出的圖片、OCR 文字檔在資料寫入試算表後**立即刪除**。
- 僅在辨識失敗（`need review` / `no detect`）時保留除錯檔，供使用者自行檢查後刪除。
- OAuth 授權 token 保存在使用者電腦的 `secrets\token.json`，使用者可隨時刪除該檔案或到 Google 帳號的「第三方應用程式」撤銷授權。

### 兒童

本程式不適用於 13 歲以下兒童，也不針對兒童設計。

### 變更

本政策若有修改，會更新本檔案並提交到本儲存庫。

### 聯絡方式

請於本儲存庫開立 Issue：<https://github.com/julienyang-cloud/credit-card-automation/issues>

---

## English

This tool is a **personal automation script that runs on the user's own computer**. It is not a hosted service and has no backend server.

### Data accessed

- **Gmail (`gmail.readonly`)** — used only to find credit-card statement emails and extract the PDF attachment or message body. Messages are processed locally.
- **Google Sheets (`spreadsheets`)** — used only to write the parsed amount and due date into a spreadsheet owned by the user.
- **Statement PDF passwords** — stored in the operating system keyring (Windows Credential Manager), never in a file.

### Data flow

All data stays between the user's computer and the user's own Google account. The developer receives no data and has no ability to access any user's email, amounts, or spreadsheet. There is no analytics, tracking, or telemetry.

### Retention

Statement PDFs, rendered images, and OCR text files are deleted immediately after the results are written to the spreadsheet. Debug files are kept only for failed parses, for the user to inspect and delete. OAuth tokens are stored locally in `secrets\token.json` and can be deleted or revoked at any time from the user's Google Account permissions page.

### Contact

Please open an issue: <https://github.com/julienyang-cloud/credit-card-automation/issues>
