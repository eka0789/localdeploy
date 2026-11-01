"""Cloudflare API integration.

Powers one-click domain provisioning: when an application domain is registered
and a Cloudflare Tunnel exists, LocalDeploy can
  1. add an ingress rule to the tunnel (hostname -> http://ld-<slug>:<port>),
  2. create the proxied DNS CNAME <hostname> -> <tunnel-id>.cfargotunnel.com,
so ANY domain on the account (com / id / my.id / biz.id / …) becomes reachable
from the public internet while the local machine is running.

The API token is stored encrypted in server_settings.
"""
from __future__ import annotations

import httpx

from ..core.config import settings
from ..core.security import decrypt_secret, encrypt_secret
from ..models.infrastructure import ServerSetting

CF_BASE = "https://api.cloudflare.com/client/v4"
TOKEN_KEY = "cloudflare.api_token"
ACCOUNT_KEY = "cloudflare.account_id"

CONNECT_TIMEOUT = 15.0


class CloudflareError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# token storage
# ---------------------------------------------------------------------------

def store_credentials(session, api_token: str, account_id: str | None = None) -> None:
    for key, value in ((TOKEN_KEY, api_token), (ACCOUNT_KEY, account_id or "")):
        setting = session.query(ServerSetting).filter_by(key=key).first()
        if setting is None:
            setting = ServerSetting(key=key, value={})
            session.add(setting)
        setting.value = {"value": value}


def get_token(session) -> str | None:
    setting = session.query(ServerSetting).filter_by(key=TOKEN_KEY).first()
    if setting is None:
        return None
    value = (setting.value or {}).get("value", "")
    try:
        return decrypt_secret(value) if value else None
    except ValueError:
        return None


def get_account_id(session) -> str | None:
    setting = session.query(ServerSetting).filter_by(key=ACCOUNT_KEY).first()
    if setting is None:
        return None
    return (setting.value or {}).get("value") or None


def disconnect(session) -> None:
    for key in (TOKEN_KEY, ACCOUNT_KEY):
        setting = session.query(ServerSetting).filter_by(key=key).first()
        if setting:
            session.delete(setting)
    session.commit()


# ---------------------------------------------------------------------------
# low-level API client
# ---------------------------------------------------------------------------

