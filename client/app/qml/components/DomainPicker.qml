import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ComboBox {
    id: root

    property var domains: []
    property int currentId: 0
    property bool glass: uiTheme.glass
    signal picked(int id)

    model: domains
    textRole: "fqdn"
    valueRole: "id"
    Layout.fillWidth: true
    font.pixelSize: 12

    function sync() {
        if (!domains || domains.length === 0) {
            currentIndex = -1
            return
        }
        for (var i = 0; i < domains.length; ++i) {
            if (domains[i].id === currentId) {
                currentIndex = i
                return
            }
        }
        currentIndex = 0
        if (domains[0])
            picked(domains[0].id)
    }

    onDomainsChanged: sync()
    onCurrentIdChanged: sync()
    Component.onCompleted: sync()
    onActivated: picked(currentValue)

    background: Rectangle {
        implicitHeight: 36
        radius: 9
        color: root.glass ? Qt.rgba(0, 0, 0, 0.22) : "#0D151C"
        border.width: 1
        border.color: root.activeFocus ? uiTheme.accent
                      : (root.glass ? Qt.rgba(0.7, 0.93, 1, 0.18) : "#2A3943")
    }

    contentItem: Text {
        leftPadding: 10
        text: root.displayText
        color: uiTheme.text
        font: root.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Text {
        x: root.width - width - 8
        y: root.topPadding + (root.availableHeight - height) / 2
        text: "⌄"
        color: uiTheme.muted
        font.pixelSize: 14
    }

    popup: Popup {
        y: root.height + 4
        width: root.width
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 260)
        padding: 4
        background: Rectangle {
            radius: 10
            color: "#0E1A22"
            border.width: 1
            border.color: Qt.rgba(0.7, 0.93, 1, 0.2)
        }
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
    }

    delegate: ItemDelegate {
        width: root.width - 8
        height: 32
        contentItem: Text {
            text: model[root.textRole]
            color: uiTheme.text
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        highlighted: root.highlightedIndex === index
        background: Rectangle {
            radius: 7
            color: parent.highlighted ? Qt.rgba(0.4, 0.9, 0.8, 0.14) : "transparent"
        }
    }
}
