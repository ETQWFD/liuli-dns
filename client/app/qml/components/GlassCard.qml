import QtQuick
import QtQuick.Effects

Rectangle {
    id: card

    property bool glass: uiTheme.glass
    property real pad: 16
    property color tint: "transparent"
    default property alias content: inner.data

    radius: 18
    color: glass ? Qt.rgba(0.60, 0.92, 1.0, 0.055) : uiTheme.cardNative
    border.width: 1
    border.color: glass ? Qt.rgba(0.72, 0.96, 1.0, 0.16) : uiTheme.borderNative

    gradient: glass ? glassGradient : null

    Gradient {
        id: glassGradient
        GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.10) }
        GradientStop { position: 0.18; color: Qt.rgba(0.74, 0.96, 1, 0.035) }
        GradientStop { position: 1.0; color: Qt.rgba(0.20, 0.55, 0.7, 0.02) }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 1
        height: 1
        radius: 1
        color: Qt.rgba(1, 1, 1, 0.38)
        opacity: card.glass ? 0.8 : 0
    }

    Item {
        id: inner
        anchors.fill: parent
        anchors.margins: card.pad
    }
}
