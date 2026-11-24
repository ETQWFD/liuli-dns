import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root

    property alias text: field.text
    property alias echoMode: field.echoMode
    property alias inputMethodHints: field.inputMethodHints
    property string label: ""
    property string placeholder: ""
    property bool glass: uiTheme.glass
    property int maxLength: 32767
    property bool readOnly: false

    spacing: 6

    Text {
        text: root.label
        visible: root.label !== ""
        color: uiTheme.muted
        font.pixelSize: 11
        font.letterSpacing: 0.3
    }

    TextField {
        id: field
        Layout.fillWidth: true
        placeholderText: root.placeholder
        color: uiTheme.text
        placeholderTextColor: Qt.rgba(0.56, 0.70, 0.76, 0.65)
        font.pixelSize: 13
        selectByMouse: true
        readOnly: root.readOnly
        maximumLength: root.maxLength
        leftPadding: 12
        rightPadding: 12
        topPadding: 9
        bottomPadding: 9

        background: Rectangle {
            radius: 10
            color: root.glass ? Qt.rgba(0, 0, 0, 0.22) : "#0D151C"
            border.width: 1
            border.color: field.activeFocus ? uiTheme.accent
                          : (root.glass ? Qt.rgba(0.70, 0.93, 1, 0.17) : "#2A3943")
            Behavior on border.color { ColorAnimation { duration: 180 } }
        }
    }
}
