import QtQuick
import Quickshell
import Quickshell.Services.Mpris
import qs.Ui
import qs.Commons

BarWidget {
  id: root
  moduleName: "llurd.music"

  readonly property var players: Mpris.players ? Mpris.players.values : []
  readonly property var player: {
    var list = players
    for (var i = 0; i < list.length; i++) {
      var p = list[i]
      var bus = String(p.dbusName || "")
      var desktop = String(p.desktopEntry || "").toLowerCase()
      var identity = String(p.identity || "")
      if (bus === "org.mpris.MediaPlayer2.Music" || desktop === "music-player" || identity === "Music")
        return p
    }
    return null
  }
  readonly property bool hasTrack: player && (player.trackTitle || player.trackArtist)
  readonly property string title: player && player.trackTitle ? player.trackTitle : ""
  readonly property string artist: player && player.trackArtist ? player.trackArtist : ""
  readonly property string playIcon: player && player.isPlaying ? "󰏤" : "󰐊"
  readonly property string trackLabel: hasTrack ? (title + (artist ? "  ·  " + artist : "")) : "Music"
  readonly property string trackTip: hasTrack ? (title + (artist ? " — " + artist : "")) : "Open Music"
  readonly property int playWidth: Style.bar.iconSlot + Style.space(8)
  readonly property real maxLabelWidth: 180

  implicitWidth: row.implicitWidth + Style.space(8)
  implicitHeight: barSize
  clip: true

  property double lastRaiseAt: 0

  FontMetrics {
    id: labelFont
    font.family: root.bar.fontFamily
    font.pixelSize: Style.font.body
  }

  function raiseWindow() {
    var now = Date.now()
    if (now - root.lastRaiseAt < 900) return
    root.lastRaiseAt = now
    Quickshell.execDetached(["music-player"])
  }

  function mpris(method) {
    Quickshell.execDetached([
      "busctl", "--user", "call",
      "org.mpris.MediaPlayer2.Music",
      "/org/mpris/MediaPlayer2",
      "org.mpris.MediaPlayer2.Player",
      method
    ])
  }

  function togglePlaying() {
    root.mpris("PlayPause")
  }

  Row {
    id: row
    anchors.centerIn: parent
    spacing: Style.space(4)

    Item {
      id: playHit
      width: root.playWidth
      height: root.barSize

      Text {
        anchors.centerIn: parent
        text: root.hasTrack ? root.playIcon : "󰝚"
        color: root.player && root.player.isPlaying ? root.bar.barForeground : Qt.darker(root.bar.barForeground, 1.4)
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.body
      }
    }

    Item {
      id: scrollClip
      readonly property real textW: {
        var w = labelFont.advanceWidth(root.trackLabel)
        return (isFinite(w) && w > 1) ? w : 1
      }
      readonly property bool needsScroll: root.hasTrack && textW > root.maxLabelWidth + 2
      readonly property real gap: 32
      readonly property real loopWidth: textW + gap
      property real offset: 0
      property string pinnedLabel: ""

      width: needsScroll ? root.maxLabelWidth : Math.min(root.maxLabelWidth, textW)
      height: Math.max(1, labelFont.height)
      clip: true
      anchors.verticalCenter: parent.verticalCenter
      visible: !root.vertical

      Row {
        id: ticker
        spacing: scrollClip.gap
        x: -scrollClip.offset
        anchors.verticalCenter: parent.verticalCenter

        Text {
          text: root.trackLabel
          color: root.bar.barForeground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.body
          wrapMode: Text.NoWrap
        }
        Text {
          text: root.trackLabel
          color: root.bar.barForeground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.body
          wrapMode: Text.NoWrap
          visible: scrollClip.needsScroll
        }
      }

      Timer {
        interval: 35
        running: scrollClip.needsScroll && !root.vertical
        repeat: true
        onTriggered: {
          var w = scrollClip.loopWidth
          if (w <= scrollClip.width + 2) {
            scrollClip.offset = 0
            return
          }
          var next = scrollClip.offset + 1
          scrollClip.offset = next >= w ? next - w : next
        }
      }

      Connections {
        target: root
        function onTrackLabelChanged() {
          if (root.trackLabel === scrollClip.pinnedLabel)
            return
          scrollClip.pinnedLabel = root.trackLabel
          scrollClip.offset = 0
        }
      }
    }
  }

  MouseArea {
    id: chipClick
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton

    function overPlay(x) {
      var origin = playHit.mapToItem(chipClick, 0, 0)
      return x >= origin.x && x <= origin.x + playHit.width
    }

    onClicked: function(mouse) {
      if (mouse.button === Qt.RightButton) {
        if (root.hasTrack) root.togglePlaying()
        else root.raiseWindow()
        return
      }
      if (mouse.button === Qt.MiddleButton) {
        if (root.hasTrack) root.mpris("Next")
        return
      }
      if (chipClick.overPlay(mouse.x) && root.hasTrack) {
        root.togglePlaying()
        return
      }
      root.raiseWindow()
    }

    onEntered: root.refreshTip(chipClick.mouseX)
    onPositionChanged: function(mouse) { root.refreshTip(mouse.x) }
    onExited: if (root.bar) root.bar.hideTooltip(root)
  }

  function refreshTip(x) {
    if (!root.bar) return
    if (x >= 0 && chipClick.overPlay(x) && root.hasTrack)
      root.bar.showTooltip(root, root.player && root.player.isPlaying ? "Pause" : "Play")
    else
      root.bar.showTooltip(root, root.trackTip)
  }
}
