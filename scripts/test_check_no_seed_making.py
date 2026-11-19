from check_no_seed_making import offending


def test_catches_the_18_nov_line():
    assert offending("  openssl rand -hex 32 | npx -y wrangler@4.158.0 secret put PRIVATE_SEED")


def test_allows_checks_and_other_secrets():
    ok = 'echo "$list" | grep -q "$n" || { echo "::error::$n is missing (openssl rand -hex 32 | wrangler secret put $n)"; exit 1; }\n'
    ok += "printf '%s' \"$v\" | npx -y wrangler secret put RESEND_API_KEY\n"
    assert offending(ok) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
