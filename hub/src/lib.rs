//! Clanstack hub on Cloudflare (H1, D-089). All rules come from hub-core / the engine (D-094);
//! this file only moves bytes between HTTP, the Durable Object's SQLite storage and hub-core.
//!
//! GET  /health                 → "ok"
//! GET  /status  (Bearer token) → counts + whether the whole chain verifies
//! GET  /pull    (Bearer token) → ?after=N&limit=M: events in this node's arrival order, from cursor N
//! Reads need a token too (F-23): the record is not public. HUB_READ_TOKEN reads; HUB_WRITE_TOKEN reads and writes.
//! POST /push    (Bearer token) → JSON array of signed engine events
//! POST /import  (Bearer token) → JSON array of {doc_id, event} from Studio Web (D-095 stage A)

use foundation_core::event::{Event, KeyPair};
use hub_core::Hub;
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
}

impl DurableObject for Record {
    fn new(state: State, env: Env) -> Self {
        Self { state, env, hub: RefCell::new(None) }
    }

    async fn fetch(&self, mut req: Request) -> Result<Response> {
        self.load()?;
        let url = req.url()?;
        let q = |k: &str| url.query_pairs().find(|(a, _)| a == k).and_then(|(_, v)| v.parse::<usize>().ok());
        match (req.method(), req.path().as_str()) {
            (Method::Get, "/status" | "/pull") if !self.can_read(&req) => Response::error("unauthorised", 401),
            (Method::Get, "/status") => Response::from_json(&self.hub.borrow().as_ref().unwrap().status()),
            (Method::Get, "/pull") => {
                let page = self.hub.borrow().as_ref().unwrap().pull(q("after").unwrap_or(0), q("limit").unwrap_or(500).min(2000));
                Response::from_json(&page)
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
