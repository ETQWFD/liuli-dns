import QtQuick
import QtQuick.Controls

Item {
    id: btn

    property string text: ""
    property string iconText: ""
    property bool primary: false
    property bool danger: false
    property bool ghost: false
    property bool small: false
    signal clicked()

    implicitWidth: Math.max(76, metrics.advanceWidth + (small ? 22 : 34))
    implicitHeight: small ? 30 : 38
    opacity: enabled ? 1.0 : 0.42

    TextMetrics {
        id: metrics
        font: label.font
        text: (btn.iconText ? btn.iconText + "  " : "") + btn.text
    }

    Rectangle {
        id: surface
        anchors.fill: parent
        radius: small ? 8 : 11
        clip: true
        color: {
            if (btn.danger) return mouse.containsMouse ? Qt.rgba(1, 0.45, 0.45, 0.26) : Qt.rgba(1, 0.45, 0.45, 0.12)
            if (btn.primary) return mouse.containsMouse ? Qt.rgba(0.37, 0.92, 0.82, 0.30) : Qt.rgba(0.37, 0.92, 0.82, 0.18)
            if (btn.ghost) return mouse.containsMouse ? Qt.rgba(1, 1, 1, 0.08) : "transparent"
            return mouse.containsMouse ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(1, 1, 1, 0.045)
        }
        border.width: btn.ghost ? 0 : 1
        border.color: btn.danger ? Qt.rgba(1, 0.55, 0.55, 0.42)
                      : btn.primary ? Qt.rgba(0.5, 0.98, 0.88, 0.5)
                      : Qt.rgba(0.75, 0.92, 1.0, 0.18)
        scale: mouse.containsMouse && btn.enabled ? 1.025 : 1.0
        Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
        Behavior on color { ColorAnimation { duration: 180 } }

        Rectangle {
            id: ripple
            width: 14
            height: 14
            radius: 7
            opacity: 0
            scale: 0
            color: btn.primary ? Qt.rgba(1, 1, 1, 0.35) : Qt.rgba(0.5, 0.98, 0.88, 0.28)
        }

        ParallelAnimation {
            id: rippleAnim
            NumberAnimation { target: ripple; property: "scale"; from: 0; to: 14; duration: 480; easing.type: Easing.OutQuad }
            NumberAnimation { target: ripple; property: "opacity"; from: 0.85; to: 0; duration: 520 }
        }

        Text {
            id: label
            anchors.centerIn: parent
            text: (btn.iconText ? btn.iconText + "  " : "") + btn.text
            color: btn.danger ? "#FFDADA" : (btn.primary ? "#DFFFF9" : uiTheme.text)
            font.pixelSize: btn.small ? 12 : 13
            font.weight: btn.primary ? Font.DemiBold : Font.Medium
        }

        MouseArea {
            id: mouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            enabled: btn.enabled
            onClicked: {
                ripple.x = mouseX - ripple.width / 2
                ripple.y = mouseY - ripple.height / 2
                rippleAnim.restart()
                btn.clicked()
            }
        }
    }
}
