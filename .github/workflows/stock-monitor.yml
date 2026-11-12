name: Stock Monitor

on:
  schedule:
    - cron: "7,17,27,37,47,57 * * * *"   # 约每 10 分钟一次 (避开整点高峰; GitHub 仍可能延迟)
  workflow_dispatch:
    inputs:
      test_email:
        description: "只发送测试邮件 (不检测网页)"
        type: boolean
        default: false

jobs:
  check:
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v6

      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          playwright install --with-deps chromium

      - name: Run check
        env:
          GMAIL_USER: ${{ secrets.GMAIL_USER }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          MAIL_TO: ghhchina714@gmail.com
          TIMEZONE: America/New_York   # 日志/邮件显示的时区 (美东)
        run: |
          if [ "${{ inputs.test_email }}" = "true" ]; then
            python check_stock.py --test-email
          else
            python check_stock.py
          fi

      - name: Upload screenshot
        if: always()
        uses: actions/upload-artifact@v6
        with:
          name: screenshot
          path: screenshot.png
          if-no-files-found: ignore
