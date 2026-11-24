import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    anchors.fill: parent
    property var appRoot
    readonly property var tr: appRoot ? appRoot.tr : ({})
    property bool active: false
    property string apiWarning: ""
    property string portStatus: ""

    function saveServer() {
        Settings.apiBase = apiField.text.trim()
        apiWarning = Bridge.apiBaseWarning()
        appRoot.notify(tr.setSaved, false)
    }

    function savePort() {
        var p = Number(portField.text)
        if (p < 1024 || p > 65535) {
            appRoot.notify(tr.setInvalidPort, true)
            return
        }
        Settings.labPort = p
        portStatus = Bridge.checkPort(p)
        if (portStatus === "") portStatus = "✓ " + p
        appRoot.notify(tr.setSaved, false)
    }

    Component.onCompleted: apiWarning = Bridge.apiBaseWarning()

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AlwaysOn; width: 5 }

        ColumnLayout {
            id: content
            width: parent.width
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    spacing: 2
                    Text { text: root.tr.setTitle; color: uiTheme.text; font.pixelSize: 24; font.weight: Font.DemiBold }
                    Text { text: root.tr.setBoundary; color: uiTheme.muted; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.maximumWidth: 720 }
                }
                Item { Layout.fillWidth: true }
                Text { text: "v" + AppVersion; color: uiTheme.muted; font.pixelSize: 11 }
            }

            Item {
                id: twoCol
                Layout.fillWidth: true
                implicitHeight: Math.max(leftCol.implicitHeight, rightCol.implicitHeight)

                ColumnLayout {
                    id: leftCol
                    width: parent.width - 436
                    spacing: 14

                    // ---------- appearance ----------
                    GlassCard {
                        Layout.fillWidth: true
                        height: 224
                        pad: 20
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 10
                            Text { text: root.tr.setAppearance; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12

                                Rectangle {
                                    Layout.fillWidth: true
                                    height: 124
                                    radius: 12
                                    color: Settings.glassMode ? Qt.rgba(0.37,0.92,0.82,0.10) : Qt.rgba(1,1,1,0.035)
                                    border.width: 1
                                    border.color: Settings.glassMode ? Qt.rgba(0.37,0.92,0.82,0.5) : Qt.rgba(1,1,1,0.1)
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 14
                                        spacing: 6
                                        RowLayout {
                                            spacing: 5
                                            Repeater {
                                                model: 3
                                                Rectangle {
                                                    width: 18; height: 26; radius: 4
                                                    color: Qt.rgba(0.6, 0.95, 1, 0.16 + index * 0.08)
                                                    border.width: 1; border.color: Qt.rgba(0.7,0.95,1,0.3)
                                                }
                                            }
                                        }
                                        Text { text: root.tr.setGlass; color: uiTheme.text; font.pixelSize: 12; font.weight: Font.DemiBold }
                                        Text { text: root.tr.setGlassHint; color: uiTheme.muted; font.pixelSize: 9; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: Settings.glassMode = true
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    height: 124
                                    radius: 12
                                    color: !Settings.glassMode ? Qt.rgba(0.49,0.66,1,0.10) : Qt.rgba(1,1,1,0.035)
                                    border.width: 1
                                    border.color: !Settings.glassMode ? Qt.rgba(0.49,0.66,1,0.5) : Qt.rgba(1,1,1,0.1)
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 14
                                        spacing: 6
                                        Rectangle { width: 58; height: 26; radius: 5; color: "#22313D" }
                                        Text { text: root.tr.setNative; color: uiTheme.text; font.pixelSize: 12; font.weight: Font.DemiBold }
                                        Text { text: root.tr.setNativeHint; color: uiTheme.muted; font.pixelSize: 9; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: Settings.glassMode = false
                                    }
                                }
                            }
                        }
                    }

                    // ---------- language ----------
                    GlassCard {
                        Layout.fillWidth: true
                        height: 142
                        pad: 20
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 10
                            Text { text: root.tr.setLanguage; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                            RowLayout {
                                spacing: 8
                                AnimatedButton {
                                    text: "简体中文"
                                    primary: root.tr.lang === "zh_CN"
                                    onClicked: I18n.setLanguage("zh_CN")
                                }
                                AnimatedButton {
                                    text: "English"
                                    primary: root.tr.lang === "en_US"
                                    onClicked: I18n.setLanguage("en_US")
                                }
                                AnimatedButton {
                                    text: "繁體中文"
                                    primary: root.tr.lang === "zh_TW"
                                    onClicked: I18n.setLanguage("zh_TW")
                                }
                                Item { Layout.fillWidth: true }
                            }
                            Text { text: "zh_CN · en_US · zh_TW"; color: Qt.rgba(0.56,0.7,0.76,0.6); font.pixelSize: 9 }
                        }
                    }

                    // ---------- server ----------
                    GlassCard {
                        Layout.fillWidth: true
                        height: 226
                        pad: 20
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 8
                            Text { text: root.tr.setServer; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                            Text { text: root.tr.setServerHint; color: uiTheme.muted; font.pixelSize: 9; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            TxField {
                                id: apiField
                                Layout.fillWidth: true
                                text: Settings.apiBase
                                placeholder: "https://api.example.com/api/v1"
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                AnimatedButton { text: root.tr.save; primary: true; small: true; onClicked: root.saveServer() }
                                Text {
                                    Layout.fillWidth: true
                                    text: root.apiWarning
                                    color: uiTheme.warning
                                    font.pixelSize: 9
                                    wrapMode: Text.Wrap
                                    visible: root.apiWarning !== ""
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: root.tr.setSecureHint
                                color: Qt.rgba(0.56,0.7,0.76,0.6)
                                font.pixelSize: 9
                                wrapMode: Text.Wrap
                            }
                        }
                    }

                    // ---------- local port ----------
                    GlassCard {
                        Layout.fillWidth: true
                        height: 206
                        pad: 20
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 8
                            Text { text: root.tr.setPort; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                            Text { text: root.tr.setPortHint; color: uiTheme.muted; font.pixelSize: 9; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                TxField {
                                    id: portField
                                    Layout.preferredWidth: 130
                                    text: String(Settings.labPort)
                                    inputMethodHints: Qt.ImhDigitsOnly
                                }
                                AnimatedButton { text: root.tr.save; small: true; onClicked: root.savePort() }
                                AnimatedButton {
                                    text: root.tr.setFirewall
                                    small: true
                                    ghost: true
                                    onClicked: Bridge.applyFirewall(Number(portField.text))
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: root.portStatus
                                color: uiTheme.accent
                                font.pixelSize: 10
                                visible: root.portStatus !== ""
                            }
                        }
                    }
                }

                ColumnLayout {
                    id: rightCol
                    x: parent.width - 420
                    width: 420
                    spacing: 14

                    // ---------- operator backend ----------
                    GlassCard {
                        Layout.fillWidth: true
                        height: 214
                        pad: 20
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 8
                            Text { text: root.tr.adminTitle; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                            Text {
                                Layout.fillWidth: true
                                text: root.tr.adminHint
                                color: uiTheme.muted
                                font.pixelSize: 9
                                wrapMode: Text.Wrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: (root.appRoot && root.appRoot.adminUrl) ? root.appRoot.adminUrl : ""
                                color: "#BFF9EF"
                                font.family: "Consolas"
                                font.pixelSize: 10
                                elide: Text.ElideMiddle
                            }
                            Text {
                                Layout.fillWidth: true
                                text: root.tr.adminEmail + ": " + ((root.appRoot && root.appRoot.realnameInbox) ? root.appRoot.realnameInbox : "2416444244@qq.com")
                                color: uiTheme.muted
                                font.pixelSize: 9
                                elide: Text.ElideMiddle
                            }
                            RowLayout {
                                spacing: 8
                                AnimatedButton {
                                    text: root.tr.adminOpen
                                    small: true
                                    primary: true
                                    onClicked: {
                                        var u = (root.appRoot && root.appRoot.adminUrl) ? root.appRoot.adminUrl : "http://127.0.0.1:8000/admin"
                                        Bridge.openUrl(u)
                                    }
                                }
                                AnimatedButton {
                                    text: root.tr.copy
                                    small: true
                                    ghost: true
                                    onClicked: {
                                        var u = (root.appRoot && root.appRoot.adminUrl) ? root.appRoot.adminUrl : ""
                                        if (u !== "") Bridge.copyText(u)
                                    }
                                }
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }

                    // ---------- GitHub ----------
                    GlassCard {
                        Layout.fillWidth: true
                        height: 190
                        pad: 20
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 8
                            RowLayout {
                                spacing: 10
                                Image {
                                    source: "../../../resources/github.svg"
                                    sourceSize.width: 30
                                    sourceSize.height: 30
                                    fillMode: Image.PreserveAspectFit
                                }
                                Text { text: root.tr.setGithub; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                                Item { Layout.fillWidth: true }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: root.tr.setGithubHint
                                color: uiTheme.muted
                                font.pixelSize: 10
                                wrapMode: Text.Wrap
                                lineHeight: 1.45
                            }
                            Text {
                                Layout.fillWidth: true
                                text: Bridge.githubUrl
                                color: Qt.rgba(0.56, 0.7, 0.76, 0.7)
                                font.pixelSize: 9
                                elide: Text.ElideMiddle
                            }
                            AnimatedButton {
                                text: root.tr.setGithubOpen
                                small: true
                                onClicked: Bridge.openUrl(Bridge.githubUrl)
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }

                    // ---------- crash ----------
                    GlassCard {
                        Layout.fillWidth: true
                        height: 202
                        pad: 20
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 8
                            Text { text: root.tr.setCrash; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                            Text {
                                Layout.fillWidth: true
                                text: root.tr.setCrashHint
                                color: uiTheme.muted
                                font.pixelSize: 10
                                wrapMode: Text.Wrap
                                lineHeight: 1.45
                            }
                            RowLayout {
                                spacing: 8
                                AnimatedButton {
                                    text: root.tr.setCrashTest
                                    small: true
                                    onClicked: Bridge.makeCrashSample()
                                }
                                AnimatedButton {
                                    text: root.tr.crashOpen
                                    small: true
                                    ghost: true
                                    onClicked: Bridge.openLogDir()
                                }
                                AnimatedButton {
                                    text: root.tr.copy
                                    small: true
                                    ghost: true
                                    onClicked: {
                                        var text = Crash.latest()
                                        if (text === "") root.appRoot.notify(root.tr.empty, true)
                                        else Bridge.copyText(text)
                                    }
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: Settings.qsettingsPath()
                                color: Qt.rgba(0.56,0.7,0.76,0.6)
                                font.pixelSize: 8
                                elide: Text.ElideMiddle
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }

                    // ---------- account ----------
                    GlassCard {
                        Layout.fillWidth: true
                        height: 184
                        pad: 20
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 8
                            Text { text: root.tr.dashAccount; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                            Text {
                                Layout.fillWidth: true
                                text: (root.appRoot && root.appRoot.user && root.appRoot.user.email) ? root.appRoot.user.email : ""
                                color: uiTheme.text
                                font.pixelSize: 12
                                elide: Text.ElideMiddle
                            }
                            Text {
                                text: (root.appRoot && root.appRoot.user && root.appRoot.user.user_no) ? root.appRoot.user.user_no : ""
                                color: uiTheme.muted
                                font.pixelSize: 10
                            }
                            Text {
                                text: Bridge.sessionStorage
                                color: Qt.rgba(0.56,0.7,0.76,0.7)
                                font.pixelSize: 9
                            }
                            Item { Layout.fillHeight: true }
                            RowLayout {
                                Layout.fillWidth: true
                                AnimatedButton {
                                    text: root.tr.setOnboardingReset
                                    small: true
                                    ghost: true
                                    onClicked: Settings.resetOnboarding()
                                }
                                Item { Layout.fillWidth: true }
                                AnimatedButton {
                                    text: root.tr.setLogout
                                    small: true
                                    danger: true
                                    onClicked: Bridge.logout()
                                }
                            }
                        }
                    }

                    // ---------- about ----------
                    GlassCard {
                        Layout.fillWidth: true
                        height: 174
                        pad: 20
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 8
                            Text { text: root.tr.setAbout; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                            Text { text: "LiuliDNS · " + root.tr.version + " " + AppVersion; color: uiTheme.accent; font.pixelSize: 11 }
                            Text {
                                Layout.fillWidth: true
                                text: root.tr.setBoundary
                                color: uiTheme.muted
                                font.pixelSize: 9
                                wrapMode: Text.Wrap
                                lineHeight: 1.4
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "PySide6 / Qt Quick · FastAPI · dnslib"
                                color: Qt.rgba(0.56,0.7,0.76,0.6)
                                font.pixelSize: 8
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }
                }
            }

            Item { height: 64 }
        }
    }
}
