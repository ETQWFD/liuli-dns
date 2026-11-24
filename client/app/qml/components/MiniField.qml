import QtQuick
import QtQuick.Controls

TextField {
    property bool glass: uiTheme.glass
    implicitHeight: 30
    font.pixelSize: 11
    color: uiTheme.text
    placeholderTextColor: Qt.rgba(0.56, 0.7, 0.76, 0.6)
    selectByMouse: true
    leftPadding: 8
    rightPadding: 8
    topPadding: 5
    bottomPadding: 5
    background: Rectangle {
        radius: 7
        color: glass ? Qt.rgba(0, 0, 0, 0.2) : "#0D151C"
        border.width: 1
        border.color: activeFocus ? uiTheme.accent : (glass ? Qt.rgba(0.7, 0.93, 1, 0.13) : "#2A3943")
    }
}
