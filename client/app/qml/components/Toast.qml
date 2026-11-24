import QtQuick
import QtQuick.Layouts

Item {
    id: root
    anchors.fill: parent
    opacity: 0
    visible: opacity > 0.01
    z: 900

    property string message: ""
    property bool isError: false
    property int duration: 3200

    function show(msg, err) {
        message = msg
        isError = err === true
        opacity = 1
        hideTimer.restart()
    }

    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 26
        width: Math.min(parent.width - 80, Math.max(220, textItem.implicitWidth + 64))
        height: 50
        radius: 14
        color: root.isError ? Qt.rgba(0.42, 0.10, 0.12, 0.92) : Qt.rgba(0.05, 0.15, 0.18, 0.92)
        border.width: 1
        border.color: root.isError ? Qt.rgba(1, 0.55, 0.55, 0.55) : Qt.rgba(0.5, 0.95, 0.85, 0.45)

        Text {
            id: textItem
            anchors.centerIn: parent
            text: root.message
            color: root.isError ? "#FFD9D9" : "#D6FFF7"
            font.pixelSize: 12
            width: parent.width - 40
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            maximumLineCount: 2
            wrapMode: Text.Wrap
        }
    }

    Timer {
        id: hideTimer
        interval: root.duration
        onTriggered: root.opacity = 0
    }
}
