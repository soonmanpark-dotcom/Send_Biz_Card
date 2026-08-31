import json
import socket
import smtplib
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

# Brevo 앞단 Cloudflare 가 기본 Python-urllib User-Agent 를 1010 으로 차단하므로 직접 지정한다.
USER_AGENT = "SendBizCard/1.0"


class EmailSender:
    def __init__(self, config: dict):
        self.card = config["card"]
        self.gmail = config["gmail"]
        self.brevo = config.get("brevo") or {}
        self.subject = config["mail"]["subject"]
        self.html = self._build_html()

    @property
    def _api_key(self) -> str:
        return (self.brevo.get("api_key") or "").strip()

    @property
    def mode(self) -> str:
        """API 키가 있으면 Brevo(HTTPS), 없으면 기존 SMTP 방식을 쓴다."""
        return "brevo" if self._api_key else "smtp"

    def _build_html(self) -> str:
        c = {k: (v if isinstance(v, list) else escape(str(v))) for k, v in self.card.items()}
        # 이름 아래 소속·주소 줄. 첫 줄만 이름과 간격을 준다.
        sub_lines = "".join(
            '<div style="font-size:13px;color:#333;{margin}">{text}</div>'.format(
                margin="margin-top:4px;" if i == 0 else "",
                text=escape(str(line)),
            )
            for i, line in enumerate(self.card.get("lines") or [])
        )
        header = self._build_header(c["name"], sub_lines)
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
        {header}
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

    def _build_header(self, name: str, sub_lines: str) -> str:
        """노란 영역. photo_url 이 있으면 원형 사진을 왼쪽에 붙인 2단 구성으로 만든다.

        메일 클라이언트 호환을 위해 table 레이아웃과 인라인 스타일만 쓴다.
        사진이 없으면 기존과 같은 한 단 구성이다.
        """
        title = (
            f'<div style="font-size:26px;font-weight:bold;color:#1a1a1a;'
            f'letter-spacing:-0.5px;">{name}</div>{sub_lines}'
        )
        photo = (self.card.get("photo_url") or "").strip()
        if not photo:
            return title

        size = int(self.card.get("photo_size") or 88)
        return (
            '<table style="border-collapse:collapse;"><tr>'
            f'<td width="{size + 16}" style="padding:0 16px 0 0;vertical-align:middle;">'
            f'<img src="{escape(photo)}" width="{size}" height="{size}" alt="{name}" '
            f'style="display:block;width:{size}px;height:{size}px;border-radius:50%;'
            'border:3px solid #ffffff;object-fit:cover;">'
            '</td>'
            f'<td style="vertical-align:middle;">{title}</td>'
            '</tr></table>'
        )

    def check(self) -> dict:
        """SMTP 연결과 로그인만 시도해 설정 상태를 진단한다. 메일은 보내지 않는다.

        포트 465/587 을 모두 시도해, 연결 자체가 막힌 것인지(호스팅 차단)
        로그인만 실패한 것인지(비밀번호 오류) 구분할 수 있게 한다.
        비밀번호 자체는 노출하지 않고 길이와 공백 포함 여부만 돌려준다.
        """
        if self.mode == "brevo":
            return self._check_brevo()

        pw = self.gmail["app_password"] or ""
        result = {
            "mode": "smtp",
            "sender": self.gmail["sender_address"],
            "password_length": len(pw),
            "password_has_space": " " in pw,
            "network": self._probe_network(),
            "attempts": [],
        }
        for label, port, use_ssl in (("465-SSL", 465, True), ("587-STARTTLS", 587, False)):
            entry = {"port": label}
            try:
                if use_ssl:
                    server = smtplib.SMTP_SSL("smtp.gmail.com", port, timeout=15)
                else:
                    server = smtplib.SMTP("smtp.gmail.com", port, timeout=15)
                    server.starttls()
                entry["connect"] = "ok"
                try:
                    server.login(self.gmail["sender_address"], pw)
                    entry["login"] = "ok"
                except Exception as e:
                    entry["login"] = f"{type(e).__name__}: {e}"
                try:
                    server.quit()
                except Exception:
                    pass
            except Exception as e:
                entry["connect"] = f"{type(e).__name__}: {e}"
            result["attempts"].append(entry)
        return result

    @staticmethod
    def _probe_network() -> dict:
        """주소별로 직접 TCP 연결을 시도해, IPv6 문제인지 포트 차단인지 구분한다."""
        out = {}
        for label, host, port in (
            ("smtp-465", "smtp.gmail.com", 465),
            ("smtp-587", "smtp.gmail.com", 587),
            ("https-443", "www.google.com", 443),
        ):
            tried = []
            try:
                addrs = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
            except Exception as e:
                out[label] = {"resolve": f"{type(e).__name__}: {e}"}
                continue
            for family, _type, _proto, _canon, sockaddr in addrs:
                fam = "IPv6" if family == socket.AF_INET6 else "IPv4"
                sock = socket.socket(family, socket.SOCK_STREAM)
                sock.settimeout(8)
                try:
                    sock.connect(sockaddr)
                    tried.append(f"{fam} {sockaddr[0]} → ok")
                except Exception as e:
                    tried.append(f"{fam} {sockaddr[0]} → {type(e).__name__}: {e}")
                finally:
                    sock.close()
            out[label] = tried
        return out

    def _check_brevo(self) -> dict:
        """Brevo API 키가 유효한지, 발신 주소가 등록·인증되어 있는지 확인한다."""
        out = {
            "mode": "brevo",
            "sender": self.gmail["sender_address"],
            "api_key_length": len(self._api_key),
        }
        account = self._brevo_get("https://api.brevo.com/v3/account")
        if isinstance(account, dict):
            out["api_key"] = "ok"
            out["account_email"] = account.get("email")
        else:
            out["api_key"] = account
            return out

        senders = self._brevo_get("https://api.brevo.com/v3/senders")
        if isinstance(senders, dict):
            listed = senders.get("senders") or []
            out["registered_senders"] = [
                {"email": x.get("email"), "active": x.get("active")} for x in listed
            ]
            out["sender_is_registered"] = any(
                (x.get("email") or "").lower() == self.gmail["sender_address"].lower()
                and x.get("active")
                for x in listed
            )
        else:
            out["registered_senders"] = senders
        return out

    def _brevo_get(self, url: str):
        req = urllib.request.Request(
            url,
            headers={
                "api-key": self._api_key,
                "accept": "application/json",
                "user-agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
        except Exception as e:
            return f"{type(e).__name__}: {e}"

    def send(self, recipient: str) -> bool:
        """설정에 따라 Brevo(HTTPS) 또는 SMTP 로 발송한다."""
        if self.mode == "brevo":
            return self._send_via_brevo(recipient)
        return self._send_via_smtp(recipient)

    def _send_via_brevo(self, recipient: str) -> bool:
        payload = {
            "sender": {"name": self.card["name"], "email": self.gmail["sender_address"]},
            "to": [{"email": recipient}],
            "subject": self.subject,
            "htmlContent": self.html,
        }
        req = urllib.request.Request(
            "https://api.brevo.com/v3/smtp/email",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "api-key": self._api_key,
                "content-type": "application/json",
                "accept": "application/json",
                "user-agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                return 200 <= res.status < 300
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            print(f"[EmailSender] Brevo 발송 실패 (HTTP {e.code}): {detail}")
            return False
        except Exception as e:
            print(f"[EmailSender] Brevo 발송 실패: {type(e).__name__}: {e}")
            return False

    def _send_via_smtp(self, recipient: str) -> bool:
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
