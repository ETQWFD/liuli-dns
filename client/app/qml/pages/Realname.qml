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

    property var statusData: ({})
    property string status: ""
    property string docType: "id_card"
    property string rejectReason: ""

    function load() {
        Bridge.api("realname_status", "GET", "/realname/status", "{}")
    }

    function submit() {
        var doc = docNumber.text.trim()
        if (!doc) {
            appRoot.notify(tr.errInvalid, true)
            return
        }
        Bridge.api("realname_submit", "POST", "/realname/submissions", JSON.stringify({
            doc_type: root.docType, doc_number: doc
        }))
    }

    function activate() {
        var code = codeField.text.trim()
        if (!code) {
            appRoot.notify(tr.errInvalid, true)
            return
        }
        Bridge.api("realname_activate", "POST", "/realname/activate", JSON.stringify({ code: code }))
    }

    function statusLabel() {
        if (status === "active") return tr.realActive
        if (status === "approved") return tr.realApproved
        if (status === "pending") return tr.realPending
        if (status === "rejected") return tr.realRejected
        return tr.realNone
    }

    function statusTone() {
        if (status === "active") return "ok"
        if (status === "approved") return "warn"
        if (status === "pending") return "warn"
        if (status === "rejected") return "bad"
        return "muted"
    }

    Connections {
        target: Bridge
        function onApiResult(action, ok, data, code, message) {
            if (!ok) return
            if (action === "realname_status" || action === "realname_submit" || action === "realname_activate") {
                var payload = JSON.parse(data || "{}")
                root.statusData = payload
                root.status = payload.status || root.status
                root.rejectReason = payload.reject_reason || ""
                if (action === "realname_submit") {
                    root.docNumber.text = ""
                    appRoot.notify(root.tr.toastSaved, false)
                } else if (action === "realname_activate") {
                    root.codeField.text = ""
                    Bridge.refreshMe()
                    appRoot.notify(root.tr.toastActivated, false)
                }
            }
        }
    }

    onActiveChanged: if (active) load()

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                spacing: 2
                Text { text: root.tr.realTitle; color: uiTheme.text; font.pixelSize: 24; font.weight: Font.DemiBold }
                Text { text: root.tr.realBoundary; color: uiTheme.muted; font.pixelSize: 10 }
            }
            Item { Layout.fillWidth: true }
            StatusPill { text: root.statusLabel(); tone: root.statusTone() }
            AnimatedButton { text: root.tr.refresh; small: true; ghost: true; onClicked: root.load() }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16

            GlassCard {
                Layout.fillWidth: true
                Layout.fillHeight: true
                pad: 22

                ScrollView {
                    anchors.fill: parent
                    clip: true
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                    ColumnLayout {
                        width: parent.width
                        spacing: 14

                        Text { text: root.tr.realStatus; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                        RowLayout {
                            spacing: 10
                            StatusPill { text: root.statusLabel(); tone: root.statusTone() }
                            Text {
                                text: root.status === "active" && root.statusData.activated_at
                                      ? root.statusData.activated_at.replace("T", " ").slice(0, 16) : ""
                                color: uiTheme.muted
                                font.pixelSize: 10
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.status === "active"
                                  ? root.tr.dashRealnameActive
                                  : root.status === "pending" ? root.tr.toastCodeSent
                                  : root.status === "rejected" ? (root.tr.realRejected + " · " + root.rejectReason)
                                  : root.tr.realHint
                            color: root.status === "rejected" ? uiTheme.warning : uiTheme.muted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                            lineHeight: 1.5
                        }

                        Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(0.7,0.93,1,0.12) }

                        Text { text: root.tr.realInstructions; color: uiTheme.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                        Repeater {
                            model: root.statusData.instructions || []
                            delegate: Text {
                                required property var modelData
                                Layout.fillWidth: true
                                text: modelData
                                color: uiTheme.muted
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                                lineHeight: 1.5
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            height: inboxColumn.implicitHeight + 24
                            radius: 10
                            color: Qt.rgba(0.4, 0.92, 0.82, 0.07)
                            border.width: 1
                            border.color: Qt.rgba(0.4, 0.92, 0.82, 0.22)

                            ColumnLayout {
                                id: inboxColumn
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 4
                                Text { text: root.tr.realInbox; color: uiTheme.muted; font.pixelSize: 10 }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        Layout.fillWidth: true
                                        text: root.statusData.inbox || ""
                                        color: "#BFF9EF"
                                        font.family: "Consolas"
                                        font.pixelSize: 12
                                    }
                                    AnimatedButton {
                                        text: root.tr.copy
                                        small: true
                                        ghost: true
                                        onClicked: Bridge.copyText(root.statusData.inbox || "")
                                    }
                                }
                            }
                        }

                        Item { Layout.fillHeight: true }
                        Text {
                            Layout.fillWidth: true
                            text: root.tr.realHint
                            color: Qt.rgba(0.56,0.7,0.76,0.6)
                            font.pixelSize: 9
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }

            GlassCard {
                Layout.preferredWidth: 430
                Layout.fillHeight: true
                pad: 24

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 12

                    // active success
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        visible: root.status === "active"
                        Rectangle {
                            width: 54; height: 54; radius: 16
                            color: Qt.rgba(0.37, 0.92, 0.82, 0.16)
                            Text { anchors.centerIn: parent; text: "✓"; color: uiTheme.accent; font.pixelSize: 24; font.weight: Font.Bold }
                        }
                        Text { text: root.tr.dashRealnameActive; color: uiTheme.accent; font.pixelSize: 20; font.weight: Font.DemiBold }
                        Text {
                            Layout.fillWidth: true
                            text: root.tr.realBoundary
                            color: uiTheme.muted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                            lineHeight: 1.5
                        }
                        Text {
                            text: root.statusData.activated_at ? root.statusData.activated_at.replace("T", " ").slice(0, 16) : ""
                            color: Qt.rgba(0.56,0.7,0.76,0.7)
                            font.pixelSize: 10
                        }
                    }

                    // submission form
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        visible: root.status !== "active"
                        Text { text: root.tr.realSubmit; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                        Text { text: root.tr.realDocType; color: uiTheme.muted; font.pixelSize: 10 }
                        MiniCombo {
                            Layout.fillWidth: true
                            model: [
                                { key: "id_card", label: root.tr.realIdCard },
                                { key: "passport", label: root.tr.realPassport }
                            ]
                            textRole: "label"
                            valueRole: "key"
                            onActivated: root.docType = currentValue
                            Component.onCompleted: currentIndex = 0
                        }
                        TxField {
                            id: docNumber
                            Layout.fillWidth: true
                            label: root.tr.realDocNumber
                            placeholder: "••••••••••••••1234"
                            enabled: root.status !== "pending"
                        }
                        AnimatedButton {
                            Layout.fillWidth: true
                            text: root.tr.realSubmit
                            primary: true
                            enabled: root.status !== "pending" && root.status !== "approved"
                            onClicked: root.submit()
                        }

                        Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(0.7,0.93,1,0.12) }

                        Text { text: root.tr.realActivate; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                        Text {
                            Layout.fillWidth: true
                            text: root.tr.realBoundary
                            color: uiTheme.muted
                            font.pixelSize: 9
                            wrapMode: Text.Wrap
                        }
                        TxField {
                            id: codeField
                            Layout.fillWidth: true
                            label: root.tr.realCode
                            placeholder: "XXXX-XXXX-XXXX"
                            enabled: root.status === "approved"
                        }
                        AnimatedButton {
                            Layout.fillWidth: true
                            text: root.tr.realActivateBtn
                            primary: root.status === "approved"
                            enabled: root.status === "approved"
                            onClicked: root.activate()
                        }
                    }

                    Item { Layout.fillHeight: true }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 64
                        radius: 10
                        color: Qt.rgba(1, 0.82, 0.42, 0.06)
                        border.width: 1
                        border.color: Qt.rgba(1, 0.82, 0.42, 0.2)
                        Text {
                            anchors.fill: parent
                            anchors.margins: 10
                            text: "One-time code · HMAC-SHA256 · bound to user_no\n" + root.tr.realHint
                            color: Qt.rgba(1, 0.9, 0.7, 0.75)
                            font.pixelSize: 9
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
    }
}
