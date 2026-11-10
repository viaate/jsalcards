// The one type a screen may draw.
//
// The chain that keeps the app from saying more than the site:
//   - what a view can draw is a `ShownText`;
//   - a `ShownText` is made only in this folder (`Words/`): its initializer is not
//     public, so no code outside SnowlightCore can make one, and a script keeps the
//     rest of this package from making one;
//   - this folder is the site's words, proven against the site's own code, plus the
//     short list of words only the app has.

/// A piece of text the app may show.
public struct ShownText: Equatable, Hashable, Sendable {
    /// The characters to draw.
    ///
    /// Named so that a script can keep every use of it to the one file of the app that
    /// turns a `ShownText` into drawn text. No other view reads it, so no view can hand
    /// these characters, or any others, to a control that takes a plain string.
    public let drawnString: String

    /// Not public: only SnowlightCore can make a `ShownText`.
    init(_ characters: String) {
        drawnString = characters
    }
}

/// Every `ShownText` a model holds, in declaration order.
///
/// The words of a screen are read off its model with this, so nobody keeps that list by
/// hand and it cannot fall behind the model. It walks stored fields, optionals, arrays,
/// tuples and the payloads of enum cases. An absent optional and an empty array give
/// nothing. A plain string is not a `ShownText` and is never reported.
///
/// Screen models are values all the way down (structs and enums); a model that held a
/// reference type would not have that object's inherited fields walked.
public func shownTexts(in model: Any) -> [ShownText] {
    var found: [ShownText] = []
    collectShownTexts(in: model, into: &found)
    return found
}

private func collectShownTexts(in value: Any, into found: inout [ShownText]) {
    if let text = value as? ShownText {
        found.append(text)
        return
    }
    for child in Mirror(reflecting: value).children {
        collectShownTexts(in: child.value, into: &found)
    }
}
