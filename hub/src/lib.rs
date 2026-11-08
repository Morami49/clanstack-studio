//! Clanstack hub on Cloudflare (H1, D-089). All rules come from hub-core / the engine (D-094);
//! this file only moves bytes between HTTP, the Durable Object's SQLite storage and hub-core.
//!
//! GET  /health                 → "ok"
//! GET  /status  (Bearer token) → counts + whether the whole chain verifies
//! GET  /pull    (Bearer token) → ?after=N&limit=M: events in this node's arrival order, from cursor N
//! Reads need a token too (F-23): the record is not public. HUB_READ_TOKEN reads; HUB_WRITE_TOKEN reads and writes.
//! POST /push    (Bearer token) → JSON array of signed engine events
//! POST /import  (Bearer token) → JSON array of {doc_id, event} from Studio Web
//! GET  /studio-export (Bearer token) → ?after=N&limit=M: {docs:[{doc_id,event}], next}: writes made on other nodes,
//!                       shaped as Studio Web events (Q44 "C now", D-101). /import skips them, so nothing loops.
//!
//! Claude connector (D-104, D-128): the hub is its own OAuth 2.1 server and MCP server; GitHub is the sign-in.
//! GET  /.well-known/oauth-protected-resource[/mcp]  RFC 9728 metadata
//! GET  /.well-known/oauth-authorization-server      RFC 8414 metadata
//! POST /register   RFC 7591 dynamic client registration (public clients)
//! GET  /authorize  checks Claude's request, then sends the person to GitHub
//! GET  /callback   GitHub returns here; allowed logins get a code and go back to Claude
//! POST /token      code + PKCE → tokens; refresh tokens rotate
//! POST /mcp        MCP JSON-RPC (Bearer token from /token); 401 + WWW-Authenticate starts sign-in

use foundation_core::event::{Event, KeyPair};
use hub_core::oauth::{self, Config, OAuthState};
use hub_core::{mcp, Hub};
use serde::Deserialize;
use std::cell::RefCell;
use worker::*;

#[event(fetch)]
async fn fetch(req: Request, env: Env, _ctx: Context) -> Result<Response> {
    if req.path() == "/health" {
        return Response::ok("ok");
    }
    // One record for now; later one Durable Object per space.
    let ns = env.durable_object("RECORD")?;
    let stub = ns.id_from_name("main")?.get_stub()?;
    stub.fetch_with_request(req).await
}

#[derive(Deserialize)]
struct Doc {
    doc_id: String,
    event: serde_json::Value,
}

#[durable_object]
pub struct Record {
    state: State,
    env: Env,
    hub: RefCell<Option<Hub>>,
    oauth: RefCell<Option<OAuthState>>,
}

fn random_hex(n: usize) -> Result<String> {
    let mut b = vec![0u8; n];
    getrandom::getrandom(&mut b).map_err(|e| Error::RustError(e.to_string()))?;
    Ok(hex::encode(b))
}

fn json_status(v: &serde_json::Value, status: u16) -> Result<Response> {
    let h = Headers::new();
    h.set("content-type", "application/json")?;
    h.set("cache-control", "no-store")?;
    Ok(Response::ok(v.to_string())?.with_status(status).with_headers(h))
}

fn page(title: &str, msg: &str, status: u16) -> Result<Response> {
    let esc = |t: &str| t.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;");
    Ok(Response::from_html(format!(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>{t}</title>\
         <body style='font:16px system-ui;max-width:36rem;margin:3rem auto;padding:0 1rem'><h1>{t}</h1><p>{m}</p>",
        t = esc(title), m = esc(msg)))?.with_status(status))
}

impl Record {
    fn sql(&self) -> SqlStorage {
        self.state.storage().sql()
    }

    fn load(&self) -> Result<()> {
        if self.hub.borrow().is_some() {
            return Ok(());
        }
        let sql = self.sql();
        sql.exec("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, json TEXT NOT NULL)", None)?;
        #[derive(Deserialize)]
        struct Row { json: String }
        let rows: Vec<Row> = sql.exec("SELECT json FROM events ORDER BY seq", None)?.to_array()?;
        let evs: Vec<Event> = rows.into_iter().filter_map(|r| serde_json::from_str(&r.json).ok()).collect();
        let (hub, r) = Hub::restore(evs);
        if !r.refused.is_empty() {
            console_error!("restore refused {} events", r.refused.len());
        }
        *self.hub.borrow_mut() = Some(hub);
        Ok(())
    }