def _cf_request(method: str, path: str, token: str, json_body: dict | None = None,
                params: dict | None = None) -> dict:
    try:
        response = httpx.request(
            method, f"{CF_BASE}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=json_body, params=params, timeout=CONNECT_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise CloudflareError(f"Cloudflare API unreachable: {exc}") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise CloudflareError(f"Cloudflare API returned invalid JSON ({response.status_code})") from exc
    if not data.get("success", False):
        errors = data.get("errors") or [{"message": f"HTTP {response.status_code}"}]
        raise CloudflareError("; ".join(f"[{e.get('code')}] {e.get('message')}" for e in errors))
    return data.get("result") or {}


# ---------------------------------------------------------------------------
# account / zones / tunnels
# ---------------------------------------------------------------------------

def verify_token(token: str) -> dict:
    """Verify the token and return {'account_id', 'account_name'}."""
    _cf_request("GET", "/user/tokens/verify", token)
    accounts = _cf_request("GET", "/accounts", token)
    if not accounts:
        raise CloudflareError(
            "Token valid but has no account access. Create it with Account:Read, "
            "Zone:Read, DNS:Edit and Cloudflare Tunnel:Edit permissions."
        )
    account = accounts[0]
    return {"account_id": account["id"], "account_name": account.get("name", "account")}


def list_zones(token: str) -> list[dict]:
    zones = _cf_request("GET", "/zones", token, params={"per_page": 50})
    return [{"id": z["id"], "name": z["name"], "status": z.get("status")} for z in zones]


def list_account_tunnels(token: str, account_id: str) -> list[dict]:
    result = _cf_request("GET", f"/accounts/{account_id}/cfd_tunnel", token,
                         params={"is_deleted": "false", "per_page": 20})
    tunnels = result if isinstance(result, list) else (result.get("tunnels") or result.get("result") or [])
    return [{
        "id": t["id"],
        "name": t.get("name"),
        "status": t.get("status"),
        "connections": len(t.get("connections") or []),
    } for t in tunnels]


# ---------------------------------------------------------------------------
# ingress + DNS provisioning
# ---------------------------------------------------------------------------

def get_tunnel_config(token: str, account_id: str, tunnel_id: str) -> list[dict]:
    result = _cf_request("GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations", token)
    return (result.get("config") or {}).get("ingress") or []


def build_ingress(existing: list[dict], hostname: str, service: str) -> list[dict]:
    """Merge a new hostname rule into an ingress list (pure, testable).

    Replaces any existing rule for the same hostname; keeps the catch-all last.
    """
    catch_all = {"service": "http_status:404"}
    others = [r for r in existing if not _is_catch_all(r)]
    others = [r for r in others if r.get("hostname") != hostname]
    rules = [{"hostname": hostname, "service": service, "origin_request": {"no_tls_verify": True}}]
    rules += others
    rules.append(catch_all)
    return rules


def _is_catch_all(rule: dict) -> bool:
    return "hostname" not in rule or rule.get("service", "").startswith("http_status")


def put_tunnel_config(token: str, account_id: str, tunnel_id: str, ingress: list[dict]) -> None:
    _cf_request("PUT", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations", token,
                json_body={"config": {"ingress": ingress}})


def find_zone_for_hostname(zones: list[dict], hostname: str) -> dict | None:
    """Longest-suffix zone match: app.example.co.id matches zone example.co.id."""
    candidates = [z for z in zones if hostname == z["name"] or hostname.endswith("." + z["name"])]
    if not candidates:
        return None
    return max(candidates, key=lambda z: len(z["name"]))


def create_dns_cname(token: str, zone_id: str, hostname: str, tunnel_id: str) -> dict:
    """Create (or return existing) proxied CNAME to the tunnel."""
    target = f"{tunnel_id}.cfargotunnel.com"
    try:
        return _cf_request("POST", f"/zones/{zone_id}/dns_records", token, json_body={
            "type": "CNAME", "name": hostname, "content": target,
            "proxied": True, "ttl": 1, "comment": "Managed by LocalDeploy",
        })
    except CloudflareError as exc:
        # 81053/81057 = record already exists — treat as success if it points at us
        if "81053" in str(exc) or "81057" in str(exc) or "already exists" in str(exc).lower():
            records = _cf_request("GET", f"/zones/{zone_id}/dns_records", token,
                                  params={"name": hostname, "per_page": 5})
            for record in records:
                if record.get("content") == target:
                    return record
        raise


def delete_dns_record(token: str, zone_id: str, record_id: str) -> None:
    _cf_request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}", token)


# ---------------------------------------------------------------------------
# high-level provisioning used by the domains route
# ---------------------------------------------------------------------------

def provision_domain(session, domain, app_slug: str, target_port: int, tunnel_id: str) -> dict:
    """Full auto-provisioning for one application domain. Returns a report."""
    token = get_token(session)
    if not token:
        raise CloudflareError("Cloudflare account not connected. Add the API token on the Networking page.")
    account_id = get_account_id(session)
    if not account_id:
        raise CloudflareError("Cloudflare account ID missing — reconnect the account.")

    service = f"http://ld-{app_slug}:{target_port}"
    zones = list_zones(token)
    zone = find_zone_for_hostname(zones, domain.hostname)
    if zone is None:
        raise CloudflareError(
            f"Zone for '{domain.hostname}' not found on this Cloudflare account. "
            "Add the domain to Cloudflare DNS first (free plan works)."
        )

    existing = get_tunnel_config(token, account_id, tunnel_id)
    ingress = build_ingress(existing, domain.hostname, service)
    put_tunnel_config(token, account_id, tunnel_id, ingress)
    record = create_dns_cname(token, zone["id"], domain.hostname, tunnel_id)

    domain.cf_tunnel_id = tunnel_id
    domain.cf_zone_id = zone["id"]
    from ..core.db import utcnow

    domain.cf_provisioned_at = utcnow()

    return {
        "hostname": domain.hostname,
        "service": service,
        "zone": zone["name"],
        "dns_record_id": record.get("id"),
        "ingress_rules": len(ingress),
        "message": (
            f"{domain.hostname} → {service} is live. Traffic flows through the tunnel "
            f"while this machine is running. SSL is provided by Cloudflare automatically."
        ),
    }


def token_is_configured(session) -> bool:
    return get_token(session) is not None
