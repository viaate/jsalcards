// The app's rules version (PLAN section 5, lock 5): a whole number raised by one whenever a
// golden answer changes, so a copy on a phone can tell, from the floor file the data host
// will publish (server piece S8, M8), whether its words and rules may still show statuses
// and chances.
//
// ios/tools/gen-golden.mjs writes the number and the sha256 over every golden family's cases
// into Tests/SnowlightCoreTests/Fixtures/rules-version.json; `--check` fails when the sha256
// differs. A commit that changes the sha256 raises the number there and here together, and
// RulesVersionTests holds the two equal.
//
// Not public: nothing outside SnowlightCore reads it in M1.

enum RulesVersion {
    /// The rules version of the golden families this build is held to.
    static let number = 1
}