    fn persist(&self, evs: &[Event]) -> Result<()> {
        let sql = self.sql();
        for e in evs {
            let json = serde_json::to_string(e).map_err(|e| Error::RustError(e.to_string()))?;
            sql.exec("INSERT OR IGNORE INTO events (id, json) VALUES (?, ?)", vec![e.id.clone().into(), json.into()])?;
        }
        Ok(())
    }

    fn has_token(&self, req: &Request, name: &str) -> bool {
        let want = match self.env.secret(name) { Ok(s) => s.to_string(), Err(_) => return false };
        let got = req.headers().get("authorization").ok().flatten().unwrap_or_default();
        !want.is_empty() && got == format!("Bearer {want}")
    }
    fn authorised(&self, req: &Request) -> bool {
        self.has_token(req, "HUB_WRITE_TOKEN")
    }
    fn can_read(&self, req: &Request) -> bool {
        self.authorised(req) || self.has_token(req, "HUB_READ_TOKEN")
    }

    fn cfg(&self, url: &Url) -> Config {
        let issuer = url.origin().ascii_serialization();
        let allowed = self.env.var("ALLOWED_GITHUB_LOGINS").map(|v| v.to_string()).unwrap_or_default();
        Config { issuer, allowed_logins: allowed.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect() }
    }

    fn load_oauth(&self) -> Result<()> {
        if self.oauth.borrow().is_some() { return Ok(()); }
        let sql = self.sql();
        sql.exec("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)", None)?;
        #[derive(Deserialize)]
        struct Row { v: String }
        let rows: Vec<Row> = sql.exec("SELECT v FROM kv WHERE k = 'oauth'", None)?.to_array()?;
        let st = rows.first().and_then(|r| serde_json::from_str(&r.v).ok()).unwrap_or_default();
        *self.oauth.borrow_mut() = Some(st);
        Ok(())
    }

    fn save_oauth(&self) -> Result<()> {
        let now = Date::now().as_millis() as i64;
        let v = { let mut b = self.oauth.borrow_mut(); let st = b.as_mut().unwrap(); st.purge(now); serde_json::to_string(&*st).map_err(|e| Error::RustError(e.to_string()))? };
        self.sql().exec("INSERT INTO kv (k, v) VALUES ('oauth', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", vec![v.into()])?;
        Ok(())
    }

    fn secret_opt(&self, name: &str) -> Option<String> {
        self.env.secret(name).ok().map(|s| s.to_string()).filter(|s| !s.is_empty())
    }

    async fn github_login(&self, code: &str, redirect_uri: &str) -> Result<String> {
        let (id, secret) = match (self.secret_opt("GH_OAUTH_CLIENT_ID"), self.secret_opt("GH_OAUTH_CLIENT_SECRET")) {
            (Some(i), Some(s)) => (i, s),
            _ => return Err(Error::RustError("GitHub sign-in is not set up yet".into())),
        };
        let h = Headers::new();
        h.set("accept", "application/json")?;
        h.set("content-type", "application/x-www-form-urlencoded")?;
        h.set("user-agent", "clanstack-hub")?;
        let body = format!("client_id={}&client_secret={}&code={}&redirect_uri={}", oauth::enc(&id), oauth::enc(&secret), oauth::enc(code), oauth::enc(redirect_uri));
        let mut init = RequestInit::new();
        init.with_method(Method::Post).with_headers(h).with_body(Some(worker::wasm_bindgen::JsValue::from_str(&body)));
        let mut r = Fetch::Request(Request::new_with_init("https://github.com/login/oauth/access_token", &init)?).send().await?;
        let tok: serde_json::Value = r.json().await?;
        let at = tok.get("access_token").and_then(|v| v.as_str()).ok_or_else(|| Error::RustError("GitHub refused the sign-in".into()))?.to_string();
        let h = Headers::new();
        h.set("authorization", &format!("Bearer {at}"))?;
        h.set("accept", "application/vnd.github+json")?;
        h.set("user-agent", "clanstack-hub")?;
        let mut init = RequestInit::new();
        init.with_method(Method::Get).with_headers(h);
        let mut r = Fetch::Request(Request::new_with_init("https://api.github.com/user", &init)?).send().await?;
        let user: serde_json::Value = r.json().await?;
        user.get("login").and_then(|v| v.as_str()).map(String::from).ok_or_else(|| Error::RustError("GitHub returned no login".into()))
    }

