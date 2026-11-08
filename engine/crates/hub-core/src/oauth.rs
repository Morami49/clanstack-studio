//! OAuth 2.1 authorisation server for the hub's Claude connector (D-104, D-128, F-44).
//!
//! Pure logic: no clock, no randomness, no network. The caller passes `now` (ms) and fresh random
//! strings, so every rule here is testable and identical on every node. Follows the MCP
//! authorisation spec and Claude's connector requirements:
//!   * discovery: RFC 9728 protected-resource metadata + RFC 8414 server metadata, 401 pointer
//!   * Dynamic Client Registration (RFC 7591), public clients only (`token_endpoint_auth_method=none`)
//!   * S256 PKCE on every authorisation; codes single-use, short-lived, bound to client + redirect
//!   * redirect URIs: Claude's hosted callback exactly, or loopback on any port (RFC 8252)
//!   * opaque bearer tokens stored only as SHA-256 hashes; rotating refresh tokens; `invalid_grant`
//!   * sign-in upstream (GitHub) is the caller's job; this module only checks the login is allowed

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashMap;

pub const CLAUDE_CALLBACK: &str = "https://claude.ai/api/mcp/auth_callback";
pub const CODE_TTL_MS: i64 = 5 * 60 * 1000;
pub const PENDING_TTL_MS: i64 = 10 * 60 * 1000;
pub const ACCESS_TTL_MS: i64 = 60 * 60 * 1000;
pub const REFRESH_TTL_MS: i64 = 30 * 24 * 60 * 60 * 1000;
pub const SCOPE: &str = "hub";

#[derive(Debug, PartialEq)]
pub struct OAuthError {
    pub status: u16,
    pub error: &'static str,
    pub description: String,
}

impl OAuthError {
    fn new(status: u16, error: &'static str, d: impl Into<String>) -> Self {
        Self { status, error, description: d.into() }
    }
    pub fn body(&self) -> Value {
        json!({ "error": self.error, "error_description": self.description })
    }
}

type R<T> = Result<T, OAuthError>;

pub fn hash(secret: &str) -> String {
    hex::encode(Sha256::digest(secret.as_bytes()))
}

fn b64url(bytes: &[u8]) -> String {
    const A: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::new();
    for c in bytes.chunks(3) {
        let n = (c[0] as u32) << 16 | (*c.get(1).unwrap_or(&0) as u32) << 8 | *c.get(2).unwrap_or(&0) as u32;
        let k = c.len() + 1;
        for i in 0..k {
            out.push(A[(n >> (18 - 6 * i) & 63) as usize] as char);
        }
    }
    out
}

/// PKCE S256: BASE64URL(SHA256(verifier)) == challenge, verifier 43–128 unreserved characters.
pub fn pkce_ok(verifier: &str, challenge: &str) -> bool {
    let ok_chars = verifier.bytes().all(|b| b.is_ascii_alphanumeric() || b"-._~".contains(&b));
    (43..=128).contains(&verifier.len()) && ok_chars && b64url(&Sha256::digest(verifier.as_bytes())) == challenge
}

/// Claude's hosted callback exactly, or a loopback `/callback` on any port (Claude Code).
pub fn redirect_allowed(uri: &str) -> bool {
    if uri == CLAUDE_CALLBACK {
        return true;
    }
    for host in ["http://localhost", "http://127.0.0.1"] {
        if let Some(rest) = uri.strip_prefix(host) {
            let rest = match rest.strip_prefix(':') {
                Some(r) => match r.find('/') {
                    Some(i) if i > 0 && r[..i].bytes().all(|b| b.is_ascii_digit()) => &r[i..],
                    _ => return false,
                },
                None => rest,
            };
            return rest == "/callback";
        }
    }
    false
}

#[derive(Clone, Debug)]
pub struct Config {
    /// e.g. https://clanstack-hub.example.workers.dev (no trailing slash)
    pub issuer: String,
    /// GitHub logins allowed to sign in (owner-only at first, F-44).
    pub allowed_logins: Vec<String>,
}

