import QtQuick
import QtQuick.Controls

ComboBox {
    id: root
    property bool glass: uiTheme.glass
    implicitHeight: 30
    font.pixelSize: 11

    background: Rectangle {
        radius: 7
        color: root.glass ? Qt.rgba(0, 0, 0, 0.2) : "#0D151C"
        border.width: 1
        border.color: root.activeFocus ? uiTheme.accent
                      : (root.glass ? Qt.rgba(0.7, 0.93, 1, 0.13) : "#2A3943")
    }

    contentItem: Text {
        leftPadding: 8
        text: root.displayText
        color: uiTheme.text
        font: root.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Text {
        x: root.width - width - 6
        y: root.topPadding + (root.availableHeight - height) / 2
        text: "⌄"
        color: uiTheme.muted
        font.pixelSize: 11
    }

    popup: Popup {
        y: root.height + 2
        width: root.width
        implicitHeight: Math.min(contentItem.implicitHeight + 6, 220)
        padding: 3
        background: Rectangle {
            radius: 8
            color: "#0E1A22"
            border.width: 1
            border.color: Qt.rgba(0.7, 0.93, 1, 0.2)
        }
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
        }
    }

    delegate: ItemDelegate {
        width: root.width - 6
        height: 26
        contentItem: Text {
            text: root.textRole !== "" ? model[root.textRole] : modelData
            color: uiTheme.text
            font.pixelSize: 11
            verticalAlignment: Text.AlignVCenter
        }
        highlighted: root.highlightedIndex === index
        background: Rectangle {
            radius: 5
            color: parent.highlighted ? Qt.rgba(0.4, 0.9, 0.8, 0.14) : "transparent"
        }
    }
}
