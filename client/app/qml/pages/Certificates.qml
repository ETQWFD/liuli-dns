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
    property bool submitting: false
    property int requested: 0

    property string certPath: ""
    property string keyPath: ""
    property string chainPath: ""
    property var pendingDelete: null

    ListModel { id: certModel }

    function load() {
        if (!appRoot || !appRoot.selectedDomainId) {
            certModel.clear()
            return
        }
        requested = appRoot.selectedDomainId
        Bridge.api("certs", "GET", "/domains/" + requested + "/certificates", "{}")
    }

    function upload() {
        if (!appRoot.selectedDomainId) {
            appRoot.notify(tr.errDomain, true)
            return
        }
        if (!certPath || !keyPath) {
            appRoot.notify(tr.errCert + " · " + tr.certFile + " / " + tr.certKey, true)
            return
        }
        submitting = true
        Bridge.uploadCertificate(appRoot.selectedDomainId, certPath, keyPath, chainPath)
    }

    function activate(id) {
        Bridge.api("cert_activate", "POST",
                   "/domains/" + appRoot.selectedDomainId + "/certificates/" + id + "/activate", "{}")
    }

    function remove(id) {
        Bridge.api("cert_delete", "DELETE",
                   "/domains/" + appRoot.selectedDomainId + "/certificates/" + id, "{}")
    }

    Connections {
        target: appRoot
        function onSelectedDomainIdChanged() { if (root.active) root.load() }
    }

    Connections {
        target: Bridge
        function onApiResult(action, ok, data, code, message) {
            if (action === "cert_upload") root.submitting = false
            if (!ok) return
            if (action === "certs") {
                if (root.requested !== appRoot.selectedDomainId) return
                var payload = JSON.parse(data || "{}")
                certModel.clear()
                var items = payload.items || []
                for (var i = 0; i < items.length; ++i) {
                    var it = items[i]
                    certModel.append({
                        id: it.id, common_name: it.common_name,
                        sans_text: (it.sans || []).join(", "),
                        serial: it.serial, fingerprint_sha256: it.fingerprint_sha256,
                        not_before: it.not_before, not_after: it.not_after,
                        status: it.status, source: it.source, created_at: it.created_at,
                        days_left: it.days_left
                    })
                }
            } else if (action === "cert_upload") {
                root.certPath = ""
                root.keyPath = ""
                root.chainPath = ""
                root.load()
                appRoot.notify(root.tr.toastUploaded, false)
            } else if (action === "cert_activate") {
                root.load()
                appRoot.notify(root.tr.toastActivated, false)
            } else if (action === "cert_delete") {
                root.load()
                appRoot.notify(root.tr.toastDeleted, false)
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
                Text { text: root.tr.certTitle; color: uiTheme.text; font.pixelSize: 24; font.weight: Font.DemiBold }
                Text { text: root.tr.certKeyNote; color: uiTheme.muted; font.pixelSize: 10 }
            }
            Item { Layout.fillWidth: true }
            DomainPicker {
                Layout.preferredWidth: 210
                domains: appRoot.domains
                currentId: appRoot.selectedDomainId
                onPicked: function(domainId) { appRoot.selectedDomainId = domainId }
            }
            AnimatedButton { text: root.tr.refresh; small: true; ghost: true; onClicked: root.load() }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16

            GlassCard {
                Layout.fillWidth: true
                Layout.fillHeight: true
                pad: 16

                ListView {
                    id: certList
                    anchors.fill: parent
                    clip: true
                    spacing: 10
                    model: certModel
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {}

                    delegate: Rectangle {
                        width: certList.width
                        height: 154
                        radius: 12
                        color: Qt.rgba(1, 1, 1, 0.04)
                        border.width: 1
                        border.color: model.status === "active"
                                      ? Qt.rgba(0.4, 0.95, 0.83, 0.3)
                                      : Qt.rgba(1, 1, 1, 0.09)

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: model.common_name
                                    color: uiTheme.text
                                    font.pixelSize: 14
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                                StatusPill {
                                    text: model.status === "active" ? root.tr.certActive
                                          : model.status === "replaced" ? root.tr.certReplaced : model.status
                                    tone: model.status === "active" ? "ok"
                                          : model.status === "replaced" ? "muted" : "bad"
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12
                                Text {
                                    text: root.tr.certExpires + "  " + (model.not_after || "").replace("T", " ").slice(0, 16)
                                    color: uiTheme.muted
                                    font.pixelSize: 10
                                }
                                Text {
                                    text: root.tr.certDays + "  " + model.days_left
                                    color: model.days_left <= 30 ? uiTheme.warning : uiTheme.accent
                                    font.pixelSize: 10
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: root.tr.certSans + "  " + (model.sans_text || "")
                                color: Qt.rgba(0.7, 0.86, 0.9, 0.8)
                                font.pixelSize: 10
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: root.tr.certFingerprint + "  " + (model.fingerprint_sha256 || "")
                                color: Qt.rgba(0.56, 0.7, 0.76, 0.7)
                                font.pixelSize: 9
                                elide: Text.ElideMiddle
                            }

                            Item { Layout.fillHeight: true }

                            RowLayout {
                                Layout.fillWidth: true
                                Item { Layout.fillWidth: true }
                                AnimatedButton {
                                    text: root.tr.certActivate
                                    small: true
                                    visible: model.status !== "active"
                                    onClicked: root.activate(model.id)
                                }
                                AnimatedButton {
                                    text: root.tr.certDelete
                                    small: true
                                    danger: true
                                    onClicked: {
                                        root.pendingDelete = modelData
                                        deleteDialog.open()
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: certModel.count === 0
                        text: root.tr.certEmpty
                        color: uiTheme.muted
                        font.pixelSize: 12
                    }
                }
            }

            GlassCard {
                Layout.preferredWidth: 400
                Layout.fillHeight: true
                pad: 20

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 10

                    Text { text: root.tr.certUpload; color: uiTheme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Text {
                        Layout.fillWidth: true
                        text: root.tr.certKeyNote
                        color: uiTheme.muted
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                        lineHeight: 1.45
                    }

                    FilePicker {
                        Layout.fillWidth: true
                        label: root.tr.certFile
                        filter: "Certificate (*.pem *.crt *.cer *.txt)"
                        onPicked: function(url) { root.certPath = url }
                    }
                    FilePicker {
                        Layout.fillWidth: true
                        label: root.tr.certKey
                        filter: "Private key (*.pem *.key *.txt)"
                        onPicked: function(url) { root.keyPath = url }
                    }
                    FilePicker {
                        Layout.fillWidth: true
                        label: root.tr.certChain
                        filter: "Chain (*.pem *.crt *.txt)"
                        onPicked: function(url) { root.chainPath = url }
                    }

                    AnimatedButton {
                        Layout.fillWidth: true
                        Layout.topMargin: 4
                        text: root.tr.certUploadBtn
                        primary: true
                        enabled: !root.submitting
                        onClicked: root.upload()
                    }

                    Item { Layout.fillHeight: true }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 76
                        radius: 10
                        color: Qt.rgba(0.49, 0.66, 1, 0.06)
                        border.width: 1
                        border.color: Qt.rgba(0.49, 0.66, 1, 0.2)
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 2
                            Text { text: "AES-256-GCM"; color: "#CBDCFF"; font.pixelSize: 10; font.weight: Font.DemiBold }
                            Text {
                                Layout.fillWidth: true
                                text: root.tr.certNoKey
                                color: Qt.rgba(0.75, 0.82, 0.95, 0.75)
                                font.pixelSize: 9
                                wrapMode: Text.Wrap
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "ACME: DNS-01 → upload PEM. " + root.tr.setBoundary
                        color: Qt.rgba(0.56, 0.7, 0.76, 0.55)
                        font.pixelSize: 8
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }

    Dialog {
        id: deleteDialog
        modal: true
        width: 420
        height: 200
        padding: 22

        background: Rectangle {
            radius: 16
            color: "#170E12"
            border.width: 1
            border.color: Qt.rgba(1, 0.55, 0.55, 0.4)
        }

        contentItem: ColumnLayout {
            spacing: 12
            Text { text: root.tr.certDelete; color: "#FFDADA"; font.pixelSize: 17; font.weight: Font.DemiBold }
            Text {
                Layout.fillWidth: true
                text: root.pendingDelete ? root.pendingDelete.common_name : ""
                color: uiTheme.muted
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }
            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                AnimatedButton { text: root.tr.cancel; onClicked: deleteDialog.close() }
                AnimatedButton {
                    text: root.tr.delete
                    danger: true
                    onClicked: {
                        deleteDialog.close()
                        if (root.pendingDelete) root.remove(root.pendingDelete.id)
                    }
                }
            }
        }
    }
}
