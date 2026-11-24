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
    readonly property var user: appRoot && appRoot.user ? appRoot.user : ({})

    function countActive() {
        var n = 0
        var ds = appRoot ? appRoot.domains : []
        for (var i = 0; i < ds.length; ++i)
            if (ds[i].status === "active") n++
        return n
    }

    function realnameLabel() {
        var st = appRoot && appRoot.user ? root.user.realname_status : ""
        if (st === "active") return tr.dashRealnameActive
        if (st === "pending" || st === "approved") return tr.dashRealnamePending
        return tr.dashRealnameNone
    }

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        ColumnLayout {
            id: content
            width: parent.width
            spacing: 16

            // header
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    spacing: 3
                    Text {
                        text: root.tr.dashTitle
                        color: uiTheme.text
                        font.pixelSize: 26
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: (root.tr.dashHello || "") + ", " + (appRoot && appRoot.user && appRoot.user.email
                              ? appRoot.user.email.split("@")[0] : "")
                        color: uiTheme.muted
                        font.pixelSize: 12
                    }
                }
                Item { Layout.fillWidth: true }
                AnimatedButton {
                    text: root.tr.dashAddDomain
                    iconText: "+"
                    primary: true
                    onClicked: appRoot.go("Domains")
                }
            }

            // stat cards
            GridLayout {
                Layout.fillWidth: true
                columns: 4
                columnSpacing: 14

                GlassCard {
                    Layout.fillWidth: true
                    height: 104
                    pad: 18
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 4
                        Text { text: root.tr.dashDomains; color: uiTheme.muted; font.pixelSize: 11 }
                        Text { text: appRoot.domains.length; color: uiTheme.text; font.pixelSize: 28; font.weight: Font.DemiBold }
                        Text { text: "apex · " + (root.tr.dashHosted || "hosted zones"); color: Qt.rgba(0.56,0.7,0.76,0.7); font.pixelSize: 9 }
                    }
                }
                GlassCard {
                    Layout.fillWidth: true
                    height: 104
                    pad: 18
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 4
                        Text { text: root.tr.dashActiveDomains; color: uiTheme.muted; font.pixelSize: 11 }
                        Text { text: root.countActive(); color: uiTheme.accent; font.pixelSize: 28; font.weight: Font.DemiBold }
                        Text { text: "authoritative DNS"; color: Qt.rgba(0.56,0.7,0.76,0.7); font.pixelSize: 9 }
                    }
                }
                GlassCard {
                    Layout.fillWidth: true
                    height: 104
                    pad: 18
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 4
                        Text { text: root.tr.dashCerts; color: uiTheme.muted; font.pixelSize: 11 }
                        Text { text: appRoot.expiring.length; color: uiTheme.accent2; font.pixelSize: 28; font.weight: Font.DemiBold }
                        Text { text: "≤ 30 days"; color: Qt.rgba(0.56,0.7,0.76,0.7); font.pixelSize: 9 }
                    }
                }
                GlassCard {
                    Layout.fillWidth: true
                    height: 104
                    pad: 18
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 4
                        Text { text: root.tr.dashRealname; color: uiTheme.muted; font.pixelSize: 11 }
                        Text {
                            text: root.realnameLabel()
                            color: (root.user.realname_status === "active") ? uiTheme.accent : uiTheme.warning
                            font.pixelSize: 16
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Text { text: "platform review"; color: Qt.rgba(0.56,0.7,0.76,0.7); font.pixelSize: 9 }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 16

                GlassCard {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 720
                    height: 300
                    pad: 20
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: root.tr.dashRecent; color: uiTheme.text; font.pixelSize: 15; font.weight: Font.DemiBold }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: root.tr.navDomains + " →"
                                color: uiTheme.accent
                                font.pixelSize: 10
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: appRoot.go("Domains")
                                }
                            }
                        }

                        Text {
                            visible: appRoot.domains.length === 0
                            Layout.fillWidth: true
                            text: root.tr.dashNoDomain
                            color: uiTheme.muted
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                            lineHeight: 1.5
                        }

                        Repeater {
                            model: appRoot.domains.slice(0, 3)
                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true
                                height: 58
                                radius: 11
                                color: rowMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.06) : "transparent"
                                border.width: 1
                                border.color: Qt.rgba(1, 1, 1, 0.06)

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 12
                                    anchors.rightMargin: 12
                                    spacing: 12
                                    Rectangle {
                                        width: 30
                                        height: 30
                                        radius: 8
                                        color: Qt.rgba(0.37, 0.92, 0.82, 0.12)
                                        Text { anchors.centerIn: parent; text: "◈"; color: uiTheme.accent; font.pixelSize: 13 }
                                    }
                                    ColumnLayout {
                                        spacing: 2
                                        Text { text: modelData.fqdn; color: uiTheme.text; font.pixelSize: 13; font.weight: Font.Medium }
                                        Text {
                                            text: "v" + modelData.zone_version + " · " + modelData.created_at
                                            color: Qt.rgba(0.56,0.7,0.76,0.65)
                                            font.pixelSize: 9
                                        }
                                    }
                                    Item { Layout.fillWidth: true }
                                    StatusPill {
                                        text: modelData.status === "active" ? root.tr.statusActive : root.tr.statusPending
                                        tone: modelData.status === "active" ? "ok" : "warn"
                                    }
                                    Text { text: "›"; color: uiTheme.muted; font.pixelSize: 16 }
                                }
                                MouseArea {
                                    id: rowMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        appRoot.selectedDomainId = modelData.id
                                        appRoot.go("Domains")
                                    }
                                }
                            }
                        }

                        Item { Layout.fillHeight: true }

                        Text {
                            Layout.fillWidth: true
                            text: root.tr.dashBoundary
                            color: Qt.rgba(0.56,0.7,0.76,0.6)
                            font.pixelSize: 9
                            wrapMode: Text.Wrap
                        }
                    }
                }

                GlassCard {
                    Layout.preferredWidth: 330
                    height: 300
                    pad: 20
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 10
                        Text { text: root.tr.dashQuick; color: uiTheme.text; font.pixelSize: 15; font.weight: Font.DemiBold }

                        AnimatedButton {
                            Layout.fillWidth: true
                            text: root.tr.dashAddDomain
                            iconText: "＋"
                            onClicked: appRoot.go("Domains")
                        }
                        AnimatedButton {
                            Layout.fillWidth: true
                            text: root.tr.navRecords
                            iconText: "≡"
                            onClicked: appRoot.go("Records")
                        }
                        AnimatedButton {
                            Layout.fillWidth: true
                            text: root.tr.navCerts
                            iconText: "✦"
                            onClicked: appRoot.go("Certificates")
                        }
                        AnimatedButton {
                            Layout.fillWidth: true
                            text: root.tr.navRealname
                            iconText: "▣"
                            onClicked: appRoot.go("Realname")
                        }

                        Item { Layout.fillHeight: true }

                        RowLayout {
                            Layout.fillWidth: true
                            Rectangle { width: 7; height: 7; radius: 4; color: uiTheme.accent; opacity: 0.9 }
                            Text { text: root.tr.online; color: uiTheme.muted; font.pixelSize: 10 }
                            Item { Layout.fillWidth: true }
                            Text { text: "v" + AppVersion; color: Qt.rgba(0.56,0.7,0.76,0.6); font.pixelSize: 9 }
                        }
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                height: 72
                pad: 18
                RowLayout {
                    anchors.fill: parent
                    spacing: 14
                    Text { text: "◈"; color: uiTheme.accent; font.pixelSize: 18 }
                    ColumnLayout {
                        spacing: 2
                        Text { text: root.tr.dashStatus; color: uiTheme.text; font.pixelSize: 12; font.weight: Font.Medium }
                        Text {
                            text: Settings.apiBase
                            color: Qt.rgba(0.56,0.7,0.76,0.7)
                            font.pixelSize: 9
                            elide: Text.ElideMiddle
                            Layout.fillWidth: true
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: root.tr.setBoundary
                        color: Qt.rgba(0.56,0.7,0.76,0.6)
                        font.pixelSize: 9
                        horizontalAlignment: Text.AlignRight
                        Layout.maximumWidth: 420
                        wrapMode: Text.Wrap
                    }
                }
            }

            Item { height: 8 }
        }
    }
}
