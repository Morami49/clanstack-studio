//! Whole-word matching, exactly as gate_core `_rx` / `_hit`:
//! `re.compile(r"(?<![a-z0-9])(w1|w2|...)(?![a-z0-9])", re.I)` with every word `re.escape(w.lower())`.
//!
//! Python's `search` tries each start position from the left, and at each position the words in list order;
//! the first word whose text matches and is not followed by a word character wins (not the longest). The hit
//! is the text as it appears in the input (its own case), so reasons quote the title or element name.
//! `_`, `-`, `.` and spaces are boundaries; letters and digits are not.

use crate::py;

#[derive(Debug, Clone)]
pub struct WordSet {
    words: Vec<Vec<char>>,
}

impl WordSet {
    /// `_rx(words)`: None when no non-empty word is given.
    pub fn new<S: AsRef<str>>(words: &[S]) -> Option<WordSet> {
        let words: Vec<Vec<char>> = words
            .iter()
            .map(|w| w.as_ref())
            .filter(|w| !w.is_empty())
            .map(|w| py::lower(w).chars().map(py::simple_lower).collect())
            .collect();
        if words.is_empty() {
            None
        } else {
            Some(WordSet { words })
        }
    }

    /// `rx.search(text)` -> `m.group(1)`.
    pub fn search(&self, text: &str) -> Option<String> {
        let chars: Vec<char> = text.chars().collect();
        for start in 0..=chars.len() {
            if start > 0 && py::is_word_class(chars[start - 1]) {
                continue;
            }
            for w in &self.words {
                let end = start + w.len();
                if end > chars.len() {
                    continue;
                }
                if !chars[start..end].iter().zip(w.iter()).all(|(t, p)| py::ci_eq(*t, *p)) {
                    continue;
                }
                if end < chars.len() && py::is_word_class(chars[end]) {
                    continue;
                }
                return Some(chars[start..end].iter().collect());
            }
        }
        None
    }
}

/// `_hit(words, *texts)`: the first matching word in the first non-empty text that has one.
pub fn hit<S: AsRef<str>>(words: &[S], texts: &[&str]) -> Option<String> {
    let rx = WordSet::new(words)?;
    texts.iter().filter(|t| !t.is_empty()).find_map(|t| rx.search(t))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn boundaries() {
        assert_eq!(hit(&["send"], &["Sender name"]), None);
        assert_eq!(hit(&["send"], &["SEND_now"]), Some("SEND".into()));
        assert_eq!(hit(&["password", "passwords"], &["my passwords.txt"]), Some("passwords".into()));
        assert_eq!(hit(&[".env"], &["x.env"]), None, "a letter before the dot blocks the match, as in Python");
        assert_eq!(hit(&[".env"], &["prod .env"]), Some(".env".into()));
        assert_eq!(hit(&["2fa"], &["12fa"]), None);
        assert_eq!(hit(&["kek"], &["\u{212a}ek"]), Some("\u{212a}ek".into()));
    }
}
