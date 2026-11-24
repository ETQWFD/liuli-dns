import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    anchors.fill: parent

    property var appRoot
    readonly property var tr: appRoot ? appRoot.tr : ({})
    property string mode: "login"       // login | register | verify | reset
    property string captchaId: ""
    property string captchaQuestion: ""
    property string pendingEmail: ""
    property bool submitting: false
    property bool resetSent: false

    function requestCaptcha() {
        captchaQuestion = ""
        Bridge.api("captcha", "POST", "/auth/captcha", "{}")
    }

    function setMode(m) {
        mode = m
        if (m === "login" || m === "register") {
            resetSent = false
            requestCaptcha()
        }
    }

    function submitLogin() {
        if (submitting) return
        if (!emailField.text || !passwordField.text) {
            appRoot.notify(tr.errInvalid, true)
            return
        }
        if (!captchaId || !captchaField.text) {
            appRoot.notify(tr.errCaptcha, true)
            requestCaptcha()
            return
        }
        submitting = true
        Bridge.api("login", "POST", "/auth/login", JSON.stringify({
            email: emailField.text.trim(),
            password: passwordField.text,
            captcha_id: captchaId,
            captcha_answer: captchaField.text.trim()
        }))
    }

    function submitRegister() {
        if (submitting) return
        if (!emailField.text || !passwordField.text) {
            appRoot.notify(tr.errInvalid, true)
            return
        }
        if (!captchaId || !captchaField.text) {
            appRoot.notify(tr.errCaptcha, true)
            requestCaptcha()
            return
        }
        submitting = true
        Bridge.api("register", "POST", "/auth/register", JSON.stringify({
            email: emailField.text.trim(),
            password: passwordField.text,
            captcha_id: captchaId,
            captcha_answer: captchaField.text.trim(),
            locale: I18n.language()
        }))
    }

    function submitVerify() {
        if (submitting) return
        submitting = true
        Bridge.api("verify_email", "POST", "/auth/verify-email", JSON.stringify({
            code: verifyField.text.trim()
        }))
    }

    function sendReset() {
        if (!emailField.text) {
            appRoot.notify(tr.errInvalid, true)
            return
        }
        submitting = true
        Bridge.api("password_forgot", "POST", "/auth/password/forgot", JSON.stringify({
            email: emailField.text.trim()
        }))
    }

    function submitReset() {
        if (submitting) return
        submitting = true
        Bridge.api("password_reset", "POST", "/auth/password/reset", JSON.stringify({
            code: resetCodeField.text.trim(),
            password: newPasswordField.text
        }))
    }

    Connections {
        target: Bridge
        function onCaptchaReady(id, question, expires) {
            root.captchaId = id
            root.captchaQuestion = question
            if (root.mode === "login" || root.mode === "register")
                captchaField.text = ""
        }
        function onApiResult(action, ok, data, code, message) {
            if (action === "login" || action === "register" || action === "verify_email"
                    || action === "password_forgot" || action === "password_reset")
                root.submitting = false
            if (!ok) {
                if (action === "login" || action === "register")
                    root.requestCaptcha()
                return
            }
            if (action === "login") {
                passwordField.text = ""
                appRoot.notify(root.tr.dashHello + ", " + emailField.text.trim(), false)
            } else if (action === "register") {
                var payload = JSON.parse(data || "{}")
                root.pendingEmail = emailField.text.trim()
                if (payload.email_verified === true) {
                    // Standalone local mode: no external SMTP or real-name
                    // reviewer exists, so the bundled API activates the account.
                    root.mode = "login"
                    passwordField.text = ""
                    appRoot.notify(payload.message || root.tr.toastVerified, false)
                    root.requestCaptcha()
                } else {
                    root.mode = "verify"
                    verifyField.text = ""
                    appRoot.notify(root.tr.toastCodeSent, false)
                }
            } else if (action === "verify_email") {
                root.mode = "login"
                passwordField.text = ""
                appRoot.notify(root.tr.toastVerified, false)
                root.requestCaptcha()
            } else if (action === "password_forgot") {
                root.resetSent = true
                appRoot.notify(root.tr.toastCodeSent, false)
            } else if (action === "password_reset") {
                root.mode = "login"
                root.resetSent = false
                passwordField.text = ""
                appRoot.notify(root.tr.toastReset, false)
                root.requestCaptcha()
            }
        }
    }

    Component.onCompleted: requestCaptcha()
    onVisibleChanged: if (visible) requestCaptcha()

    RowLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 1020)
        spacing: 64

        // ---------- brand / hero ----------
        Item {
            Layout.fillWidth: true
            Layout.preferredWidth: 470
            implicitHeight: hero.implicitHeight

            ColumnLayout {
                id: hero
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 18

                RowLayout {
                    spacing: 12
                    Rectangle {
                        width: 44
                        height: 44
                        radius: 13
                        gradient: Gradient {
                            GradientStop { position: 0; color: "#5FE3C8" }
                            GradientStop { position: 1; color: "#3B7BD4" }
                        }
                        Text {
                            anchors.centerIn: parent
                            text: "琉"
                            color: "#042027"
                            font.pixelSize: 22
                            font.weight: Font.Black
                        }
                    }
                    ColumnLayout {
                        spacing: 2
                        Text { text: root.tr.appName || "LiuliDNS"; color: uiTheme.text; font.pixelSize: 24; font.weight: Font.DemiBold }
                        Text { text: root.tr.tagline || ""; color: uiTheme.muted; font.pixelSize: 12 }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "自有域名，\n在自己的控制台里发光。"
                    color: uiTheme.text
                    font.pixelSize: 34
                    font.weight: Font.DemiBold
                    lineHeight: 1.18
                    wrapMode: Text.Wrap
                }

                Text {
                    Layout.fillWidth: true
                    text: root.tr.onbStep1Body || ""
                    color: uiTheme.muted
                    font.pixelSize: 13
                    lineHeight: 1.55
                    wrapMode: Text.Wrap
                }

                Repeater {
                    model: [
                        { glyph: "◈", text: "A / AAAA / CNAME / TXT / MX", hint: "真实权威 DNS 应答" },
                        { glyph: "✦", text: "PEM 证书上传与到期提醒", hint: "私钥 AES-256-GCM 加密" },
                        { glyph: "⬡", text: "NS 委派 · TXT 验证", hint: "不做注册商，域名始终属于你" }
                    ]
                    delegate: RowLayout {
                        required property var modelData
                        spacing: 12
                        Text {
                            text: modelData.glyph
                            color: uiTheme.accent
                            font.pixelSize: 16
                            Layout.preferredWidth: 22
                        }
                        ColumnLayout {
                            spacing: 1
                            Text { text: modelData.text; color: uiTheme.text; font.pixelSize: 12 }
                            Text { text: modelData.hint; color: Qt.rgba(0.56, 0.70, 0.76, 0.75); font.pixelSize: 10 }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: Qt.rgba(0.7, 0.93, 1, 0.14)
                }

                Text {
                    Layout.fillWidth: true
                    text: root.tr.onbBoundary || ""
                    color: Qt.rgba(0.56, 0.70, 0.76, 0.75)
                    font.pixelSize: 10
                    wrapMode: Text.Wrap
                    lineHeight: 1.4
                }
            }
        }

        // ---------- auth card ----------
        GlassCard {
            Layout.preferredWidth: 430
            Layout.alignment: Qt.AlignVCenter
            height: root.mode === "login" ? 500
                  : root.mode === "register" ? 540
                  : root.mode === "verify" ? 350 : 560
            pad: 26

            Behavior on height { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

            ColumnLayout {
                anchors.fill: parent
                spacing: 12

                // mode tabs
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    visible: root.mode === "login" || root.mode === "register"
                    AnimatedButton {
                        text: root.tr.authLogin || "Sign in"
                        primary: root.mode === "login"
                        small: true
                        onClicked: root.setMode("login")
                    }
                    AnimatedButton {
                        text: root.tr.authRegister || "Register"
                        primary: root.mode === "register"
                        small: true
                        onClicked: root.setMode("register")
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: Bridge.sessionStorage
                        color: Qt.rgba(0.56, 0.70, 0.76, 0.7)
                        font.pixelSize: 9
                    }
                }

                // ---------- login / register ----------
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    visible: root.mode === "login" || root.mode === "register"

                    Text {
                        text: root.mode === "login" ? root.tr.authLogin : root.tr.authRegister
                        color: uiTheme.text
                        font.pixelSize: 22
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: root.mode === "login" ? root.tr.tagline : root.tr.authHint
                        color: uiTheme.muted
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    TxField {
                        id: emailField
                        Layout.fillWidth: true
                        label: root.tr.authEmail
                        placeholder: "you@example.com"
                        inputMethodHints: Qt.ImhEmailCharactersOnly | Qt.ImhNoAutoUppercase
                    }
                    TxField {
                        id: passwordField
                        Layout.fillWidth: true
                        label: root.tr.authPassword
                        placeholder: "••••••••••"
                        echoMode: TextInput.Password
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Rectangle {
                            Layout.fillWidth: true
                            height: 38
                            radius: 10
                            color: uiTheme.glass ? Qt.rgba(0, 0, 0, 0.22) : "#0D151C"
                            border.width: 1
                            border.color: uiTheme.glass ? Qt.rgba(0.7, 0.93, 1, 0.16) : "#2A3943"
                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                verticalAlignment: Text.AlignVCenter
                                text: root.captchaQuestion !== "" ? root.captchaQuestion : root.tr.authCaptcha
                                color: root.captchaQuestion !== "" ? "#BFF9EF" : Qt.rgba(0.56, 0.7, 0.76, 0.6)
                                font.pixelSize: 12
                                elide: Text.ElideRight
                            }
                        }
                        TxField {
                            id: captchaField
                            Layout.preferredWidth: 112
                            Layout.minimumWidth: 112
                            Layout.maximumWidth: 112
                            placeholder: root.tr.authCaptchaHint
                            maxLength: 16
                        }
                        AnimatedButton {
                            text: root.tr.refresh
                            small: true
                            onClicked: root.requestCaptcha()
                        }
                    }

                    AnimatedButton {
                        Layout.fillWidth: true
                        Layout.topMargin: 4
                        text: root.mode === "login" ? root.tr.authSubmit : root.tr.domCreate
                        primary: true
                        enabled: !root.submitting
                        onClicked: root.mode === "login" ? root.submitLogin() : root.submitRegister()
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: root.tr.authForgot || ""
                            color: uiTheme.accent
                            font.pixelSize: 11
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.mode = "reset"
                                    root.resetSent = false
                                    root.requestCaptcha()
                                }
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: root.mode === "login" ? root.tr.authNoAccount : root.tr.authHasAccount
                            color: Qt.rgba(0.56, 0.7, 0.76, 0.85)
                            font.pixelSize: 10
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.setMode(root.mode === "login" ? "register" : "login")
                            }
                        }
                    }
                }

                // ---------- verify email ----------
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 14
                    visible: root.mode === "verify"

                    Text { text: root.tr.authVerifyTitle; color: uiTheme.text; font.pixelSize: 22; font.weight: Font.DemiBold }
                    Text {
                        Layout.fillWidth: true
                        text: root.tr.authVerifyBody
                        color: uiTheme.muted
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                    }
                    Text {
                        visible: root.pendingEmail !== ""
                        text: root.pendingEmail
                        color: uiTheme.accent
                        font.pixelSize: 11
                    }
                    TxField {
                        id: verifyField
                        Layout.fillWidth: true
                        label: root.tr.authVerifyCode
                        placeholder: "ABCDE-FGHJK"
                        maxLength: 16
                    }
                    AnimatedButton {
                        Layout.fillWidth: true
                        text: root.tr.authVerifyBtn
                        primary: true
                        enabled: !root.submitting
                        onClicked: root.submitVerify()
                    }
                    Text {
                        text: root.tr.authBack
                        color: uiTheme.muted
                        font.pixelSize: 11
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.setMode("login")
                        }
                    }
                }

                // ---------- reset password ----------
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    visible: root.mode === "reset"

                    Text { text: root.tr.authResetTitle; color: uiTheme.text; font.pixelSize: 22; font.weight: Font.DemiBold }
                    Text {
                        Layout.fillWidth: true
                        text: root.tr.authHint
                        color: uiTheme.muted
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                    }
                    TxField {
                        id: resetEmailField
                        Layout.fillWidth: true
                        label: root.tr.authEmail
                        placeholder: "you@example.com"
                        text: emailField.text
                    }
                    AnimatedButton {
                        Layout.fillWidth: true
                        text: root.tr.toastCodeSent
                        enabled: !root.submitting
                        onClicked: {
                            emailField.text = resetEmailField.text
                            root.sendReset()
                        }
                    }
                    TxField {
                        id: resetCodeField
                        Layout.fillWidth: true
                        label: root.tr.authResetCode
                        visible: root.resetSent
                    }
                    TxField {
                        id: newPasswordField
                        Layout.fillWidth: true
                        label: root.tr.authNewPassword
                        echoMode: TextInput.Password
                        visible: root.resetSent
                    }
                    AnimatedButton {
                        Layout.fillWidth: true
                        text: root.tr.authResetBtn
                        primary: true
                        enabled: !root.submitting && root.resetSent
                        onClicked: root.submitReset()
                    }
                    Text {
                        text: root.tr.authBack
                        color: uiTheme.muted
                        font.pixelSize: 11
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.setMode("login")
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: Qt.rgba(0.7, 0.93, 1, 0.12)
                }
                Text {
                    Layout.fillWidth: true
                    text: root.tr.setSecureHint || ""
                    color: Qt.rgba(0.56, 0.7, 0.76, 0.65)
                    font.pixelSize: 9
                    wrapMode: Text.Wrap
                }
            }
        }
    }
}
