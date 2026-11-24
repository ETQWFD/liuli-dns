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
    property string activateError: ""

    function load() {
        Bridge.api("realname_status", "GET", "/realname/status", "{}")
    }

    function userNo() {
        var no = root.statusData.user_no || ""
        if (!no && root.appRoot && root.appRoot.user) no = root.appRoot.user.user_no || ""
        return no
    }

    function copyNo() {
        var no = root.userNo()
        if (no) Bridge.copyText(no)
    }

    function submit() {
        // The reviewer only needs the user number and the ID photos sent to
        // the review mailbox. No full document number is required in the app.
        Bridge.api("realname_submit", "POST", "/realname/submissions", JSON.stringify({
            doc_type: "id_card"
        }))
    }

    function activate() {
        var code = codeField.text.trim()
        if (!code) {
            root.activateError = tr.errInvalid
            return
        }
        root.activateError = ""
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
            if (action !== "realname_status" && action !== "realname_submit"
                    && action !== "realname_activate") return
            if (!ok) {
                root.activateError = message || ""
                return
            }
            var payload = JSON.parse(data || "{}")
            root.statusData = payload
            root.status = payload.status || root.status
            root.activateError = ""
            if (action === "realname_submit") {
                appRoot.notify(root.tr.toastSaved, false)
            } else if (action === "realname_activate") {
                // The activate endpoint returns a short success message, not the
                // full status object. Reflect success immediately and then
                // reload status so activated_at/instructions stay accurate.
                root.codeField.text = ""
                root.status = "active"
                root.statusData = Object.assign({}, root.statusData, {status: "active"})
                root.load()
                Bridge.refreshMe()
                appRoot.notify(root.tr.toastActivated, false)
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
                Text { text: root.tr.realBoundary; color: uiTheme.muted; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.fillWidth: true }
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
                    contentWidth: availableWidth
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
                                  : root.status === "approved" ? root.tr.realApprovedWaitCode
                                  : root.status === "rejected" ? (root.tr.realRejected + " · " + (root.statusData.reject_reason || ""))
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
                                lineHeight: 1.55
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
                                        text: root.statusData.inbox || "2416444244@qq.com"
                                        color: "#BFF9EF"
                                        font.family: "Consolas"
                                        font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                    }
                                    AnimatedButton {
                                        text: root.tr.copy
                                        small: true
                                        ghost: true
                                        onClicked: Bridge.copyText(root.statusData.inbox || "2416444244@qq.com")
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
                Layout.preferredWidth: 470
                Layout.fillHeight: true
                pad: 22

                ScrollView {
                    anchors.fill: parent
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                    ColumnLayout {
                        width: parent.width
                        spacing: 12

                        // 1) Activation code is above the user number, as requested.
                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: root.status !== "active"
                            spacing: 10
                            Text { text: root.tr.realCodeTitle; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                            Text {
                                Layout.fillWidth: true
                                text: root.tr.realCodeHint
                                color: uiTheme.muted
                                font.pixelSize: 10
                                wrapMode: Text.Wrap
                                lineHeight: 1.5
                            }
                            TxField {
                                id: codeField
                                Layout.fillWidth: true
                                label: root.tr.realCode
                                placeholder: "XXXX-XXXX-XXXX"
                            }
                            AnimatedButton {
                                Layout.fillWidth: true
                                text: root.tr.realActivateBtn
                                primary: true
                                onClicked: root.activate()
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: root.activateError !== ""
                                text: root.activateError
                                color: uiTheme.warning
                                font.pixelSize: 10
                                wrapMode: Text.Wrap
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true; height: 1
                            visible: root.status !== "active"
                            color: Qt.rgba(0.7,0.93,1,0.12)
                        }

                        // 2) The user number that must be copied and sent with the ID photos.
                        Text { text: root.tr.realMyNumber; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                        Rectangle {
                            Layout.fillWidth: true
                            height: 58
                            radius: 10
                            color: Qt.rgba(0.4, 0.92, 0.82, 0.08)
                            border.width: 1
                            border.color: Qt.rgba(0.4, 0.92, 0.82, 0.28)
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 12
                                Text {
                                    Layout.fillWidth: true
                                    text: root.userNo() || "—"
                                    color: "#BFF9EF"
                                    font.family: "Consolas"
                                    font.pixelSize: 18
                                    font.weight: Font.DemiBold
                                }
                                AnimatedButton {
                                    text: root.tr.realCopyNo
                                    small: true
                                    primary: true
                                    onClicked: root.copyNo()
                                }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: root.status !== "active"
                            text: root.tr.realNoNumber
                            color: uiTheme.warning
                            font.pixelSize: 10
                            wrapMode: Text.Wrap
                            lineHeight: 1.5
                        }

                        Rectangle {
                            Layout.fillWidth: true; height: 1
                            visible: root.status !== "active"
                            color: Qt.rgba(0.7,0.93,1,0.12)
                        }

                        // 3) Email review instructions with the fixed inbox.
                        Text {
                            visible: root.status !== "active"
                            text: root.tr.realEmailTitle
                            color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: root.status !== "active"
                            text: root.tr.realEmailSteps
                            color: uiTheme.muted
                            font.pixelSize: 10
                            wrapMode: Text.Wrap
                            lineHeight: 1.55
                        }

                        AnimatedButton {
                            Layout.fillWidth: true
                            visible: root.status !== "pending" && root.status !== "approved" && root.status !== "active"
                            text: root.tr.realSubmitAfterEmail
                            onClicked: root.submit()
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: root.status === "pending"
                            text: root.tr.realWait
                            color: uiTheme.warning
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: root.status === "approved"
                            text: root.tr.realApprovedWaitCode
                            color: uiTheme.accent
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }
                        // 4) Privacy promise.
                        Rectangle {
                            Layout.fillWidth: true
                            visible: root.status !== "active"
                            height: privacyText.implicitHeight + 24
                            radius: 10
                            color: Qt.rgba(1, 0.82, 0.42, 0.06)
                            border.width: 1
                            border.color: Qt.rgba(1, 0.82, 0.42, 0.2)
                            Text {
                                id: privacyText
                                anchors.fill: parent
                                anchors.margins: 12
                                text: root.tr.realPrivacy
                                color: Qt.rgba(1, 0.9, 0.7, 0.85)
                                font.pixelSize: 10
                                wrapMode: Text.Wrap
                                lineHeight: 1.5
                            }
                        }

                        // Active success block.
                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: root.status === "active"
                            spacing: 8
                            Rectangle {
                                width: 54; height: 54; radius: 16
                                color: Qt.rgba(0.37, 0.92, 0.82, 0.16)
                                Text { anchors.centerIn: parent; text: "✓"; color: uiTheme.accent; font.pixelSize: 24; font.weight: Font.Bold }
                            }
                            Text { text: root.tr.dashRealnameActive; color: uiTheme.accent; font.pixelSize: 18; font.weight: Font.DemiBold }
                            Text { text: root.tr.realLifetime; color: uiTheme.muted; font.pixelSize: 10 }
                        }
                    }
                }
            }
        }
    }
}
