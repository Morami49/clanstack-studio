//! Browser sessions for Nodach Studio served by the hub (D-171 S1, Q21 A).
//!
//! Pure logic: no clock, no randomness, no network, so every rule is testable on every node.
//! A session is a cookie `login.expires.signature`, where the signature is HMAC-SHA256 over
//! `login.expires` with a key derived from a hub secret. Nothing is stored server-side, so a
//! restart or a new node keeps everyone signed in; rotating the secret signs everyone out.
//!
//! Sign-in itself (GitHub) is the node's job; this module only mints and checks cookies and
//! checks the login is allowed.

use sha2::{Digest, Sha256};

pub const SESSION_COOKIE: &str = "nodach_session";
pub const STATE_COOKIE: &str = "nodach_state";
/// Sign-ins started from Studio carry this prefix in the GitHub `state`, so `/callback` can tell them
/// apart from the Claude connector's sign-ins (which use bare hex).
pub const STATE_PREFIX: &str = "studio-";
pub const SESSION_TTL_MS: i64 = 30 * 24 * 60 * 60 * 1000;
pub const STATE_TTL_S: i64 = 10 * 60;
/// Header every Studio write must carry. Browsers refuse to send custom headers cross-site without a
/// CORS preflight the hub never grants, so a page on another site cannot write with your cookie.
pub const CSRF_HEADER: &str = "x-nodach-studio";

const BLOCK: usize = 64;

pub fn hmac_sha256(key: &[u8], msg: &[u8]) -> [u8; 32] {
    let mut k = [0u8; BLOCK];
    if key.len() > BLOCK {
        k[..32].copy_from_slice(&Sha256::digest(key));
    } else {
        k[..key.len()].copy_from_slice(key);
    }
    let mut inner = Sha256::new();
    inner.update(k.iter().map(|b| b ^ 0x36).collect::<Vec<u8>>());
    inner.update(msg);
    let ih = inner.finalize();
    let mut outer = Sha256::new();
    outer.update(k.iter().map(|b| b ^ 0x5c).collect::<Vec<u8>>());
    outer.update(ih);
    outer.finalize().into()
}

/// The session key: derived from a hub secret with a fixed label, so the secret itself never signs
/// anything else's format and a leaked session key reveals nothing about the secret.
pub fn session_key(secret: &str) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(b"nodach-studio-session-v1\0");
    h.update(secret.trim().as_bytes());
    h.finalize().into()
}

/// GitHub logins: letters, digits and single hyphens, at most 39 characters. Anything else is refused,
/// which also keeps `.` out of the cookie's login part.
pub fn valid_login(login: &str) -> bool {
    !login.is_empty() && login.len() <= 39 && login.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
        && !login.starts_with('-') && !login.ends_with('-')
}

pub fn allowed(login: &str, allowed_logins: &[String]) -> bool {
    allowed_logins.iter().any(|a| a.eq_ignore_ascii_case(login))
}

fn ct_eq(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

/// Cookie value for `login`, valid until `now + SESSION_TTL_MS`. None if the login is malformed.
pub fn mint(key: &[u8; 32], login: &str, now: i64) -> Option<String> {
    if !valid_login(login) {
        return None;
    }
    let payload = format!("{login}.{}", now + SESSION_TTL_MS);
    Some(format!("{payload}.{}", hex::encode(hmac_sha256(key, payload.as_bytes()))))
}

/// The signed-in login, if the cookie is genuine, unexpired and the login is still allowed.
pub fn verify(key: &[u8; 32], cookie: &str, now: i64, allowed_logins: &[String]) -> Option<String> {
    let mut parts = cookie.rsplitn(2, '.');
    let sig = parts.next()?;
    let payload = parts.next()?;
    let (login, exp) = payload.split_once('.')?;
    let exp: i64 = exp.parse().ok()?;
    let want = hex::encode(hmac_sha256(key, payload.as_bytes()));
    if !ct_eq(sig.as_bytes(), want.as_bytes()) || exp <= now || !valid_login(login) || !allowed(login, allowed_logins) {
        return None;
    }
    Some(login.to_string())
}

/// One cookie's value from a `Cookie:` header.
pub fn cookie_value(header: &str, name: &str) -> Option<String> {
    header.split(';').map(str::trim).find_map(|kv| {
        let (k, v) = kv.split_once('=')?;
        (k.trim() == name).then(|| v.trim().to_string())
    })
}

/// `Set-Cookie` for the session (or, with `None`, one that clears it).
pub fn session_set_cookie(value: Option<&str>) -> String {
    match value {
        Some(v) => format!("{SESSION_COOKIE}={v}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={}", SESSION_TTL_MS / 1000),
        None => format!("{SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0"),
    }
}

/// `Set-Cookie` for the short-lived sign-in state (or, with `None`, one that clears it).
pub fn state_set_cookie(value: Option<&str>) -> String {
    match value {
        Some(v) => format!("{STATE_COOKIE}={v}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={STATE_TTL_S}"),
        None => format!("{STATE_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0"),
    }
}

/// The GitHub callback carries a Studio sign-in only if its state has our prefix and matches the
/// state cookie set when the sign-in started (so a link from elsewhere cannot complete it).
pub fn state_matches(query_state: &str, cookie_state: Option<&str>) -> bool {
    query_state.starts_with(STATE_PREFIX) && query_state.len() > STATE_PREFIX.len() + 16
        && cookie_state.is_some_and(|c| ct_eq(c.as_bytes(), query_state.as_bytes()))
}
