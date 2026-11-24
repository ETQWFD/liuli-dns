import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

ColumnLayout {
    id: root
    property string label: ""
    property string path: ""
    property string filter: "PEM (*.pem *.crt *.cer *.key)"
    signal picked(string url)
    spacing: 6

    Text {
        text: root.label
        visible: root.label !== ""
        color: uiTheme.muted
        font.pixelSize: 11
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8

        Rectangle {
            Layout.fillWidth: true
            height: 36
            radius: 9
            color: uiTheme.glass ? Qt.rgba(0, 0, 0, 0.2) : "#0D151C"
            border.width: 1
            border.color: uiTheme.glass ? Qt.rgba(0.7, 0.93, 1, 0.16) : "#2A3943"

            Text {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                verticalAlignment: Text.AlignVCenter
                text: root.path ? decodeURIComponent(root.path.split("/").pop()) : "—"
                color: root.path ? uiTheme.text : Qt.rgba(0.56, 0.7, 0.76, 0.6)
                font.pixelSize: 12
                elide: Text.ElideMiddle
            }
        }

        AnimatedButton {
            text: "…"
            small: true
            onClicked: dlg.open()
        }
    }

    FileDialog {
        id: dlg
        title: root.label
        nameFilters: [root.filter]
        onAccepted: {
            root.path = selectedFile.toString()
            root.picked(root.path)
        }
    }
}
