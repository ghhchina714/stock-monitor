#!/usr/bin/env python3
"""
Van Cleef & Arpels 补货监控 (Python + Playwright)

退出码:
  0 = 检测成功 (有货会发邮件; 没货只打印日志)
  1 = 两个按钮都"看不到" (页面异常/被拦截), 已保存截图
  2 = 其他错误 (网络、邮件发送失败等), 尽量保存截图

用法:
  python check_stock.py               # 正常检测
  python check_stock.py --test-email  # 只发一封测试邮件, 不打开网页

需要的环境变量 (在 GitHub Secrets 里设置, 代码里不写密码):
  GMAIL_USER          发件 Gmail 地址
  GMAIL_APP_PASSWORD  Gmail 应用专用密码 (16 位)
  MAIL_TO             (可选) 收件邮箱, 不设置则发给自己
"""

import argparse
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.message import EmailMessage

PRODUCT_URL = (
    "https://www.vancleefarpels.com/us/en/collections/jewelry/alhambra/"
    "vcard35600---vintage-alhambra-bracelet-5-motifs.html"
)

# 按钮文字 (正则, 不区分大小写)。要改文字就改这里。
IN_STOCK_PATTERN = r"^\s*add to (bag|cart)\s*$"
OUT_OF_STOCK_PATTERN = r"^\s*order by phone\s*$"

SCREENSHOT_PATH = "screenshot.png"
WAIT_SECONDS = 25  # 最多等页面渲染多少秒

# 在浏览器里运行的 JS: 找出所有匹配文字的按钮, 并严格判断是否"真的可见"
FIND_BUTTONS_JS = """
([inPat, outPat]) => {
  const inRe = new RegExp(inPat, 'i');
  const outRe = new RegExp(outPat, 'i');
  const sel = 'button, a, [role="button"], input[type="submit"], input[type="button"]';

  function isVisible(el) {
    // 自己和所有祖先都不能是 display:none / visibility:hidden / opacity:0 / hidden
    let node = el;
    while (node && node.nodeType === 1) {
      const cs = getComputedStyle(node);
      if (cs.display === 'none') return false;
      if (cs.visibility === 'hidden' || cs.visibility === 'collapse') return false;
      if (parseFloat(cs.opacity) === 0) return false;
      if (node.hasAttribute('hidden')) return false;
      if (node.hasAttribute('inert')) return false;
      node = node.parentElement;
    }
    // 必须有实际大小
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    // 不能被 overflow 裁切到完全看不见 / 被移到屏幕外很远
    if (r.right < 0 || r.bottom < -5000 || r.left > window.innerWidth + 5000) return false;
    return true;
  }

  const out = [];
  document.querySelectorAll(sel).forEach(el => {
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.textContent || '')
      .replace(/\\s+/g, ' ').trim();
    let kind = null;
    if (inRe.test(text)) kind = 'in_stock';
    else if (outRe.test(text)) kind = 'out_of_stock';
    if (!kind) return;
    out.push({
      kind,
      text,
      visible: isVisible(el),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
    });
  });
  return out;
}
"""


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC] {msg}", flush=True)


# ----------------------------------------------------------------- 邮件
def send_email(subject, body):
    user = os.environ.get("GMAIL_USER", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    to_addr = os.environ.get("MAIL_TO", "").strip() or user
    if not user or not password:
        raise RuntimeError("缺少环境变量 GMAIL_USER 或 GMAIL_APP_PASSWORD (请检查 GitHub Secrets)")

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    log(f"邮件已发送 -> {to_addr}")


# ----------------------------------------------------------------- 检测
def check_stock():
    """返回 'in_stock' / 'out_of_stock' / 'unknown'"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        result = "unknown"
        try:
            log(f"打开页面: {PRODUCT_URL}")
            page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=60000)

            # 尝试关掉 cookie 弹窗 (没有也没关系)
            for sel in ("#onetrust-accept-btn-handler", "button:has-text('Accept all')",
                        "button:has-text('Accept All')"):
                try:
                    page.locator(sel).first.click(timeout=1500)
                    break
                except Exception:
                    pass

            # 轮询: 等到任意一个按钮"可见"或超时
            deadline = time.time() + WAIT_SECONDS
            buttons = []
            while time.time() < deadline:
                buttons = page.evaluate(FIND_BUTTONS_JS, [IN_STOCK_PATTERN, OUT_OF_STOCK_PATTERN])
                if any(b["visible"] for b in buttons):
                    break
                time.sleep(1)

            for b in buttons:
                log(f"找到按钮: {b}")

            in_visible = [b for b in buttons if b["kind"] == "in_stock" and b["visible"] and not b["disabled"]]
            out_visible = [b for b in buttons if b["kind"] == "out_of_stock" and b["visible"]]

            if in_visible:
                result = "in_stock"
            elif out_visible:
                result = "out_of_stock"
            else:
                result = "unknown"
        finally:
            try:
                page.screenshot(path=SCREENSHOT_PATH, full_page=True)
                log(f"截图已保存: {SCREENSHOT_PATH}")
            except Exception as e:
                log(f"截图失败: {e}")
            browser.close()
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-email", action="store_true", help="只发测试邮件, 不检测网页")
    args = parser.parse_args()

    if args.test_email:
        try:
            send_email(
                "【测试】补货监控邮件通道正常",
                "如果你收到这封邮件, 说明 Gmail 发信配置成功。\n\n监控商品:\n" + PRODUCT_URL,
            )
            return 0
        except Exception as e:
            log(f"测试邮件失败: {e}")
            return 2

    try:
        state = check_stock()
    except Exception as e:
        log(f"检测出错: {e}")
        return 2

    if state == "in_stock":
        log("结果: 有货!")
        try:
            send_email(
                "🔔 有货了! Van Cleef & Arpels Vintage Alhambra 手链 (5 motifs)",
                "页面上 ADD TO BAG 按钮已可见, 可能补货了!\n\n快去看:\n" + PRODUCT_URL,
            )
        except Exception as e:
            log(f"邮件发送失败: {e}")
            return 2
        return 0

    if state == "out_of_stock":
        log("结果: 没货 (只看到 ORDER BY PHONE)")
        return 0

    log("结果: 两个按钮都看不到 (页面可能被拦截或改版), 已保存截图, 退出码 1")
    return 1


if __name__ == "__main__":
    sys.exit(main())
