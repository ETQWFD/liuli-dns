import QtQuick

Rectangle {
    id: pill

    property string text: ""
    property string tone: "muted"   // ok | warn | bad | muted
    property bool glass: uiTheme.glass

    implicitWidth: label.implicitWidth + 20
    implicitHeight: 24
    radius: 12
    color: {
        if (tone === "ok") return Qt.rgba(0.35, 0.9, 0.78, 0.16)
        if (tone === "warn") return Qt.rgba(1, 0.82, 0.42, 0.16)
        if (tone === "bad") return Qt.rgba(1, 0.45, 0.45, 0.16)
        return Qt.rgba(1, 1, 1, 0.07)
    }
    border.width: 1
    border.color: tone === "ok" ? Qt.rgba(0.4, 0.95, 0.83, 0.42)
                  : tone === "warn" ? Qt.rgba(1, 0.85, 0.5, 0.38)
                  : tone === "bad" ? Qt.rgba(1, 0.55, 0.55, 0.4)
                  : Qt.rgba(1, 1, 1, 0.14)

    Text {
        id: label
        anchors.centerIn: parent
        text: pill.text
        color: pill.tone === "ok" ? "#A8FFEF"
               : pill.tone === "warn" ? "#FFE7B4"
               : pill.tone === "bad" ? "#FFCECE"
               : uiTheme.muted
        font.pixelSize: 11
    }
}
