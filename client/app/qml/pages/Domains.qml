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
    property string addMode: "platform"

    readonly property var current: {
        if (!appRoot) return null
        var ds = appRoot.domains || []
        for (var i = 0; i < ds.length; ++i)
            if (ds[i].id === appRoot.selectedDomainId) return ds[i]
        return null
    }
    readonly property bool realnameActive: appRoot && appRoot.user &&
                                           appRoot.user.realname_status === "active"
    readonly property var tunnelInfo: appRoot ? (appRoot.tunnel || ({})) : ({})

    function refresh() {
        if (!appRoot) return
        appRoot.refreshDomains()
    }

    function statusLabel(d) {
        if (!d) return ""
        if (d.status === "active") return tr.domActive || "已生效"
        if (d.stage === "ns_pending") return "等待 NS 切换"
        if (d.stage === "tunnel_pending") return "域名暂不可用"
        return tr.domPending || "待验证"
    }

    function statusTone(d) {
        if (!d) return "warn"
        return d.status === "active" ? "ok" : (d.stage === "ns_pending" ? "warn" : "bad")
    }

    function openAdd() {
        if (!realnameActive) {
            appRoot.notify("请先完成实名认证并输入激活码", true)
            appRoot.go("Realname")
            return
        }
        addDialog.open()
    }

    function createDomain() {
        if (!realnameActive) {
            appRoot.notify("请先完成实名认证并输入激活码", true)
            return
        }
        var upstream = upstreamField.text.trim()
        if (addMode === "platform") {
            var prefix = prefixField.text.trim().toLowerCase()
            if (!prefix) { appRoot.notify(tr.errInvalid || "输入不合法", true); return }
            Bridge.api("domain_create", "POST", "/domains/platform", JSON.stringify({
                prefix: prefix, upstream_url: upstream
            }))
        } else if (addMode === "external") {
            var fqdn = externalField.text.trim().toLowerCase()
            if (!fqdn) { appRoot.notify(tr.errInvalid || "输入不合法", true); return }
            Bridge.api("domain_create", "POST", "/domains/external", JSON.stringify({
                fqdn: fqdn, upstream_url: upstream
            }))
        } else {
            var fp = prefixField.text.trim().toLowerCase()
            var suffix = freeSuffix.text.trim().toLowerCase()
            if (!fp || !suffix) { appRoot.notify(tr.errInvalid || "输入不合法", true); return }
            Bridge.api("domain_create", "POST", "/domains/free", JSON.stringify({
                prefix: fp, suffix: suffix, upstream_url: upstream
            }))
        }
    }

    function verifyDomain() {
        if (!current) return
        Bridge.api("domain_verify", "POST", "/domains/" + current.id + "/verify-ns", "{}")
    }

    function saveUpstream() {
        if (!current) return
        var value = detailUpstream.text.trim()
        if (!value) { appRoot.notify(tr.errInvalid || "输入不合法", true); return }
        Bridge.api("upstream_save", "PATCH", "/domains/" + current.id + "/upstream",
                   JSON.stringify({upstream_url: value}))
    }

    Component.onCompleted: if (active) refresh()
    onActiveChanged: if (active) refresh()

    Connections {
        target: Bridge
        function onApiResult(action, ok, data, code, message) {
            if (!ok) {
                if (code === "DOMAIN_NS_PENDING")
                    appRoot.notify("等待 NS 切换：请先在注册商处修改 NS", true)
                else if (code === "TUNNEL_UNAVAILABLE" || code === "CLOUDFLARE_NOT_CONFIGURED")
                    appRoot.notify(message || "域名暂不可用", true)
                return
            }
            if (action === "domain_create" || action === "domain_verify" ||
                action === "upstream_save" || action === "domain_delete") {
                if (action === "domain_create" || action === "domain_verify")
                    addDialog.close()
                var d = (action === "domain_create" || action === "domain_verify")
                        ? JSON.parse(data || "{}") : ({})
                if (d.id) appRoot.selectedDomainId = d.id
                root.refresh()
                if (action === "domain_create") appRoot.notify("域名已创建；等待 NS 或 Tunnel 就绪", false)
                else if (action === "domain_verify") appRoot.notify(tr.toastVerified || "验证通过", false)
                else if (action === "upstream_save") appRoot.notify(tr.toastSaved || "已保存", false)
                else appRoot.notify(tr.toastDeleted || "已删除", false)
            } else if (action === "tunnel_status") {
                appRoot.tunnel = JSON.parse(data || "{}")
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 16

        GlassCard {
            Layout.preferredWidth: 450
            Layout.fillHeight: true
            pad: 18

            ColumnLayout {
                anchors.fill: parent
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        spacing: 2
                        Text { text: root.tr.domTitle; color: uiTheme.text; font.pixelSize: 20; font.weight: Font.DemiBold }
                        Text { text: (appRoot ? appRoot.domains.length : 0) + " / 5"; color: uiTheme.muted; font.pixelSize: 10 }
                    }
                    Item { Layout.fillWidth: true }
                    AnimatedButton {
                        text: root.tr.domAdd || "添加域名"
                        iconText: "+"
                        primary: true
                        small: true
                        onClicked: root.openAdd()
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: visible ? 54 : 0
                    visible: !root.realnameActive
                    radius: 9
                    color: Qt.rgba(1, 0.72, 0.3, 0.08)
                    border.width: 1
                    border.color: Qt.rgba(1, 0.72, 0.3, 0.3)
                    Text {
                        anchors.fill: parent
                        anchors.margins: 9
                        text: "未实名：创建域名已禁用。请先完成实名认证并输入激活码。"
                        color: "#FFE0A8"
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(0.7,0.93,1,0.12) }

                ListView {
                    id: domainList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 8
                    model: appRoot ? appRoot.domains : []
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {}

                    delegate: Rectangle {
                        required property var modelData
                        width: domainList.width
                        height: 74
                        radius: 11
                        color: root.current && root.current.id === modelData.id
                               ? Qt.rgba(0.4, 0.92, 0.82, 0.10)
                               : (itemMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.05) : "transparent")
                        border.width: 1
                        border.color: root.current && root.current.id === modelData.id
                                      ? Qt.rgba(0.4, 0.92, 0.82, 0.38)
                                      : Qt.rgba(1, 1, 1, 0.06)

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 10
                            Rectangle {
                                width: 34; height: 34; radius: 9
                                color: modelData.status === "active"
                                       ? Qt.rgba(0.37,0.92,0.82,0.14) : Qt.rgba(1,0.82,0.42,0.12)
                                Text {
                                    anchors.centerIn: parent
                                    text: modelData.status === "active" ? "◈" : "◌"
                                    color: modelData.status === "active" ? uiTheme.accent : uiTheme.warning
                                    font.pixelSize: 14
                                }
                            }
                            ColumnLayout {
                                spacing: 2
                                Text {
                                    text: modelData.fqdn; color: uiTheme.text
                                    font.pixelSize: 13; font.weight: Font.Medium
                                    elide: Text.ElideRight; Layout.fillWidth: true
                                }
                                Text {
                                    text: (modelData.kind || "external") + " · " + root.statusLabel(modelData)
                                    color: Qt.rgba(0.56,0.7,0.76,0.65); font.pixelSize: 9
                                }
                            }
                            StatusPill {
                                text: root.statusLabel(modelData)
                                tone: root.statusTone(modelData)
                            }
                        }

                        MouseArea {
                            id: itemMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: appRoot.selectedDomainId = modelData.id
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: (!appRoot || appRoot.domains.length === 0)
                        text: root.tr.domEmpty || "还没有托管域名"
                        color: uiTheme.muted
                        font.pixelSize: 12
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 66
                    radius: 10
                    color: Qt.rgba(0.49, 0.66, 1, 0.06)
                    border.width: 1
                    border.color: Qt.rgba(0.49, 0.66, 1, 0.2)
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 9
                        spacing: 3
                        Text {
                            text: root.tunnelInfo.running ? "Tunnel 运行中" : "Tunnel 未运行"
                            color: root.tunnelInfo.running ? "#A8FFEF" : "#FFE7B4"
                            font.pixelSize: 10; font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            text: (root.tunnelInfo.warning
                                   ? "连接数较高，新访问可能变慢或失败"
                                   : "一个 Tunnel 共享全部域名；公网入口仅 Cloudflare Tunnel")
                            color: Qt.rgba(0.85,0.9,0.95,0.72)
                            font.pixelSize: 9; wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }

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
                    spacing: 12

                    Text {
                        visible: !root.current
                        text: root.tr.domEmpty || "还没有托管域名"
                        color: uiTheme.muted
                        font.pixelSize: 13
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        visible: root.current

                        RowLayout {
                            Layout.fillWidth: true
                            ColumnLayout {
                                spacing: 3
                                Text {
                                    text: root.current ? root.current.fqdn : ""
                                    color: uiTheme.text; font.pixelSize: 24; font.weight: Font.DemiBold
                                }
                                Text {
                                    text: (root.current ? (root.current.kind || "") : "") + " · " +
                                          (root.current ? root.current.stage : "")
                                    color: uiTheme.muted; font.pixelSize: 10
                                }
                            }
                            Item { Layout.fillWidth: true }
                            StatusPill {
                                text: root.statusLabel(root.current)
                                tone: root.statusTone(root.current)
                            }
                        }

                        Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(0.7,0.93,1,0.12) }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 112
                            radius: 12
                            color: Qt.rgba(0.4, 0.92, 0.82, 0.055)
                            border.width: 1
                            border.color: Qt.rgba(0.4, 0.92, 0.82, 0.2)
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 14
                                spacing: 6
                                Text { text: "公网访问（仅 Cloudflare Tunnel）"; color: "#BFF9EF"; font.pixelSize: 12; font.weight: Font.DemiBold }
                                Text {
                                    Layout.fillWidth: true
                                    text: root.current ? (root.current.public_url || ("https://" + root.current.fqdn)) : ""
                                    color: "#D8FFFA"; font.family: "Consolas"; font.pixelSize: 11
                                    elide: Text.ElideRight
                                }
                                RowLayout {
                                    Text {
                                        Layout.fillWidth: true
                                        text: "源站 " + (root.current ? root.current.upstream_url : "")
                                        color: uiTheme.muted; font.pixelSize: 9
                                        elide: Text.ElideMiddle
                                    }
                                    AnimatedButton {
                                        text: root.tr.copy || "复制"; small: true; ghost: true
                                        onClicked: Bridge.copyText(root.current.public_url || (""))
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: visible ? 240 : 0
                            visible: root.current && root.current.kind !== "platform"
                            radius: 12
                            color: Qt.rgba(0.49, 0.66, 1, 0.05)
                            border.width: 1
                            border.color: Qt.rgba(0.49, 0.66, 1, 0.22)
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 14
                                spacing: 7
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "NS 切换（Cloudflare 分配）"; color: "#CBDCFF"; font.pixelSize: 12; font.weight: Font.DemiBold }
                                    Item { Layout.fillWidth: true }
                                    AnimatedButton {
                                        text: root.tr.copy || "复制"; small: true; ghost: true
                                        visible: root.current && root.current.kind !== "platform" && (root.current.ns_nameservers || []).length > 0
                                        onClicked: Bridge.copyText((root.current.ns_nameservers || []).join("\n"))
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "请到域名注册商把 NS 改成以下两个地址；NS 生效前不会标记为可用。"
                                    color: uiTheme.muted; font.pixelSize: 10; wrapMode: Text.Wrap
                                }
                                Repeater {
                                    model: root.current ? (root.current.ns_nameservers || []) : []
                                    delegate: Rectangle {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        height: 28; radius: 7
                                        color: Qt.rgba(0,0,0,0.24)
                                        Text {
                                            anchors.fill: parent; anchors.leftMargin: 9
                                            verticalAlignment: Text.AlignVCenter
                                            text: modelData; color: "#CFFFF8"
                                            font.family: "Consolas"; font.pixelSize: 11
                                        }
                                    }
                                }
                                AnimatedButton {
                                    text: "我已切换 NS，重新检测"
                                    primary: true; small: true
                                    visible: root.current && root.current.status !== "active"
                                    onClicked: root.verifyDomain()
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 100
                            radius: 12
                            color: Qt.rgba(1,1,1,0.035)
                            border.width: 1
                            border.color: Qt.rgba(1,1,1,0.08)
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 12; spacing: 5
                                Text { text: "本机源站（Tunnel 转发目标）"; color: uiTheme.text; font.pixelSize: 11; font.weight: Font.DemiBold }
                                RowLayout {
                                    Layout.fillWidth: true
                                    TxField {
                                        id: detailUpstream
                                        Layout.fillWidth: true
                                        text: root.current ? (root.current.upstream_url || "") : ""
                                        placeholder: "http://127.0.0.1:8080"
                                    }
                                    AnimatedButton { text: root.tr.save || "保存"; small: true; onClicked: root.saveUpstream() }
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            AnimatedButton { text: root.tr.domRecords || "编辑解析"; onClicked: appRoot.go("Records") }
                            AnimatedButton { text: root.tr.domCerts || "证书"; onClicked: appRoot.go("Certificates") }
                            Item { Layout.fillWidth: true }
                            AnimatedButton { text: root.tr.domDelete || "删除域名"; danger: true; onClicked: deleteDialog.open() }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "本方案依赖 Cloudflare Tunnel；免费版无 SLA，国内访问速度/稳定性不承诺，不适合大文件、视频串流或高并发站点。"
                            color: Qt.rgba(0.56,0.7,0.76,0.62)
                            font.pixelSize: 9; wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: addDialog
        modal: true
        width: 520
        height: 430
        padding: 24

        background: Rectangle {
            radius: 16; color: "#0C1820"
            border.width: 1; border.color: Qt.rgba(0.7, 0.93, 1, 0.24)
        }

        contentItem: ColumnLayout {
            spacing: 10
            Text { text: "添加域名"; color: uiTheme.text; font.pixelSize: 18; font.weight: Font.DemiBold }
            Text {
                Layout.fillWidth: true
                text: "实名已激活。平台二级域名走 Tunnel；自有域名需先改 NS。最多 5 个域名。"
                color: uiTheme.muted; font.pixelSize: 10; wrapMode: Text.Wrap
            }
            RowLayout {
                spacing: 6
                AnimatedButton {
                    text: "平台 *.asnia.cc"; small: true; primary: addMode === "platform"
                    onClicked: addMode = "platform"
                }
                AnimatedButton {
                    text: "导入自有域名"; small: true; primary: addMode === "external"
                    onClicked: addMode = "external"
                }
                AnimatedButton {
                    text: "免费域名"; small: true; primary: addMode === "free"
                    onClicked: addMode = "free"
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: addMode === "platform" || addMode === "free"
                spacing: 6
                TxField {
                    id: prefixField
                    Layout.fillWidth: true
                    label: "前缀"
                    placeholder: "abc"
                }
                Text {
                    visible: addMode === "platform"
                    text: "." + (appRoot ? appRoot.platformDomain : "asnia.cc")
                    color: "#BFF9EF"; font.pixelSize: 12; font.family: "Consolas"
                }
                TxField {
                    id: freeSuffix
                    visible: addMode === "free"
                    Layout.preferredWidth: 110
                    text: "de5.net"
                    label: "后缀"
                }
            }

            TxField {
                id: externalField
                Layout.fillWidth: true
                visible: addMode === "external"
                label: "一级域名"
                placeholder: "example.com"
            }

            TxField {
                id: upstreamField
                Layout.fillWidth: true
                text: "http://127.0.0.1:8080"
                label: "本机源站"
                placeholder: "http://127.0.0.1:8080"
            }

            Text {
                Layout.fillWidth: true
                text: addMode === "external"
                      ? "创建后会显示 Cloudflare NS；NS 生效前状态为“等待 NS 切换”。"
                      : (addMode === "free" ? "免费域名服务若不能修改 NS，会明确提示“该前缀暂不可用”，不会假装成功。" : "abc.asnia.cc 由平台自有域名分配，不需要你付费。")
                color: Qt.rgba(0.7,0.8,0.85,0.8); font.pixelSize: 9; wrapMode: Text.Wrap
            }
            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                AnimatedButton { text: root.tr.cancel || "取消"; onClicked: addDialog.close() }
                AnimatedButton { text: "创建并接入 Tunnel"; primary: true; onClicked: root.createDomain() }
            }
        }
    }

    Dialog {
        id: deleteDialog
        modal: true
        width: 430
        height: 210
        padding: 24
        background: Rectangle {
            radius: 16; color: "#170E12"
            border.width: 1; border.color: Qt.rgba(1, 0.55, 0.55, 0.4)
        }
        contentItem: ColumnLayout {
            spacing: 12
            Text { text: root.tr.domDelete || "删除域名"; color: "#FFDADA"; font.pixelSize: 18; font.weight: Font.DemiBold }
            Text {
                Layout.fillWidth: true
                text: "删除后 Cloudflare CNAME、Tunnel ingress 与解析记录都会移除，确定继续？"
                color: uiTheme.muted; font.pixelSize: 11; wrapMode: Text.Wrap
            }
            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                AnimatedButton { text: root.tr.cancel || "取消"; onClicked: deleteDialog.close() }
                AnimatedButton {
                    text: root.tr.confirm || "确认"; danger: true
                    onClicked: {
                        deleteDialog.close()
                        Bridge.api("domain_delete", "DELETE", "/domains/" + root.current.id, "{}")
                    }
                }
            }
        }
    }
}