    fn connector_key(&self) -> Result<KeyPair> {
        let seed_hex = self.env.secret("CONNECTOR_SEED")?.to_string();
        let seed: [u8; 32] = hex::decode(seed_hex.trim()).ok().and_then(|v| v.try_into().ok())
            .ok_or_else(|| Error::RustError("CONNECTOR_SEED must be 64 hex chars".into()))?;
        Ok(KeyPair::from_seed(seed))
    }

    /// Connector routes; None = not a connector route.
    async fn connector(&self, req: &mut Request, url: &Url) -> Result<Option<Response>> {
        let cfg = self.cfg(url);
        let now = Date::now().as_millis() as i64;
        let path = req.path();
        let resp = match (req.method(), path.as_str()) {
            (Method::Get, "/.well-known/oauth-protected-resource" | "/.well-known/oauth-protected-resource/mcp") => json_status(&cfg.protected_resource_metadata(), 200)?,
            (Method::Get, "/.well-known/oauth-authorization-server" | "/.well-known/oauth-authorization-server/mcp") => json_status(&cfg.authorization_server_metadata(), 200)?,
            (Method::Post, "/register") => {
                self.load_oauth()?;
                let body: serde_json::Value = req.json().await.unwrap_or(serde_json::Value::Null);
                let r = self.oauth.borrow_mut().as_mut().unwrap().register(&body, random_hex(16)?, now);
                match r { Ok(v) => { self.save_oauth()?; json_status(&v, 201)? } Err(e) => json_status(&e.body(), e.status)? }
            }
            (Method::Get, "/authorize") => {
                self.load_oauth()?;
                let Some(gh_id) = self.secret_opt("GH_OAUTH_CLIENT_ID") else {
                    return Ok(Some(page("Not set up yet", "The hub's GitHub sign-in isn't configured yet (D-128).", 503)?));
                };
                let params = oauth::parse_form(url.query().unwrap_or(""));
                let upstream = random_hex(16)?;
                let r = self.oauth.borrow_mut().as_mut().unwrap().authorize(&cfg, &params, upstream.clone(), now);
                match r {
                    Ok(()) => {
                        self.save_oauth()?;
                        let to = format!("https://github.com/login/oauth/authorize?client_id={}&redirect_uri={}&state={}&scope=read:user&allow_signup=false",
                            oauth::enc(&gh_id), oauth::enc(&format!("{}/callback", cfg.issuer)), upstream);
                        Response::redirect(Url::parse(&to)?)?
                    }
                    Err(e) => page("Can't start sign-in", &e.description, e.status)?,
                }
            }
            (Method::Get, "/callback") => {
                self.load_oauth()?;
                let q = oauth::parse_form(url.query().unwrap_or(""));
                let (Some(code), Some(state)) = (q.get("code"), q.get("state")) else {
                    return Ok(Some(page("Sign-in cancelled", "GitHub didn't return a sign-in code. Start again from Claude.", 400)?));
                };
                let login = match self.github_login(code, &format!("{}/callback", cfg.issuer)).await {
                    Ok(l) => l,
                    Err(e) => return Ok(Some(page("Sign-in failed", &e.to_string(), 502)?)),
                };
                let our_code = random_hex(32)?;
                let r = self.oauth.borrow_mut().as_mut().unwrap().complete(&cfg, state, &login, &our_code, now);
                self.save_oauth()?;
                match r {
                    Ok(to) => Response::redirect(Url::parse(&to)?)?,
                    Err(e) => page("Not allowed", &e.description, e.status)?,
                }
            }
            (Method::Post, "/token") => {
                self.load_oauth()?;
                let params = oauth::parse_form(&req.text().await.unwrap_or_default());
                let r = self.oauth.borrow_mut().as_mut().unwrap().token(&params, &random_hex(32)?, &random_hex(32)?, now);
                self.save_oauth()?;
                match r { Ok(v) => json_status(&v, 200)?, Err(e) => json_status(&e.body(), e.status)? }
            }
            (Method::Post, "/mcp") => {
                self.load_oauth()?;
                let bearer = req.headers().get("authorization").ok().flatten();
                let mut login = self.oauth.borrow().as_ref().unwrap().authenticate(bearer.as_deref(), now);
                // F-46 follow-up: the deploy's smoke test drives /mcp with HUB_WRITE_TOKEN (already full-access via /push)
                if login.is_none() && self.authorised(req) { login = Some("service:deploy-check".into()); }
                let Some(login) = login else {
                    let h = Headers::new();
                    h.set("www-authenticate", &cfg.www_authenticate())?;
                    h.set("content-type", "application/json")?;
                    return Ok(Some(Response::ok(r#"{"error":"invalid_token"}"#)?.with_status(401).with_headers(h)));
                };
                let msg: serde_json::Value = match req.json().await {
                    Ok(v) => v,
                    Err(_) => return Ok(Some(json_status(&serde_json::json!({"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"parse error"}}), 400)?)),
                };
                let key = self.connector_key()?;
                let before = self.hub.borrow().as_ref().unwrap().status().events;
                let replies: Vec<serde_json::Value> = {
                    let mut b = self.hub.borrow_mut();
                    let hub = b.as_mut().unwrap();
                    match &msg {
                        serde_json::Value::Array(batch) => batch.iter().filter_map(|m| mcp::handle(hub, &login, &key, m, now)).collect(),
                        m => mcp::handle(hub, &login, &key, m, now).into_iter().collect(),
                    }
                };
                let added = self.hub.borrow().as_ref().unwrap().pull(before, usize::MAX).events;
                self.persist(&added)?;
                match (&msg, replies.len()) {
                    (_, 0) => Response::empty()?.with_status(202),
                    (serde_json::Value::Array(_), _) => json_status(&serde_json::Value::Array(replies), 200)?,
                    _ => json_status(&replies[0], 200)?,
                }
            }
            (_, "/mcp") => {
                let h = Headers::new();
                h.set("allow", "POST")?;
                Response::error("use POST", 405)?.with_headers(h)
            }
            _ => return Ok(None),
        };
        Ok(Some(resp))
    }
}

impl DurableObject for Record {
    fn new(state: State, env: Env) -> Self {
        Self { state, env, hub: RefCell::new(None), oauth: RefCell::new(None) }
    }

    async fn fetch(&self, mut req: Request) -> Result<Response> {
        self.load()?;
        let url = req.url()?;
        if let Some(r) = self.connector(&mut req, &url).await? {
            return Ok(r);
        }
        let q = |k: &str| url.query_pairs().find(|(a, _)| a == k).and_then(|(_, v)| v.parse::<usize>().ok());
        match (req.method(), req.path().as_str()) {
            (Method::Get, "/status" | "/pull" | "/studio-export") if !self.can_read(&req) => Response::error("unauthorised", 401),
            (Method::Get, "/status") => Response::from_json(&self.hub.borrow().as_ref().unwrap().status()),
            (Method::Get, "/pull") => {
                let page = self.hub.borrow().as_ref().unwrap().pull(q("after").unwrap_or(0), q("limit").unwrap_or(500).min(2000));
                Response::from_json(&page)
            }
            (Method::Get, "/studio-export") => {
                let (docs, next) = self.hub.borrow().as_ref().unwrap().to_studio(q("after").unwrap_or(0), q("limit").unwrap_or(500).min(2000));
                let docs: Vec<serde_json::Value> = docs.into_iter().map(|(d, e)| serde_json::json!({"doc_id": d, "event": e})).collect();
                Response::from_json(&serde_json::json!({"docs": docs, "next": next}))
            }
            (Method::Post, "/push") => {
                if !self.authorised(&req) { return Response::error("unauthorised", 401); }
                let evs: Vec<Event> = req.json().await?;
                let r = self.hub.borrow_mut().as_mut().unwrap().push(evs);
                let added: Vec<Event> = { let b = self.hub.borrow(); let h = b.as_ref().unwrap(); r.added.iter().filter_map(|id| h.get(id).cloned()).collect() };
                self.persist(&added)?;
                Response::from_json(&r)
            }
            (Method::Post, "/import") => {
                if !self.authorised(&req) { return Response::error("unauthorised", 401); }
                let seed_hex = self.env.secret("IMPORTER_SEED")?.to_string();
                let seed: [u8; 32] = hex::decode(seed_hex.trim()).ok().and_then(|v| v.try_into().ok())
                    .ok_or_else(|| Error::RustError("IMPORTER_SEED must be 64 hex chars".into()))?;
                let docs: Vec<Doc> = req.json().await?;
                let now = Date::now().as_millis() as i64;
                let made = self.hub.borrow_mut().as_mut().unwrap()
                    .import(&KeyPair::from_seed(seed), docs.into_iter().map(|d| (d.doc_id, d.event)).collect(), now)
                    .map_err(|e| Error::RustError(e.to_string()))?;
                self.persist(&made)?;
                Response::from_json(&serde_json::json!({ "imported": made.len() }))
            }
            _ => Response::error("not found", 404),
        }
    }
}
