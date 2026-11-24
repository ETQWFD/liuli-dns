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
    property int version: 0
    property int requested: 0

    readonly property var recordTypes: ["A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV", "CAA"]

    ListModel { id: recModel }
    property var versionLabels: []
    property var versionValues: []

    function load() {
        if (!appRoot || !appRoot.selectedDomainId) {
            recModel.clear()
            versionLabels = []
            versionValues = []
            return
        }
        requested = appRoot.selectedDomainId
        Bridge.api("records", "GET", "/domains/" + requested + "/records", "{}")
        Bridge.api("revisions", "GET", "/domains/" + requested + "/revisions", "{}")
    }

    function fillRecords(items) {
        recModel.clear()
        for (var i = 0; i < items.length; ++i) {
            var r = items[i]
            recModel.append({
                name: r.name || "@", type: r.type || "A",
                ttl: String(r.ttl || 300), value: r.value || "",
                priority: r.priority === null || r.priority === undefined ? "" : String(r.priority)
            })
        }
    }

    function addRow() {
        recModel.append({ name: "@", type: "A", ttl: "300", value: "", priority: "" })
    }

    function save() {
        if (!appRoot.selectedDomainId) {
            appRoot.notify(tr.errDomain, true)
            return
        }
        var arr = []
        for (var i = 0; i < recModel.count; ++i) {
            var r = recModel.get(i)
            if (!r.value || !String(r.value).trim()) {
                appRoot.notify(tr.errInvalid + " · " + tr.recValue, true)
                return
            }
            var pri = r.priority
            arr.push({
                name: String(r.name || "@").trim(),
                type: r.type || "A",
                ttl: Math.max(60, Math.min(86400, Number(r.ttl) || 300)),
                value: String(r.value).trim(),
                priority: (pri === "" || pri === null || pri === undefined) ? null : Number(pri)
            })
        }
        Bridge.api("records_batch", "POST", "/domains/" + appRoot.selectedDomainId + "/records/batch",
                   JSON.stringify({ records: arr, mode: "replace", reason: "apply" }))
    }

    function rollback() {
        if (versionCombo.currentIndex < 0 || !appRoot.selectedDomainId) return
        var v = root.versionValues[versionCombo.currentIndex]
        Bridge.api("rollback", "POST",
                   "/domains/" + appRoot.selectedDomainId + "/records/rollback/" + v, "{}")
    }

    Connections {
        target: appRoot
        function onSelectedDomainIdChanged() { if (root.active) root.load() }
        function onDomainsChanged() { if (root.active && appRoot.selectedDomainId) root.load() }
    }

    Connections {
        target: Bridge
        function onApiResult(action, ok, data, code, message) {
            if (!ok) return
            var payload = JSON.parse(data || "{}")
            if (action === "records") {
                if (root.requested !== appRoot.selectedDomainId) return
                root.version = payload.version || 0
                root.fillRecords(payload.items || [])
            } else if (action === "revisions") {
                if (root.requested !== appRoot.selectedDomainId) return
                var revs = payload.items || []
                var labels = []
                var values = []
                for (var i = 0; i < revs.length; ++i) {
                    values.push(revs[i].version)
                    labels.push("v" + revs[i].version + " · " + (revs[i].reason || "apply"))
                }
                root.versionValues = values
                root.versionLabels = labels
            } else if (action === "records_batch") {
                root.version = payload.version || root.version + 1
                root.fillRecords(payload.items || [])
                appRoot.notify(root.tr.recSaved, false)
                root.load()
            } else if (action === "rollback") {
                root.version = payload.version || root.version
                root.fillRecords(payload.items || [])
                appRoot.notify(root.tr.toastSaved, false)
                root.load()
            }
        }
    }

    onActiveChanged: if (active) load()

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            ColumnLayout {
                spacing: 2
                Text { text: root.tr.recTitle; color: uiTheme.text; font.pixelSize: 24; font.weight: Font.DemiBold }
                Text {
                    text: root.tr.recHint
                    color: uiTheme.muted
                    font.pixelSize: 10
                    wrapMode: Text.Wrap
                    Layout.maximumWidth: 520
                }
            }
            Item { Layout.fillWidth: true }
            DomainPicker {
                Layout.preferredWidth: 210
                domains: appRoot.domains
                currentId: appRoot.selectedDomainId
                onPicked: function(domainId) { appRoot.selectedDomainId = domainId }
            }
            Rectangle {
                width: 1; height: 28
                color: Qt.rgba(0.7,0.93,1,0.14)
            }
            Text {
                text: root.tr.recVersion + " " + root.version
                color: uiTheme.accent
                font.pixelSize: 11
            }
            AnimatedButton {
                text: root.tr.refresh
                small: true
                ghost: true
                onClicked: root.load()
            }
            AnimatedButton {
                text: root.tr.recAdd
                iconText: "+"
                small: true
                onClicked: root.addRow()
            }
            AnimatedButton {
                text: root.tr.recSave
                primary: true
                small: true
                onClicked: root.save()
            }
        }

        GlassCard {
            Layout.fillWidth: true
            Layout.fillHeight: true
            pad: 14

            ColumnLayout {
                anchors.fill: parent
                spacing: 8

                // table header
                Rectangle {
                    Layout.fillWidth: true
                    height: 32
                    radius: 8
                    color: Qt.rgba(1, 1, 1, 0.045)

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 8
                        spacing: 8
                        Text { text: root.tr.recName;  color: uiTheme.muted; font.pixelSize: 10; Layout.preferredWidth: 130 }
                        Text { text: root.tr.recType;  color: uiTheme.muted; font.pixelSize: 10; Layout.preferredWidth: 92 }
                        Text { text: root.tr.recTtl;   color: uiTheme.muted; font.pixelSize: 10; Layout.preferredWidth: 74 }
                        Text { text: "MX";             color: uiTheme.muted; font.pixelSize: 10; Layout.preferredWidth: 58 }
                        Text { text: root.tr.recValue; color: uiTheme.muted; font.pixelSize: 10; Layout.fillWidth: true }
                        Item { Layout.preferredWidth: 30 }
                    }
                }

                ListView {
                    id: recordList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 6
                    model: recModel
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {}

                    delegate: Rectangle {
                        required property int index
                        required property string name
                        required property string type
                        required property string ttl
                        required property string value
                        required property string priority
                        width: recordList.width
                        height: 40
                        radius: 8
                        color: rowMouse.containsMouse ? Qt.rgba(1,1,1,0.045) : "transparent"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 2
                            anchors.rightMargin: 2
                            spacing: 8

                            MiniField {
                                Layout.preferredWidth: 130
                                text: name
                                onTextEdited: recModel.setProperty(index, "name", text)
                            }
                            MiniCombo {
                                Layout.preferredWidth: 92
                                model: root.recordTypes
                                currentIndex: Math.max(0, root.recordTypes.indexOf(type))
                                onActivated: recModel.setProperty(index, "type", currentText)
                            }
                            MiniField {
                                Layout.preferredWidth: 74
                                text: ttl
                                inputMethodHints: Qt.ImhDigitsOnly
                                onTextEdited: recModel.setProperty(index, "ttl", text)
                            }
                            MiniField {
                                Layout.preferredWidth: 58
                                text: priority
                                inputMethodHints: Qt.ImhDigitsOnly
                                onTextEdited: recModel.setProperty(index, "priority", text)
                            }
                            MiniField {
                                Layout.fillWidth: true
                                text: value
                                placeholderText: "203.0.113.10 / target.example.com / text"
                                onTextEdited: recModel.setProperty(index, "value", text)
                            }
                            AnimatedButton {
                                Layout.preferredWidth: 30
                                text: "×"
                                small: true
                                ghost: true
                                onClicked: recModel.remove(index)
                            }
                        }

                        MouseArea {
                            id: rowMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.NoButton
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: recModel.count === 0
                        text: root.tr.recEmpty
                        color: uiTheme.muted
                        font.pixelSize: 12
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 46
                    radius: 9
                    color: Qt.rgba(0, 0, 0, 0.16)

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        spacing: 8
                        Text { text: root.tr.recHistory; color: uiTheme.muted; font.pixelSize: 10 }
                        MiniCombo {
                            id: versionCombo
                            Layout.preferredWidth: 170
                            model: root.versionLabels
                        }
                        AnimatedButton {
                            text: root.tr.recRollback
                            small: true
                            onClicked: root.rollback()
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: root.tr.recHint
                            color: Qt.rgba(0.56,0.7,0.76,0.6)
                            font.pixelSize: 9
                            elide: Text.ElideRight
                            Layout.maximumWidth: 360
                        }
                    }
                }
            }
        }
    }
}
