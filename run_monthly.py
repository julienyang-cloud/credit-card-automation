"""排程進入點：每月 21 日處理信用卡帳單。

電腦不一定整天開著，所以本檔不靠「今天剛好是 21 日」判斷，而是看
「最近一個 21 日（本期）是否已經跑過」：

  - 21 日 09:00 電腦開著   -> 排程直接執行
  - 21 日關機、22 日才開機 -> Task Scheduler 補執行（StartWhenAvailable）
                              本檔判斷本期還沒跑，於是補跑
  - 本月已跑過             -> 直接跳過，不會重複寫入

帳單區間一律以「本期 21 日」計算，不會因為補跑日期較晚而多抓資料。

參數：
  --force              忽略「已跑過」檢查，立刻執行
  --date YYYY/MM/DD    模擬「今天是某一天」，區間為前月 22 日 ~ 該日
                       （模擬不會寫入完成標記，可重複執行）

本檔用 pythonw.exe 執行時沒有主控台，所以訊息一律寫入 logs\\。

範例：
    venv\\Scripts\\python.exe run_monthly.py --date 2026/10/21
"""
import datetime
import os
import sys
import traceback

import config


def _log_dir():
    log_dir = os.path.join(config.BASE_DIR, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _emit(message):
    """有主控台才印；pythonw.exe 底下 sys.stdout 是 None。"""
    if sys.stdout is not None:
        print(message)


def _parse_date(text):
    for fmt in ('%Y/%m/%d', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise SystemExit(f'日期格式錯誤，請用 YYYY/MM/DD：{text}')


def _previous_month_22(day):
    """回傳前一個月的 22 日。"""
    if day.month == 1:
        return datetime.date(day.year - 1, 12, 22)
    return datetime.date(day.year, day.month - 1, 22)


def _period_date(today):
    """最近一個已經到來的 21 日。

    21 日（含）之後 -> 本月 21 日；否則 -> 上月 21 日。
    補跑時仍以這個日期計算區間，欄位才不會跑掉。
    """
    if today.day >= 21:
        return datetime.date(today.year, today.month, 21)
    if today.month == 1:
        return datetime.date(today.year - 1, 12, 21)
    return datetime.date(today.year, today.month - 1, 21)


def _marker_path(period):
    return os.path.join(_log_dir(), f'.done_{period:%Y-%m}')


def _already_done(period):
    return os.path.exists(_marker_path(period))


def _mark_done(period):
    with open(_marker_path(period), 'w', encoding='utf-8') as f:
        f.write(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n')


def _parse_args(argv):
    options = {'force': False, 'date': None}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == '--force':
            options['force'] = True
        elif arg == '--date':
            index += 1
            if index >= len(argv):
                raise SystemExit('--date 後面要接日期，例如 --date 2026/10/21')
            options['date'] = _parse_date(argv[index])
        elif arg.startswith('--date='):
            options['date'] = _parse_date(arg.split('=', 1)[1])
        index += 1
    return options


def _apply_statement_window(day):
    """把帳單區間設為 前月22日 ~ day，並回傳實際使用的區間。"""
    start = _previous_month_22(day)
    config.STATEMENT_START = start.strftime('%Y/%m/%d')
    config.STATEMENT_END = day.strftime('%Y/%m/%d')
    return config.STATEMENT_START, config.STATEMENT_END


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    options = _parse_args(argv)

    simulated = options['date'] is not None
    if simulated:
        period = options['date']
        now = datetime.datetime.combine(period, datetime.time(9, 0))
    else:
        now = datetime.datetime.now()
        period = _period_date(now.date())

    # 本期已跑過就跳過（--force 與模擬執行不受限制）
    if not simulated and not options['force'] and _already_done(period):
        with open(os.path.join(_log_dir(), 'skipped.log'),
                  'a', encoding='utf-8') as skip_log:
            skip_log.write(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S} '
                           f'本期 {period:%Y-%m} 已完成，跳過\n')
        _emit(f'本期 {period:%Y/%m} 已完成，跳過。')
        return 0

    _apply_statement_window(period)

    # 檔名一律用真實時間，避免模擬執行時覆蓋同一份 log
    stamp = datetime.datetime.now()
    log_path = os.path.join(_log_dir(), f'run_{stamp:%Y%m%d_%H%M%S}.log')
    original_stdout, original_stderr = sys.stdout, sys.stderr

    with open(log_path, 'w', encoding='utf-8') as log:
        sys.stdout = log
        sys.stderr = log
        try:
            print(f'=== 信用卡帳單自動化 開始 {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===')
            print(f'本期結算日 {period:%Y/%m/%d}')
            if simulated:
                print(f'（模擬執行日：{period:%Y/%m/%d}）')
            print(f'帳單區間 {config.STATEMENT_START} ~ {config.STATEMENT_END}')
            import main as credit_card_main
            credit_card_main.main()
            print(f'=== 結束 {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===')
        except Exception:
            traceback.print_exc()
            raise
        finally:
            sys.stdout, sys.stderr = original_stdout, original_stderr

    # 只有真實執行才寫完成標記（模擬可重複跑）
    if not simulated:
        _mark_done(period)

    _emit(f'已完成，log: {log_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
