//! Event supply chain scenarios (S35–S37 + what goes wrong), simulated as a
//! catered builder meetup (Q33, Claude's call): organiser = a community group,
//! supplier = a caterer, crew engaged by the caterer (Q32 A).

use exchange_core::*;

const ORG: Id = "group:builders-meetup";
const CATERER: Id = "group:caterer";
const SECURITY: Id = "group:security-co";
const AMY: Id = "person:amy";
const BEN: Id = "person:ben";

fn chain() -> Chain {
    let mut c = Chain::new(500, 14); // 5% cut, 14-day late-cancel window (placeholders until Q34/Q35)
    c.add_credential(CATERER, Credential::FoodBusinessRegistration);
    c.add_credential(CATERER, Credential::PublicLiabilityInsurance);
    c
}

#[test]
fn s35_organiser_books_caterer_happy_path() {
    let mut c = chain();
    let b = c.quote(ORG, CATERER, Role::Catering, 120_000, 30, 30, "v1: 60 covers, halal + veg");
    c.revise_terms(b, "v2: 70 covers, halal + veg, 18:00 service").unwrap();
    c.agree(b).unwrap();
    c.pay_deposit(b).unwrap();
    assert_eq!(c.escrow[&b], 36_000);
    c.start(b).unwrap();
    c.confirm(b, ORG).unwrap();
    c.confirm(b, CATERER).unwrap();
    c.settle(b).unwrap();
    assert_eq!(c.balances[CATERER], 114_000); // £1,200 minus 5%
    assert_eq!(c.platform, 6_000);
    assert_eq!(c.bookings[b].terms_versions.len(), 2); // both versions kept
}

#[test]
fn s36_crew_paid_from_supplier_treasury_without_a_cut() {
    let mut c = chain();
    let b = c.quote(ORG, CATERER, Role::Catering, 120_000, 30, 30, "v1");
    c.agree(b).unwrap(); c.pay_deposit(b).unwrap();
    c.engage_crew(CATERER, AMY, true);
    c.engage_crew(CATERER, BEN, false);
    c.roster(CATERER, AMY, 6, 1_400).unwrap();
    assert_eq!(c.roster(CATERER, BEN, 6, 1_400), Err(Error::RightToWorkNotChecked(BEN)));
    c.start(b).unwrap();
    c.check_out(CATERER, AMY).unwrap();
    c.confirm(b, ORG).unwrap(); c.confirm(b, CATERER).unwrap(); c.settle(b).unwrap();
    let before = c.platform;
    assert_eq!(c.pay_crew(CATERER), 8_400);
    assert_eq!(c.balances[AMY], 8_400);
    assert_eq!(c.platform, before); // no cut inside the group
}

#[test]
fn s37_rebook_the_same_chain() {
    let mut c = chain();
    let b = c.quote(ORG, CATERER, Role::Catering, 120_000, 30, 30, "v1");
    c.revise_terms(b, "v2 final").unwrap();
    c.agree(b).unwrap();
    let again = c.rebook(&[b], 395);
    let nb = &c.bookings[again[0]];
    assert_eq!((nb.supplier, nb.price, nb.deposit, nb.event_day), (CATERER, 120_000, 36_000, 395));
    assert_eq!(nb.terms_versions.last().unwrap(), "v2 final");
}

#[test]
fn missing_credential_blocks_agreement() {
    let mut c = chain();
    let b = c.quote(ORG, SECURITY, Role::Security, 50_000, 20, 30, "v1");
    assert_eq!(c.agree(b), Err(Error::MissingCredential(SECURITY, Credential::SiaLicence)));
    c.add_credential(SECURITY, Credential::SiaLicence);
    assert_eq!(c.agree(b), Err(Error::MissingCredential(SECURITY, Credential::PublicLiabilityInsurance)));
}

#[test]
fn supplier_cancels_organiser_refunded_in_full() {
    let mut c = chain();
    let b = c.quote(ORG, CATERER, Role::Catering, 120_000, 30, 30, "v1");
    c.agree(b).unwrap(); c.pay_deposit(b).unwrap();
    c.cancel(b, CATERER, 25).unwrap();
    assert_eq!(c.balances[ORG], 36_000);
    assert_eq!(c.platform, 0);
}

#[test]
fn organiser_cancels_late_deposit_goes_to_supplier_minus_cut() {
    let mut c = chain();
    let b = c.quote(ORG, CATERER, Role::Catering, 120_000, 30, 30, "v1");
    c.agree(b).unwrap(); c.pay_deposit(b).unwrap();
    c.cancel(b, ORG, 20).unwrap(); // 10 days before: inside the 14-day window
    assert_eq!(c.balances[CATERER], 34_200);
    assert_eq!(c.platform, 1_800);
}

#[test]
fn organiser_cancels_early_full_refund() {
    let mut c = chain();
    let b = c.quote(ORG, CATERER, Role::Catering, 120_000, 30, 30, "v1");
    c.agree(b).unwrap(); c.pay_deposit(b).unwrap();
    c.cancel(b, ORG, 1).unwrap(); // 29 days before
    assert_eq!(c.balances[ORG], 36_000);
}

