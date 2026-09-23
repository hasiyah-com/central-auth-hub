"""ที่มาของเหตุการณ์ — ตัดสินว่าอะไรนับเป็นผล production ได้.

ลำดับการตัดสิน (ข้อแรกที่เข้าเงื่อนไขชนะ)

  1. demo      marker `RiskDemo` ใน user agent หรือ IP ช่วงเอกสาร (RFC 5737 / RFC 3849)
  2. test      user agent ของชุดทดสอบ (`pytest`, `testclient`)
  3. unknown   ไม่มี IP หรือแปลงเป็น IP ไม่ได้
  4. local     loopback / private / link-local — **ระบุที่มาไม่ได้** ไม่ใช่ "สังเคราะห์"
  5. external  IP สาธารณะ
  6. unknown   ช่วงพิเศษอื่น เช่น CGNAT 100.64.0.0/10

ใช้ `ipaddress` แทนการเทียบ prefix ของสตริง — prefix `172.1` ที่สคริปต์เทียบ
distribution เคยใช้ กิน 172.100.x ซึ่งเป็น IP สาธารณะไปด้วย
"""

from __future__ import annotations

import ipaddress

DEMO_UA_MARKERS = ("RiskDemo",)
TEST_UA_MARKERS = ("pytest", "testclient")
DOC_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
)


def parse_ip(ip) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not ip:
        return None
    try:
        return ipaddress.ip_address(str(ip).split("/")[0].strip())
    except ValueError:
        return None


def classify(ip, user_agent: str | None) -> str:
    ua = user_agent or ""
    if any(m in ua for m in DEMO_UA_MARKERS):
        return "demo"
    addr = parse_ip(ip)
    if addr is not None and any(addr in net for net in DOC_NETWORKS):
        return "demo"
    if any(m in ua for m in TEST_UA_MARKERS):
        return "test"
    if addr is None:
        return "unknown"
    if addr.is_loopback or addr.is_private or addr.is_link_local:
        return "local"
    if addr.is_global:
        return "external"
    return "unknown"


def is_eligible(
    provenance: str, risk_config_id: str | None, scoring_commit: str | None
) -> bool:
    """นับเป็นผล production ได้เมื่อมาจากภายนอก **และ** พิสูจน์คอนฟิกที่รันได้."""
    return provenance == "external" and bool(risk_config_id) and bool(scoring_commit)
