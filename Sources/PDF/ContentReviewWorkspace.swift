import SwiftUI

/// A bounded workspace inside the page's outer scroll view. The inspector's
/// entire content scrolls, including its heading and actions; neither a long
/// selection nor larger text may push content above the split's clipping edge.
struct ContentReviewWorkspace<Preview: View, Inspector: View>: View {
    let availableHeight: CGFloat
    let inspectorLabel: String
    private let preview: Preview
    private let inspector: Inspector

    init(availableHeight: CGFloat, inspectorLabel: String,
         @ViewBuilder preview: () -> Preview,
         @ViewBuilder inspector: () -> Inspector) {
        self.availableHeight = availableHeight
        self.inspectorLabel = inspectorLabel
        self.preview = preview()
        self.inspector = inspector()
    }

    private var paneHeight: CGFloat { max(320, availableHeight * 0.65) }

    var body: some View {
        // Keep the split's identity while resizing, preserving the preview's
        // zoom and scroll position. Both minimum widths fit the app's minimum
        // window width, including its sidebar and page padding.
        HSplitView {
            preview.frame(minWidth: 320, maxWidth: .infinity, maxHeight: .infinity)
            inspectorPane.frame(minWidth: 300, idealWidth: 380, maxWidth: 500)
        }.frame(height: paneHeight)
    }

    private var inspectorPane: some View {
        ScrollView {
            inspector
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .padding(12)
        }
        .scrollIndicators(.visible)
        .accessibilityLabel(inspectorLabel)
    }
}

/// Actions keep their full labels and wrap into rows when the pane is narrow.
struct ContentReviewActions<Actions: View>: View {
    private let actions: Actions
    init(@ViewBuilder actions: () -> Actions) { self.actions = actions() }
    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: 10) { actions }
                .fixedSize(horizontal: true, vertical: false)
            VStack(alignment: .leading, spacing: 8) { actions }
        }
    }
}