#[test]
fn dispute_freezes_then_splits() {
    let mut c = chain();
    let b = c.quote(ORG, CATERER, Role::Catering, 120_000, 30, 30, "v1");
    c.agree(b).unwrap(); c.pay_deposit(b).unwrap(); c.start(b).unwrap();
    c.dispute(b, ORG).unwrap();
    assert_eq!(c.confirm(b, CATERER), Err(Error::Frozen));
    assert_eq!(c.cancel(b, ORG, 30), Err(Error::Frozen));
    c.resolve(b, 20_000).unwrap();
    assert_eq!(c.balances[CATERER], 19_000);
    assert_eq!(c.balances[ORG], 16_000);
    assert_eq!(c.platform, 1_000);
}

#[test]
fn outsiders_cannot_act_and_steps_cannot_be_skipped() {
    let mut c = chain();
    let b = c.quote(ORG, CATERER, Role::Catering, 120_000, 30, 30, "v1");
    assert!(matches!(c.pay_deposit(b), Err(Error::WrongState(_))));
    c.agree(b).unwrap();
    assert!(matches!(c.start(b), Err(Error::WrongState(_))));
    c.pay_deposit(b).unwrap(); c.start(b).unwrap();
    assert_eq!(c.confirm(b, "person:stranger"), Err(Error::NotAParty("person:stranger")));
    c.confirm(b, ORG).unwrap();
    assert!(matches!(c.settle(b), Err(Error::WrongState(_)))); // needs both sides
    assert!(matches!(c.revise_terms(b, "sneaky v2"), Err(Error::WrongState(_))));
}

#[test]
fn cut_is_visible_to_seller_only() {
    let mut c = chain();
    let b = c.quote(ORG, CATERER, Role::Catering, 120_000, 30, 30, "v1");
    assert_eq!(c.buyer_view(b), BuyerView { total: 120_000 });
    assert_eq!(c.seller_view(b), SellerView { price: 120_000, cut: 6_000, net: 114_000 });
}

#[test]
fn money_is_conserved_and_everything_is_logged() {
    let mut c = chain();
    let b = c.quote(ORG, CATERER, Role::Catering, 120_000, 30, 30, "v1");
    c.agree(b).unwrap(); c.pay_deposit(b).unwrap(); c.start(b).unwrap();
    c.confirm(b, ORG).unwrap(); c.confirm(b, CATERER).unwrap(); c.settle(b).unwrap();
    let paid_in = 120_000; // deposit + balance from the organiser
    let out: i64 = c.balances.values().sum::<i64>() + c.platform + c.escrow.values().sum::<i64>();
    assert_eq!(out, paid_in);
    assert!(c.log.len() >= 7);
}

#[test]
fn tiered_cut_by_seller_class_and_volume() {
    let mut c = Chain::with_policy(CutPolicy::Tiered { community_bps: 300, small_bps: 500, large_bps: 800, large_after: 200_000 }, 14);
    c.add_credential(CATERER, Credential::FoodBusinessRegistration);
    c.add_credential(CATERER, Credential::PublicLiabilityInsurance);
    c.set_seller_class("group:food-coop", SellerClass::Community);
    assert_eq!(c.cut_for("group:food-coop", 100_000), 3_000);
    assert_eq!(c.cut_for(CATERER, 100_000), 5_000);           // small until volume passes the threshold
    for _ in 0..2 {
        let b = c.quote(ORG, CATERER, Role::Catering, 120_000, 30, 30, "v1");
        c.agree(b).unwrap(); c.pay_deposit(b).unwrap(); c.start(b).unwrap();
        c.confirm(b, ORG).unwrap(); c.confirm(b, CATERER).unwrap(); c.settle(b).unwrap();
    }
    assert_eq!(c.volume[CATERER], 240_000);
    assert_eq!(c.cut_for(CATERER, 100_000), 8_000);           // now above £2,000 settled
    assert_eq!(c.platform, 6_000 + 6_000);                     // both sales were cut at 5% (threshold crossed after)
}

#[test]
fn suppliers_set_their_own_deposit_and_window_within_limits() {
    let mut c = chain();
    assert_eq!(c.set_supplier_terms(CATERER, 60, 14), Err(Error::OutsideLimits("deposit")));
    assert_eq!(c.set_supplier_terms(CATERER, 40, 45), Err(Error::OutsideLimits("late-cancel window")));
    c.set_supplier_terms(CATERER, 40, 21).unwrap();
    let b = c.quote(ORG, CATERER, Role::Catering, 100_000, 30, 30, "v1");
    assert_eq!((c.bookings[b].deposit, c.bookings[b].late_cancel_days), (40_000, 21));
    c.agree(b).unwrap(); c.pay_deposit(b).unwrap();
    c.cancel(b, ORG, 12).unwrap(); // 18 days before: inside this supplier's 21-day window
    assert_eq!(c.balances[CATERER], 38_000);
}

#[test]
fn treasury_split_60_30_10_with_tax_top_up() {
    let a = Allocation::default();
    assert_eq!(a.split(0, None), Buckets { growth: 0, owner: 0, tax: 0 });
    assert_eq!(a.split(100_000, None), Buckets { growth: 60_000, owner: 30_000, tax: 10_000 });
    // high-margin month: estimated tax £19,000 on £100,000 → reserve topped up from owner first
    assert_eq!(a.split(100_000, Some(19_000)), Buckets { growth: 60_000, owner: 21_000, tax: 19_000 });
    let b = a.split(99_999, None);
    assert_eq!(b.growth + b.owner + b.tax, 99_999);
}
