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
    property string output: ""
    property string dnsAnswer: ""
    property string portAnswer: ""
    property bool labRunning: Bridge.labRunning

    readonly property var dnsTypes: ["A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV", "CAA"]

    function logLine(line) {
        var t = new Date().toLocaleTimeString()
        output += "[" + t + "] " + line + "\n"
    }

    function queryDns() {
        if (!dnsName.text.trim()) {
            appRoot.notify(tr.errInvalid, true)
            return
        }
        dnsAnswer = tr.loading
        Bridge.api("tools_dns", "GET",
                   "/tools/dns-check?name=" + encodeURIComponent(dnsName.text.trim())
                   + "&type=" + encodeURIComponent(dnsType.currentText), "{}")
    }

    function checkPort() {
        var p = Number(portField.text)
        if (!appRoot.selectedDomainId || p < 1 || p > 65535) {
            appRoot.notify(tr.errInvalid, true)
            return
        }
        portAnswer = tr.loading
        Bridge.api("tools_port", "POST", "/tools/port-check", JSON.stringify({
            domain_id: appRoot.selectedDomainId, port: p
        }))
    }

    function startLab() {
        var p = Number(labPortField.text)
        if (p < 1024 || p > 65535) {
            appRoot.notify(tr.setInvalidPort, true)
            return
        }
        Settings.labPort = p
        Bridge.startLab(p)
    }

    function hostsLine() {
        var d = root.currentDomain()
        return d ? ("127.0.0.1\t" + d.fqdn + "\t# liuli-local-lab") : ""
    }

    function currentDomain() {
        var ds = appRoot ? appRoot.domains : []
        for (var i = 0; i < ds.length; ++i)
            if (ds[i].id === appRoot.selectedDomainId) return ds[i]
        return null
    }

    Connections {
        target: Bridge
        function onApiResult(action, ok, data, code, message) {
            if (!ok) {
                if (action === "tools_dns") root.dnsAnswer = ""
                if (action === "tools_port") root.portAnswer = ""
                return
            }
            var payload = JSON.parse(data || "{}")
            if (action === "tools_dns") {
                root.dnsAnswer = (payload.answers || []).length > 0
                        ? (payload.answers || []).join("\n")
                        : "NXDOMAIN / NO DATA"
                root.logLine("DNS " + payload.name + " " + payload.type + " → "
                             + (payload.answers || []).join(", "))
            } else if (action === "tools_port") {
                var lines = []
                var results = payload.results || []
                for (var i = 0; i < results.length; ++i) {
                    var r = results[i]
                    lines.push(r.address + ":" + r.port + "  "
                               + (r.reachable ? "OPEN" : "CLOSED") + "  " + (r.latency_ms || 0) + "ms"
                               + (r.error ? " · " + r.error : ""))
                }
                root.portAnswer = lines.join("\n")
                root.logLine("PORT " + payload.domain + " → " + lines.join(" | "))
            }
        }
    }

    Connections {
        target: Bridge
        function onLabChanged(running, port, message) {
            root.labRunning = running
            root.logLine((running ? "LAB START " : "LAB STOP ") + port + " · " + message)
        }
    }

    Component.onCompleted: {
        labPortField.text = String(Settings.labPort)
        logLine("ready · " + Settings.apiBase)
    }

    onActiveChanged: {
        if (active) {
            dnsName.text = root.currentDomain() ? root.currentDomain().fqdn : ""
        }
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
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    spacing: 2
                    Text { text: root.tr.toolsTitle; color: uiTheme.text; font.pixelSize: 24; font.weight: Font.DemiBold }
                    Text { text: root.tr.toolsLocalHint; color: uiTheme.muted; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.maximumWidth: 640 }
                }
                Item { Layout.fillWidth: true }
                StatusPill { text: root.labRunning ? root.tr.online : root.tr.offline; tone: root.labRunning ? "ok" : "muted" }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 16

                GlassCard {
                    Layout.fillWidth: true
                    height: 244
                    pad: 18
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 8
                        Text { text: root.tr.toolsDns; color: uiTheme.text; font.pixelSize: 15; font.weight: Font.DemiBold }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            TxField {
                                id: dnsName
                                Layout.fillWidth: true
                                label: root.tr.toolsName
                                placeholder: "example.com"
                            }
                            ColumnLayout {
                                Layout.preferredWidth: 92
                                spacing: 6
                                Text { text: root.tr.toolsType; color: uiTheme.muted; font.pixelSize: 11 }
                                MiniCombo {
                                    id: dnsType
                                    Layout.fillWidth: true
                                    model: root.dnsTypes
                                    Component.onCompleted: currentIndex = 0
                                }
                            }
                        }

                        AnimatedButton {
                            text: root.tr.toolsQuery
                            primary: true
                            small: true
                            onClicked: root.queryDns()
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 8
                            color: Qt.rgba(0, 0, 0, 0.2)
                            TextArea {
                                anchors.fill: parent
                                anchors.margins: 8
                                readOnly: true
                                text: root.dnsAnswer
                                color: "#CFFFF8"
                                font.family: "Consolas"
                                font.pixelSize: 11
                                wrapMode: TextArea.Wrap
                                background: null
                            }
                        }
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    height: 244
                    pad: 18
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 8
                        Text { text: root.tr.toolsPort; color: uiTheme.text; font.pixelSize: 15; font.weight: Font.DemiBold }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            DomainPicker {
                                Layout.fillWidth: true
                                domains: appRoot.domains
                                currentId: appRoot.selectedDomainId
                                onPicked: function(domainId) { appRoot.selectedDomainId = domainId }
                            }
                            TxField {
                                id: portField
                                Layout.preferredWidth: 96
                                text: "443"
                                inputMethodHints: Qt.ImhDigitsOnly
                            }
                        }

                        AnimatedButton {
                            text: root.tr.toolsCheck
                            primary: true
                            small: true
                            onClicked: root.checkPort()
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 8
                            color: Qt.rgba(0, 0, 0, 0.2)
                            TextArea {
                                anchors.fill: parent
                                anchors.margins: 8
                                readOnly: true
                                text: root.portAnswer
                                color: "#CFFFF8"
                                font.family: "Consolas"
                                font.pixelSize: 11
                                wrapMode: TextArea.Wrap
                                background: null
                            }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 16

                GlassCard {
                    Layout.fillWidth: true
                    height: 204
                    pad: 18
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 8
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: root.tr.toolsLocal; color: uiTheme.text; font.pixelSize: 15; font.weight: Font.DemiBold }
                            Item { Layout.fillWidth: true }
                            Rectangle {
                                width: 8; height: 8; radius: 4
                                color: root.labRunning ? uiTheme.accent : uiTheme.muted
                                opacity: root.labRunning ? 0.95 : 0.4
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: root.tr.toolsLocalHint
                            color: uiTheme.muted
                            font.pixelSize: 10
                            wrapMode: Text.Wrap
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            TxField {
                                id: labPortField
                                Layout.preferredWidth: 120
                                label: root.tr.toolsLocalPort
                                inputMethodHints: Qt.ImhDigitsOnly
                            }
                            AnimatedButton {
                                text: root.labRunning ? root.tr.toolsLocalStop : root.tr.toolsLocalStart
                                primary: !root.labRunning
                                small: true
                                onClicked: root.labRunning ? Bridge.stopLab() : root.startLab()
                            }
                            AnimatedButton {
                                text: root.tr.toolsFirewall
                                small: true
                                ghost: true
                                onClicked: Bridge.applyFirewall(Number(labPortField.text))
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: root.tr.toolsFirewallHint
                            color: Qt.rgba(0.56,0.7,0.76,0.6)
                            font.pixelSize: 9
                            wrapMode: Text.Wrap
                        }
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    height: 204
                    pad: 18
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 8
                        Text { text: root.tr.toolsHosts; color: uiTheme.text; font.pixelSize: 15; font.weight: Font.DemiBold }
                        Text {
                            Layout.fillWidth: true
                            text: root.tr.toolsLocalHint
                            color: uiTheme.muted
                            font.pixelSize: 10
                            wrapMode: Text.Wrap
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            height: 44
                            radius: 8
                            color: Qt.rgba(0, 0, 0, 0.2)
                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: 9
                                verticalAlignment: Text.AlignVCenter
                                text: root.hostsLine()
                                color: "#CFFFF8"
                                font.family: "Consolas"
                                font.pixelSize: 10
                                elide: Text.ElideMiddle
                            }
                        }
                        AnimatedButton {
                            text: root.tr.toolsCopyHosts
                            small: true
                            onClicked: Bridge.copyText(root.hostsLine())
                        }
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                height: 166
                pad: 16
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 6
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: root.tr.toolsLog; color: uiTheme.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                        Item { Layout.fillWidth: true }
                        AnimatedButton {
                            text: root.tr.copy
                            small: true
                            ghost: true
                            onClicked: Bridge.copyText(root.output)
                        }
                        AnimatedButton {
                            text: "×"
                            small: true
                            ghost: true
                            onClicked: root.output = ""
                        }
                    }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        TextArea {
                            readOnly: true
                            text: root.output
                            color: "#A9D5DF"
                            font.family: "Consolas"
                            font.pixelSize: 10
                            wrapMode: TextArea.NoWrap
                            background: Rectangle {
                                radius: 8
                                color: Qt.rgba(0, 0, 0, 0.2)
                            }
                        }
                    }
                }
            }

            Item { height: 6 }
        }
    }
}
