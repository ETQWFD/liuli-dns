import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dlg

    property string reportPath: ""
    property string reportText: ""
    property var tr: ({})

    modal: true
    width: 720
    height: 560
    padding: 24
    closePolicy: Popup.CloseOnEscape

    function showReport(path, text) {
        reportPath = path
        reportText = text
        open()
    }

    background: Rectangle {
        radius: 18
        color: "#0B161E"
        border.width: 1
        border.color: Qt.rgba(1, 0.55, 0.55, 0.45)
    }

    contentItem: ColumnLayout {
        spacing: 10

        Text {
            text: dlg.tr.crashTitle || "程序发生异常"
            color: "#FFE1E1"
            font.pixelSize: 18
            font.weight: Font.DemiBold
        }

        Text {
            Layout.fillWidth: true
            text: dlg.tr.crashBody || ""
            color: uiTheme.muted
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }

        Text {
            Layout.fillWidth: true
            text: (dlg.tr.crashFile || "Log") + ": " + dlg.reportPath
            color: Qt.rgba(0.7, 0.86, 0.9, 0.8)
            font.pixelSize: 11
            elide: Text.ElideMiddle
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            TextArea {
                readOnly: true
                text: dlg.reportText
                color: "#CFEAF1"
                font.family: "Consolas"
                font.pixelSize: 11
                wrapMode: TextArea.Wrap
                background: Rectangle {
                    radius: 10
                    color: Qt.rgba(0, 0, 0, 0.28)
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.1)
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            AnimatedButton { text: dlg.tr.crashCopy || "复制日志"; onClicked: Bridge.copyText(dlg.reportText) }
            AnimatedButton { text: dlg.tr.crashOpen || "打开日志目录"; onClicked: Bridge.openLogDir() }
            AnimatedButton { text: dlg.tr.close || "关闭"; primary: true; onClicked: dlg.close() }
        }
    }

    Connections {
        target: Crash
        function onCrashReported(path, text) { dlg.showReport(path, text) }
    }

    Connections {
        target: Bridge
        function onCrashLogReady(path, text) { dlg.showReport(path, text) }
    }
}
