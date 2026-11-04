//! Exchange Kit: the event supply chain (D-071, D-075), thin slice v0.
//!
//! A deterministic model of one event chain: an organiser group briefs needs,
//! supplier groups quote, terms are agreed (credentials checked), a deposit is
//! held by a third-party provider (simulated escrow; Clanstack never holds funds,
//! D-067), suppliers engage their own crew (Q32 A), crew check in/out on the
//! run-sheet, completion is confirmed by both sides, escrow settles with one
//! seller-side cut per external sale (D-070), and the event can be reused as a
//! template. Every transition is appended to an audit log; nothing is overwritten.
//!
//! Money is integer pence. Time is a day number (0 = today). No I/O, no clock.

use std::collections::BTreeMap;

pub type Pence = i64;
pub type Id = &'static str;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Credential {
    FoodBusinessRegistration,
    SiaLicence,
    PublicLiabilityInsurance,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Role { Catering, Security, Av, Cleaning }

impl Role {
    /// UK pack v0: credentials a supplier must hold for this role.
    pub fn required(self) -> &'static [Credential] {
        match self {
            Role::Catering => &[Credential::FoodBusinessRegistration, Credential::PublicLiabilityInsurance],
            Role::Security => &[Credential::SiaLicence, Credential::PublicLiabilityInsurance],
            Role::Av | Role::Cleaning => &[Credential::PublicLiabilityInsurance],
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Error {
    MissingCredential(Id, Credential),
    WrongState(&'static str),
    NotAParty(Id),
    RightToWorkNotChecked(Id),
    NotRostered(Id),
    Frozen,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum State { Quoted, Agreed, DepositHeld, Running, Completed, Settled, Cancelled, Disputed }

#[derive(Clone, Debug)]
pub struct Booking {
    pub id: usize,
    pub organiser: Id,
    pub supplier: Id,
    pub role: Role,
    pub price: Pence,
    pub deposit: Pence,
    pub event_day: i64,
    pub terms_versions: Vec<String>,
    pub state: State,
    pub confirmed_by: Vec<Id>,
}

/// What each side is shown (D-070: the cut is visible to the seller only).
#[derive(Debug, PartialEq, Eq)]
pub struct BuyerView { pub total: Pence }
#[derive(Debug, PartialEq, Eq)]
pub struct SellerView { pub price: Pence, pub cut: Pence, pub net: Pence }

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Shift { pub person: Id, pub supplier: Id, pub hours: i64, pub rate: Pence, pub checked_out: bool }

pub struct Chain {
    pub cut_bps: i64,                         // cut in basis points (100 = 1%)
    pub late_cancel_days: i64,                // organiser cancelling closer than this forfeits the deposit
    credentials: BTreeMap<Id, Vec<Credential>>,
    right_to_work: BTreeMap<(Id, Id), bool>,  // (supplier, person) -> checked by that supplier
    pub bookings: Vec<Booking>,
    pub escrow: BTreeMap<usize, Pence>,       // held by the provider, per booking
    pub balances: BTreeMap<Id, Pence>,        // money that has reached each party
    pub platform: Pence,                      // Clanstack's cuts
    pub shifts: Vec<Shift>,
    pub log: Vec<String>,                     // append-only audit trail
}

impl Chain {
    pub fn new(cut_bps: i64, late_cancel_days: i64) -> Self {
        Self { cut_bps, late_cancel_days, credentials: BTreeMap::new(), right_to_work: BTreeMap::new(),
               bookings: vec![], escrow: BTreeMap::new(), balances: BTreeMap::new(), platform: 0,
               shifts: vec![], log: vec![] }
    }

    fn note(&mut self, s: String) { self.log.push(s); }
    fn credit(&mut self, who: Id, amount: Pence) { *self.balances.entry(who).or_insert(0) += amount; }
    pub fn cut_of(&self, amount: Pence) -> Pence { amount * self.cut_bps / 10_000 }

    pub fn add_credential(&mut self, party: Id, c: Credential) {
        self.credentials.entry(party).or_default().push(c);
        self.note(format!("credential {party} {c:?}"));
    }

    /// Supplier quotes for one need of the organiser's brief.
    pub fn quote(&mut self, organiser: Id, supplier: Id, role: Role, price: Pence, deposit_pct: i64, event_day: i64, terms: &str) -> usize {
        let id = self.bookings.len();
        self.bookings.push(Booking { id, organiser, supplier, role, price, deposit: price * deposit_pct / 100, event_day,
            terms_versions: vec![terms.to_string()], state: State::Quoted, confirmed_by: vec![] });
        self.note(format!("#{id} quote {supplier}->{organiser} {role:?} {price}p"));
        id
    }

    /// Change terms before agreement: a new version is added, the old one kept.
    pub fn revise_terms(&mut self, b: usize, terms: &str) -> Result<(), Error> {
        if self.bookings[b].state != State::Quoted { return Err(Error::WrongState("terms can only change before agreement")); }
        self.bookings[b].terms_versions.push(terms.to_string());
        self.note(format!("#{b} terms v{}", self.bookings[b].terms_versions.len()));
        Ok(())
    }

    pub fn agree(&mut self, b: usize) -> Result<(), Error> {
        let (supplier, role) = (self.bookings[b].supplier, self.bookings[b].role);
        if self.bookings[b].state != State::Quoted { return Err(Error::WrongState("not a quote")); }
        let held = self.credentials.get(supplier).cloned().unwrap_or_default();
        for c in role.required() {
            if !held.contains(c) { return Err(Error::MissingCredential(supplier, *c)); }
        }
        self.bookings[b].state = State::Agreed;
        self.note(format!("#{b} agreed on terms v{}", self.bookings[b].terms_versions.len()));
        Ok(())
    }

    /// Organiser pays the deposit to the provider's escrow (never to Clanstack).
    pub fn pay_deposit(&mut self, b: usize) -> Result<(), Error> {
        if self.bookings[b].state != State::Agreed { return Err(Error::WrongState("agree first")); }
        let d = self.bookings[b].deposit;
        *self.escrow.entry(b).or_insert(0) += d;
        self.bookings[b].state = State::DepositHeld;
        self.note(format!("#{b} deposit {d}p held by provider"));
        Ok(())
    }

    /// Supplier engages its own crew (Q32 A) and records its right-to-work check.
    pub fn engage_crew(&mut self, supplier: Id, person: Id, right_to_work_checked: bool) {
        self.right_to_work.insert((supplier, person), right_to_work_checked);
        self.note(format!("{supplier} engaged {person} (right to work checked: {right_to_work_checked})"));
    }

    pub fn roster(&mut self, supplier: Id, person: Id, hours: i64, rate: Pence) -> Result<(), Error> {
        if self.right_to_work.get(&(supplier, person)) != Some(&true) { return Err(Error::RightToWorkNotChecked(person)); }
        self.shifts.push(Shift { person, supplier, hours, rate, checked_out: false });
        self.note(format!("{person} rostered by {supplier} for {hours}h"));
        Ok(())
    }

    pub fn start(&mut self, b: usize) -> Result<(), Error> {
        if self.bookings[b].state != State::DepositHeld { return Err(Error::WrongState("deposit not held")); }
        self.bookings[b].state = State::Running;
        self.note(format!("#{b} running"));
        Ok(())
    }

    pub fn check_out(&mut self, supplier: Id, person: Id) -> Result<(), Error> {
        let s = self.shifts.iter_mut().find(|s| s.person == person && s.supplier == supplier && !s.checked_out)
            .ok_or(Error::NotRostered(person))?;
        s.checked_out = true;
        self.note(format!("{person} checked out ({supplier})"));
        Ok(())
    }

    /// Both organiser and supplier confirm the work was delivered.
    pub fn confirm(&mut self, b: usize, who: Id) -> Result<(), Error> {
        let bk = &self.bookings[b];
        if bk.state == State::Disputed { return Err(Error::Frozen); }
        if bk.state != State::Running && bk.state != State::Completed { return Err(Error::WrongState("not running")); }
        if who != bk.organiser && who != bk.supplier { return Err(Error::NotAParty(who)); }
        if !self.bookings[b].confirmed_by.contains(&who) { self.bookings[b].confirmed_by.push(who); }
        if self.bookings[b].confirmed_by.len() == 2 { self.bookings[b].state = State::Completed; }
        self.note(format!("#{b} confirmed by {who}"));
        Ok(())
    }

    /// Organiser pays the balance into escrow; the provider releases price minus one seller-side cut.
    pub fn settle(&mut self, b: usize) -> Result<(), Error> {
        if self.bookings[b].state != State::Completed { return Err(Error::WrongState("needs both confirmations")); }
        let (price, supplier) = (self.bookings[b].price, self.bookings[b].supplier);
        // The organiser pays the balance (price - deposit) into escrow at completion; the provider releases it all.
        self.escrow.remove(&b);
        let cut = self.cut_of(price);
        self.platform += cut;
        self.credit(supplier, price - cut);
        self.bookings[b].state = State::Settled;
        self.note(format!("#{b} settled: {supplier} +{}p, cut {cut}p", price - cut));
        Ok(())
    }

    /// Supplier pays its crew from its own treasury: inside the group, so no cut.
    pub fn pay_crew(&mut self, supplier: Id) -> Pence {
        let due: Vec<(Id, Pence)> = self.shifts.iter().filter(|s| s.supplier == supplier && s.checked_out)
            .map(|s| (s.person, s.hours * s.rate)).collect();
        let mut total = 0;
        for (p, amt) in due {
            self.credit(supplier, -amt);
            self.credit(p, amt);
            total += amt;
            self.note(format!("{supplier} paid {p} {amt}p (treasury, no cut)"));
        }
        self.shifts.retain(|s| !(s.supplier == supplier && s.checked_out));
        total
    }

    /// Cancellation rules: supplier cancels → full refund. Organiser cancels early → full refund;
    /// late (closer than late_cancel_days) → deposit goes to the supplier, minus the cut (it's a sale).
    pub fn cancel(&mut self, b: usize, by: Id, today: i64) -> Result<(), Error> {
        let bk = self.bookings[b].clone();
        if matches!(bk.state, State::Settled | State::Cancelled) { return Err(Error::WrongState("already closed")); }
        if bk.state == State::Disputed { return Err(Error::Frozen); }
        if by != bk.organiser && by != bk.supplier { return Err(Error::NotAParty(by)); }
        let held = self.escrow.remove(&b).unwrap_or(0);
        let late = by == bk.organiser && bk.event_day - today < self.late_cancel_days;
        if late && held > 0 {
            let cut = self.cut_of(held);
            self.platform += cut;
            self.credit(bk.supplier, held - cut);
            self.note(format!("#{b} late cancel by {by}: deposit to {} minus cut {cut}p", bk.supplier));
        } else if held > 0 {
            self.credit(bk.organiser, held);
            self.note(format!("#{b} cancelled by {by}: {held}p refunded to {}", bk.organiser));
        }
        self.bookings[b].state = State::Cancelled;
        Ok(())
    }

    /// A dispute freezes escrow until resolved by a split (in pence to the supplier).
    pub fn dispute(&mut self, b: usize, by: Id) -> Result<(), Error> {
        let bk = &self.bookings[b];
        if by != bk.organiser && by != bk.supplier { return Err(Error::NotAParty(by)); }
        if matches!(bk.state, State::Settled | State::Cancelled) { return Err(Error::WrongState("already closed")); }
        self.bookings[b].state = State::Disputed;
        self.note(format!("#{b} disputed by {by}: escrow frozen"));
        Ok(())
    }

    pub fn resolve(&mut self, b: usize, to_supplier: Pence) -> Result<(), Error> {
        if self.bookings[b].state != State::Disputed { return Err(Error::WrongState("not disputed")); }
        let bk = self.bookings[b].clone();
        let held = self.escrow.remove(&b).unwrap_or(0);
        let pay = to_supplier.clamp(0, held);
        let cut = self.cut_of(pay);
        self.platform += cut;
        self.credit(bk.supplier, pay - cut);
        self.credit(bk.organiser, held - pay);
        self.bookings[b].state = State::Settled;
        self.note(format!("#{b} resolved: {pay}p to supplier (cut {cut}p), {}p back to organiser", held - pay));
        Ok(())
    }

    pub fn buyer_view(&self, b: usize) -> BuyerView { BuyerView { total: self.bookings[b].price } }
    pub fn seller_view(&self, b: usize) -> SellerView {
        let p = self.bookings[b].price; let c = self.cut_of(p);
        SellerView { price: p, cut: c, net: p - c }
    }

    /// Reuse an event: same suppliers get first offer at last time's price and latest terms.
    pub fn rebook(&mut self, from: &[usize], new_day: i64) -> Vec<usize> {
        let old: Vec<Booking> = from.iter().map(|&b| self.bookings[b].clone()).collect();
        old.into_iter().map(|o| {
            let pct = if o.price == 0 { 0 } else { o.deposit * 100 / o.price };
            let terms = o.terms_versions.last().cloned().unwrap_or_default();
            self.quote(o.organiser, o.supplier, o.role, o.price, pct, new_day, &terms)
        }).collect()
    }
}
