"""Mailbox existence check: asks the recipient's own mail server whether it would accept mail for the
address (SMTP RCPT TO), then disconnects. No email is ever sent.

Results
  EXISTS          server accepted the address and rejected a random address at the same domain
  NOT_FOUND       server says the mailbox does not exist (the same 550 you would get as a bounce)
  CATCH_ALL       server accepts every address at the domain, so existence cannot be confirmed
  NO_MAIL_SERVER  the domain has no mail server (MX/A record) at all
  UNKNOWN         server unreachable, greylisting, or an unclear answer - treat as unconfirmed
"""
import re
import smtplib
import threading
import time
import uuid
from datetime import datetime, timedelta

import dns.exception
import dns.resolver

NOT_FOUND_RE = re.compile(r"5\.1\.[0-9]|5\.4\.1|does not exist|no such user|user unknown|unknown user|"
                          r"recipient not found|invalid recipient|mailbox (unavailable|not found)|address rejected|"
                          r"undeliverable|not a valid", re.I)
BLOCKED_RE = re.compile(r"5\.7\.|blocked|blacklist|spamhaus|reputation|not permitted to relay|relay denied|"
                        r"client host|policy|authentication required|try again later", re.I)
HELO_NAME = "usajobhunter.local"
TIMEOUT = 20
RECHECK_AFTER = timedelta(days=7)
_host_last: dict[str, float] = {}
_lock = threading.Lock()
_catch_all_cache: dict[str, tuple[bool, float]] = {}


def _mx_hosts(domain: str) -> list[str]:
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=15)
        return [r.exchange.to_text().rstrip(".") for r in sorted(answers, key=lambda r: r.preference)]
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        # RFC 5321: a domain with an A record and no MX receives mail on that host
        try:
            dns.resolver.resolve(domain, "A", lifetime=15)
            return [domain]
        except dns.exception.DNSException:
            return []
    except dns.exception.DNSException:
        raise


def _polite(host: str):
    with _lock:
        wait = 2.0 - (time.monotonic() - _host_last.get(host, 0))
        _host_last[host] = time.monotonic() + max(wait, 0)
    if wait > 0:
        time.sleep(wait)


def check(address: str) -> dict:
    now = datetime.utcnow()
    address = (address or "").strip()
    out = {"address": address, "result": "UNKNOWN", "code": None, "detail": None, "mx": None,
           "checked_at": now.isoformat(timespec="seconds")}
    if "@" not in address:
        out.update(result="NOT_FOUND", detail="Not an email address")
        return out
    domain = address.rsplit("@", 1)[1].lower()
    try:
        hosts = _mx_hosts(domain)
    except dns.exception.DNSException as e:
        out["detail"] = f"DNS lookup failed: {type(e).__name__}"
        return out
    if not hosts:
        out.update(result="NO_MAIL_SERVER", detail=f"{domain} has no mail server")
        return out
    for host in hosts[:2]:
        try:
            _polite(host)
            with smtplib.SMTP(host, 25, timeout=TIMEOUT, local_hostname=HELO_NAME) as s:
                s.ehlo_or_helo_if_needed()
                code, msg = s.mail("")
                if code >= 400:
                    out.update(code=code, detail=msg.decode(errors="ignore")[:200], mx=host)
                    continue
                code, msg = s.rcpt(address)
                text = msg.decode(errors="ignore").replace("\n", " ")[:240]
                out.update(code=code, detail=text, mx=host)
                if code in (250, 251):
                    catch_all = _catch_all_cache.get(domain)
                    if not catch_all or time.time() - catch_all[1] > 86400:
                        c2, _ = s.rcpt(f"no-such-user-{uuid.uuid4().hex[:12]}@{domain}")
                        _catch_all_cache[domain] = (c2 in (250, 251), time.time())
                    out["result"] = "CATCH_ALL" if _catch_all_cache[domain][0] else "EXISTS"
                elif code >= 500 and BLOCKED_RE.search(text):
                    out["result"] = "UNKNOWN"        # the server refused *us* (IP/policy), not the mailbox
                elif code >= 500 and NOT_FOUND_RE.search(text):
                    out["result"] = "NOT_FOUND"
                elif code in (550, 551, 553):
                    out["result"] = "NOT_FOUND"
                elif 400 <= code < 500:
                    out["result"] = "UNKNOWN"        # greylisting / temporary - try again later
                else:
                    out["result"] = "UNKNOWN"
                try:
                    s.rset()
                except smtplib.SMTPException:
                    pass
                return out
        except (OSError, smtplib.SMTPException) as e:
            out.update(detail=f"{host}: {type(e).__name__} {e}"[:200], mx=host)
            continue
    return out


def needs_check(checked_at: datetime | None) -> bool:
    return checked_at is None or datetime.utcnow() - checked_at > RECHECK_AFTER
