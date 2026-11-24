import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    anchors.fill: parent
    z: 800
    visible: !Settings.onboardingDone

    property var appRoot
    readonly property var tr: appRoot ? appRoot.tr : ({})
    property int step: 0
    property bool closing: false

    function finish() {
        if (closing) return
        closing = true
        Settings.onboardingDone = true
        if (appRoot)
            appRoot.notify(root.tr.onbStart || "Ready", false)
    }

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0.015, 0.045, 0.065, 0.72)
    }

    Rectangle {
        anchors.centerIn: parent
        width: 880
        height: 560
        radius: 80
        color: Qt.rgba(0.25, 0.75, 0.86, 0.055)
    }

    GlassCard {
        id: card
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 760)
        height: 468
        pad: 30
        opacity: 0
        scale: 0.97

        Behavior on opacity { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }

        Component.onCompleted: {
            opacity = 1
            scale = 1
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 14

            RowLayout {
                Layout.fillWidth: true

                RowLayout {
                    spacing: 10
                    Rectangle {
                        width: 34
                        height: 34
                        radius: 10
                        gradient: Gradient {
                            GradientStop { position: 0; color: "#5FE3C8" }
                            GradientStop { position: 1; color: "#3B7BD4" }
                        }
                        Text {
                            anchors.centerIn: parent
                            text: "琉"
                            color: "#042027"
                            font.pixelSize: 17
                            font.weight: Font.Black
                        }
                    }
                    Text {
                        text: root.tr.onbTitle || ""
                        color: uiTheme.text
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }
                }

                Item { Layout.fillWidth: true }

                Text {
                    text: (root.step + 1) + " / 3"
                    color: uiTheme.muted
                    font.pixelSize: 11
                }

                AnimatedButton {
                    text: root.tr.onbSkip || "Skip"
                    ghost: true
                    small: true
                    onClicked: root.finish()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Qt.rgba(0.7, 0.93, 1, 0.14)
            }

            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: 178

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 12

                    Text {
                        text: root.step === 0 ? root.tr.onbStep1Title
                              : root.step === 1 ? root.tr.onbStep2Title
                              : root.tr.onbStep3Title
                        color: uiTheme.text
                        font.pixelSize: 30
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.step === 0 ? root.tr.onbStep1Body
                              : root.step === 1 ? root.tr.onbStep2Body
                              : root.tr.onbStep3Body
                        color: uiTheme.muted
                        font.pixelSize: 13
                        lineHeight: 1.6
                        wrapMode: Text.Wrap
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                height: warningText.implicitHeight + 24
                radius: 10
                color: Qt.rgba(1, 0.78, 0.35, 0.10)
                border.width: 1
                border.color: Qt.rgba(1, 0.82, 0.45, 0.32)
                visible: true

                RowLayout {
                    id: warning
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14
                    anchors.topMargin: 10
                    anchors.bottomMargin: 10
                    spacing: 10
                    Text { text: "!"; color: "#FFD37A"; font.pixelSize: 16; font.weight: Font.Bold }
                    Text {
                        id: warningText
                        Layout.fillWidth: true
                        text: root.tr.onbWarning || ""
                        color: "#FFE7B4"
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                    }
                }
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Repeater {
                    model: 3
                    delegate: Rectangle {
                        required property int index
                        width: 26
                        height: 5
                        radius: 3
                        color: index === root.step ? uiTheme.accent : Qt.rgba(1, 1, 1, 0.16)
                        Behavior on color { ColorAnimation { duration: 180 } }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.step = index
                        }
                    }
                }

                Item { Layout.fillWidth: true }

                AnimatedButton {
                    text: root.tr.back || "Back"
                    visible: root.step > 0
                    onClicked: root.step -= 1
                }
                AnimatedButton {
                    text: root.step < 2 ? (root.tr.next || "Next") : (root.tr.onbStart || "Get started")
                    primary: true
                    onClicked: {
                        if (root.step < 2)
                            root.step += 1
                        else
                            root.finish()
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: root.tr.onbBoundary || ""
                color: Qt.rgba(0.56, 0.7, 0.76, 0.7)
                font.pixelSize: 9
                wrapMode: Text.Wrap
            }
        }
    }
}