impl Config {
    pub fn resource(&self) -> String {
        format!("{}/mcp", self.issuer)
    }
    pub fn resource_metadata_url(&self) -> String {
        format!("{}/.well-known/oauth-protected-resource", self.issuer)
    }
    /// The 401 header that starts sign-in.
    pub fn www_authenticate(&self) -> String {
        format!("Bearer resource_metadata=\"{}\", scope=\"{SCOPE}\"", self.resource_metadata_url())
    }
    pub fn protected_resource_metadata(&self) -> Value {
        json!({
            "resource": self.resource(),
            "authorization_servers": [self.issuer],
            "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"],
            "resource_name": "Clanstack hub"
        })
    }
    pub fn authorization_server_metadata(&self) -> Value {
        json!({
            "issuer": self.issuer,
            "authorization_endpoint": format!("{}/authorize", self.issuer),
            "token_endpoint": format!("{}/token", self.issuer),
            "registration_endpoint": format!("{}/register", self.issuer),
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [SCOPE]
        })
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Client {
    pub client_id: String,
    pub redirect_uris: Vec<String>,
    pub client_name: String,
    pub created: i64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Pending {
    pub client_id: String,
    pub redirect_uri: String,
    pub code_challenge: String,
    pub client_state: Option<String>,
    pub expires: i64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct CodeGrant {
    pub client_id: String,
    pub redirect_uri: String,
    pub code_challenge: String,
    pub login: String,
    pub expires: i64,
    pub used: bool,
    /// access/refresh hashes issued from this code: revoked if the code is ever replayed
    pub issued: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Grant {
    pub client_id: String,
    pub login: String,
    pub expires: i64,
}

/// Everything the authorisation server remembers. Secrets appear only as hashes.
#[derive(Default, Debug, Serialize, Deserialize, PartialEq)]
pub struct OAuthState {
    pub clients: HashMap<String, Client>,
    /// keyed by the hub's own upstream `state` (sent to GitHub, not to Claude)
    pub pending: HashMap<String, Pending>,
    /// keyed by hash(code)
    pub codes: HashMap<String, CodeGrant>,
    /// keyed by hash(access token)
    pub access: HashMap<String, Grant>,
    /// keyed by hash(refresh token)
    pub refresh: HashMap<String, Grant>,
}

pub type Params = HashMap<String, String>;

fn need<'a>(p: &'a Params, k: &str) -> R<&'a str> {
    p.get(k).map(String::as_str).filter(|v| !v.is_empty())
        .ok_or_else(|| OAuthError::new(400, "invalid_request", format!("missing {k}")))
}

impl OAuthState {
    pub fn purge(&mut self, now: i64) {
        self.pending.retain(|_, p| p.expires > now);
        self.codes.retain(|_, c| c.expires > now || (c.used && c.expires + REFRESH_TTL_MS > now));
        self.access.retain(|_, g| g.expires > now);
        self.refresh.retain(|_, g| g.expires > now);
    }

    /// RFC 7591 registration. Public clients only; every redirect URI must be allowed.
    pub fn register(&mut self, body: &Value, client_id: String, now: i64) -> R<Value> {
        let uris: Vec<String> = body.get("redirect_uris").and_then(Value::as_array)
            .map(|a| a.iter().filter_map(Value::as_str).map(String::from).collect()).unwrap_or_default();
        if uris.is_empty() || !uris.iter().all(|u| redirect_allowed(u)) {
            return Err(OAuthError::new(400, "invalid_redirect_uri", "redirect URIs must be Claude's callback or a loopback /callback"));
        }
        match body.get("token_endpoint_auth_method").and_then(Value::as_str) {
            None | Some("none") => {}
            Some(_) => return Err(OAuthError::new(400, "invalid_client_metadata", "only public clients (token_endpoint_auth_method=none)")),
        }
        let name = body.get("client_name").and_then(Value::as_str).unwrap_or("client").chars().take(80).collect::<String>();
        let c = Client { client_id: client_id.clone(), redirect_uris: uris.clone(), client_name: name.clone(), created: now };
        self.clients.insert(client_id.clone(), c);
        Ok(json!({
            "client_id": client_id, "client_id_issued_at": now / 1000, "client_name": name,
            "redirect_uris": uris, "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]
        }))
    }

    /// /authorize: validate Claude's request and park it under the hub's own upstream state.
    /// Errors here are shown to the person, never redirected (the redirect URI isn't trusted yet).
    pub fn authorize(&mut self, cfg: &Config, p: &Params, upstream_state: String, now: i64) -> R<()> {
        if need(p, "response_type")? != "code" {
            return Err(OAuthError::new(400, "unsupported_response_type", "response_type must be code"));
        }
        let client = self.clients.get(need(p, "client_id")?)
            .ok_or_else(|| OAuthError::new(400, "invalid_client", "unknown client_id"))?;
        let redirect = need(p, "redirect_uri")?;
        if !client.redirect_uris.iter().any(|u| u == redirect) {
            return Err(OAuthError::new(400, "invalid_request", "redirect_uri not registered for this client"));
        }
        if p.get("code_challenge_method").map(String::as_str) != Some("S256") {
            return Err(OAuthError::new(400, "invalid_request", "code_challenge_method must be S256"));
        }
        let challenge = need(p, "code_challenge")?;
        if let Some(res) = p.get("resource") {
            if res.trim_end_matches('/') != cfg.resource() {
                return Err(OAuthError::new(400, "invalid_target", "resource must be this hub's /mcp"));
            }
        }
        self.pending.insert(upstream_state, Pending {
            client_id: client.client_id.clone(), redirect_uri: redirect.to_string(),
            code_challenge: challenge.to_string(), client_state: p.get("state").cloned(),
            expires: now + PENDING_TTL_MS,
        });
        Ok(())
    }

    /// After upstream sign-in: check the login, mint a single-use code, return Claude's redirect URL.
    pub fn complete(&mut self, cfg: &Config, upstream_state: &str, login: &str, code: &str, now: i64) -> R<String> {
        let p = self.pending.remove(upstream_state).filter(|p| p.expires > now)
            .ok_or_else(|| OAuthError::new(400, "invalid_request", "sign-in expired or unknown; start again from Claude"))?;
        if !cfg.allowed_logins.iter().any(|a| a.eq_ignore_ascii_case(login)) {
            return Err(OAuthError::new(403, "access_denied", format!("{login} is not allowed to use this hub")));
        }
        self.codes.insert(hash(code), CodeGrant {
            client_id: p.client_id, redirect_uri: p.redirect_uri.clone(), code_challenge: p.code_challenge,
            login: login.to_string(), expires: now + CODE_TTL_MS, used: false, issued: vec![],
        });
        let mut url = format!("{}?code={}", p.redirect_uri, enc(code));
        if let Some(s) = p.client_state {
            url.push_str(&format!("&state={}", enc(&s)));
        }
        url.push_str(&format!("&iss={}", enc(&cfg.issuer)));
        Ok(url)
    }

    fn issue(&mut self, client_id: &str, login: &str, access: &str, refresh: &str, now: i64) -> Value {
        let g = |ttl| Grant { client_id: client_id.to_string(), login: login.to_string(), expires: now + ttl };
        self.access.insert(hash(access), g(ACCESS_TTL_MS));
        self.refresh.insert(hash(refresh), g(REFRESH_TTL_MS));
        json!({ "access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TTL_MS / 1000,
                "refresh_token": refresh, "scope": SCOPE })
    }

    /// /token (form-encoded). `new_access`/`new_refresh` are fresh random strings from the caller.
    pub fn token(&mut self, p: &Params, new_access: &str, new_refresh: &str, now: i64) -> R<Value> {
        match need(p, "grant_type")? {
            "authorization_code" => {
                let h = hash(need(p, "code")?);
                let client_id = need(p, "client_id")?.to_string();
                let c = self.codes.get_mut(&h).ok_or_else(|| OAuthError::new(400, "invalid_grant", "unknown code"))?;
                if c.used {
                    // replay: revoke everything this code produced (OAuth 2.1 §4.1.3)
                    let issued = c.issued.clone();
                    for t in issued {
                        self.access.remove(&t);
                        self.refresh.remove(&t);
                    }
                    return Err(OAuthError::new(400, "invalid_grant", "code already used"));
                }
                if c.expires <= now { return Err(OAuthError::new(400, "invalid_grant", "code expired")); }
                if c.client_id != client_id { return Err(OAuthError::new(400, "invalid_grant", "code was issued to another client")); }
                if p.get("redirect_uri").map(String::as_str) != Some(c.redirect_uri.as_str()) {
                    return Err(OAuthError::new(400, "invalid_grant", "redirect_uri mismatch"));
                }
                if !pkce_ok(need(p, "code_verifier")?, &c.code_challenge) {
                    return Err(OAuthError::new(400, "invalid_grant", "PKCE verification failed"));
                }
                c.used = true;
                c.issued = vec![hash(new_access), hash(new_refresh)];
                let login = c.login.clone();
                Ok(self.issue(&client_id, &login, new_access, new_refresh, now))
            }
            "refresh_token" => {
                let h = hash(need(p, "refresh_token")?);
                let g = self.refresh.get(&h).cloned().filter(|g| g.expires > now)
                    .ok_or_else(|| OAuthError::new(400, "invalid_grant", "refresh token invalid or expired"))?;
                if let Some(cid) = p.get("client_id") {
                    if cid != &g.client_id { return Err(OAuthError::new(400, "invalid_grant", "refresh token belongs to another client")); }
                }
                self.refresh.remove(&h); // rotation: the old refresh token dies now
                Ok(self.issue(&g.client_id, &g.login, new_access, new_refresh, now))
            }
            _ => Err(OAuthError::new(400, "unsupported_grant_type", "use authorization_code or refresh_token")),
        }
    }

    /// Bearer check for /mcp. Returns the signed-in login.
    pub fn authenticate(&self, bearer: Option<&str>, now: i64) -> Option<String> {
        let t = bearer?.strip_prefix("Bearer ")?.trim();
        self.access.get(&hash(t)).filter(|g| g.expires > now).map(|g| g.login.clone())
    }
}

/// Percent-encode for query values.
pub fn enc(s: &str) -> String {
    s.bytes().map(|b| if b.is_ascii_alphanumeric() || b"-._~".contains(&b) { (b as char).to_string() } else { format!("%{b:02X}") }).collect()
}

/// Parse `a=1&b=x%20y` (form bodies and query strings).
pub fn parse_form(s: &str) -> Params {
    fn dec(v: &str) -> String {
        let b = v.as_bytes();
        let mut out = Vec::with_capacity(b.len());
        let mut i = 0;
        while i < b.len() {
            match b[i] {
                b'+' => out.push(b' '),
                b'%' if i + 2 < b.len() => {
                    match u8::from_str_radix(std::str::from_utf8(&b[i + 1..i + 3]).unwrap_or("zz"), 16) {
                        Ok(x) => { out.push(x); i += 2; }
                        Err(_) => out.push(b'%'),
                    }
                }
                c => out.push(c),
            }
            i += 1;
        }
        String::from_utf8_lossy(&out).into_owned()
    }
    s.split('&').filter(|kv| !kv.is_empty()).map(|kv| {
        let (k, v) = kv.split_once('=').unwrap_or((kv, ""));
        (dec(k), dec(v))
    }).collect()
}
