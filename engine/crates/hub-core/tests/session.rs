//! Studio served by the hub (D-171 S1): browser sessions must be unforgeable, expire, follow the
//! allow-list, and never mix with the Claude connector's sign-ins.

use hub_core::session::*;

fn owners() -> Vec<String> { vec!["Morami49".to_string()] }
const NOW: i64 = 1_762_880_000_000;

#[test]
fn hmac_matches_rfc_4231_case_2() {
    let mac = hmac_sha256(b"Jefe", b"what do ya want for nothing?");
    assert_eq!(hex::encode(mac), "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843");
}

#[test]
fn hmac_long_key_is_hashed_first() {
    // RFC 4231 case 6: 131-byte key
    let key = [0xaau8; 131];
    let mac = hmac_sha256(&key, b"Test Using Larger Than Block-Size Key - Hash Key First");
    assert_eq!(hex::encode(mac), "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54");
}

#[test]
fn a_minted_session_verifies_for_its_owner() {
    let k = session_key("secret-a");
    let c = mint(&k, "Morami49", NOW).unwrap();
    assert_eq!(verify(&k, &c, NOW + 1000, &owners()).as_deref(), Some("Morami49"));
    // GitHub logins are case-insensitive on the allow-list
    assert_eq!(verify(&k, &c, NOW, &["morami49".to_string()]).as_deref(), Some("Morami49"));
}

#[test]
fn sessions_expire() {
    let k = session_key("secret-a");
    let c = mint(&k, "Morami49", NOW).unwrap();
    assert!(verify(&k, &c, NOW + SESSION_TTL_MS - 1, &owners()).is_some());
    assert!(verify(&k, &c, NOW + SESSION_TTL_MS, &owners()).is_none());
}

#[test]
fn tampering_or_another_key_fails() {
    let k = session_key("secret-a");
    let c = mint(&k, "Morami49", NOW).unwrap();
    // someone else's login with the owner's signature
    let forged = c.replacen("Morami49", "attacker", 1);
    assert!(verify(&k, &forged, NOW, &["attacker".to_string()]).is_none());
    // pushing the expiry out
    let (payload, sig) = c.rsplit_once('.').unwrap();
    let (login, _) = payload.split_once('.').unwrap();
    assert!(verify(&k, &format!("{login}.99999999999999.{sig}"), NOW, &owners()).is_none());
    // a rotated secret signs everyone out
    assert!(verify(&session_key("secret-b"), &c, NOW, &owners()).is_none());
    // junk
    for j in ["", ".", "a.b", "Morami49..", "Morami49.123.", "Morami49.x.deadbeef"] {
        assert!(verify(&k, j, NOW, &owners()).is_none(), "{j}");
    }
}

#[test]
fn removing_a_login_from_the_allow_list_signs_it_out() {
    let k = session_key("secret-a");
    let c = mint(&k, "Morami49", NOW).unwrap();
    assert!(verify(&k, &c, NOW, &[]).is_none());
    assert!(verify(&k, &c, NOW, &["someone-else".to_string()]).is_none());
}

#[test]
fn malformed_logins_get_no_session() {
    let k = session_key("secret-a");
    for bad in ["", "a.b", "-lead", "trail-", "has space", &"x".repeat(40)] {
        assert!(mint(&k, bad, NOW).is_none(), "{bad}");
    }
    assert!(valid_login("a-b-c9"));
}

#[test]
fn cookie_header_parsing() {
    let h = "theme=dark; nodach_session=abc.123.ff ; nodach_state=studio-xyz";
    assert_eq!(cookie_value(h, SESSION_COOKIE).as_deref(), Some("abc.123.ff"));
    assert_eq!(cookie_value(h, STATE_COOKIE).as_deref(), Some("studio-xyz"));
    assert_eq!(cookie_value(h, "missing"), None);
    assert_eq!(cookie_value("", SESSION_COOKIE), None);
}

#[test]
fn set_cookie_headers_are_locked_down() {
    for c in [session_set_cookie(Some("v")), session_set_cookie(None), state_set_cookie(Some("v")), state_set_cookie(None)] {
        assert!(c.contains("HttpOnly") && c.contains("Secure") && c.contains("SameSite=Lax") && c.contains("Path=/"), "{c}");
    }
    assert!(session_set_cookie(None).contains("Max-Age=0"));
}

#[test]
fn studio_sign_in_state_must_match_its_cookie() {
    let s = format!("{STATE_PREFIX}{}", "ab".repeat(16));
    assert!(state_matches(&s, Some(&s)));
    assert!(!state_matches(&s, None));
    assert!(!state_matches(&s, Some("studio-other")));
    // the connector's bare-hex states never count as Studio sign-ins
    let bare = "ab".repeat(16);
    assert!(!state_matches(&bare, Some(&bare)));
    // a prefix with nothing random after it is refused
    assert!(!state_matches(STATE_PREFIX, Some(STATE_PREFIX)));
}
