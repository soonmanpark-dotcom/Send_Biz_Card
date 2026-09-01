import base64
import json
import socket
import smtplib
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from html import escape
from urllib.parse import urlencode

# Brevo 앞단 Cloudflare 가 기본 Python-urllib User-Agent 를 1010 으로 차단하므로 직접 지정한다.
USER_AGENT = "SendBizCard/1.0"


class EmailSender:
    def __init__(self, config: dict):
        self.card = config["card"]
        self.gmail = config["gmail"]
        self.brevo = config.get("brevo") or {}
        self.gmail_api = config.get("gmail_api") or {}
        self.subject = config["mail"]["subject"]
        self.html = self._build_html()

    @property
    def _api_key(self) -> str:
        return (self.brevo.get("api_key") or "").strip()

    @property
    def _google(self) -> dict:
        return self.gmail_api

    @property
    def _google_ready(self) -> bool:
        g = self.gmail_api
        return all((g.get("client_id"), g.get("client_secret"), g.get("refresh_token")))

    @property
    def mode(self) -> str:
        """Gmail API > Brevo > SMTP 순으로 사용 가능한 방식을 고른다.

        Gmail API 는 보낸사람이 실제 Gmail 주소로 나가고 HTTPS 를 쓰므로
        SMTP 가 막힌 호스팅에서도 동작한다.
        """
        if self._google_ready:
            return "gmail_api"
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
        contact_rows = self._build_contact_rows()
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
{contact_rows}
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    def _build_contact_rows(self) -> str:
        """연락처 표의 각 줄. 값이 비어 있는 항목은 아예 표시하지 않는다."""
        c = self.card
        rows = []

        def row(label: str, value: str, first: bool = False) -> str:
            width = ' width="76"' if first else ""
            return (
                f'<tr><td style="padding:6px 0;color:#888;"{width}>{escape(label)}</td>'
                f'<td style="padding:6px 0;">{value}</td></tr>'
            )

        if c.get("phone"):
            rows.append(row("전화", escape(str(c["phone"])), first=True))
        if c.get("kakao_id"):
            rows.append(row("카카오 ID", escape(str(c["kakao_id"]))))
        if c.get("email"):
            mail = escape(str(c["email"]))
            rows.append(row("이메일", f'<a href="mailto:{mail}" style="color:#0077cc;">{mail}</a>'))
        if c.get("homepage"):
            url = str(c["homepage"]).strip()
            # 링크 글자는 보기 좋게 http(s):// 와 끝 슬래시를 뗀 형태로 보여준다.
            label = url.split("://", 1)[-1].rstrip("/")
            rows.append(
                row(
                    "홈페이지",
                    f'<a href="{escape(url)}" style="color:#0077cc;">{escape(label)}</a>',
                )
            )
        return "".join(rows)

    def _build_header(self, name: str, sub_lines: str) -> str:
        """노란 영역 구성. photo_layout 으로 사진 배치를 고른다.

        좁은 화면(모바일 메일 앱)에서는 가로 공간이 부족해, 사진 옆에 긴 글이
        들어가면 이름과 주소가 어색하게 끊긴다. 그래서 배치를 선택할 수 있게 한다.

          stack   : 사진 위, 글자는 전체 폭 (어떤 화면에서도 안전)
          compact : 사진 옆에 이름만, 주소는 아래 전체 폭
          side    : 사진 옆에 이름과 주소 모두 (넓은 화면 전용)

        메일 클라이언트 호환을 위해 table 레이아웃과 인라인 스타일만 쓴다.
        """
        photo = (self.card.get("photo_url") or "").strip()

        def title(size: int = 26) -> str:
            return (
                f'<div style="font-size:{size}px;font-weight:bold;color:#1a1a1a;'
                f'letter-spacing:-0.5px;line-height:1.25;">{name}</div>'
            )

        if not photo:
            return title() + sub_lines

        size = int(self.card.get("photo_size") or 72)
        layout = (self.card.get("photo_layout") or "stack").strip()
        img = (
            f'<img src="{escape(photo)}" width="{size}" height="{size}" alt="{name}" '
            f'style="display:block;width:{size}px;height:{size}px;border-radius:50%;'
            'border:3px solid #ffffff;object-fit:cover;">'
        )

        if layout == "side":
            return (
                '<table style="border-collapse:collapse;"><tr>'
                f'<td width="{size + 16}" style="padding:0 16px 0 0;vertical-align:middle;">{img}</td>'
                f'<td style="vertical-align:middle;">{title()}{sub_lines}</td>'
                "</tr></table>"
            )
        if layout == "compact":
            return (
                '<table style="border-collapse:collapse;"><tr>'
                f'<td width="{size + 14}" style="padding:0 14px 0 0;vertical-align:middle;">{img}</td>'
                f'<td style="vertical-align:middle;">{title(21)}</td>'
                f'</tr></table><div style="margin-top:12px;">{sub_lines}</div>'
            )
        return f'<div style="margin-bottom:12px;">{img}</div>{title()}{sub_lines}'

    def check(self) -> dict:
        """SMTP 연결과 로그인만 시도해 설정 상태를 진단한다. 메일은 보내지 않는다.

        포트 465/587 을 모두 시도해, 연결 자체가 막힌 것인지(호스팅 차단)
        로그인만 실패한 것인지(비밀번호 오류) 구분할 수 있게 한다.
        비밀번호 자체는 노출하지 않고 길이와 공백 포함 여부만 돌려준다.
        """
        if self.mode == "gmail_api":
            return self._check_gmail_api()
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

    def _check_gmail_api(self) -> dict:
        """리프레시 토큰이 살아있는지, 어떤 계정으로 보내게 되는지 확인한다."""
        out = {"mode": "gmail_api", "sender": self.gmail["sender_address"]}
        try:
            token = self._google_access_token()
        except urllib.error.HTTPError as e:
            out["auth"] = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
            return out
        except Exception as e:
            out["auth"] = f"{type(e).__name__}: {e}"
            return out
        out["auth"] = "ok"

        req = urllib.request.Request(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"authorization": f"Bearer {token}", "user-agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                data = json.loads(res.read().decode())
            out["gmail_account"] = data.get("emailAddress")
            out["sender_matches_account"] = (
                (data.get("emailAddress") or "").lower()
                == self.gmail["sender_address"].lower()
            )
        except urllib.error.HTTPError as e:
            out["profile"] = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
        except Exception as e:
            out["profile"] = f"{type(e).__name__}: {e}"
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
        mode = self.mode
        if mode == "gmail_api":
            return self._send_via_gmail_api(recipient)
        if mode == "brevo":
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

    def _build_message(self, recipient: str) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = self.subject
        # formataddr 이 한글 표시 이름을 알아서 인코딩한다.
        msg["From"] = formataddr(
            (self.card["name"], self.gmail["sender_address"]), charset="utf-8"
        )
        msg["To"] = recipient
        msg.attach(MIMEText(self.html, "html", "utf-8"))
        return msg

    # ── Gmail API ─────────────────────────────────────────────────────
    def _google_access_token(self) -> str:
        """리프레시 토큰으로 단기 액세스 토큰을 받아온다."""
        g = self.gmail_api
        data = urlencode({
            "client_id": g["client_id"],
            "client_secret": g["client_secret"],
            "refresh_token": g["refresh_token"],
            "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=data,
            headers={"content-type": "application/x-www-form-urlencoded",
                     "user-agent": USER_AGENT},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode())["access_token"]

    def _send_via_gmail_api(self, recipient: str) -> bool:
        try:
            token = self._google_access_token()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            print(f"[EmailSender] Gmail 인증 실패 (HTTP {e.code}): {detail}")
            return False
        except Exception as e:
            print(f"[EmailSender] Gmail 인증 실패: {type(e).__name__}: {e}")
            return False

        raw = base64.urlsafe_b64encode(
            self._build_message(recipient).as_bytes()
        ).decode()
        req = urllib.request.Request(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            data=json.dumps({"raw": raw}).encode(),
            headers={
                "authorization": f"Bearer {token}",
                "content-type": "application/json",
                "user-agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as res:
                return 200 <= res.status < 300
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            print(f"[EmailSender] Gmail 발송 실패 (HTTP {e.code}): {detail}")
            return False
        except Exception as e:
            print(f"[EmailSender] Gmail 발송 실패: {type(e).__name__}: {e}")
            return False

    def _send_via_smtp(self, recipient: str) -> bool:
        msg = self._build_message(recipient)

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.gmail["sender_address"], self.gmail["app_password"])
                server.sendmail(self.gmail["sender_address"], [recipient], msg.as_string())
            return True
        except Exception as e:
            print(f"[EmailSender] 발송 실패: {e}")
            return False
