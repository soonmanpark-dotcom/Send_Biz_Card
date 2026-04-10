import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class EmailSender:
    def __init__(self, config: dict):
        self.card = config["card"]
        self.gmail = config["gmail"]
        self.subject = config["mail"]["subject"]
        self.html = self._build_html()

    def _build_html(self) -> str:
        c = self.card
        return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:20px;font-family:'Malgun Gothic',Arial,sans-serif;background:#f4f4f4;">
  <table style="max-width:480px;margin:auto;background:#fff;border-radius:8px;
                box-shadow:0 2px 8px rgba(0,0,0,0.1);overflow:hidden;">
    <tr>
      <td style="padding:24px 28px;border-bottom:1px solid #f0f0f0;">
        <p style="margin:0 0 8px 0;font-size:14px;color:#444;line-height:1.7;">
          안녕하세요. 반갑습니다.<br>
          제 간단한 연락처 정보는 아래와 같습니다.<br>
          앞으로 소통하시면서 좋은 관계 유지하기를 희망합니다.<br>
          감사합니다.
        </p>
      </td>
    </tr>
    <tr>
      <td style="background:#FEE500;padding:20px 28px;">
        <div style="font-size:26px;font-weight:bold;color:#1a1a1a;letter-spacing:-0.5px;">{c['name']}</div>
        <div style="font-size:13px;color:#333;margin-top:4px;">{c['title']}, {c['department']}</div>
        <div style="font-size:13px;color:#333;">{c['company']}</div>
      </td>
    </tr>
    <tr>
      <td style="padding:20px 28px;">
        <table style="width:100%;border-collapse:collapse;font-size:13px;color:#444;">
          <tr>
            <td style="padding:6px 0;width:76px;color:#888;">전화</td>
            <td style="padding:6px 0;">{c['phone']}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#888;">카카오 ID</td>
            <td style="padding:6px 0;">{c['kakao_id']}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#888;">이메일</td>
            <td style="padding:6px 0;"><a href="mailto:{c['email']}" style="color:#0077cc;">{c['email']}</a></td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    def send(self, recipient: str) -> bool:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = self.subject
        msg["From"] = self.gmail["sender_address"]
        msg["To"] = recipient
        msg.attach(MIMEText(self.html, "html", "utf-8"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.gmail["sender_address"], self.gmail["app_password"])
                server.sendmail(self.gmail["sender_address"], [recipient], msg.as_string())
            return True
        except Exception as e:
            print(f"[EmailSender] 발송 실패: {e}")
            return False
