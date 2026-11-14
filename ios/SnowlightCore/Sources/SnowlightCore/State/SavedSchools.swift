import Foundation

// The schools the app keeps: their ids only, at most five, each once, the first the home
// school. Nothing else of a school is kept: its name, place and status always come from the
// files.

/// The saved schools, in order; the first is the home school.
struct SavedSchools: Equatable {
    /// The most schools that can be saved.
    static let most = 5

    /// The saved ids, in order: each a school id, each once, at most `most`.
    private(set) var ids: [String]

    /// No school saved.
    init() {
        ids = []
    }

    /// The schools of a kept list, in its order: anything that is not a school id, a second
    /// copy of one, and any past the fifth are left out.
    init(kept: [String]) {
        var found: [String] = []
        for id in kept where isSchoolId(id) && !found.contains(id) && found.count < SavedSchools.most {
            found.append(id)
        }
        ids = found
    }

    /// The home school, or nil with none saved.
    var home: String? {
        return ids.first
    }

    /// Whether a school is saved.
    func holds(_ id: String) -> Bool {
        return ids.contains(id)
    }

    /// Saves a school at the end of the list. False, with nothing changed, for a text that
    /// is not a school id, a school already saved, or a full list.
    @discardableResult
    mutating func add(_ id: String) -> Bool {
        guard isSchoolId(id), !ids.contains(id), ids.count < SavedSchools.most else {
            return false
        }
        ids.append(id)
        return true
    }

    /// Forgets a school. False, with nothing changed, for one not saved. Forgetting the home
    /// school makes the next one home.
    @discardableResult
    mutating func remove(_ id: String) -> Bool {
        guard let at = ids.firstIndex(of: id) else {
            return false
        }
        ids.remove(at: at)
        return true
    }

    /// Moves a saved school to a place in the list (0 is home), the others keeping their
    /// order. False, with nothing changed, for one not saved or a place outside the list.
    @discardableResult
    mutating func move(_ id: String, to place: Int) -> Bool {
        guard let at = ids.firstIndex(of: id), place >= 0, place < ids.count else {
            return false
        }
        ids.remove(at: at)
        ids.insert(id, at: place)
        return true
    }

    /// Makes a saved school the home school.
    @discardableResult
    mutating func makeHome(_ id: String) -> Bool {
        return move(id, to: 0)
    }
}
