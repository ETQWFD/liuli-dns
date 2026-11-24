import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "pages"

ApplicationWindow {
    id: app

    width: 1280
    height: 820
    minimumWidth: 1080
    minimumHeight: 700
    visible: true
    color: "#050B12"
    title: (tr.appName || "LiuliDNS") + " · " + (tr.tagline || "")

    property var tr: ({})
    property bool glass: Settings.glassMode
    property bool loggedIn: Bridge.loggedIn
    property var user: ({})
    property var domains: []
    property var expiring: []
    property var tunnel: ({})
    property string platformDomain: "asnia.cc"
    property string adminUrl: "http://127.0.0.1:8000/admin"
    property string realnameInbox: "2416444244@qq.com"
    property int selectedDomainId: 0
    property string page: "Dashboard"
    property bool busy: false
    property string bannerText: ""

    Timer {
        interval: 30000
        running: app.loggedIn
        repeat: true
        onTriggered: app.refreshTunnelStatus()
    }

    readonly property var navItems: [
        { key: "Dashboard", icon: "◈", labelKey: "navDashboard" },
        { key: "Domains", icon: "⬡", labelKey: "navDomains" },
        { key: "Records", icon: "≡", labelKey: "navRecords" },
        { key: "Certificates", icon: "✦", labelKey: "navCerts" },
        { key: "Realname", icon: "▣", labelKey: "navRealname" },
        { key: "Tools", icon: "⌁", labelKey: "navTools" },
        { key: "Settings", icon: "⚙", labelKey: "navSettings" }
    ]

    function go(name) {
        if (page !== name) page = name
    }

    function notify(msg, isError) {
        toast.show(msg, isError === true)
    }

    function pageTitle() {
        var keys = {
            Dashboard: "dashTitle", Domains: "domTitle", Records: "recTitle",
            Certificates: "certTitle", Realname: "realTitle", Tools: "toolsTitle",
            Settings: "setTitle"
        }
        return tr[keys[page]] || tr.dashTitle || ""
    }

    function pageSubtitle() {
        if (page === "Dashboard") return tr.tagline || ""
        if (page === "Domains") return tr.domDetail || ""
        if (page === "Records") return tr.recHint || ""
        if (page === "Certificates") return tr.certKeyNote || ""
        if (page === "Realname") return tr.realBoundary || ""
        if (page === "Tools") return tr.toolsLocalHint || ""
        return tr.setBoundary || ""
    }

    function refreshDomains() {
        if (!Bridge.loggedIn) return
        Bridge.refreshMe()
        Bridge.api("domains", "GET", "/domains", "{}")
        Bridge.api("expiring", "GET", "/certificates/expiring?days=45", "{}")
        refreshTunnelStatus()
    }

    function refreshTunnelStatus() {
        if (!Bridge.loggedIn) return
        Bridge.api("tunnel_status", "GET", "/domains/tunnel/status", "{}")
    }

    function showBanner(msg) {
        bannerText = msg
        banner.opacity = 1
        bannerTimer.restart()
    }

    Component.onCompleted: {
        tr = I18n.bundle()
        user = Bridge.userJson ? JSON.parse(Bridge.userJson) : ({})
        if (Bridge.loggedIn) {
            refreshDomains()
            Bridge.api("meta_public", "GET", "/meta/public", "{}")
        }
    }

    Connections {
        target: I18n
        function onLanguageChanged() { app.tr = I18n.bundle() }
    }

    Connections {
        target: Bridge
        function onAuthChanged(logged, userJson) {
            app.user = JSON.parse(userJson || "{}")
            if (logged) {
                app.page = "Dashboard"
                app.refreshDomains()
            } else {
                app.domains = []
                app.expiring = []
                app.tunnel = ({})
                app.selectedDomainId = 0
                app.page = "Dashboard"
            }
        }

        function onApiResult(action, ok, data, code, message) {
            if (ok) {
                if (action === "domains") {
                    var list = JSON.parse(data || "{}").items || []
                    app.domains = list
                    var found = false
                    for (var i = 0; i < list.length; ++i)
                        if (list[i].id === app.selectedDomainId) found = true
                    if (!found)
                        app.selectedDomainId = list.length > 0 ? list[0].id : 0
                } else if (action === "expiring") {
                    app.expiring = JSON.parse(data || "{}").items || []
                } else if (action === "me") {
                    app.user = JSON.parse(data || "{}")
                } else if (action === "tunnel_status") {
                    app.tunnel = JSON.parse(data || "{}")
                } else if (action === "meta_public") {
                    var meta = JSON.parse(data || "{}")
                    if (meta.platform_domain) app.platformDomain = meta.platform_domain
                    if (meta.admin_url) app.adminUrl = meta.admin_url
                    if (meta.realname_inbox) app.realnameInbox = meta.realname_inbox
                }
                return
            }
            if (action === "expiring" || action === "captcha" || action === "realname_status")
                return
            if (action === "refresh" || action === "refresh_silent")
                return
            app.notify(message || app.tr.errGeneric, true)
            if (code === "REALNAME_REQUIRED") {
                app.notify(app.tr.errRealname, true)
                app.go("Realname")
            }
        }

        function onToast(message, isError) { app.notify(message, isError) }
        function onServerWarning(message) { app.showBanner(message) }
        function onBusyChanged(value) { app.busy = value }
        function onNavigateTo(name) { app.go(name) }
        function onResetView() { app.page = "Dashboard" }
    }

    // ================= background =================
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#0B2433" }
            GradientStop { position: 0.42; color: "#081826" }
            GradientStop { position: 1.0; color: "#040A10" }
        }
    }

    Item {
        id: orbLayer
        anchors.fill: parent
        opacity: app.glass ? 1 : 0.25
        Behavior on opacity { NumberAnimation { duration: 260 } }

        Rectangle {
            width: 620; height: 620; radius: 310
            color: Qt.rgba(0.30, 0.86, 0.78, 0.075)
            NumberAnimation on x { from: 120; to: 260; duration: 22000; loops: Animation.Infinite; easing.type: Easing.InOutSine; running: app.visible }
            NumberAnimation on y { from: -160; to: -80; duration: 18000; loops: Animation.Infinite; easing.type: Easing.InOutSine; running: app.visible }
        }
        Rectangle {
            width: 520; height: 520; radius: 260
            color: Qt.rgba(0.42, 0.58, 1.0, 0.075)
            NumberAnimation on x { from: 760; to: 680; duration: 26000; loops: Animation.Infinite; easing.type: Easing.InOutSine; running: app.visible }
            NumberAnimation on y { from: 180; to: 120; duration: 20000; loops: Animation.Infinite; easing.type: Easing.InOutSine; running: app.visible }
        }
        Rectangle {
            width: 380; height: 380; radius: 190
            color: Qt.rgba(0.65, 0.42, 0.95, 0.05)
            y: 560
            NumberAnimation on x { from: 300; to: 380; duration: 24000; loops: Animation.Infinite; easing.type: Easing.InOutSine; running: app.visible }
        }
    }

    Rectangle {
        width: parent.width * 1.4
        height: 300
        x: -120
        y: -140
        rotation: -14
        opacity: app.glass ? 0.28 : 0.08
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 0.45; color: Qt.rgba(1, 1, 1, 0.10) }
            GradientStop { position: 0.55; color: Qt.rgba(0.6, 1, 0.95, 0.12) }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    Image {
        anchors.fill: parent
        source: NoiseUrl
        fillMode: Image.Tile
        opacity: app.glass ? 0.055 : 0
        smooth: false
    }

    // ================= shell =================
    Item {
        id: shell
        anchors.fill: parent
        visible: app.loggedIn && Settings.onboardingDone

        Rectangle {
            id: sidebar
            width: 224
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            color: app.glass ? Qt.rgba(0.04, 0.11, 0.15, 0.55) : "#0B141B"
            border.width: 1
            border.color: app.glass ? Qt.rgba(0.7, 0.93, 1, 0.10) : "#1E2A33"

            gradient: app.glass ? sidebarGlass : null
            Gradient {
                id: sidebarGlass
                GradientStop { position: 0; color: Qt.rgba(0.5, 0.9, 1, 0.06) }
                GradientStop { position: 1; color: Qt.rgba(0.2, 0.4, 0.6, 0.02) }
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 6
                    Layout.bottomMargin: 14
                    spacing: 10
                    Rectangle {
                        width: 38; height: 38; radius: 11
                        gradient: Gradient {
                            GradientStop { position: 0; color: "#5FE3C8" }
                            GradientStop { position: 1; color: "#3B7BD4" }
                        }
                        Text { anchors.centerIn: parent; text: "琉"; color: "#042027"; font.pixelSize: 19; font.weight: Font.Black }
                    }
                    ColumnLayout {
                        spacing: 1
                        Text { text: app.tr.appName || "LiuliDNS"; color: uiTheme.text; font.pixelSize: 15; font.weight: Font.DemiBold }
                        Text { text: "DNS · TLS CONSOLE"; color: Qt.rgba(0.56,0.7,0.76,0.6); font.pixelSize: 8; font.letterSpacing: 0.6 }
                    }
                }

                Text {
                    Layout.leftMargin: 4
                    Layout.bottomMargin: 4
                    text: "WORKSPACE"
                    color: Qt.rgba(0.56, 0.7, 0.76, 0.45)
                    font.pixelSize: 8
                    font.letterSpacing: 1.2
                }

                Repeater {
                    model: app.navItems
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        height: 42
                        radius: 10
                        color: app.page === modelData.key
                               ? Qt.rgba(0.37, 0.92, 0.82, 0.12)
                               : (navMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.055) : "transparent")
                        border.width: app.page === modelData.key ? 1 : 0
                        border.color: Qt.rgba(0.4, 0.95, 0.83, 0.28)

                        Rectangle {
                            anchors.left: parent.left
                            anchors.leftMargin: 1
                            anchors.verticalCenter: parent.verticalCenter
                            width: 3
                            height: app.page === modelData.key ? 22 : 0
                            radius: 2
                            color: uiTheme.accent
                            Behavior on height { NumberAnimation { duration: 180 } }
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 13
                            anchors.rightMargin: 10
                            spacing: 10
                            Text {
                                text: modelData.icon
                                color: app.page === modelData.key ? uiTheme.accent : Qt.rgba(0.72, 0.85, 0.9, 0.7)
                                font.pixelSize: 14
                                Layout.preferredWidth: 18
                            }
                            Text {
                                text: app.tr[modelData.labelKey] || modelData.key
                                color: app.page === modelData.key ? uiTheme.text : Qt.rgba(0.75, 0.86, 0.9, 0.78)
                                font.pixelSize: 12
                                font.weight: app.page === modelData.key ? Font.DemiBold : Font.Normal
                            }
                        }

                        MouseArea {
                            id: navMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: app.go(modelData.key)
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: Qt.rgba(0.7, 0.93, 1, 0.1)
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 6
                    Rectangle {
                        width: 7; height: 7; radius: 4
                        color: uiTheme.accent
                        SequentialAnimation on opacity {
                            loops: Animation.Infinite
                            NumberAnimation { from: 0.45; to: 1; duration: 1400 }
                            NumberAnimation { from: 1; to: 0.45; duration: 1400 }
                        }
                    }
                    Text {
                        text: app.busy ? (app.tr.loading || "…") : (app.tr.online || "Online")
                        color: uiTheme.muted
                        font.pixelSize: 10
                    }
                    Item { Layout.fillWidth: true }
                    Text { text: "v" + AppVersion; color: Qt.rgba(0.56,0.7,0.76,0.5); font.pixelSize: 8 }
                }

                Text {
                    Layout.fillWidth: true
                    Layout.bottomMargin: 8
                    text: app.tr.onbBoundary || ""
                    color: Qt.rgba(0.56, 0.7, 0.76, 0.45)
                    font.pixelSize: 8
                    wrapMode: Text.Wrap
                    lineHeight: 1.35
                }
            }
        }

        // top bar
        Rectangle {
            id: topbar
            anchors.left: sidebar.right
            anchors.right: parent.right
            anchors.top: parent.top
            height: 66
            color: "transparent"

            Rectangle {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                height: 1
                color: app.glass ? Qt.rgba(0.7, 0.93, 1, 0.09) : "#1E2A33"
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 22
                spacing: 12

                ColumnLayout {
                    spacing: 1
                    Text {
                        text: app.pageTitle()
                        color: uiTheme.text
                        font.pixelSize: 19
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: app.pageSubtitle()
                        color: Qt.rgba(0.56, 0.7, 0.76, 0.6)
                        font.pixelSize: 9
                        elide: Text.ElideRight
                        Layout.maximumWidth: 560
                    }
                }

                Item { Layout.fillWidth: true }

                Rectangle {
                    height: 26
                    radius: 13
                    width: 140
                    color: app.user.realname_status === "active"
                           ? Qt.rgba(0.37, 0.92, 0.82, 0.12) : Qt.rgba(1, 0.82, 0.42, 0.10)
                    border.width: 1
                    border.color: app.user.realname_status === "active"
                                  ? Qt.rgba(0.4, 0.95, 0.83, 0.35) : Qt.rgba(1, 0.82, 0.42, 0.3)
                    Text {
                        id: realLabel
                        anchors.centerIn: parent
                        width: parent.width - 12
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                        text: app.user.realname_status === "active" ? app.tr.dashRealnameActive
                              : app.user.realname_status === "approved" ? app.tr.realApproved
                              : app.user.realname_status === "pending" ? app.tr.realPending
                              : app.tr.dashRealnameNone
                        color: app.user.realname_status === "active" ? "#A8FFEF" : "#FFE7B4"
                        font.pixelSize: 9
                    }
                }

                Rectangle {
                    width: 32; height: 32; radius: 16
                    color: Qt.rgba(0.42, 0.72, 1, 0.14)
                    border.width: 1
                    border.color: Qt.rgba(0.6, 0.85, 1, 0.3)
                    Text {
                        anchors.centerIn: parent
                        text: app.user.email ? app.user.email.charAt(0).toUpperCase() : "?"
                        color: "#CFE8FF"
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }
                }

                ColumnLayout {
                    spacing: 0
                    Text {
                        text: app.user.email || ""
                        color: Qt.rgba(0.78, 0.9, 0.94, 0.85)
                        font.pixelSize: 10
                        elide: Text.ElideMiddle
                        Layout.maximumWidth: 160
                    }
                    Text {
                        text: app.user.user_no || ""
                        color: Qt.rgba(0.56, 0.7, 0.76, 0.55)
                        font.pixelSize: 8
                    }
                }

                AnimatedButton {
                    text: app.tr.logout || "Logout"
                    iconText: "⏻"
                    small: true
                    ghost: true
                    onClicked: Bridge.logout()
                }
            }
        }

        Item {
            id: pageHost
            anchors.left: sidebar.right
            anchors.right: parent.right
            anchors.top: topbar.bottom
            anchors.bottom: parent.bottom
            anchors.margins: 20

            Dashboard {
                anchors.fill: parent
                appRoot: app
                active: app.page === "Dashboard"
                opacity: app.page === "Dashboard" ? 1 : 0
                visible: opacity > 0.01
                enabled: app.page === "Dashboard"
                z: app.page === "Dashboard" ? 2 : 1
                Behavior on opacity { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
            }
            Domains {
                anchors.fill: parent
                appRoot: app
                active: app.page === "Domains"
                opacity: app.page === "Domains" ? 1 : 0
                visible: opacity > 0.01
                enabled: app.page === "Domains"
                z: app.page === "Domains" ? 2 : 1
                Behavior on opacity { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
            }
            Records {
                anchors.fill: parent
                appRoot: app
                active: app.page === "Records"
                opacity: app.page === "Records" ? 1 : 0
                visible: opacity > 0.01
                enabled: app.page === "Records"
                z: app.page === "Records" ? 2 : 1
                Behavior on opacity { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
            }
            Certificates {
                anchors.fill: parent
                appRoot: app
                active: app.page === "Certificates"
                opacity: app.page === "Certificates" ? 1 : 0
                visible: opacity > 0.01
                enabled: app.page === "Certificates"
                z: app.page === "Certificates" ? 2 : 1
                Behavior on opacity { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
            }
            Realname {
                anchors.fill: parent
                appRoot: app
                active: app.page === "Realname"
                opacity: app.page === "Realname" ? 1 : 0
                visible: opacity > 0.01
                enabled: app.page === "Realname"
                z: app.page === "Realname" ? 2 : 1
                Behavior on opacity { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
            }
            Tools {
                anchors.fill: parent
                appRoot: app
                active: app.page === "Tools"
                opacity: app.page === "Tools" ? 1 : 0
                visible: opacity > 0.01
                enabled: app.page === "Tools"
                z: app.page === "Tools" ? 2 : 1
                Behavior on opacity { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
            }
            SettingsPage {
                anchors.fill: parent
                appRoot: app
                active: app.page === "Settings"
                opacity: app.page === "Settings" ? 1 : 0
                visible: opacity > 0.01
                enabled: app.page === "Settings"
                z: app.page === "Settings" ? 2 : 1
                Behavior on opacity { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
            }
        }
    }

    // ================= auth =================
    Auth {
        anchors.fill: parent
        appRoot: app
        visible: !app.loggedIn && Settings.onboardingDone
    }

    // ================= onboarding =================
    Onboarding {
        anchors.fill: parent
        appRoot: app
    }

    // ================= server warning banner =================
    Rectangle {
        id: banner
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 18
        width: Math.min(parent.width - 80, bannerLabel.implicitWidth + 74)
        height: 44
        radius: 12
        color: Qt.rgba(0.24, 0.16, 0.05, 0.95)
        border.width: 1
        border.color: Qt.rgba(1, 0.82, 0.45, 0.45)
        opacity: 0
        visible: opacity > 0.01
        z: 700

        Behavior on opacity { NumberAnimation { duration: 220 } }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 10
            spacing: 8
            Text { text: "!"; color: "#FFD37A"; font.pixelSize: 14; font.weight: Font.Bold }
            Text {
                id: bannerLabel
                Layout.fillWidth: true
                text: app.bannerText
                color: "#FFE7B4"
                font.pixelSize: 10
                wrapMode: Text.Wrap
            }
            Text {
                text: "×"
                color: Qt.rgba(1, 0.9, 0.7, 0.8)
                font.pixelSize: 15
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: banner.opacity = 0
                }
            }
        }
    }

    Timer {
        id: bannerTimer
        interval: 9000
        onTriggered: banner.opacity = 0
    }

    // ================= overlays =================
    Toast { id: toast }

    CrashDialog {
        tr: app.tr
    }
}
